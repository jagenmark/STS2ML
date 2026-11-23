"""Unit tests for opt-in enemy_mechanics and card_potion_mechanics (Phase 10)."""

from __future__ import annotations

from sts2rl.encounter import EncounterModel, EncounterPolicy
from sts2rl.native import legal_actions
from sts2rl.run_policy import IDENTITY, RunPolicy, RunWeights
from sts2rl.selections import combat_selection
from sts2rl.turn_planning import (
    _enemy_attack_hits_list,
    _poison_tick_loss,
    _resolve_attack_hits,
    _search_survival_lines,
    choose_turn_survival,
)


def _combat_state(
    *,
    hp=50,
    max_hp=70,
    block=0,
    energy=3,
    hand=(),
    potions=(),
    enemies=(),
    player_powers=(),
    room_type="Boss",
    act=1,
    floor=17,
    round_num=3,
):
    pots = [{"can_use": True, **p} for p in potions]
    return {
        "observation_version": 2,
        "decision": "combat_play",
        "in_combat": True,
        "runtime_identity": IDENTITY,
        "round": round_num,
        "energy": energy,
        "hand": list(hand),
        "enemies": list(enemies),
        "player_powers": list(player_powers),
        "player": {
            "hp": hp,
            "max_hp": max_hp,
            "block": block,
            "potions": pots,
            "deck": list(hand),
        },
        "context": {
            "act": act,
            "floor": floor,
            "room_type": room_type,
        },
    }


def _card(idx, cid, ctype, cost, stats, *, target="AnyEnemy", dmg_targets=None, keywords=()):
    c = {
        "index": idx,
        "id": f"CARD.{cid}",
        "type": ctype,
        "cost": cost,
        "can_play": True,
        "target_type": target,
        "stats": dict(stats),
        "keywords": list(keywords),
    }
    if dmg_targets is not None:
        c["damage_by_target"] = dmg_targets
    return c


def _enemy(idx, eid, hp, max_hp, intents, powers=(), block=0):
    return {
        "index": idx,
        "id": f"MONSTER.{eid}",
        "hp": hp,
        "max_hp": max_hp,
        "block": block,
        "intents": list(intents),
        "powers": [{"id": f"POWER.{k}_POWER", "amount": v} for k, v in powers],
    }


def test_poison_tick_loss_with_slippery():
    assert _poison_tick_loss(12, 0, False, slippery=0) == 12
    assert _poison_tick_loss(12, 0, False, slippery=7) == 1
    assert _poison_tick_loss(12, 1, False, slippery=1) == 1 + 11
    assert _poison_tick_loss(12, 1, False, slippery=2) == 2


def test_vital_spark_exact_weak_math():
    # Native verified Infested Prism R3: base 6 -> Weak 4x3; +3 -> 6x3; +6 -> 9x3.
    assert _enemy_attack_hits_list(12, 3, True, False, -3, False) == (6.0, 6.0, 6.0)
    assert _enemy_attack_hits_list(12, 3, True, False, -6, False) == (9.0, 9.0, 9.0)
    # Native verified R4: base 10 -> Weak 7; +3 -> 9; +6 -> 12.
    assert _enemy_attack_hits_list(7, 1, True, False, -3, False) == (9.0,)
    assert _enemy_attack_hits_list(7, 1, True, False, -6, False) == (12.0,)
    # Native verified R5: unweakened 17 + 6 -> 23.
    assert _enemy_attack_hits_list(17, 1, False, False, -6, False) == (23.0,)


def test_plow_multi_card_stun_overrides_defend():
    """Ceremonial Beast at 175 HP with Plow=160 and Attack 26: Dash(10) + Precise Cut(11) stuns at 154 HP."""
    beast = _enemy(
        0,
        "CEREMONIAL_BEAST",
        175,
        262,
        [{"type": "Attack", "damage": 26}, {"type": "Buff"}],
        powers=[("PLOW", 160), ("STRENGTH", 6)],
    )
    hand = [
        _card(0, "DASH", "Attack", 2, {"damage": 10, "block": 10}, dmg_targets=[{"target_index": 0, "damage": 10}]),
        _card(1, "PRECISE_CUT", "Attack", 0, {"damage": 11}, dmg_targets=[{"target_index": 0, "damage": 11}]),
        _card(2, "DEFEND_SILENT", "Skill", 1, {"block": 5}, target="Self"),
    ]
    # With energy=2, playing Defend(1) leaves only 1 energy so Dash(2) is unplayable and Plow cannot be crossed!
    state = _combat_state(hp=39, energy=2, hand=hand, enemies=[beast])
    actor = EncounterPolicy(RunWeights(), style="guard", mechanics=True, act2_mechanics=True, enemy_mechanics=True)
    # Even if greedy proposes Defend, choose_turn_survival finds Dash + Precise Cut -> Plow stun!
    defend = next(a for a in legal_actions(state) if a.kind == "play_card" and a.args["card_index"] == 2)
    chosen = choose_turn_survival(state, actor, defend)
    assert chosen.kind == "play_card" and chosen.args["card_index"] in (0, 1)


def test_vital_spark_avoids_suicidal_defend():
    """Infested Prism R5: Vital Spark 6, Attack 17, Silent at 10 HP; Defend boosts 17->23 (net -1 HP)."""
    prism = _enemy(
        0,
        "INFESTED_PRISM",
        57,
        170,
        [{"type": "Attack", "damage": 17}],
        powers=[("VITAL_SPARK", 6)],
    )
    hand = [
        _card(0, "DEFEND_SILENT", "Skill", 1, {"block": 5}, target="Self"),
        _card(1, "STRIKE_SILENT", "Attack", 1, {"damage": 6}, dmg_targets=[{"target_index": 0, "damage": 6}]),
    ]
    state = _combat_state(hp=25, energy=2, hand=hand, enemies=[prism], act=2, room_type="Elite")
    actor = EncounterPolicy(RunWeights(), style="isolate", mechanics=True, act2_mechanics=True, enemy_mechanics=True)
    actions = legal_actions(state)
    scores = actor.combat_scores(state, actions)
    defend_idx = next(i for i, a in enumerate(actions) if a.kind == "play_card" and a.args["card_index"] == 0)
    strike_idx = next(i for i, a in enumerate(actions) if a.kind == "play_card" and a.args["card_index"] == 1)
    assert scores[defend_idx] < 0.0
    assert scores[strike_idx] > scores[defend_idx]


def test_slippery_stops_wasting_vulnerable_potion_and_values_shivs():
    vantom = _enemy(
        0,
        "VANTOM",
        183,
        183,
        [{"type": "Attack", "damage": 8}],
        powers=[("SLIPPERY", 9)],
    )
    hand = [
        _card(0, "BLADE_DANCE", "Skill", 1, {"cards": 3}, target="Self"),
        _card(1, "STRIKE_SILENT", "Attack", 1, {"damage": 6}, dmg_targets=[{"target_index": 0, "damage": 6}]),
    ]
    potions = [{"index": 0, "id": "POTION.VULNERABLE_POTION", "target_type": "AnyEnemy", "vars": {"VulnerablePower": 3}}]
    state = _combat_state(hp=52, energy=3, hand=hand, potions=potions, enemies=[vantom])
    actor = EncounterPolicy(RunWeights(), style="engine", mechanics=True, act2_mechanics=True, enemy_mechanics=True)
    actions = legal_actions(state)
    scores = actor.combat_scores(state, actions)
    vuln_idx = next(i for i, a in enumerate(actions) if a.kind == "use_potion")
    bd_idx = next(i for i, a in enumerate(actions) if a.kind == "play_card" and a.args["card_index"] == 0)
    assert scores[vuln_idx] < 0.0
    assert scores[bd_idx] > scores[vuln_idx]


def test_adaptable_prevents_false_clear():
    ts = _enemy(
        0,
        "TEST_SUBJECT",
        5,
        111,
        [{"type": "Attack", "damage": 25}],
        powers=[("ADAPTABLE", 1)],
    )
    hand = [
        _card(0, "STRIKE_SILENT", "Attack", 1, {"damage": 6}, dmg_targets=[{"target_index": 0, "damage": 6}]),
        _card(1, "FOOTWORK", "Power", 1, {"dexteritypower": 2}, target="Self"),
    ]
    state = _combat_state(hp=10, energy=2, hand=hand, enemies=[ts], act=3)
    actor = EncounterPolicy(RunWeights(), style="engine", mechanics=True, act2_mechanics=True, enemy_mechanics=True)
    actions = legal_actions(state)
    best, _ = _search_survival_lines(state, actor, actions)
    # Killing Phase 1 cancels the 25 attack this turn (survives=1), but Adaptable prevents clears=1!
    assert best[0] == 1 and best[1] == 0


def test_flex_potion_plays_before_zero_cost_shivs():
    queen = _enemy(0, "QUEEN", 350, 419, [{"type": "Buff"}])
    hand = [
        _card(0, "SHIV", "Attack", 0, {"damage": 4}, dmg_targets=[{"target_index": 0, "damage": 4}]),
        _card(1, "SHIV", "Attack", 0, {"damage": 4}, dmg_targets=[{"target_index": 0, "damage": 4}]),
        _card(2, "SHIV", "Attack", 0, {"damage": 4}, dmg_targets=[{"target_index": 0, "damage": 4}]),
        _card(3, "SLICE", "Attack", 0, {"damage": 6}, dmg_targets=[{"target_index": 0, "damage": 6}]),
        _card(4, "STRIKE_SILENT", "Attack", 1, {"damage": 6}, dmg_targets=[{"target_index": 0, "damage": 6}]),
    ]
    potions = [{"index": 0, "id": "POTION.FLEX_POTION", "target_type": "AnyPlayer", "vars": {"StrengthPower": 5}}]
    state = _combat_state(hp=60, energy=3, hand=hand, potions=potions, enemies=[queen], act=3)
    actor = EncounterPolicy(RunWeights(), style="engine", mechanics=True, act2_mechanics=True, card_potion_mechanics=True)
    actions = legal_actions(state)
    best = actor.combat(state, actions)
    assert best.kind == "use_potion" and best.args["potion_index"] == 0


def test_flex_potion_not_burned_in_normal_hallway():
    slime = _enemy(0, "SLUDGE_SPINNER", 41, 41, [{"type": "Attack", "damage": 8}])
    hand = [
        _card(0, "STRIKE_SILENT", "Attack", 1, {"damage": 6}, dmg_targets=[{"target_index": 0, "damage": 6}]),
        _card(1, "STRIKE_SILENT", "Attack", 1, {"damage": 6}, dmg_targets=[{"target_index": 0, "damage": 6}]),
        _card(2, "STRIKE_SILENT", "Attack", 1, {"damage": 6}, dmg_targets=[{"target_index": 0, "damage": 6}]),
        _card(3, "SURVIVOR", "Skill", 1, {"block": 8}, target="Self"),
    ]
    potions = [
        {"index": 0, "id": "POTION.FLEX_POTION", "target_type": "AnyPlayer", "vars": {"StrengthPower": 5}},
        {"index": 1, "id": "POTION.GIGANTIFICATION_POTION", "target_type": "AnyPlayer", "vars": {"GigantificationPower": 1}},
    ]
    state = _combat_state(hp=56, energy=3, hand=hand, potions=potions, enemies=[slime], act=1, floor=2, room_type="Monster")
    actor = EncounterPolicy(RunWeights(), style="balanced", mechanics=True, act2_mechanics=True, card_potion_mechanics=True)
    actions = legal_actions(state)
    best = actor.combat(state, actions)
    assert best.kind == "play_card"


def test_shadowmeld_enables_survival_line():
    enemy = _enemy(0, "SLAVER", 80, 80, [{"type": "Attack", "damage": 20}])
    hand = [
        _card(0, "SHADOWMELD", "Skill", 1, {"power": 1}, target="Self"),
        _card(1, "DEFEND_SILENT", "Skill", 1, {"block": 6}, target="Self"),
        _card(2, "DEFEND_SILENT", "Skill", 1, {"block": 6}, target="Self"),
    ]
    # Silent at 5 HP against 23 dmg: Defend+Shadowmeld+Defend = 6+12 = 18 Block (5 dmg -> DIES).
    # Shadowmeld + Defend + Defend = 12+12 = 24 Block (0 dmg -> SURVIVES!).
    enemy = _enemy(0, "SLAVER", 80, 80, [{"type": "Attack", "damage": 23}])
    state = _combat_state(hp=5, energy=3, hand=hand, enemies=[enemy], room_type="Monster")
    actor = EncounterPolicy(RunWeights(), style="balanced", mechanics=True, act2_mechanics=True, card_potion_mechanics=True)
    defend = next(a for a in legal_actions(state) if a.kind == "play_card" and a.args["card_index"] == 1)
    chosen = choose_turn_survival(state, actor, defend)
    assert chosen.kind == "play_card" and chosen.args["card_index"] == 0


def test_missing_silent_cards_scored_positively():
    enemy = _enemy(0, "TEST", 100, 100, [{"type": "Attack", "damage": 10}])
    hand = [
        _card(0, "KNIFE_TRAP", "Skill", 2, {"calculatedshivs": 5}),
        _card(1, "PANACHE", "Power", 0, {"panachedamage": 10}, target="Self"),
        _card(2, "LETHALITY", "Power", 1, {"lethalitypower": 50}, target="Self"),
        _card(3, "STRANGLE", "Attack", 1, {"damage": 8, "stranglepower": 2}, dmg_targets=[{"target_index": 0, "damage": 8}]),
    ]
    state = _combat_state(hp=50, energy=3, hand=hand, enemies=[enemy])
    actor = EncounterPolicy(RunWeights(), style="engine", mechanics=True, act2_mechanics=True, card_potion_mechanics=True)
    actions = legal_actions(state)
    scores = actor.combat_scores(state, actions)
    for i, a in enumerate(actions):
        if a.kind == "play_card":
            assert scores[i] > 5.0, f"Card {a.args} scored too low: {scores[i]}"


def test_combat_selection_discards_unplayable_over_playable():
    enemy = _enemy(0, "TEST", 60, 60, [{"type": "Attack", "damage": 12}])
    c_unplayable = _card(0, "PREDATOR", "Attack", 2, {"damage": 15})
    c_playable = _card(1, "DEFEND_SILENT", "Skill", 1, {"block": 5}, target="Self")
    c_grand = _card(2, "GRAND_FINALE", "Attack", 0, {"damage": 50})
    c_grand["can_play"] = False
    state = {
        "decision": "card_select",
        "in_combat": True,
        "min_select": 1,
        "max_select": 1,
        "cards": [c_unplayable, c_playable, c_grand],
        "selection_source": {"kind": "card", "id": "CARD.SURVIVOR"},
        "combat_state": {
            "energy": 1,
            "enemies": [enemy],
            "player": {"hp": 40, "max_hp": 70, "block": 0, "deck": [c_unplayable, c_playable, c_grand]},
            "context": {"room_type": "Monster"},
        },
    }
    actor = EncounterPolicy(RunWeights(), card_potion_mechanics=True)
    choice = combat_selection(state, actor)
    assert choice.args["indices"] == "2"

    # Without Grand Finale, should discard unplayable 2-cost Predator over playable 1-cost Defend.
    state2 = {**state, "cards": [c_unplayable, c_playable]}
    choice2 = combat_selection(state2, actor)
    assert choice2.args["indices"] == "0"


def test_default_flags_preserve_backward_compatibility():
    data = {"version": 1, "runtime_identity": IDENTITY, "default": "balanced"}
    model = EncounterModel(data)
    assert model.enemy_mechanics is False
    assert model.card_potion_mechanics is False
    base = RunPolicy(RunWeights())
    state = _combat_state(
        hand=[_card(0, "STRIKE_SILENT", "Attack", 1, {"damage": 6}, dmg_targets=[{"target_index": 0, "damage": 6}])],
        enemies=[_enemy(0, "TEST", 30, 30, [{"type": "Attack", "damage": 6}])],
    )
    model.prepare(state, base)
    assert model.actor.enemy_mechanics is False
    assert model.actor.card_potion_mechanics is False


def test_build_all_v2_mech_v3_profile_and_dirty_check(tmp_path):
    import importlib.util
    import json
    from pathlib import Path
    import pytest

    spec = importlib.util.spec_from_file_location(
        "build_batch1",
        Path(__file__).resolve().parents[1] / "scripts" / "build-batch1-challengers.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    base = Path(__file__).resolve().parents[1] / "releases/silent-a10-mecha-knight/challenger/policy.json"
    out = mod.build_batch1_bundle(base, tmp_path / "v3", profile="all_v2_mech_v3")
    enc = json.loads((out.parent / "encounter_model.json").read_text(encoding="utf-8"))
    assert enc["act2_mechanics"] is True
    assert enc["enemy_mechanics"] is True
    assert enc["card_potion_mechanics"] is True

    # Exercise each new dirty key independently on an otherwise clean base bundle.
    from sts2rl.act1 import save_json
    from sts2rl.run_bundle import freeze_bundle, load_bundle

    for flag in ("enemy_mechanics", "card_potion_mechanics"):
        role, opts = load_bundle(base)
        clean_enc = json.loads(opts["encounter_model"].read_bytes())
        clean_enc[flag] = True
        stage = tmp_path / f"dirty_{flag}"
        stage.mkdir()
        save_json(stage / "encounter_model.json", clean_enc)
        dirty_bundle = freeze_bundle(
            {"args": {**opts, "encounter_model": stage / "encounter_model.json", "roles": [role]}},
            stage / "policy",
        )
        with pytest.raises(ValueError, match="already has Batch 1/2 settings"):
            mod.build_batch1_bundle(dirty_bundle, tmp_path / f"fail_{flag}", profile="all_v2_mech_v3")


def test_vital_spark_with_duplication_avoids_lethal_skill():
    """22 HP vs Prism 17 dmg (Vital Spark 3) with Duplication 1: Deadly Poison plays twice -> 23 dmg (lethal)."""
    prism = _enemy(0, "INFESTED_PRISM", 120, 170, [{"type": "Attack", "damage": 17}], powers=[("VITAL_SPARK", 3)])
    hand = [_card(0, "DEADLY_POISON", "Skill", 1, {"poisonpower": 5})]
    state = _combat_state(
        hp=22,
        energy=1,
        hand=hand,
        enemies=[prism],
        player_powers=[{"id": "POWER.DUPLICATION_POWER", "amount": 1}],
        act=2,
        room_type="Elite",
    )
    actor = EncounterPolicy(RunWeights(), style="isolate", mechanics=True, act2_mechanics=True, enemy_mechanics=True)
    dp = next(a for a in legal_actions(state) if a.kind == "play_card")
    chosen = choose_turn_survival(state, actor, dp)
    assert chosen.kind == "end_turn"


def test_plow_below_threshold_still_stuns():
    """Beast acquired Plow 160 while already at 151 HP: 1-cost Strike stuns and cancels 20 dmg (Defend dies)."""
    beast = _enemy(0, "CEREMONIAL_BEAST", 151, 262, [{"type": "Attack", "damage": 20}], powers=[("PLOW", 160)])
    hand = [
        _card(0, "STRIKE_SILENT", "Attack", 1, {"damage": 6}, dmg_targets=[{"target_index": 0, "damage": 6}]),
        _card(1, "DEFEND_SILENT", "Skill", 1, {"block": 5}, target="Self"),
    ]
    state = _combat_state(hp=10, energy=1, hand=hand, enemies=[beast])
    actor = EncounterPolicy(RunWeights(), style="guard", mechanics=True, act2_mechanics=True, enemy_mechanics=True)
    actions = legal_actions(state)
    scores = actor.combat_scores(state, actions)
    strike_idx = next(i for i, a in enumerate(actions) if a.kind == "play_card" and a.args["card_index"] == 0)
    defend_idx = next(i for i, a in enumerate(actions) if a.kind == "play_card" and a.args["card_index"] == 1)
    assert scores[strike_idx] > scores[defend_idx]
    chosen = choose_turn_survival(state, actor, actions[defend_idx])
    assert chosen.kind == "play_card" and chosen.args["card_index"] == 0


def test_slippery_after_block_and_buffer_prevents_false_clear():
    """2 HP, 10 Block, Slippery 1, Poison 7: Strike 6 leaves 4 Block + Slippery 1, so Poison deals 1 -> NOT clear."""
    hp_loss, eb, ebuf, eslip, _ = _resolve_attack_hits(
        6.0, 1, 10.0, 0, 1, 0, False, slippery_after_block=True
    )
    assert hp_loss == 0.0 and eb == 4.0 and eslip == 1
    assert _poison_tick_loss(7, 0, False, slippery=1, buffer=0) == 1
    assert _poison_tick_loss(7, 0, False, slippery=0, buffer=1) == 0

    enemy = _enemy(0, "VANTOM", 2, 183, [{"type": "Attack", "damage": 30}], powers=[("SLIPPERY", 1), ("POISON", 7)], block=10)
    hand = [_card(0, "STRIKE_SILENT", "Attack", 1, {"damage": 6}, dmg_targets=[{"target_index": 0, "damage": 6}])]
    state = _combat_state(hp=10, energy=1, hand=hand, enemies=[enemy])
    actor = EncounterPolicy(RunWeights(), style="engine", mechanics=True, act2_mechanics=True, enemy_mechanics=True)
    best, _ = _search_survival_lines(state, actor, legal_actions(state))
    assert best[0] == 0 and best[1] == 0


def test_knife_trap_thorns_recoil_and_afterimage():
    """Knife Trap with 2 exhausted Shivs vs Thorns 5 deals 10 recoil -> fatal at 10 HP unless avoided."""
    toad = _enemy(0, "SPINY_TOAD", 80, 122, [{"type": "Buff"}], powers=[("THORNS", 5)])
    hand = [_card(0, "KNIFE_TRAP", "Skill", 2, {"calculatedshivs": 2})]
    state = _combat_state(hp=10, energy=2, hand=hand, enemies=[toad], act=2, room_type="Monster")
    actor = EncounterPolicy(RunWeights(), style="engine", mechanics=True, act2_mechanics=True, card_potion_mechanics=True)
    kt = next(a for a in legal_actions(state) if a.kind == "play_card")
    chosen = choose_turn_survival(state, actor, kt)
    assert chosen.kind == "end_turn"


def test_shadowmeld_doubles_afterimage_and_block_potion():
    """Shadowmeld + Afterimage 1 + Block Potion 12 gives 2 (on Shadowmeld) + 24 (on Block Potion) = 26 Block."""
    enemy = _enemy(0, "SLAVER", 80, 80, [{"type": "Attack", "damage": 26}])
    hand = [_card(0, "SHADOWMELD", "Skill", 1, {"power": 1}, target="Self")]
    potions = [{"index": 0, "id": "POTION.BLOCK_POTION", "target_type": "AnyPlayer", "vars": {"Block": 12}}]
    state = _combat_state(
        hp=5,
        energy=1,
        hand=hand,
        potions=potions,
        enemies=[enemy],
        player_powers=[{"id": "POWER.AFTERIMAGE_POWER", "amount": 1}],
        room_type="Monster",
    )
    actor = EncounterPolicy(RunWeights(), style="balanced", mechanics=True, act2_mechanics=True, card_potion_mechanics=True)
    pot_act = next(a for a in legal_actions(state) if a.kind == "use_potion")
    # Potion alone = 12 Block (14 dmg -> dies). Shadowmeld -> Block Potion = 2 + 24 = 26 Block (0 dmg -> survives!).
    chosen = choose_turn_survival(state, actor, pot_act)
    assert chosen.kind == "play_card" and chosen.args["card_index"] == 0


def test_gigantification_only_triples_first_attack_and_flex_respects_vulnerable():
    """With Gigantification active, 3 Slices preview 18 each, but native deals 18 + 6 + 6 = 30 (< 40 HP)."""
    enemy = _enemy(0, "TEST", 40, 100, [{"type": "Attack", "damage": 30}])
    hand = [
        _card(0, "SLICE", "Attack", 0, {"damage": 18}, dmg_targets=[{"target_index": 0, "damage": 18}]),
        _card(1, "SLICE", "Attack", 0, {"damage": 18}, dmg_targets=[{"target_index": 0, "damage": 18}]),
        _card(2, "SLICE", "Attack", 0, {"damage": 18}, dmg_targets=[{"target_index": 0, "damage": 18}]),
    ]
    state = _combat_state(
        hp=10,
        energy=3,
        hand=hand,
        enemies=[enemy],
        player_powers=[{"id": "POWER.GIGANTIFICATION_POWER", "amount": 1}],
    )
    actor = EncounterPolicy(RunWeights(), style="engine", mechanics=True, act2_mechanics=True, card_potion_mechanics=True)
    best, _ = _search_survival_lines(state, actor, legal_actions(state))
    assert best[0] == 0 and best[1] == 0

    # Flex Potion (+5 Str) + Strike (9 preview vs Vulnerable) deals 9 + floor(5*1.5) = 16 -> kills 16 HP enemy!
    vuln_enemy = _enemy(0, "TEST", 16, 100, [{"type": "Attack", "damage": 30}], powers=[("VULNERABLE", 2)])
    hand2 = [_card(0, "STRIKE_SILENT", "Attack", 1, {"damage": 9}, dmg_targets=[{"target_index": 0, "damage": 9}])]
    pot2 = [{"index": 0, "id": "POTION.FLEX_POTION", "target_type": "AnyPlayer", "vars": {"StrengthPower": 5}}]
    state2 = _combat_state(hp=10, energy=1, hand=hand2, potions=pot2, enemies=[vuln_enemy])
    best2, _ = _search_survival_lines(state2, actor, legal_actions(state2))
    assert best2[0] == 1 and best2[1] == 1


def test_shared_fate_and_debilitate_survival_forecast():
    # Debilitate turns Weak from 25% into 50%: native Weak Prism 13 -> 9!
    assert _enemy_attack_hits_list(13, 1, True, False, 0, False, newly_debilitated=True) == (9.0,)

    # Shared Fate (-2 player Str) prevents false kill: 5 HP enemy with 6-dmg Strike drops to 4 dmg after Shared Fate.
    enemy = _enemy(0, "TEST", 5, 50, [{"type": "Attack", "damage": 30}])
    hand = [
        _card(0, "SHARED_FATE", "Skill", 0, {"enemystrengthloss": 2, "playerstrengthloss": 2}),
        _card(1, "STRIKE_SILENT", "Attack", 1, {"damage": 6}, dmg_targets=[{"target_index": 0, "damage": 6}]),
    ]
    state = _combat_state(hp=10, energy=1, hand=hand, enemies=[enemy])
    actor = EncounterPolicy(RunWeights(), style="engine", mechanics=True, act2_mechanics=True, card_potion_mechanics=True)
    sf = next(a for a in legal_actions(state) if a.kind == "play_card" and a.args["card_index"] == 0)
    chosen = choose_turn_survival(state, actor, sf)
    # Must play Strike first (6 >= 5 clear!), NOT Shared Fate first!
    assert chosen.kind == "play_card" and chosen.args["card_index"] == 1


def test_bouncing_flask_multi_enemy_slippery_no_crash():
    e0 = _enemy(0, "A", 40, 40, [{"type": "Attack", "damage": 6}], powers=[("SLIPPERY", 1), ("ARTIFACT", 2)])
    e1 = _enemy(1, "B", 40, 40, [{"type": "Attack", "damage": 6}])
    hand = [_card(0, "BOUNCING_FLASK", "Skill", 2, {"poisonpower": 3, "repeat": 3}, target="RandomEnemy")]
    state = _combat_state(hp=40, energy=3, hand=hand, enemies=[e0, e1])
    actor = EncounterPolicy(
        RunWeights(), style="engine", mechanics=True, scorer_fixes=True, act2_mechanics=True, enemy_mechanics=True
    )
    scores = actor.combat_scores(state, legal_actions(state))
    assert len(scores) == 2


def test_nonlethal_plow_does_not_waste_fire_potion_when_blocked():
    """With 26 Block vs 26 incoming, Beast 175 HP (Plow 160), and only Fire Potion: keep End Turn."""
    beast = _enemy(0, "CEREMONIAL_BEAST", 175, 262, [{"type": "Attack", "damage": 26}], powers=[("PLOW", 160)])
    potions = [{"index": 0, "id": "POTION.FIRE_POTION", "target_type": "AnyEnemy", "vars": {"Damage": 20}}]
    state = _combat_state(hp=40, block=26, energy=0, hand=[], potions=potions, enemies=[beast])
    actor = EncounterPolicy(RunWeights(), style="guard", mechanics=True, act2_mechanics=True, enemy_mechanics=True)
    end_turn = next(a for a in legal_actions(state) if a.kind == "end_turn")
    chosen = choose_turn_survival(state, actor, end_turn)
    assert chosen.kind == "end_turn"


def test_grand_finale_selection_prompt_without_can_play_uses_hand():
    enemy = _enemy(0, "TEST", 60, 60, [{"type": "Attack", "damage": 12}])
    gf_prompt = {"index": 0, "id": "CARD.GRAND_FINALE", "type": "Attack", "cost": 0, "stats": {"damage": 50}}
    strike_prompt = {"index": 1, "id": "CARD.STRIKE_SILENT", "type": "Attack", "cost": 1, "stats": {"damage": 6}}
    gf_hand = {**gf_prompt, "can_play": True}
    strike_hand = {**strike_prompt, "can_play": True}
    state = {
        "decision": "card_select",
        "in_combat": True,
        "min_select": 1,
        "max_select": 1,
        "cards": [gf_prompt, strike_prompt],
        "selection_source": {"kind": "card", "id": "CARD.SURVIVOR"},
        "combat_state": {
            "energy": 1,
            "draw_pile_count": 0,
            "hand": [gf_hand, strike_hand],
            "enemies": [enemy],
            "player": {"hp": 40, "max_hp": 70, "block": 0, "deck": [gf_prompt, strike_prompt]},
            "context": {"room_type": "Monster"},
        },
    }
    actor = EncounterPolicy(RunWeights(), card_potion_mechanics=True)
    choice = combat_selection(state, actor)
    # Grand Finale is playable (draw pile empty), so discard Strike (index 1), NOT Grand Finale!
    assert choice.args["indices"] == "1"


