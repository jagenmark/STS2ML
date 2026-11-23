"""Unit tests for Phase 16 isolated P1/P2 opt-in bugfixes."""

from __future__ import annotations

from pathlib import Path
import json
import runpy

from sts2rl.deck_policy import DeckPolicy
from sts2rl.encounter import EncounterModel, EncounterPolicy
from sts2rl.merchant import marginal_removal_value, merchant_choice
from sts2rl.native import legal_actions
from sts2rl.routing import RoomModel
from sts2rl.run_bundle import load_bundle
from sts2rl.run_policy import IDENTITY, RunPolicy, RunWeights
from sts2rl.selections import combat_selection
from sts2rl.strategy import StrategyModel, _event_terms
from sts2rl.turn_planning import _search_survival_lines, choose_turn_survival


def _base_combat(
    *,
    hp=20,
    max_hp=70,
    block=0,
    energy=3,
    hand=(),
    enemies=(),
    potions=(),
    player_powers=(),
    room_type="Monster",
    act=2,
):
    return {
        "runtime_identity": IDENTITY,
        "observation_version": 2,
        "in_combat": True,
        "decision": "combat_play",
        "round": 2,
        "energy": energy,
        "max_energy": 3,
        "context": {"act": act, "floor": 8, "room_type": room_type},
        "player": {
            "hp": hp,
            "max_hp": max_hp,
            "block": block,
            "gold": 100,
            "potions": list(potions),
            "relics": [],
            "deck": [],
        },
        "player_powers": list(player_powers),
        "hand": [{"index": i, "can_play": True, **c} for i, c in enumerate(hand)],
        "enemies": [{"index": i, "block": 0, "powers": [], "intents": [], **e} for i, e in enumerate(enemies)],
    }


def test_selection_fixes_v4_keeps_card_generating_potions_and_fixes_tools_discard():
    view = _base_combat(
        hp=20,
        energy=1,
        enemies=[{"id": "MONSTER.SPINY_TOAD", "hp": 40, "max_hp": 40, "intents": [{"damage": 25, "hits": 1}]}],
    )
    leg_sweep = {
        "index": 0,
        "id": "CARD.LEG_SWEEP",
        "type": "Skill",
        "cost": 2,
        "stats": {"block": 11, "weakpower": 2},
    }
    st_pot = {
        "runtime_identity": IDENTITY,
        "in_combat": True,
        "decision": "card_select",
        "min_select": 0,
        "max_select": 1,
        "selection_source": {"kind": "use_potion", "id": "POTION.SKILL_POTION"},
        "combat_state": view,
        "cards": [leg_sweep],
    }
    legacy = EncounterPolicy(RunWeights(), enemy_mechanics=True, card_potion_mechanics=True)
    fixed = EncounterPolicy(RunWeights(), enemy_mechanics=True, card_potion_mechanics=True, selection_fixes_v4=True)

    # Legacy negates usefulness and skips the free Leg Sweep!
    assert combat_selection(st_pot, legacy).kind == "skip_select"
    # selection_fixes_v4 takes the free Leg Sweep!
    assert combat_selection(st_pot, fixed).kind == "select_cards"

    # Tools of the Trade start-of-turn discard inherits end_turn with min_select=1 -> must discard worst card!
    strike = {"index": 0, "id": "CARD.STRIKE_SILENT", "type": "Attack", "cost": 1, "stats": {"damage": 6}}
    dash = {"index": 1, "id": "CARD.DASH", "type": "Attack", "cost": 2, "stats": {"damage": 10, "block": 10}}
    view_tools = _base_combat(
        energy=3,
        player_powers=[{"id": "POWER.TOOLS_OF_THE_TRADE_POWER", "amount": 1}],
        enemies=[{"id": "MONSTER.A", "hp": 50, "max_hp": 50, "intents": [{"damage": 15, "hits": 1}]}],
    )
    st_tools = {
        "runtime_identity": IDENTITY,
        "in_combat": True,
        "decision": "card_select",
        "min_select": 1,
        "max_select": 1,
        "selection_source": {"kind": "end_turn"},
        "combat_state": view_tools,
        "cards": [strike, dash],
    }
    assert combat_selection(st_tools, fixed).args["indices"] == "0"


def test_combat_fixes_v4_kin_priest_doomed_minion_and_buffer_constrict_sandpit():
    # 1. Kin Priest: 3-HP follower already doomed by 12 Poison must NOT beat hitting Kin Priest
    st_kin = _base_combat(
        hp=40,
        energy=1,
        hand=[{"id": "CARD.STRIKE_SILENT", "type": "Attack", "target_type": "AnyEnemy", "cost": 1, "stats": {"damage": 6}}],
        enemies=[
            {
                "id": "MONSTER.KIN_FOLLOWER",
                "hp": 3,
                "max_hp": 50,
                "powers": [{"id": "POWER.MINION_POWER", "amount": 1}, {"id": "POWER.POISON_POWER", "amount": 12}],
                "intents": [{"damage": 10, "hits": 1}],
            },
            {
                "id": "MONSTER.KIN_PRIEST",
                "hp": 120,
                "max_hp": 190,
                "intents": [{"damage": 12, "hits": 1}],
            },
        ],
    )
    pol_v4 = EncounterPolicy(
        RunWeights(),
        style="isolate",
        scorer_fixes=True,
        act2_mechanics=True,
        enemy_mechanics=True,
        card_potion_mechanics=True,
        combat_fixes_v4=True,
    )
    acts = legal_actions(st_kin)
    chosen = pol_v4.combat(st_kin, acts)
    assert chosen.args.get("target_index") == 1

    # 2. Buffer conservative ordering: 1 Buffer vs [1 dmg, 20 dmg] at 15 HP must play Defend instead of End Turn
    st_buf = _base_combat(
        hp=15,
        energy=1,
        player_powers=[{"id": "POWER.BUFFER_POWER", "amount": 1}],
        hand=[{"id": "CARD.DEFEND_SILENT", "type": "Skill", "target_type": "Self", "cost": 1, "stats": {"block": 10}}],
        enemies=[
            {"id": "MONSTER.A", "hp": 50, "max_hp": 50, "intents": [{"damage": 1, "hits": 1}]},
            {"id": "MONSTER.B", "hp": 50, "max_hp": 50, "intents": [{"damage": 20, "hits": 1}]},
        ],
    )
    end_act = next(a for a in legal_actions(st_buf) if a.kind == "end_turn")
    assert choose_turn_survival(st_buf, pol_v4, end_act).kind == "play_card"

    # 3. Constrict: 6 HP with Constrict 6 and playable Defend must play Defend
    st_con = _base_combat(
        hp=6,
        energy=1,
        player_powers=[{"id": "POWER.CONSTRICT_POWER", "amount": 6}],
        hand=[{"id": "CARD.DEFEND_SILENT", "type": "Skill", "target_type": "Self", "cost": 1, "stats": {"block": 5}}],
        enemies=[{"id": "MONSTER.SLITHERING_STRANGLER", "hp": 40, "max_hp": 40, "intents": []}],
    )
    end_con = next(a for a in legal_actions(st_con) if a.kind == "end_turn")
    assert choose_turn_survival(st_con, pol_v4, end_con).kind == "play_card"

    # 4. Sandpit == 1: 34 HP vs 12x2 attack with Frantic Escape must play Frantic Escape
    st_sp = _base_combat(
        hp=34,
        energy=1,
        hand=[{"id": "CARD.FRANTIC_ESCAPE", "type": "Status", "target_type": "Self", "cost": 1, "stats": {}}],
        enemies=[
            {
                "id": "MONSTER.THE_INSATIABLE",
                "hp": 200,
                "max_hp": 340,
                "powers": [{"id": "POWER.SANDPIT_POWER", "amount": 1}],
                "intents": [{"damage": 12, "hits": 2}],
            }
        ],
    )
    end_sp = next(a for a in legal_actions(st_sp) if a.kind == "end_turn")
    assert choose_turn_survival(st_sp, pol_v4, end_sp).kind == "play_card"


def test_combat_fixes_v4_precise_cut_ordering_and_energy_potion_unlock():
    pol_v4 = EncounterPolicy(
        RunWeights(),
        scorer_fixes=True,
        act2_mechanics=True,
        enemy_mechanics=True,
        card_potion_mechanics=True,
        combat_fixes_v4=True,
    )
    # Precise Cut (6 dmg, +2 per emptied card) + Shiv (5 dmg) vs 50 HP enemy with 37 Poison, 40 incoming, 6 HP:
    # Shiv -> Cut deals 5 + 8 = 13 -> leaves 37 HP -> Poison kills! Cut -> Shiv deals 6 + 5 = 11 -> dies!
    st_pc = _base_combat(
        hp=6,
        energy=0,
        hand=[
            {"id": "CARD.PRECISE_CUT", "type": "Attack", "target_type": "AnyEnemy", "cost": 0, "stats": {"damage": 6, "extradamage": 2}},
            {"id": "CARD.SHIV", "type": "Attack", "target_type": "AnyEnemy", "cost": 0, "stats": {"damage": 5}},
        ],
        enemies=[
            {
                "id": "MONSTER.SOUL_NEXUS",
                "hp": 50,
                "max_hp": 200,
                "powers": [{"id": "POWER.POISON_POWER", "amount": 37}],
                "intents": [{"damage": 10, "hits": 4}],
            }
        ],
    )
    acts = legal_actions(st_pc)
    cut_act = next(a for a in acts if a.kind == "play_card" and a.args["card_index"] == 0)
    chosen = choose_turn_survival(st_pc, pol_v4, cut_act)
    assert chosen.kind == "play_card" and chosen.args["card_index"] == 1

    # Energy Potion unlocking unaffordable 2-cost Leg Sweep (11 Block) at 4 HP vs 10 incoming
    st_ep = _base_combat(
        hp=4,
        energy=0,
        hand=[
            {
                "id": "CARD.LEG_SWEEP",
                "type": "Skill",
                "target_type": "AnyEnemy",
                "cost": 2,
                "can_play": False,
                "stats": {"block": 11, "weakpower": 2},
            }
        ],
        potions=[{"index": 0, "id": "POTION.ENERGY_POTION", "can_use": True, "target_type": "Self", "vars": {"Energy": 2}}],
        enemies=[{"id": "MONSTER.A", "hp": 50, "max_hp": 50, "intents": [{"damage": 10, "hits": 1}]}],
    )
    end_ep = next(a for a in legal_actions(st_ep) if a.kind == "end_turn")
    assert choose_turn_survival(st_ep, pol_v4, end_ep).kind == "use_potion"


def test_event_and_shop_fixes_v4_abyssal_baths_spoils_map_and_gambit():
    # Abyssal Baths: Take 10 damage at 8 HP -> danger=1.0
    opt = {"description": "Gain 2 Max HP. Take {Damage} damage.", "vars": {"Damage": 10}}
    legacy_terms = _event_terms(opt, 8, 70, 100)
    v4_terms = _event_terms(opt, 8, 70, 100, event_fixes_v4=True)
    assert legacy_terms["danger"] == 0.0
    assert v4_terms["danger"] == 1.0 and v4_terms["hurt"] > 0.0

    # StrategyModel serialization preserves event_fixes_v4
    sm = StrategyModel({}, ["event"], 1.0, event_fixes_v4=True)
    assert sm.event_fixes_v4 is True

    # Spoils Map (Quest) must NOT be treated as a Curse to delete
    quest = {"id": "CARD.SPOILS_MAP", "type": "Quest", "cost": 0}
    assert marginal_removal_value(quest, [quest], lambda c: -10.0, keep_quests=False) > 15.0
    assert marginal_removal_value(quest, [quest], lambda c: -10.0, keep_quests=True) < 0.0

    # Shop must refuse buying The Gambit
    shop_st = {
        "runtime_identity": IDENTITY,
        "decision": "shop",
        "context": {"act": 2, "floor": 5},
        "player": {"hp": 60, "max_hp": 70, "gold": 250, "potions": [], "deck": []},
        "card_removal_cost": 100,
        "cards": [
            {
                "index": 0,
                "id": "CARD.THE_GAMBIT",
                "name": "The Gambit",
                "type": "Skill",
                "cost": 165,
                "card_cost": 0,
                "is_stocked": True,
                "stats": {"block": 50},
            }
        ],
        "relics": [],
        "potions": [],
    }
    act_old = merchant_choice(shop_st, lambda c: 30.0, reserve=1.0, permanent=1.1, gold_curve=True, potion_capacity=True, shop_fixes_v4=False)
    act_new = merchant_choice(shop_st, lambda c: 30.0, reserve=1.0, permanent=1.1, gold_curve=True, potion_capacity=True, shop_fixes_v4=True)
    assert act_old.kind == "buy_card"
    assert act_new.kind == "leave_room"


def test_energy_potion_unlocks_frantic_escape_and_burst_skips_dead_thorns():
    pol_v4 = EncounterPolicy(
        RunWeights(),
        scorer_fixes=True,
        act2_mechanics=True,
        enemy_mechanics=True,
        card_potion_mechanics=True,
        combat_fixes_v4=True,
    )
    # 1. Energy Potion must unlock 1-cost Status FRANTIC_ESCAPE against lethal Sandpit=1.
    st_sand = _base_combat(
        hp=35,
        energy=0,
        hand=[
            {
                "id": "CARD.FRANTIC_ESCAPE",
                "type": "Status",
                "target_type": "Self",
                "cost": 1,
                "can_play": False,
                "stats": {},
            }
        ],
        potions=[{"index": 0, "id": "POTION.ENERGY_POTION", "can_use": True, "target_type": "Self", "vars": {"Energy": 2}}],
        enemies=[
            {
                "id": "MONSTER.THE_INSATIABLE",
                "hp": 200,
                "max_hp": 340,
                "powers": [{"id": "POWER.SANDPIT_POWER", "amount": 1}],
                "intents": [{"damage": 10, "hits": 1}],
            }
        ],
    )
    end_sand = next(a for a in legal_actions(st_sand) if a.kind == "end_turn")
    assert choose_turn_survival(st_sand, pol_v4, end_sand).kind == "use_potion"

    # 2. Duplication replay must not double-trigger Thorns on an enemy killed by the first strike.
    # Player has 10 HP, 1 Duplication, Dagger Spray (6 dmg to all -> kills 5 HP Thorns-8 enemy).
    # First execution kills enemy and takes 8 Thorns (survives at 2 HP); replay must not take another 8 Thorns.
    st_dup = _base_combat(
        hp=10,
        energy=1,
        player_powers=[{"id": "POWER.DUPLICATION_POWER", "amount": 1}],
        hand=[
            {"id": "CARD.DAGGER_SPRAY", "type": "Attack", "target_type": "AllEnemies", "cost": 1, "stats": {"damage": 6}}
        ],
        enemies=[
            {
                "id": "MONSTER.A",
                "hp": 5,
                "max_hp": 40,
                "powers": [{"id": "POWER.THORNS_POWER", "amount": 8}],
                "intents": [{"damage": 20, "hits": 1}],
            }
        ],
    )
    end_dup = next(a for a in legal_actions(st_dup) if a.kind == "end_turn")
    assert choose_turn_survival(st_dup, pol_v4, end_dup).kind == "play_card"
    best_dup, _ = _search_survival_lines(st_dup, pol_v4, legal_actions(st_dup))
    assert best_dup[0] == 1 and best_dup[1] == 1


def test_p1_review_regressions_constrict_sandpit_buffer_wither_noblock_giga():
    pol_v4 = EncounterPolicy(
        RunWeights(),
        scorer_fixes=True,
        act2_mechanics=True,
        enemy_mechanics=True,
        card_potion_mechanics=True,
        combat_fixes_v4=True,
    )
    # P1-1: 3 HP + Constrict 3 + Defend + Strangler carrying lethal Poison -> MUST play Defend before Constrict fires!
    st_con = _base_combat(
        hp=3,
        energy=1,
        player_powers=[{"id": "POWER.CONSTRICT_POWER", "amount": 3}],
        hand=[{"id": "CARD.DEFEND_SILENT", "type": "Skill", "target_type": "Self", "cost": 1, "stats": {"block": 5}}],
        enemies=[
            {
                "id": "MONSTER.SLITHERING_STRANGLER",
                "hp": 10,
                "max_hp": 50,
                "powers": [{"id": "POWER.POISON_POWER", "amount": 20}],
                "intents": [],
            }
        ],
    )
    assert choose_turn_survival(st_con, pol_v4, next(a for a in legal_actions(st_con) if a.kind == "end_turn")).kind == "play_card"
    # Direct kill of Strangler avoids Constrict completely:
    st_con_kill = _base_combat(
        hp=3,
        energy=1,
        player_powers=[{"id": "POWER.CONSTRICT_POWER", "amount": 10}],
        hand=[{"id": "CARD.STRIKE_SILENT", "type": "Attack", "target_type": "AnyEnemy", "cost": 1, "stats": {"damage": 6}}],
        enemies=[{"id": "MONSTER.SLITHERING_STRANGLER", "hp": 6, "max_hp": 50, "intents": []}],
    )
    best_ck, _ = _search_survival_lines(st_con_kill, pol_v4, legal_actions(st_con_kill))
    assert best_ck[0] == 1 and best_ck[1] == 1

    # P1-2: Sandpit==1, 4 HP, 2E, 10-HP Insatiable attacking for 12, Burst + Deadly Poison + 2-cost Frantic Escape
    model_v4 = EncounterModel(
        {
            "version": 1,
            "runtime_identity": IDENTITY,
            "default": "tempo",
            "survival_search": True,
            "search_hand": True,
            "survival_beam": True,
            "sandpit_threshold": 1,
            "scorer_fixes": True,
            "act2_mechanics": True,
            "enemy_mechanics": True,
            "card_potion_mechanics": True,
            "combat_fixes_v4": True,
        }
    )
    st_insat = _base_combat(
        hp=4,
        energy=2,
        room_type="Boss",
        hand=[
            {"id": "CARD.FRANTIC_ESCAPE", "type": "Status", "target_type": "Self", "cost": 2, "stats": {}},
            {"id": "CARD.BURST", "type": "Skill", "target_type": "Self", "cost": 1, "stats": {"skills": 1}},
            {"id": "CARD.DEADLY_POISON", "type": "Skill", "target_type": "AnyEnemy", "cost": 1, "stats": {"poisonpower": 5}},
        ],
        enemies=[
            {
                "id": "MONSTER.THE_INSATIABLE",
                "hp": 10,
                "max_hp": 340,
                "powers": [{"id": "POWER.SANDPIT_POWER", "amount": 1}],
                "intents": [{"damage": 12, "hits": 1}],
            }
        ],
    )
    chosen_insat = model_v4.choose(st_insat, RunPolicy(RunWeights()))
    assert chosen_insat.kind == "play_card" and st_insat["hand"][chosen_insat.args["card_index"]]["id"] == "CARD.BURST"

    # P1-3a: Native hit order [10, 9] with 9 Block + 1 Buffer at 9 HP -> takes 9 on second hit -> must play Defend!
    st_buf_ord = _base_combat(
        hp=9,
        block=9,
        energy=1,
        player_powers=[{"id": "POWER.BUFFER_POWER", "amount": 1}],
        hand=[{"id": "CARD.DEFEND_SILENT", "type": "Skill", "target_type": "Self", "cost": 1, "stats": {"block": 5}}],
        enemies=[
            {"id": "MONSTER.A", "hp": 50, "max_hp": 50, "intents": [{"damage": 10, "hits": 1}]},
            {"id": "MONSTER.B", "hp": 50, "max_hp": 50, "intents": [{"damage": 9, "hits": 1}]},
        ],
    )
    assert choose_turn_survival(st_buf_ord, pol_v4, next(a for a in legal_actions(st_buf_ord) if a.kind == "end_turn")).kind == "play_card"

    # P1-3b: 3 HP with Wither in hand killing the last enemy directly -> beam marks survives=1, clears=1
    st_wither = _base_combat(
        hp=3,
        energy=1,
        hand=[
            {"id": "CARD.STRIKE_SILENT", "type": "Attack", "target_type": "AnyEnemy", "cost": 1, "stats": {"damage": 6}},
            {"id": "CARD.WITHER", "type": "Status", "target_type": "Self", "cost": 1, "can_play": False, "stats": {"damage": 3}},
        ],
        enemies=[{"id": "MONSTER.A", "hp": 5, "max_hp": 50, "intents": []}],
    )
    best_w, _ = _search_survival_lines(st_wither, pol_v4, legal_actions(st_wither))
    assert best_w[0] == 1 and best_w[1] == 1

    # P1-4a: 1 HP, No Block, Afterimage 1 vs 1 incoming -> plays card and survives via Afterimage!
    st_nb = _base_combat(
        hp=1,
        energy=1,
        player_powers=[{"id": "POWER.NO_BLOCK_POWER", "amount": 1}, {"id": "POWER.AFTERIMAGE_POWER", "amount": 1}],
        hand=[{"id": "CARD.NEUTRALIZE", "type": "Attack", "target_type": "AnyEnemy", "cost": 0, "stats": {"damage": 3}}],
        enemies=[{"id": "MONSTER.A", "hp": 50, "max_hp": 50, "intents": [{"damage": 1, "hits": 1}]}],
    )
    assert choose_turn_survival(st_nb, pol_v4, next(a for a in legal_actions(st_nb) if a.kind == "end_turn")).kind == "play_card"

    # P1-4b: Panic Button in a line disables subsequent card Block (while Defend->Panic Button survives; Fortifier+Shadowmeld scales)
    st_pb = _base_combat(
        hp=5,
        energy=1,
        hand=[
            {"id": "CARD.PANIC_BUTTON", "type": "Skill", "target_type": "Self", "cost": 0, "stats": {"block": 30}},
            {"id": "CARD.DEFEND_SILENT", "type": "Skill", "target_type": "Self", "cost": 1, "stats": {"block": 5}},
        ],
        enemies=[{"id": "MONSTER.A", "hp": 50, "max_hp": 50, "intents": [{"damage": 35, "hits": 1}]}],
    )
    acts_pb = legal_actions(st_pb)
    best_pb, _ = _search_survival_lines(st_pb, pol_v4, acts_pb)
    assert best_pb[0] == 1  # Defend -> Panic Button gains 35 Block and survives
    best_pb_first, _ = _search_survival_lines(st_pb, pol_v4, acts_pb, forced_first=0)
    assert best_pb_first[0] == 0  # Panic Button first blocks Defend (30 < 35)

    # Shadowmeld scales Fortifier (5 + 2*5*2 = 25 Block)
    st_fort = _base_combat(
        hp=1,
        block=5,
        energy=0,
        player_powers=[{"id": "POWER.SHADOWMELD_POWER", "amount": 1}],
        potions=[{"index": 0, "id": "POTION.FORTIFIER", "can_use": True, "target_type": "Self", "vars": {}}],
        enemies=[{"id": "MONSTER.A", "hp": 50, "max_hp": 50, "intents": [{"damage": 25, "hits": 1}]}],
    )
    best_fort, _ = _search_survival_lines(st_fort, pol_v4, legal_actions(st_fort))
    assert best_fort[0] == 1

    # P1-5: Duplicated Strike (native Gigantification root preview 18 = 6x3) deals 18 + 6 = 24 -> clears 24 HP, not 25!
    st_giga_dup_24 = _base_combat(
        hp=10,
        energy=1,
        player_powers=[
            {"id": "POWER.GIGANTIFICATION_POWER", "amount": 1},
            {"id": "POWER.DUPLICATION_POWER", "amount": 1},
        ],
        hand=[{"id": "CARD.STRIKE_SILENT", "type": "Attack", "target_type": "AnyEnemy", "cost": 1, "stats": {"damage": 18}}],
        enemies=[{"id": "MONSTER.A", "hp": 24, "max_hp": 40, "intents": [{"damage": 20, "hits": 1}]}],
    )
    best_gd_24, _ = _search_survival_lines(st_giga_dup_24, pol_v4, legal_actions(st_giga_dup_24))
    assert best_gd_24[0] == 1 and best_gd_24[1] == 1
    st_giga_dup_25 = {**st_giga_dup_24, "enemies": [{"index": 0, "id": "MONSTER.A", "hp": 25, "max_hp": 40, "block": 0, "powers": [], "intents": [{"damage": 20, "hits": 1}]}]}
    best_gd_25, _ = _search_survival_lines(st_giga_dup_25, pol_v4, legal_actions(st_giga_dup_25))
    assert best_gd_25[0] == 0 and best_gd_25[1] == 0


def test_p1_review_x_cost_energy_unlock_and_precise_cut_hand_size():
    pol_v4 = EncounterPolicy(
        RunWeights(),
        scorer_fixes=True,
        act2_mechanics=True,
        enemy_mechanics=True,
        card_potion_mechanics=True,
        combat_fixes_v4=True,
    )
    # P1-6a: 0 energy Energy Potion -> Skewer clears 14-HP enemy!
    st_skewer = _base_combat(
        hp=5,
        energy=0,
        hand=[{"id": "CARD.SKEWER", "type": "Attack", "target_type": "AnyEnemy", "cost": 0, "costs_x": True, "stats": {"damage": 7}}],
        potions=[{"index": 0, "id": "POTION.ENERGY_POTION", "can_use": True, "target_type": "Self", "vars": {"Energy": 2}}],
        enemies=[{"id": "MONSTER.A", "hp": 14, "max_hp": 40, "intents": [{"damage": 20, "hits": 1}]}],
    )
    best_sk, _ = _search_survival_lines(st_skewer, pol_v4, legal_actions(st_skewer))
    assert best_sk[0] == 1 and best_sk[1] == 1
    assert choose_turn_survival(st_skewer, pol_v4, next(a for a in legal_actions(st_skewer) if a.kind == "end_turn")).kind == "use_potion"

    # P1-6b: Burst active + 0-cost Adrenaline (+1E) unlocks 2-cost Leg Sweep
    st_adr_burst = _base_combat(
        hp=5,
        energy=0,
        player_powers=[{"id": "POWER.BURST_POWER", "amount": 1}],
        hand=[
            {"id": "CARD.ADRENALINE", "type": "Skill", "target_type": "Self", "cost": 0, "stats": {"energy": 1, "cards": 2}},
            {"id": "CARD.LEG_SWEEP", "type": "Skill", "target_type": "AnyEnemy", "cost": 2, "can_play": False, "stats": {"block": 11, "weakpower": 2}},
        ],
        enemies=[{"id": "MONSTER.A", "hp": 40, "max_hp": 40, "intents": [{"damage": 10, "hits": 1}]}],
    )
    assert choose_turn_survival(st_adr_burst, pol_v4, next(a for a in legal_actions(st_adr_burst) if a.kind == "end_turn")).kind == "play_card"

    # P1-6c: Star-cost card lacking Stars must NOT be unlocked by Energy Potion
    st_stars = _base_combat(
        hp=5,
        energy=0,
        hand=[{"id": "CARD.STAR_WALL", "type": "Skill", "target_type": "Self", "cost": 2, "star_cost": 2, "can_play": False, "stats": {"block": 20}}],
        potions=[{"index": 0, "id": "POTION.ENERGY_POTION", "can_use": True, "target_type": "Self", "vars": {"Energy": 2}}],
        enemies=[{"id": "MONSTER.A", "hp": 40, "max_hp": 40, "intents": [{"damage": 10, "hits": 1}]}],
    )
    best_st, _ = _search_survival_lines(st_stars, pol_v4, legal_actions(st_stars))
    assert best_st[0] == 0

    # P1-7a: 3-card hand (Precise Cut previews 9, Blade Dance adds 3 Shivs): Blade Dance first leaves 5 dmg -> must NOT project kill vs 9-HP enemy!
    st_bd_pc = _base_combat(
        hp=5,
        energy=1,
        hand=[
            {"id": "CARD.BLADE_DANCE", "type": "Skill", "target_type": "Self", "cost": 1, "stats": {"cards": 3}},
            {"id": "CARD.PRECISE_CUT", "type": "Attack", "target_type": "AnyEnemy", "cost": 0, "stats": {"damage": 9, "extradamage": 2}},
            {"id": "CARD.DEFEND_SILENT", "type": "Skill", "target_type": "Self", "cost": 1, "can_play": False, "stats": {"block": 5}},
        ],
        enemies=[{"id": "MONSTER.A", "hp": 9, "max_hp": 40, "intents": [{"damage": 20, "hits": 1}]}],
    )
    bd_act = next(a for a in legal_actions(st_bd_pc) if a.kind == "play_card" and a.args["card_index"] == 0)
    # Precise Cut directly kills 9-HP enemy; Blade Dance first would add Shivs and only deal 5!
    assert choose_turn_survival(st_bd_pc, pol_v4, bd_act).args["card_index"] == 1

    # P1-7b: 8-card hand where Precise Cut previews 0 recovers positive damage after playing Deflects!
    zero_pc_hand = [
        {"id": "CARD.PRECISE_CUT", "type": "Attack", "target_type": "AnyEnemy", "cost": 0, "stats": {"damage": 0, "extradamage": 2}},
        *[
            {"id": "CARD.DEFLECT", "type": "Skill", "target_type": "Self", "cost": 0, "stats": {"block": 2}}
            for _ in range(7)
        ],
    ]
    st_zero_pc = _base_combat(
        hp=5,
        energy=0,
        hand=zero_pc_hand,
        enemies=[{"id": "MONSTER.A", "hp": 7, "max_hp": 40, "intents": [{"damage": 20, "hits": 1}]}],
    )
    best_zpc, _ = _search_survival_lines(st_zero_pc, pol_v4, legal_actions(st_zero_pc))
    assert best_zpc[0] == 1 and best_zpc[1] == 1


def test_p2_review_poison_scoring_probes_events_shop_null_id_and_quests():
    pol_v4 = EncounterPolicy(
        RunWeights(),
        scorer_fixes=True,
        act2_mechanics=True,
        enemy_mechanics=True,
        card_potion_mechanics=True,
        combat_fixes_v4=True,
    )
    # P2-1: 6-HP enemy with 9 Poison -> Deadly Poison has small cost penalty only (no huge negative overshoot,
    # and End Turn wins); Fire Potion does NOT burn against doomed enemy; Constrict Strangler still credits direct kill.
    st_doomed = _base_combat(
        hp=50,
        energy=1,
        hand=[{"id": "CARD.DEADLY_POISON", "type": "Skill", "target_type": "AnyEnemy", "cost": 1, "stats": {"poisonpower": 5}}],
        potions=[{"index": 0, "id": "POTION.FIRE_POTION", "can_use": True, "target_type": "AnyEnemy", "vars": {"Damage": 20}}],
        enemies=[{"id": "MONSTER.A", "hp": 6, "max_hp": 40, "powers": [{"id": "POWER.POISON_POWER", "amount": 9}], "intents": [{"damage": 10, "hits": 1}]}],
    )
    acts_d = legal_actions(st_doomed)
    scores_d = pol_v4.combat_scores(st_doomed, acts_d)
    assert -0.5 <= scores_d[0] <= 0.0
    assert pol_v4.combat(st_doomed, acts_d).kind == "end_turn"

    # P2-3: Two same-ID same-cost cards with different upgrades stay distinct in fallback probes
    st_probes = _base_combat(
        hp=1,
        energy=1,
        hand=[
            {"id": "CARD.STRIKE_SILENT", "type": "Attack", "target_type": "AnyEnemy", "cost": 1, "upgrades": 0, "stats": {"damage": 6}},
            {"id": "CARD.STRIKE_SILENT", "type": "Attack", "target_type": "AnyEnemy", "cost": 1, "upgrades": 1, "stats": {"damage": 9}},
        ],
        enemies=[{"id": "MONSTER.A", "hp": 9, "max_hp": 40, "intents": [{"damage": 20, "hits": 1}]}],
    )
    chosen_probe = choose_turn_survival(st_probes, pol_v4, next(a for a in legal_actions(st_probes) if a.kind == "end_turn"))
    assert chosen_probe.kind == "play_card" and chosen_probe.args["card_index"] == 1

    # P2-4: Abyssal Baths gain Max HP before taking Damage; Regret wording avoids false positive
    baths_opt = {"description": "Gain {MaxHp} Max HP. Take {Damage} damage.", "vars": {"MaxHp": 2, "Damage": 3}}
    assert _event_terms(baths_opt, 3, 70, 100, event_fixes_v4=True)["danger"] == 0.0
    assert _event_terms(baths_opt, 1, 70, 100, event_fixes_v4=True)["danger"] == 1.0
    assert _event_terms({"description": "Regrettably, you cannot proceed."}, 50, 70, 100, event_fixes_v4=True)["curse"] == 0.0
    assert _event_terms({"description": "Add [red]Regret[/red] to your [gold]Deck[/gold]."}, 50, 70, 100, event_fixes_v4=True)["curse"] == 1.0

    # P2-7: shop_fixes_v4=False must stay invariant and not crash on null ID shop cards
    shop_null = {
        "runtime_identity": IDENTITY,
        "decision": "shop",
        "context": {"act": 1, "floor": 5},
        "player": {"hp": 70, "max_hp": 70, "gold": 100, "potions": [], "deck": []},
        "card_removal_cost": 100,
        "cards": [{"index": 0, "id": None, "name": "Mystery", "cost": 50, "is_stocked": True}],
        "relics": [],
        "potions": [],
    }
    assert merchant_choice(shop_null, lambda c: 20.0, reserve=1.0, permanent=1.1, shop_fixes_v4=False).kind == "buy_card"
    assert merchant_choice(shop_null, lambda c: 20.0, reserve=1.0, permanent=1.1, shop_fixes_v4=True).kind == "buy_card"

    # P2-5: potion_capacity=False matches potion_capacity=True (counts empty-belt +2.7 once across 2 potions)
    shop_no_cap = {
        "runtime_identity": IDENTITY,
        "decision": "shop",
        "context": {"act": 1, "floor": 13},
        "player": {"hp": 70, "max_hp": 70, "gold": 95, "max_potions": 2, "potions": [], "deck": []},
        "card_removal_cost": 90,
        "cards": [],
        "relics": [{"index": 0, "name": "Test Relic", "cost": 90, "is_stocked": True, "description": ""}],
        "potions": [
            {"index": 0, "id": "POTION.P0", "name": "Med Pot 0", "cost": 45, "is_stocked": True, "can_procure": True, "description": ""},
            {"index": 1, "id": "POTION.P1", "name": "Med Pot 1", "cost": 45, "is_stocked": True, "can_procure": True, "description": ""},
        ],
    }
    assert merchant_choice(shop_no_cap, lambda c: -10.0, reserve=1.0, permanent=1.1, gold_curve=True, potion_capacity=False, shop_fixes_v4=True).kind == "buy_relic"

    # P2-6: DeckPolicy protects Spoils Map (Quest) even when optional_selections=False across remove & transform
    quest = {"index": 0, "id": "CARD.SPOILS_MAP", "name": "Spoils Map", "type": "Quest", "cost": 0, "rarity": "Quest"}
    strike = {"index": 1, "id": "CARD.STRIKE_SILENT", "name": "Strike", "type": "Attack", "cost": 1, "rarity": "Basic", "stats": {"damage": 6}}
    dp = DeckPolicy(
        {
            "version": 1,
            "runtime_identity": IDENTITY,
            "prompt_aware": True,
            "optional_selections": False,
            "merchant": {"shop_fixes_v4": True},
        }
    )
    for prompt_goal in ("remove", "transform"):
        dp.prompt = prompt_goal
        sel = dp.choose(
            {
                "runtime_identity": IDENTITY,
                "decision": "card_select",
                "in_combat": False,
                "min_select": 1,
                "max_select": 2,
                "context": {"act": 1, "floor": 4},
                "player": {"hp": 70, "max_hp": 70, "deck": [quest, strike]},
                "cards": [quest, strike],
            },
            lambda s: None,
        )
        assert sel.args["indices"] == "1"


def test_rereview_p1_fastpath_strength_giga_burst_volley_and_empty_draw_piles():
    pol_v4 = EncounterPolicy(
        RunWeights(),
        scorer_fixes=True,
        act2_mechanics=True,
        enemy_mechanics=True,
        card_potion_mechanics=True,
        combat_fixes_v4=True,
    )
    # Re-review P1-1a: Fast path must NOT accept duplicated Strike vs Thorns 8 (16 >= 15 HP)
    st_dup_thorns = _base_combat(
        hp=15,
        energy=1,
        player_powers=[
            {"id": "POWER.DUPLICATION_POWER", "amount": 1},
            {"id": "POWER.GIGANTIFICATION_POWER", "amount": 1},
        ],
        hand=[{"id": "CARD.STRIKE_SILENT", "type": "Attack", "target_type": "AnyEnemy", "cost": 1, "stats": {"damage": 18}}],
        enemies=[{"id": "MONSTER.A", "hp": 40, "max_hp": 40, "powers": [{"id": "POWER.THORNS_POWER", "amount": 8}], "intents": []}],
    )
    strike_act = next(a for a in legal_actions(st_dup_thorns) if a.kind == "play_card")
    assert choose_turn_survival(st_dup_thorns, pol_v4, strike_act).kind == "end_turn"

    # Re-review P1-1b: Fast path must NOT accept duplicated Bloodletting (3 * 2 = 6 >= 5 HP)
    st_dup_blood = _base_combat(
        hp=5,
        energy=1,
        player_powers=[{"id": "POWER.DUPLICATION_POWER", "amount": 1}],
        hand=[{"id": "CARD.BLOODLETTING", "type": "Skill", "target_type": "Self", "cost": 0, "stats": {"hploss": 3, "energy": 2}}],
        enemies=[{"id": "MONSTER.A", "hp": 40, "max_hp": 40, "intents": []}],
    )
    blood_act = next(a for a in legal_actions(st_dup_blood) if a.kind == "play_card")
    assert choose_turn_survival(st_dup_blood, pol_v4, blood_act).kind == "end_turn"

    # Re-review P1-2a: Strength Potion (+2) -> Gigantified Strike (18) deals (6+2)*3 = 24 and clears!
    st_str_giga = _base_combat(
        hp=10,
        energy=1,
        player_powers=[{"id": "POWER.GIGANTIFICATION_POWER", "amount": 1}],
        hand=[{"id": "CARD.STRIKE_SILENT", "type": "Attack", "target_type": "AnyEnemy", "cost": 1, "stats": {"damage": 18}}],
        potions=[{"index": 0, "id": "POTION.STRENGTH_POTION", "can_use": True, "target_type": "Self", "vars": {"StrengthPower": 2}}],
        enemies=[{"id": "MONSTER.A", "hp": 24, "max_hp": 40, "intents": [{"damage": 20, "hits": 1}]}],
    )
    strike_first = next(a for a in legal_actions(st_str_giga) if a.kind == "play_card")
    assert choose_turn_survival(st_str_giga, pol_v4, strike_first).kind == "use_potion"

    # Re-review P1-2b: Duplication + Burst -> Defend -> Defend yields 20 Block and survives!
    st_dup_burst = _base_combat(
        hp=1,
        energy=3,
        player_powers=[{"id": "POWER.DUPLICATION_POWER", "amount": 1}],
        hand=[
            {"id": "CARD.BURST", "type": "Skill", "target_type": "Self", "cost": 1, "stats": {"skills": 1}},
            {"id": "CARD.DEFEND_SILENT", "type": "Skill", "target_type": "Self", "cost": 1, "stats": {"block": 5}},
            {"id": "CARD.DEFEND_SILENT", "type": "Skill", "target_type": "Self", "cost": 1, "stats": {"block": 5}},
        ],
        enemies=[{"id": "MONSTER.A", "hp": 40, "max_hp": 40, "intents": [{"damage": 20, "hits": 1}]}],
    )
    best_db, _ = _search_survival_lines(st_dup_burst, pol_v4, legal_actions(st_dup_burst))
    best_db_burst, _ = _search_survival_lines(
        st_dup_burst, pol_v4, legal_actions(st_dup_burst), forced_first=0
    )
    assert best_db[0] == 1 and best_db_burst[0] == 1
    assert (
        choose_turn_survival(
            st_dup_burst, pol_v4, next(a for a in legal_actions(st_dup_burst) if a.kind == "end_turn")
        ).kind
        == "play_card"
    )

    # Re-review P1-3: Random-target Volley (2E) at 5 HP vs two Thorns-8 enemies picks end_turn
    st_volley = _base_combat(
        hp=5,
        energy=2,
        hand=[{"id": "CARD.VOLLEY", "type": "Attack", "target_type": "RandomEnemy", "cost": 0, "costs_x": True, "stats": {"damage": 10}}],
        enemies=[
            {"id": "MONSTER.A", "hp": 50, "max_hp": 50, "powers": [{"id": "POWER.THORNS_POWER", "amount": 8}], "intents": []},
            {"id": "MONSTER.B", "hp": 50, "max_hp": 50, "powers": [{"id": "POWER.THORNS_POWER", "amount": 8}], "intents": []},
        ],
    )
    volley_act = next(a for a in legal_actions(st_volley) if a.kind == "play_card")
    assert choose_turn_survival(st_volley, pol_v4, volley_act).kind == "end_turn"

    # Re-review P1-4: Precise Cut with empty draw+discard piles does not invent phantom Adrenaline draws
    st_empty_piles = _base_combat(
        hp=5,
        energy=0,
        hand=[
            {"id": "CARD.ADRENALINE", "type": "Skill", "target_type": "Self", "cost": 0, "stats": {"energy": 1, "cards": 2}},
            {"id": "CARD.PRECISE_CUT", "type": "Attack", "target_type": "AnyEnemy", "cost": 0, "stats": {"damage": 0, "extradamage": 2}},
            *[
                {"id": "CARD.WOUND", "type": "Status", "target_type": "Self", "cost": 1, "can_play": False, "keywords": ["Unplayable"], "stats": {}}
                for _ in range(6)
            ],
        ],
        potions=[{"index": 0, "id": "POTION.BLOCK_POTION", "can_use": True, "target_type": "Self", "vars": {"Block": 12}}],
        enemies=[{"id": "MONSTER.A", "hp": 1, "max_hp": 40, "intents": [{"damage": 12, "hits": 1}]}],
    )
    st_empty_piles["draw_pile_count"] = 0
    st_empty_piles["discard_pile_count"] = 0
    best_ep, _ = _search_survival_lines(st_empty_piles, pol_v4, legal_actions(st_empty_piles))
    assert best_ep[0] == 1 and best_ep[1] == 1 and best_ep[2] == 0
    assert choose_turn_survival(st_empty_piles, pol_v4, next(a for a in legal_actions(st_empty_piles) if a.kind == "use_potion")).kind == "play_card"


def test_rereview_p2_constrict_buffer_flask_cap_and_shadowmeld_greedy():
    pol_v4 = EncounterPolicy(
        RunWeights(),
        scorer_fixes=True,
        act2_mechanics=True,
        enemy_mechanics=True,
        card_potion_mechanics=True,
        combat_fixes_v4=True,
    )
    # P2-a1: Poison+Accelerant already dooms Buffer-1 Strangler -> Buffer stops Strike -> NO bogus Constrict mitigation!
    st_str_buf = _base_combat(
        hp=30,
        energy=1,
        player_powers=[
            {"id": "POWER.CONSTRICT_POWER", "amount": 10},
            {"id": "POWER.ACCELERANT_POWER", "amount": 1},
        ],
        hand=[{"id": "CARD.STRIKE_SILENT", "type": "Attack", "target_type": "AnyEnemy", "cost": 1, "stats": {"damage": 6}}],
        enemies=[{"id": "MONSTER.SLITHERING_STRANGLER", "hp": 6, "max_hp": 50, "powers": [{"id": "POWER.POISON_POWER", "amount": 20}, {"id": "POWER.BUFFER_POWER", "amount": 1}], "intents": []}],
    )
    # P2-a2: Direct kill of Poison-doomed Strangler (no attack intent) DOES credit Constrict mitigation when Unbuffered!
    st_str_kill = {**st_str_buf, "enemies": [{"index": 0, "id": "MONSTER.SLITHERING_STRANGLER", "hp": 6, "max_hp": 50, "block": 0, "powers": [{"id": "POWER.POISON_POWER", "amount": 20}], "intents": []}]}
    s_buf = pol_v4.combat_scores(st_str_buf, legal_actions(st_str_buf))[0]
    s_kill = pol_v4.combat_scores(st_str_kill, legal_actions(st_str_kill))[0]
    assert s_buf < 0.0 and s_kill > 5.0

    # P2-b: Bouncing Flask with enemy_mechanics=False & Hard to Kill 2 does not award uncapped kill credit
    pol_no_em = EncounterPolicy(RunWeights(), scorer_fixes=True, combat_fixes_v4=True)
    st_flask_cap = _base_combat(
        hp=40,
        energy=2,
        hand=[{"id": "CARD.BOUNCING_FLASK", "type": "Skill", "target_type": "RandomEnemy", "cost": 2, "stats": {"poisonpower": 3, "repeat": 3}}],
        enemies=[{"id": "MONSTER.A", "hp": 4, "max_hp": 50, "powers": [{"id": "POWER.POISON_POWER", "amount": 9}, {"id": "POWER.HARD_TO_KILL_POWER", "amount": 2}], "intents": [{"damage": 15, "hits": 1}]}],
    )
    assert pol_no_em.combat_scores(st_flask_cap, legal_actions(st_flask_cap))[0] == pol_v4.combat_scores(st_flask_cap, legal_actions(st_flask_cap))[0]

    # P2-c: Shadowmeld boosts Fortifier's greedy score (5 Block vs 25 incoming)
    st_sm_0 = _base_combat(
        hp=1,
        block=5,
        energy=0,
        potions=[{"index": 0, "id": "POTION.FORTIFIER", "can_use": True, "target_type": "Self", "vars": {}}],
        enemies=[{"id": "MONSTER.A", "hp": 50, "max_hp": 50, "intents": [{"damage": 25, "hits": 1}]}],
    )
    st_sm_1 = {**st_sm_0, "player_powers": [{"id": "POWER.SHADOWMELD_POWER", "amount": 1}]}
    assert pol_v4.combat_scores(st_sm_1, legal_actions(st_sm_1))[0] > pol_v4.combat_scores(st_sm_0, legal_actions(st_sm_0))[0]


def test_shop_fixes_v4_empty_belt_bonus_modes():
    # With potion_capacity=False, shop_fixes_v4 must preserve the empty-belt bonus on buy_potion.
    shop_greedy = {
        "runtime_identity": IDENTITY,
        "decision": "shop",
        "context": {"act": 1, "floor": 6},
        "player": {"hp": 70, "max_hp": 70, "gold": 80, "potions": [], "deck": []},
        "card_removal_cost": 100,
        "cards": [],
        "relics": [],
        "potions": [
            {
                "index": 0,
                "id": "POTION.BLOCK_POTION",
                "name": "Block Potion",
                "cost": 50,
                "is_stocked": True,
                "can_procure": True,
                "description": "Gain 12 Block.",
            }
        ],
    }
    act_greedy = merchant_choice(
        shop_greedy, lambda c: 0.0, reserve=1.0, permanent=1.1, gold_curve=True, potion_capacity=False, shop_fixes_v4=True
    )
    assert act_greedy.kind == "buy_potion"

    # With potion_capacity=True and 2 cheap potions (+1 empty bonus max once), total value of buying both:
    # legacy gives 2*(2.3+2.7+2.0)=14.0; fixed gives (2.3+2.7+2.0) + (2.3+2.0) = 11.3.
    # Plain relic has value 12.0 * 1.1 = 13.2 at same cost 90 so fixed prefers relic over 2 mediocre potions.
    shop_two_pots = {
        "runtime_identity": IDENTITY,
        "decision": "shop",
        "context": {"act": 1, "floor": 13},
        "player": {"hp": 70, "max_hp": 70, "gold": 95, "max_potions": 2, "potions": [], "deck": []},
        "card_removal_cost": 90,
        "cards": [],
        "relics": [{"index": 0, "name": "Test Relic", "cost": 90, "is_stocked": True, "description": ""}],
        "potions": [
            {"index": 0, "id": "POTION.P0", "name": "Med Pot 0", "cost": 45, "is_stocked": True, "can_procure": True, "description": ""},
            {"index": 1, "id": "POTION.P1", "name": "Med Pot 1", "cost": 45, "is_stocked": True, "can_procure": True, "description": ""},
        ],
    }
    act_legacy = merchant_choice(
        shop_two_pots, lambda c: -10.0, reserve=1.0, permanent=1.1, gold_curve=True, potion_capacity=True, shop_fixes_v4=False
    )
    act_fixed = merchant_choice(
        shop_two_pots, lambda c: -10.0, reserve=1.0, permanent=1.1, gold_curve=True, potion_capacity=True, shop_fixes_v4=True
    )
    assert act_legacy.kind == "buy_potion"
    assert act_fixed.kind == "buy_relic"


def test_build_batch1_all_v2_p1_v4_and_mech_v3_invariance(tmp_path):
    root = Path(__file__).resolve().parents[1]
    build = runpy.run_path(str(root / "scripts/build-batch1-challengers.py"))["build_batch1_bundle"]
    base = root / "releases/silent-a10-mecha-knight/challenger/policy.json"

    p_v4 = build(base, tmp_path / "v4", profile="all_v2_p1_v4")
    role_v4, opts_v4 = load_bundle(p_v4)
    assert role_v4
    RunWeights.load(opts_v4["weights"])
    em_v4 = EncounterModel.load(opts_v4["encounter_model"])
    sm_v4 = StrategyModel.load(opts_v4["strategy_model"])
    dp_v4 = DeckPolicy.load(opts_v4["deck_model"])
    RoomModel.load(opts_v4["room_model"])
    RoomModel.load(opts_v4["late_room_model"])
    assert em_v4.selection_fixes_v4 is True
    assert em_v4.combat_fixes_v4 is True
    assert sm_v4.event_fixes_v4 is True
    assert sm_v4.deck_size_penalty == 0.0
    assert (dp_v4.merchant or {}).get("shop_fixes_v4") is True

    p_v3 = build(base, tmp_path / "v3", profile="all_v2_mech_v3")
    _, opts_v3 = load_bundle(p_v3)
    enc_v3 = json.loads(opts_v3["encounter_model"].read_bytes())
    strat_v3 = json.loads(opts_v3["strategy_model"].read_bytes())
    deck_v3 = json.loads(opts_v3["deck_model"].read_bytes())
    assert enc_v3.get("enemy_mechanics") is True
    assert enc_v3.get("card_potion_mechanics") is True
    assert "selection_fixes_v4" not in enc_v3
    assert "combat_fixes_v4" not in enc_v3
    assert strat_v3.get("deck_size_penalty") == 0.12
    assert "event_fixes_v4" not in strat_v3
    assert "shop_fixes_v4" not in (deck_v3.get("merchant") or {})
