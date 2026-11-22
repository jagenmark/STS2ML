import json
from pathlib import Path
import runpy

import pytest

from sts2rl.deck_policy import DeckPolicy
from sts2rl.encounter import EncounterModel, EncounterPolicy
from sts2rl.mecha_knight import item_features
from sts2rl.merchant import marginal_removal_value, merchant_choice
from sts2rl.native import legal_actions
from sts2rl.run_bundle import load_bundle
from sts2rl.run_policy import IDENTITY, RunPolicy, RunWeights
from sts2rl.selections import selection_goal
from sts2rl.turn_planning import choose_turn, choose_turn_survival
from test_mecha_knight import knight
from test_teacher_status import hand


def _base_encounter_cfg(**extra):
    return {
        "version": 1,
        "runtime_identity": IDENTITY,
        "default": "engine",
        **extra,
    }


def test_lethal_survival_overrides_greedy_and_beam_while_preserving_legacy_defaults():
    obs = hand(
        ("CARD.BIG_HIT", "AnyEnemy", {"damage": 60}),
        ("CARD.DEFEND_SILENT", "Self", {"block": 5}),
    )
    obs["hand"][0].update(type="Attack", cost=1)
    obs["hand"][1].update(type="Skill", cost=1)
    obs["energy"] = 1
    obs["player"].update(hp=5, block=0)
    obs["enemies"][0].update(hp=100, max_hp=100, intents=[{"type": "Attack", "total_damage": 5}])

    base = RunPolicy(RunWeights())
    legacy = EncounterModel(_base_encounter_cfg())
    # Historical greedy model keeps its exact legacy behavior (picks the 60-damage attack).
    assert legacy.choose(obs, base).args["card_index"] == 0
    # Historical beam charges only a flat -30 death penalty, so 60-damage beats Defend.
    assert choose_turn(obs, EncounterPolicy(RunWeights(), style="engine")).args["card_index"] == 0

    # Opt-in survival search & survival-priority beam both choose Defend to survive.
    guarded = EncounterModel(_base_encounter_cfg(survival_search=True))
    assert guarded.choose(obs, base).args["card_index"] == 1
    assert (
        choose_turn(
            obs, EncounterPolicy(RunWeights(), style="engine"), survival_priority=True
        ).args["card_index"]
        == 1
    )


def test_survival_search_keeps_greedy_when_continuation_survives_without_wasting_potion():
    obs = hand(
        ("CARD.BIG_HIT", "AnyEnemy", {"damage": 35}),
        ("CARD.DEFEND_SILENT", "Self", {"block": 6}),
    )
    obs["hand"][0].update(type="Attack", cost=1)
    obs["hand"][1].update(type="Skill", cost=1)
    obs["energy"] = 2
    obs["player"].update(
        hp=5,
        block=0,
        potions=[
            {
                "id": "POTION.BLOCK_POTION",
                "index": 0,
                "can_use": True,
                "target_type": "Self",
                "vars": {"Block": 12},
            }
        ],
    )
    obs["enemies"][0].update(hp=50, max_hp=50, intents=[{"type": "Attack", "total_damage": 6}])
    actor = EncounterPolicy(RunWeights(), style="engine")
    actions = legal_actions(obs)
    proposed = actor.combat(obs, actions)
    # Greedy proposes Big Hit first; since Big Hit + Defend survives with 2 energy, keep it!
    assert proposed.kind == "play_card" and proposed.args["card_index"] == 0
    assert choose_turn_survival(obs, actor, proposed) == proposed


def test_survival_beam_handles_two_card_lethal_x_cost_afterimage_and_potion_conservation():
    # 1. X-cost card exported with cost=0 must consume all energy so beam cannot chain a paid card.
    obs = hand(
        ("CARD.SKEWER", "AnyEnemy", {"damage": 7}),
        ("CARD.DEFEND_SILENT", "Self", {"block": 6}),
    )
    obs["hand"][0].update(type="Attack", cost=0, costs_x=True)
    obs["hand"][1].update(type="Skill", cost=1)
    obs["energy"] = 1
    obs["player"].update(hp=5, block=0)
    obs["enemies"][0].update(hp=50, max_hp=50, intents=[{"type": "Attack", "total_damage": 6}])
    actor = EncounterPolicy(RunWeights(), style="engine")
    # Skewer spends all energy (1 -> 0), so Defend cannot be played after it; must play Defend.
    assert choose_turn(obs, actor, survival_priority=True).args["card_index"] == 1

    # 2. Safe lethal clear prefers conserving a potion when cards alone kill cleanly.
    obs2 = hand(
        ("CARD.STRIKE_SILENT", "AnyEnemy", {"damage": 6}),
        ("CARD.STRIKE_SILENT", "AnyEnemy", {"damage": 6}),
    )
    obs2["hand"][0].update(type="Attack", cost=1)
    obs2["hand"][1].update(type="Attack", cost=1)
    obs2["energy"] = 2
    obs2["player"].update(
        hp=5,
        block=0,
        potions=[
            {
                "id": "POTION.FIRE_POTION",
                "index": 0,
                "can_use": True,
                "target_type": "AnyEnemy",
                "vars": {"Damage": 20},
            }
        ],
    )
    obs2["enemies"][0].update(hp=12, max_hp=12, intents=[{"type": "Attack", "total_damage": 15}])
    choice = choose_turn(obs2, actor, survival_priority=True)
    assert choice.kind == "play_card"

    # 3. After Image adds +1 block per played card, letting 2 zero/one-cost cards survive lethal.
    obs3 = hand(
        ("CARD.SLICE", "AnyEnemy", {"damage": 6}),
        ("CARD.DEFEND_SILENT", "Self", {"block": 4}),
    )
    obs3["hand"][0].update(type="Attack", cost=0)
    obs3["hand"][1].update(type="Skill", cost=1)
    obs3["energy"] = 1
    obs3["player"].update(hp=2, block=0)
    obs3["player_powers"] = [{"id": "POWER.AFTERIMAGE_POWER", "amount": 1}]
    obs3["enemies"][0].update(hp=50, max_hp=50, intents=[{"type": "Attack", "total_damage": 7}])
    # Slice (+1) + Defend (4+1) = 6 block -> 1 damage -> survives at 1 HP!
    choice3 = choose_turn(obs3, actor, survival_priority=True)
    assert choice3.kind == "play_card"

    # 4. One-step projection uses EncounterPolicy's 0.74 cost exponent without double-counting.
    from sts2rl.turn_planning import _search_survival_lines

    obs4 = hand(
        ("CARD.DASH", "AnyEnemy", {"damage": 10, "block": 10}),
        ("CARD.STRIKE_SILENT", "AnyEnemy", {"damage": 6}),
    )
    obs4["hand"][0].update(type="Attack", cost=2)
    obs4["hand"][1].update(type="Attack", cost=1)
    obs4["energy"] = 2
    obs4["player"].update(hp=50, block=0)
    obs4["enemies"][0].update(hp=80, max_hp=80, intents=[{"type": "Attack", "total_damage": 10}])
    actions4 = legal_actions(obs4)
    scores4 = actor.combat_scores(obs4, actions4)
    _, by_first = _search_survival_lines(obs4, actor, actions4, width=8, depth=1)
    # 1-step utility of Dash (cost=2) should equal scores[0] * 2**0.74 (zero double-counting).
    assert by_first[0][3] == pytest.approx(scores4[0] * (2**0.74), rel=1e-5)


def test_survival_beam_respects_poison_kill_revive_and_escape_on_unavoidable_death():
    # 1. Poison lethal cancels enemy attack, while unavoidable lethal prefers a draw escape.
    obs = hand(
        ("CARD.DEADLY_POISON", "AnyEnemy", {"poisonpower": 5}),
        ("CARD.DEFEND_SILENT", "Self", {"block": 5}),
    )
    obs["hand"][0].update(type="Skill", cost=1)
    obs["hand"][1].update(type="Skill", cost=1)
    obs["energy"] = 1
    obs["player"].update(hp=5, block=0)
    obs["enemies"][0].update(
        hp=9,
        max_hp=20,
        powers=[{"id": "POWER.POISON_POWER", "amount": 1}],
        intents=[{"type": "Attack", "total_damage": 20}],
    )
    obs["player_powers"] = [{"id": "POWER.ACCELERANT_POWER", "amount": 1}]
    # 6 poison with Accelerant 1 -> ticks 6 + 5 = 11 >= 9 HP -> enemy dies before attacking!
    actor = EncounterPolicy(RunWeights(), style="engine")
    assert choose_turn(obs, actor, survival_priority=True).args["card_index"] == 0

    # 2. If enemy has ILLUSION (revive), killing does not clear the fight, and unavoidable death prefers draw.
    obs2 = hand(
        ("CARD.STRIKE_SILENT", "AnyEnemy", {"damage": 6}),
        ("CARD.ACROBATICS", "Self", {"cards": 3}),
    )
    obs2["hand"][0].update(type="Attack", cost=1)
    obs2["hand"][1].update(type="Skill", cost=1)
    obs2["energy"] = 1
    obs2["player"].update(hp=5, block=0)
    obs2["enemies"][0].update(
        hp=50,
        max_hp=50,
        powers=[{"id": "POWER.ILLUSION_POWER", "amount": 1}],
        intents=[{"type": "Attack", "total_damage": 30}],
    )
    assert choose_turn(obs2, actor, survival_priority=True).args["card_index"] == 1


def test_silent_scorer_fixes_gamble_sly_hidden_daggers_envenom_and_flask():
    # 1. Calculated Gamble on a 10-card hand should credit redrawing 9 cards, not 1.
    cards = [("CARD.CALCULATED_GAMBLE", "Self", {})] + [
        ("CARD.STRIKE_SILENT", "AnyEnemy", {"damage": 6}) for _ in range(9)
    ]
    obs = hand(*cards)
    obs["hand"][0].update(type="Skill", cost=0)
    obs["energy"] = 3
    old = EncounterPolicy(RunWeights(), style="engine", scorer_fixes=False)
    new = EncounterPolicy(RunWeights(), style="engine", scorer_fixes=True)
    actions = legal_actions(obs)
    assert new.combat_scores(obs, actions)[0] > old.combat_scores(obs, actions)[0] + 15.0

    # 2. Sly discarder should not credit discarding itself, but still credits a second Sly copy.
    obs_sly = hand(("CARD.PREPARED", "Self", {"cards": 1}))
    obs_sly["hand"][0].update(type="Skill", cost=0, keywords=["Sly"])
    sly_actions = legal_actions(obs_sly)
    # Without another Sly card, scorer_fixes removes self-discard credit.
    assert new.combat_scores(obs_sly, sly_actions)[0] < old.combat_scores(obs_sly, sly_actions)[0]
    # Add a second Sly card: now scorer_fixes gives positive discard credit for the other copy.
    obs_sly2 = hand(
        ("CARD.PREPARED", "Self", {"cards": 1}),
        ("CARD.REFLEX", "Self", {"cards": 2}),
    )
    obs_sly2["hand"][0].update(type="Skill", cost=0, keywords=["Sly"])
    obs_sly2["hand"][1].update(type="Skill", cost=0, keywords=["Sly"])
    sly2_actions = legal_actions(obs_sly2)
    assert new.combat_scores(obs_sly2, sly2_actions)[0] > new.combat_scores(obs_sly, sly_actions)[0]

    # 3. Hidden Daggers on a 10-card hand frees slots via discard before generating Shivs.
    hd_cards = [("CARD.HIDDEN_DAGGERS", "Self", {"cards": 2, "shivs": 2})] + [
        ("CARD.STRIKE_SILENT", "AnyEnemy", {"damage": 6}) for _ in range(9)
    ]
    obs_hd = hand(*hd_cards)
    obs_hd["hand"][0].update(type="Skill", cost=0)
    hd_actions = legal_actions(obs_hd)
    # Old caps shivs at 10 - 10 + 1 = 1; new frees 2 discards -> caps at min(2, 3) = 2 Shivs.
    assert new.combat_scores(obs_hd, hd_actions)[0] > old.combat_scores(obs_hd, hd_actions)[0] + 2.0

    # 4. Envenom walks hits sequentially against block and Artifact (3x4 into 6 block = 2 hits, not 3).
    obs_env = hand(("CARD.MULTI", "AnyEnemy", {"damage": 4, "calculatedhits": 3}))
    obs_env["hand"][0].update(type="Attack", cost=1)
    obs_env["player_powers"] = [{"id": "POWER.ENVENOM_POWER", "amount": 2}]
    obs_env["enemies"][0].update(hp=50, max_hp=50, block=6, powers=[])
    env_actions = legal_actions(obs_env)
    # Old credits 3 hits * 2 poison = 6 poison; new credits 2 unblocked hits * 2 = 4 poison.
    assert new.combat_scores(obs_env, env_actions)[0] < old.combat_scores(obs_env, env_actions)[0]

    # 5. Bouncing Flask uses exact expected landed poison against Artifact without double-dividing.
    obs_flask = hand(("CARD.BOUNCING_FLASK", "RandomEnemy", {"poisonpower": 3, "repeat": 3}))
    obs_flask["hand"][0].update(type="Skill", cost=2)
    e0 = {**obs_flask["enemies"][0], "index": 0, "hp": 50, "max_hp": 50, "powers": [{"id": "POWER.ARTIFACT_POWER", "amount": 1}]}
    e1 = {**obs_flask["enemies"][0], "index": 1, "hp": 50, "max_hp": 50, "powers": [{"id": "POWER.ARTIFACT_POWER", "amount": 1}]}
    obs_flask["enemies"] = [e0, e1]
    flask_old = EncounterPolicy(RunWeights(), style="engine", mechanics=True, scorer_fixes=False)
    flask_new = EncounterPolicy(RunWeights(), style="engine", mechanics=True, scorer_fixes=True)
    fa = legal_actions(obs_flask)
    # Old subtracts Artifact as if all 3 bounces hit each enemy (3-1=2 bounces per enemy = 6 poison);
    # exact expectation per enemy is 1.875 poison (sum 3.75 across 2 enemies).
    assert 0 < flask_new.combat_scores(obs_flask, fa)[0] < flask_old.combat_scores(obs_flask, fa)[0]


def test_act_coverage_defaults_enable_in_act1_and_respect_plan_overrides():
    obs = hand(("CARD.STRIKE_SILENT", "AnyEnemy", {"damage": 6}))
    obs["context"].update(act=1, room_type="Monster")
    cfg = _base_encounter_cfg(
        mechanics_from_act=1,
        persistent_from_act=1,
        potion_effects_from_act=1,
        draw_potions_from_act=1,
    )
    model = EncounterModel(cfg)
    model.choose(obs, RunPolicy(RunWeights()))
    assert model.actor.mechanics
    assert model.actor.persistent
    assert model.actor.potion_effects
    assert model.actor.draw_potions

    # Explicit false in a hallway plan overrides the act default.
    obs["context"].update(act=3, room_type="Monster")
    cfg["act3_hallways"] = {
        "plans": {"plain": {"style": "guard", "potion_effects": False, "draw_potions": False}},
        "by_room": {"Monster": "plain"},
    }
    model2 = EncounterModel(cfg)
    model2.choose(obs, RunPolicy(RunWeights()))
    assert model2.actor.mechanics and model2.actor.persistent
    assert not model2.actor.potion_effects and not model2.actor.draw_potions


def test_mecha_v2_burn_avoids_double_credit_and_tools_of_the_trade_immediate_discard():
    s = knight()
    s["player"].update(block=0, potions=[])
    base = s["hand"][0]
    s["hand"] = [
        {
            **base,
            "id": "CARD.SURVIVOR",
            "type": "Skill",
            "target_type": "Self",
            "index": 0,
            "cost": 1,
            "stats": {"calculatedblock": 8},
        },
        {
            **base,
            "id": "CARD.TOOLS_OF_THE_TRADE",
            "type": "Power",
            "target_type": "Self",
            "index": 1,
            "cost": 1,
            "stats": {},
        },
        {
            **base,
            "id": "CARD.BURN",
            "type": "Status",
            "index": 2,
            "can_play": False,
            "stats": {"damage": 2},
        },
    ]
    actions = legal_actions(s)
    old = list(item_features(s, actions, "windup", v2_burn=False))
    new = list(item_features(s, actions, "windup", v2_burn=True))
    # Survivor already blocks the 2-damage Burn: old double-credits (4), new caps at 2.
    assert old[0]["burn"] == 4.0 and new[0]["burn"] == 2.0
    # Tools of the Trade discards next turn, not this Windup turn.
    assert old[1]["burn"] == 2.0 and new[1]["burn"] == 0.0


def test_merchant_marginal_removal_gold_curve_and_potion_capacity():
    strike = {"id": "CARD.STRIKE_SILENT", "type": "Attack", "rarity": "Basic", "cost": 1, "stats": {"damage": 6}}
    defend = {"id": "CARD.DEFEND_SILENT", "type": "Skill", "rarity": "Basic", "cost": 1, "stats": {"block": 5}}
    bane = {"id": "CARD.ASCENDERS_BANE", "type": "Curse", "rarity": "Curse", "cost": 0}
    deck = [strike] * 6 + [defend] * 6 + [bane]
    model = DeckPolicy({"version": 1, "runtime_identity": IDENTITY})
    ctx = {"act": 1, "floor": 6}
    info = ({"n": len(deck), "power": 0, "attack": 0, "poison": 0, "block": 0, "shiv": 0, "discard": 0, "sly": 0, "aoe": 0, "noxious": 0, "accuracy": 0, "afterimage": 0, "dexterity": 0, "accel": 0}, {"STRIKE_SILENT": 6, "DEFEND_SILENT": 6, "ASCENDERS_BANE": 1})
    def grade(c):
        return model.grade(c, ctx, info)

    shop = {
        "decision": "shop",
        "context": ctx,
        "player": {"hp": 65, "max_hp": 70, "deck": deck, "gold": 900, "potions": []},
        "cards": [],
        "relics": [],
        "potions": [],
        "card_removal_cost": 75,
        "card_removal_available": True,
    }
    # Legacy merchant walks away with 900g and declines a 75g Strike removal!
    assert merchant_choice(shop, grade, reserve=1.0, permanent=1.1).kind == "leave_room"
    # With marginal_removal + gold_curve, it gladly removes a Strike at 900g.
    assert (
        merchant_choice(
            shop,
            grade,
            reserve=1.0,
            permanent=1.1,
            marginal_removal=True,
            gold_curve=True,
            potion_capacity=True,
        ).kind
        == "remove_card"
    )
    assert marginal_removal_value(bane, deck, grade) < -50

    # Potion capacity stops basket planner from treating two potions as simultaneously buyable when only 1 slot is free.
    shop_pot = {
        "decision": "shop",
        "context": {"act": 1, "floor": 14},
        "player": {"hp": 30, "max_hp": 70, "deck": deck, "gold": 120, "potions": [{"id": "POTION.BLOCK_POTION"}], "max_potions": 2},
        "cards": [],
        "relics": [{"index": 0, "is_stocked": True, "cost": 110, "name": "Kunai", "description": "Gain Dexterity."}],
        "potions": [
            {"index": 0, "is_stocked": True, "cost": 50, "can_procure": True, "name": "Fairy in a Bottle", "description": "Revive."},
            {"index": 1, "is_stocked": True, "cost": 50, "can_procure": True, "name": "Ghost in a Jar", "description": "Gain Intangible."},
        ],
    }
    # Without capacity guard, two potions (100g) beat Kunai (110g); with 1 open slot, Kunai beats 1 potion.
    assert (
        merchant_choice(
            shop_pot, grade, reserve=1.0, permanent=1.1, potion_capacity=False
        ).kind
        == "buy_potion"
    )
    assert (
        merchant_choice(
            shop_pot, grade, reserve=1.0, permanent=1.1, potion_capacity=True
        ).kind
        == "buy_relic"
    )


def test_optional_deck_selections_skip_negative_ev_and_separate_prompt_goals():
    # Detailed selection_goal separates transform/remove, duplicate/enchant, and recognizes "remove a card".
    ev = {"decision": "event_choice", "options": [{"index": 0, "description": "Remove a card."}]}
    act = legal_actions(ev)[0]
    assert selection_goal(ev, act) is None
    assert selection_goal(ev, act, detailed=True) == "remove"
    ev["options"][0]["description"] = "Choose a card to Transform."
    assert selection_goal(ev, act, detailed=True) == "transform"
    ev["options"][0]["description"] = "Duplicate a card in your deck."
    assert selection_goal(ev, act, detailed=True) == "duplicate"

    # Optional upgrade prompt with only negative-EV upgrades: legacy picks max_select, opt-in skips!
    bad_card = {
        "index": 0,
        "id": "CARD.STRIKE_SILENT",
        "type": "Attack",
        "cost": 1,
        "stats": {"damage": 6},
        "after_upgrade": {},
    }
    state = {
        "decision": "card_select",
        "runtime_identity": IDENTITY,
        "in_combat": False,
        "context": {"act": 1, "floor": 5},
        "player": {"hp": 60, "max_hp": 70, "deck": [bad_card]},
        "min_select": 0,
        "max_select": 1,
        "cards": [bad_card],
    }
    legacy = DeckPolicy({"version": 1, "runtime_identity": IDENTITY, "prompt_aware": True})
    legacy.to_upgrade = True
    assert legacy.choose(state, RunPolicy(RunWeights())).kind == "select_cards"

    opt = DeckPolicy(
        {
            "version": 1,
            "runtime_identity": IDENTITY,
            "prompt_aware": True,
            "optional_selections": True,
        }
    )
    opt.to_upgrade = True
    assert opt.choose(state, RunPolicy(RunWeights())).kind == "skip_select"

    # Optional removal removes Strike (+) and skips Footwork+ (-).
    footwork = {
        "index": 1,
        "id": "CARD.FOOTWORK",
        "type": "Power",
        "cost": 1,
        "upgrades": 1,
        "stats": {"dexteritypower": 3},
    }
    strike = {
        "index": 0,
        "id": "CARD.STRIKE_SILENT",
        "type": "Attack",
        "rarity": "Basic",
        "cost": 1,
        "stats": {"damage": 6},
    }
    rem_state = {
        **state,
        "player": {"hp": 60, "max_hp": 70, "deck": [strike] * 6 + [footwork] * 4},
        "min_select": 0,
        "max_select": 2,
        "cards": [strike, footwork],
    }
    opt.prompt = "remove"
    picked = opt.choose(rem_state, RunPolicy(RunWeights()))
    assert picked.kind == "select_cards" and picked.args == {"indices": "0"}


def test_checked_in_release_bundles_keep_legacy_flags_and_batch1_builder_freezes_cleanly(tmp_path):
    root = Path(__file__).resolve().parents[1]
    bundle_paths = sorted(root.glob("releases/**/policy.json"))
    assert len(bundle_paths) >= 6
    for path in bundle_paths:
        _, settings = load_bundle(path)
        is_v2_release = "silent-a10-v2-tactics" in path.parts
        if "encounter_model" in settings:
            enc = EncounterModel.load(settings["encounter_model"])
            if is_v2_release:
                assert enc.survival_search and enc.scorer_fixes
                assert enc.overrides.get("THE_KIN_BOSS") == "isolate"
                assert enc.overrides.get("SOUL_FYSH_BOSS") == "isolate"
            else:
                assert not enc.survival_search and not enc.scorer_fixes
                assert enc.potion_effects_from_act == 4 and enc.draw_potions_from_act == 4
        if "deck_model" in settings:
            deck = DeckPolicy.load(settings["deck_model"])
            assert deck.optional_selections == is_v2_release

    builder = runpy.run_path(str(root / "scripts/build-batch1-challengers.py"))["build_batch1_bundle"]
    base = root / "releases/silent-a10-mecha-knight/challenger/policy.json"
    for profile in ("survival", "scorer", "shop", "all"):
        frozen = builder(base, tmp_path / profile, profile=profile)
        role, settings = load_bundle(frozen)
        assert role == "candidate"
        enc = EncounterModel.load(settings["encounter_model"])
        deck = DeckPolicy.load(settings["deck_model"])
        assert enc.survival_search == (profile in ("survival", "all"))
        assert enc.scorer_fixes == (profile in ("scorer", "all"))
        assert enc.mechanics_from_act == (1 if profile in ("scorer", "all") else 4)
        assert deck.optional_selections == (profile in ("shop", "all"))
        merchant_cfg = json.loads(settings["deck_model"].read_text())["merchant"]
        assert merchant_cfg.get("marginal_removal", False) == (profile in ("shop", "all"))
    # Building a single-profile ablation from an already-modified Batch 1 bundle must fail closed.
    with pytest.raises(ValueError, match="clean baseline"):
        builder(tmp_path / "all/policy/policy.json", tmp_path / "dirty", profile="shop")


def test_survival_guard_catches_two_action_self_lethal_thorns_burn_and_buffer_multiattack():
    actor = EncounterPolicy(RunWeights(), style="engine")

    # 1. Two legal actions only: lethal self-damage Hemokinesis vs End Turn.
    obs_hemo = hand(("CARD.HEMOKINESIS", "AnyEnemy", {"damage": 15, "hploss": 3}))
    obs_hemo["hand"][0].update(type="Attack", cost=1)
    obs_hemo["energy"] = 1
    obs_hemo["player"].update(hp=3, block=0)
    obs_hemo["enemies"][0].update(hp=50, max_hp=50, intents=[])
    hemo_action = legal_actions(obs_hemo)[0]
    assert choose_turn_survival(obs_hemo, actor, hemo_action).kind == "end_turn"
    assert choose_turn(obs_hemo, actor, survival_priority=True).kind == "end_turn"

    # 2. Lethal Thorns recoil (3 HP, Strike into 3 Thorns) must be rejected in favor of End Turn.
    obs_thorns = hand(("CARD.STRIKE_SILENT", "AnyEnemy", {"damage": 6}))
    obs_thorns["hand"][0].update(type="Attack", cost=1)
    obs_thorns["energy"] = 1
    obs_thorns["player"].update(hp=3, block=0)
    obs_thorns["enemies"][0].update(
        hp=50, max_hp=50, powers=[{"id": "POWER.THORNS_POWER", "amount": 3}], intents=[]
    )
    assert choose_turn_survival(obs_thorns, actor, legal_actions(obs_thorns)[0]).kind == "end_turn"

    # 3. End-of-turn Burn (2 HP, Burn in hand, playable Defend) must play Defend instead of End Turn.
    obs_burn = hand(
        ("CARD.DEFEND_SILENT", "Self", {"block": 5}),
        ("CARD.BURN", "Self", {"damage": 2}),
    )
    obs_burn["hand"][0].update(type="Skill", cost=1)
    obs_burn["hand"][1].update(type="Status", can_play=False)
    obs_burn["energy"] = 1
    obs_burn["player"].update(hp=2, block=0)
    obs_burn["enemies"][0].update(hp=50, max_hp=50, intents=[])
    end_act = [a for a in legal_actions(obs_burn) if a.kind == "end_turn"][0]
    assert choose_turn_survival(obs_burn, actor, end_act).kind == "play_card"

    # 4. Buffer multiattack: two 5-dmg hits vs 4 Block + 1 Buffer at 5 HP -> 2nd hit deals 5 (lethal!).
    obs_buf = hand(("CARD.DEFEND_SILENT", "Self", {"block": 5}))
    obs_buf["hand"][0].update(type="Skill", cost=1)
    obs_buf["energy"] = 1
    obs_buf["player"].update(hp=5, block=4)
    obs_buf["player_powers"] = [{"id": "POWER.BUFFER_POWER", "amount": 1}]
    obs_buf["enemies"][0].update(
        hp=50, max_hp=50, intents=[{"type": "Attack", "damage": 5, "hits": 2, "total_damage": 10}]
    )
    end_buf = [a for a in legal_actions(obs_buf) if a.kind == "end_turn"][0]
    # Must play Defend (9 block absorbs 1st hit + 4 of 2nd, Buffer negates remaining 1 -> survives!).
    assert choose_turn_survival(obs_buf, actor, end_buf).kind == "play_card"


def test_survival_guard_handles_mandatory_discard_x0_slippery_weak_str_loss_and_deathblow():
    actor = EncounterPolicy(RunWeights(), style="engine")

    # 1. Mandatory discard: Survivor + Defend (2 cards in hand), 2 energy, 2 HP, 12 incoming.
    # Playing Survivor first forces discarding Defend (only 8 block -> dies); must play Defend first or potion.
    obs_surv = hand(
        ("CARD.SURVIVOR", "Self", {"block": 8}),
        ("CARD.DEFEND_SILENT", "Self", {"block": 5}),
    )
    obs_surv["hand"][0].update(type="Skill", cost=1)
    obs_surv["hand"][1].update(type="Skill", cost=1)
    obs_surv["energy"] = 2
    obs_surv["player"].update(hp=2, block=0)
    obs_surv["enemies"][0].update(hp=50, max_hp=50, intents=[{"type": "Attack", "total_damage": 12}])
    surv_act = legal_actions(obs_surv)[0]
    assert choose_turn_survival(obs_surv, actor, surv_act).args["card_index"] == 1

    # 2. X-cost at 0 energy must NOT claim a guaranteed 7-damage kill.
    obs_x0 = hand(
        ("CARD.SKEWER", "AnyEnemy", {"damage": 7}),
        ("CARD.DEFEND_SILENT", "Self", {"block": 5}),
    )
    obs_x0["hand"][0].update(type="Attack", cost=0, costs_x=True)
    obs_x0["hand"][1].update(type="Skill", cost=0)
    obs_x0["energy"] = 0
    obs_x0["player"].update(hp=5, block=0)
    obs_x0["enemies"][0].update(hp=6, max_hp=20, intents=[{"type": "Attack", "total_damage": 5}])
    assert choose_turn(obs_x0, actor, survival_priority=True).args["card_index"] == 1

    # 3. Slippery reduces a single-hit Strike to 1 dmg so it does NOT kill a 5-HP enemy.
    obs_slip = hand(
        ("CARD.STRIKE_SILENT", "AnyEnemy", {"damage": 6}),
        ("CARD.DEFEND_SILENT", "Self", {"block": 5}),
    )
    obs_slip["hand"][0].update(type="Attack", cost=1)
    obs_slip["hand"][1].update(type="Skill", cost=1)
    obs_slip["energy"] = 1
    obs_slip["player"].update(hp=5, block=0)
    obs_slip["enemies"][0].update(
        hp=5,
        max_hp=20,
        powers=[{"id": "POWER.SLIPPERY_POWER", "amount": 1}],
        intents=[{"type": "Attack", "total_damage": 5}],
    )
    assert choose_turn(obs_slip, actor, survival_priority=True).args["card_index"] == 1

    # 4. Strength loss BEFORE Weak: base 10 displayed as 7 (Weak) - 4 Str = floor(6*0.75) = 4 dmg (lethal at 4 HP!).
    obs_str = hand(
        ("CARD.DARK_SHACKLES", "AnyEnemy", {"strengthloss": 4}),
        ("CARD.DEFEND_SILENT", "Self", {"block": 5}),
    )
    obs_str["hand"][0].update(type="Skill", cost=1)
    obs_str["hand"][1].update(type="Skill", cost=1)
    obs_str["energy"] = 1
    obs_str["player"].update(hp=4, block=0)
    obs_str["enemies"][0].update(
        hp=50,
        max_hp=50,
        powers=[{"id": "POWER.WEAK_POWER", "amount": 2}],
        intents=[{"type": "Attack", "damage": 7, "hits": 1, "total_damage": 7}],
    )
    # Dark Shackles leaves 4 damage (lethal at 4 HP); Defend leaves 2 damage (survives!).
    assert choose_turn(obs_str, actor, survival_priority=True).args["card_index"] == 1

    # 5. Surviving Waterfall Giant's DeathBlow clears combat -> prefer Defend over spending Block Potion.
    obs_db = hand(("CARD.DEFEND_SILENT", "Self", {"block": 5}))
    obs_db["hand"][0].update(type="Skill", cost=1)
    obs_db["energy"] = 1
    obs_db["player"].update(
        hp=4,
        block=0,
        potions=[
            {
                "id": "POTION.BLOCK_POTION",
                "index": 0,
                "can_use": True,
                "target_type": "Self",
                "vars": {"Block": 12},
            }
        ],
    )
    obs_db["enemies"][0].update(
        id="MONSTER.WATERFALL_GIANT",
        hp=999_999_999,
        max_hp=999_999_999,
        intents=[{"type": "DeathBlow", "damage": 5, "hits": 1, "total_damage": 5}],
    )
    pot_action = [a for a in legal_actions(obs_db) if a.kind == "use_potion"][0]
    assert choose_turn_survival(obs_db, actor, pot_action).kind == "play_card"

    # 6. Forced-first fallback prevents width-8 pruning from overriding a surviving 4-Block opener.
    ten = [("CARD.SMALL_BLOCK", "Self", {"block": 4})] + [
        ("CARD.DEFEND_SILENT", "Self", {"block": 5}) for _ in range(9)
    ]
    obs_w = hand(*ten)
    for c in obs_w["hand"]:
        c.update(type="Skill", cost=1)
    obs_w["energy"] = 2
    obs_w["player"].update(hp=3, block=0)
    obs_w["enemies"][0].update(hp=50, max_hp=50, intents=[{"type": "Attack", "total_damage": 11}])
    proposed_4 = legal_actions(obs_w)[0]
    assert choose_turn_survival(obs_w, actor, proposed_4, width=8, depth=2) == proposed_4


def test_eternal_curse_late_act3_gold_kifuda_enchant_and_dollys_mirror():
    # 1. Eternal curse (Curse of the Bell) is excluded from marginal_removal_value.
    bell = {"id": "CARD.CURSE_OF_THE_BELL", "type": "Curse", "keywords": ["Eternal"], "cost": 0}
    strike = {"id": "CARD.STRIKE_SILENT", "type": "Attack", "rarity": "Basic", "cost": 1, "stats": {"damage": 6}}
    model = DeckPolicy({"version": 1, "runtime_identity": IDENTITY, "prompt_aware": True, "optional_selections": True})
    ctx = {"act": 3, "floor": 10}
    info = ({"n": 2, "power": 0, "attack": 0, "poison": 0, "block": 0, "shiv": 0, "discard": 0, "sly": 0, "aoe": 0, "noxious": 0, "accuracy": 0, "afterimage": 0, "dexterity": 0, "accel": 0}, {"STRIKE_SILENT": 1, "CURSE_OF_THE_BELL": 1})

    def grade(c):
        return model.grade(c, ctx, info)

    assert marginal_removal_value(bell, [bell, strike], grade) < -50

    # 2. Late Act 3 (floor 8+) gold opportunity cost is strictly lower than floor 7 even above 400g.
    from sts2rl.merchant import _retained_gold_value

    cost_f7 = _retained_gold_value(900, 0.070, 3, 7) - _retained_gold_value(800, 0.070, 3, 7)
    cost_f8 = _retained_gold_value(900, 0.035, 3, 8) - _retained_gold_value(800, 0.035, 3, 8)
    assert cost_f8 < cost_f7

    # 3. Optional enchantment (Kifuda) never skips a free enchantment on a starter Strike.
    ench_state = {
        "decision": "card_select",
        "runtime_identity": IDENTITY,
        "in_combat": False,
        "context": ctx,
        "player": {"hp": 60, "max_hp": 70, "deck": [strike]},
        "min_select": 0,
        "max_select": 1,
        "cards": [{**strike, "index": 0}],
    }
    model.prompt = "enchant"
    assert model.choose(ench_state, RunPolicy(RunWeights())).kind == "select_cards"

    # 4. Dolly's Mirror ("obtain an additional copy of a card") maps to "duplicate".
    mirror_shop = {
        "decision": "shop",
        "player": {"gold": 300, "potions": []},
        "relics": [{"index": 0, "is_stocked": True, "cost": 150, "name": "Dolly's Mirror", "description": "Upon pickup, obtain an additional copy of a card in your deck."}],
        "cards": [],
        "potions": [],
    }
    buy_mirror = [a for a in legal_actions(mirror_shop) if a.kind == "buy_relic"][0]
    assert selection_goal(mirror_shop, buy_mirror, detailed=True) == "duplicate"

    # 5. Envenom + Poisoned Stab with 1 Artifact: Envenom strips Artifact so printed Poison still lands.
    obs_ps = hand(("CARD.POISONED_STAB", "AnyEnemy", {"damage": 6, "poisonpower": 3}))
    obs_ps["hand"][0].update(type="Attack", cost=1)
    obs_ps["player_powers"] = [{"id": "POWER.ENVENOM_POWER", "amount": 1}]
    obs_ps["enemies"][0].update(hp=50, max_hp=50, block=0, powers=[{"id": "POWER.ARTIFACT_POWER", "amount": 1}])
    ps_old = EncounterPolicy(RunWeights(), style="engine", scorer_fixes=False)
    ps_new = EncounterPolicy(RunWeights(), style="engine", scorer_fixes=True)
    pa = legal_actions(obs_ps)
    # Old sees artifact=True and zeros printed poison (credits only 1 Envenom poison);
    # New spends Artifact on Envenom and lands the 3 printed Poison!
    assert ps_new.combat_scores(obs_ps, pa)[0] > ps_old.combat_scores(obs_ps, pa)[0] + 5.0

