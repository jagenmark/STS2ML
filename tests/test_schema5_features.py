"""Unit tests for Schema 5 combat value features and artifact round-trip."""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from sts2rl.combat_search_v2.artifact import CombatValueModel, export_model
from sts2rl.combat_search_v2.features import (
    FEATURE_NAMES,
    SCHEMA2_NAMES,
    SCHEMA4_NAMES,
    SCHEMA5_NAMES,
    extract_leaf_features,
)
from sts2rl.combat_search_v2.state import Boundary, Card, Enemy, Intent, Relic, State, Variant
from sts2rl.combat_search_v2.value import leaf_value


def _sample_completed_state() -> State:
    v_def = Variant("DEFEND_SILENT", "Skill", 1, "Self")
    v_blk = Variant("BACKFLIP", "Skill", 1, "Self")
    v_atk = Variant("STRIKE_SILENT", "Attack", 1, "AnyEnemy")
    v_neu = Variant("NEUTRALIZE", "Attack", 0, "AnyEnemy")
    v_wail = Variant("PIERCING_WAIL", "Skill", 1, "AllEnemies")
    v_esc = Variant("FRANTIC_ESCAPE", "Skill", 1, "Self")
    v_burn = Variant("BURN", "Status", -1, "None")

    e0 = Enemy(
        slot=0,
        name="CRUSHER",
        hp=12,
        max_hp=120,
        block=10,
        powers=(("POISON", 8), ("WEAK", 2), ("STRENGTH", 3)),
        intents=(Intent("Attack", damage=14, hits=2),),
        preview_strength=3,
        preview_weak=True,
    )
    e1 = Enemy(
        slot=1,
        name="ROCKET",
        hp=90,
        max_hp=150,
        block=0,
        powers=(("VULNERABLE", 1), ("SLIPPERY", 1)),
        intents=(Intent("Buff", damage=None, hits=1),),
        preview_strength=0,
        preview_weak=False,
    )
    relics = (
        Relic("PEN_NIB", counter=9, used=False),
        Relic("KUNAI", counter=0, used=False),
        Relic("ART_OF_WAR", counter=None, used=False, status="Active"),
        Relic("POCKETWATCH", counter=0, used=False, status="Active"),
        Relic("LIZARD_TAIL", counter=None, used=True),  # used up -> must not count as active!
        Relic("RING_OF_THE_SNAKE", counter=None, used=False),
    )
    return State(
        hp=30,
        max_hp=70,
        block=15,
        energy=4,
        max_energy=3,
        round=4,
        act=2,
        room="Boss",
        powers=(("ACCELERANT", 1), ("BLUR", 1), ("SHADOW_STEP", 1), ("SURROUNDED", 1)),
        enemies=(e0, e1),
        hand=(Card(0, v_wail), Card(1, v_neu), Card(2, v_esc)),
        draw=(v_blk, v_atk),  # 2 cards in draw -> next_draw=5 triggers reshuffle of 3 from discard!
        discard=(v_def, v_def, v_burn, v_atk),
        exhaust=(),
        relics=relics,
        boundary=Boundary("next turn", count=5, shuffle=True),
        outcome="completed",
        floor=17,
        additional_public_energy=1,
        facing=1,
    )


def test_schema5_feature_names_and_exact_values():
    st = _sample_completed_state()
    f2 = extract_leaf_features(st, schema=2)
    f3 = extract_leaf_features(st, schema=3)
    f4 = extract_leaf_features(st, schema=4)
    f5 = extract_leaf_features(st, schema=5)

    assert len(SCHEMA2_NAMES) == len(f2)
    assert len(FEATURE_NAMES) == len(f3)
    assert len(SCHEMA4_NAMES) == len(f4)
    assert len(SCHEMA5_NAMES) == len(f5) == 420
    assert len(set(SCHEMA5_NAMES)) == len(SCHEMA5_NAMES)
    assert np.isfinite(f5).all()
    # Schema 5 strictly prefixes Schema 4 without mutating any Schema 4 element
    assert np.array_equal(f5[: len(f4)], f4)

    idx = {name: i for i, name in enumerate(SCHEMA5_NAMES)}
    # 1. Exact next-turn resources
    assert f5[idx["s5.next_energy"]] == 4.0
    assert f5[idx["s5.next_draw_count"]] == 5.0
    assert f5[idx["s5.will_shuffle"]] == 1.0
    assert f5[idx["s5.next_hand_size"]] == 8.0
    assert f5[idx["s5.missing_hp"]] == 40.0
    assert f5[idx["s5.below_half_hp"]] == 1.0
    assert f5[idx["s5.block_carry"]] == 15.0

    # 2. Extra powers
    assert f5[idx["s5.player.power.SHADOW_STEP"]] == 1.0
    assert f5[idx["s5.player.power.SURROUNDED"]] == 1.0

    # 3. Relics & counters (used Lizard Tail excluded!)
    assert f5[idx["s5.relic.PEN_NIB"]] == 1.0
    assert f5[idx["s5.relic.KUNAI"]] == 1.0
    assert f5[idx["s5.relic.LIZARD_TAIL"]] == 0.0
    assert f5[idx["s5.act_lizard_tail"]] == 0.0
    assert f5[idx["s5.ctr_pen_nib"]] == 9.0
    assert f5[idx["s5.act_art_of_war"]] == 1.0
    assert f5[idx["s5.act_pocketwatch"]] == 1.0
    assert f5[idx["s5.relic_count"]] == 5.0

    # 4. Per-enemy slots (e0 has poison=8 + accelerant=1 -> next tick = 8+7=15 >= 12 hp -> doomed!)
    assert f5[idx["s5.e0.poison"]] == 8.0
    assert f5[idx["s5.e0.doomed_poison"]] == 1.0
    assert f5[idx["s5.e0.last_dmg"]] == 28.0
    assert f5[idx["s5.e0.last_hits"]] == 2.0
    assert f5[idx["s5.e1.defense_power"]] == 1.0
    assert f5[idx["s5.e1.last_non_atk"]] == 1.0

    # 5. Aggregate & boss mechanics
    assert f5[idx["s5.living_non_doomed"]] == 1.0
    assert abs(f5[idx["s5.kaiser_crusher_hp"]] - 0.1) < 1e-6
    assert abs(f5[idx["s5.kaiser_rocket_hp"]] - 0.6) < 1e-6
    assert f5[idx["s5.kaiser_facing"]] == 1.0
    assert f5[idx["s5.frantic_escapes_live"]] == 1.0

    # 6. Analytical expected next-5 draw: 2/2 from draw (1 block, 1 attack) + 3/4 from discard (2 block, 1 attack, 1 burn)
    assert abs(f5[idx["s5.exp_draw_block"]] - (1.0 + 0.75 * 2.0)) < 1e-5
    assert abs(f5[idx["s5.exp_draw_attack"]] - (1.0 + 0.75 * 1.0)) < 1e-5
    assert abs(f5[idx["s5.exp_draw_junk"]] - 0.75) < 1e-5

    # 7. Retained hand (Piercing Wail cost 1, Neutralize cost 0, Frantic Escape cost 1)
    assert f5[idx["s5.ret_block"]] == 1.0
    assert f5[idx["s5.ret_weak_wail"]] == 2.0
    assert f5[idx["s5.ret_zero_cost"]] == 1.0
    assert f5[idx["s5.ret_escape"]] == 1.0
    assert abs(f5[idx["s5.ret_avg_cost"]] - (2.0 / 3.0)) < 1e-5


def test_schema5_artifact_roundtrip_and_leaf_inference(tmp_path):
    st = _sample_completed_state()
    n = len(SCHEMA5_NAMES)
    widths = (256, 128, 64)
    rng = np.random.default_rng(7)
    mean = np.zeros(n, dtype=np.float32)
    scale = np.ones(n, dtype=np.float32)
    dims = (n, *widths, 2)
    layers = [
        (rng.normal(0, 0.05, size=(a, b)).astype(np.float32), np.zeros(b, dtype=np.float32))
        for a, b in zip(dims, dims[1:])
    ]
    out = tmp_path / "combat_value_v5_test.npz"
    export_model(out, mean, scale, layers, (1.1, -0.05), widths, schema=5)
    model = CombatValueModel.load(out)
    assert model.schema == 5
    p_win, hp_frac = model.leaf(st)
    assert 0.0 < p_win < 1.0
    assert 0.0 < hp_frac < 1.0


def test_kaiser_v68_fallback_is_strictly_opt_in():
    class DummyModel:
        def __init__(self):
            self.calls = 0

        def leaf(self, _state):
            self.calls += 1
            return 0.5, 0.5

    st = _sample_completed_state()
    st_kaiser = replace(st, kaiser_v63=True)

    # Legacy value_v68=False ALWAYS calls model even on kaiser_v63
    m1 = DummyModel()
    leaf_value(st_kaiser, 7.0, model=m1, win_weight=25.0, boss_safe=True, value_v68=False)
    assert m1.calls == 1

    # Opt-in value_v68=True keeps the neural model active across all fights including kaiser_v63
    m2 = DummyModel()
    leaf_value(st_kaiser, 7.0, model=m2, win_weight=25.0, boss_safe=True, value_v68=True)
    assert m2.calls == 1

    # Non-kaiser fights ALSO use the neural model under value_v68=True
    m3 = DummyModel()
    leaf_value(st, 7.0, model=m3, win_weight=25.0, boss_safe=True, value_v68=True)
    assert m3.calls == 1


def test_kaiser_scaling_v69_prefers_early_scaling_at_high_hp():
    class FlatModel:
        def leaf(self, _state):
            return 0.15, 0.30

    st = _sample_completed_state()
    v_poi = Variant("SNAKEBITE", "Skill", 2, "AnyEnemy")
    e0 = Enemy(0, "CRUSHER", 210, 219, 0, (), (Intent("Attack", 21, 1),), 0, False)
    e1 = Enemy(1, "ROCKET", 209, 209, 0, (), (Intent("Attack", 4, 1),), 0, False)
    base = replace(
        st,
        hp=77,
        max_hp=80,
        block=0,
        powers=(("SURROUNDED", 1),),
        enemies=(e0, e1),
        draw=(v_poi, v_poi),
        kaiser_v63=True,
    )
    # Option A: Defend -> stay at 77 HP, no Accelerant
    opt_defend = base
    # Option B: Play Accelerant+ -> take 6 chip damage (71 HP), gain ACCELERANT=2
    opt_scale = replace(base, hp=71, powers=(("ACCELERANT", 2), ("SURROUNDED", 1)))

    # Legacy Kaiser adjustment (4.0 * hp, 0 * Accelerant) wrongly prefers Defend over Accelerant+!
    _, s_def_old = leaf_value(opt_defend, 7.0, model=FlatModel(), win_weight=15.0, boss_safe=True, kaiser_scaling_v69=False)
    _, s_scl_old = leaf_value(opt_scale, 7.0, model=FlatModel(), win_weight=15.0, boss_safe=True, kaiser_scaling_v69=False)
    assert s_def_old > s_scl_old

    # Opt-in kaiser_scaling_v69 takes 6 chip damage at 77 HP to get Accelerant+ online!
    _, s_def_new = leaf_value(opt_defend, 7.0, model=FlatModel(), win_weight=15.0, boss_safe=True, kaiser_scaling_v69=True)
    _, s_scl_new = leaf_value(opt_scale, 7.0, model=FlatModel(), win_weight=15.0, boss_safe=True, kaiser_scaling_v69=True)
    assert s_scl_new > s_def_new + 10.0

    # At critical low HP (14 HP vs 2 HP), taking 12 damage is still strongly penalized
    low_safe = replace(base, hp=14)
    low_risk = replace(base, hp=2, powers=(("ACCELERANT", 2), ("SURROUNDED", 1)))
    _, s_low_safe = leaf_value(low_safe, 7.0, model=FlatModel(), win_weight=15.0, boss_safe=True, kaiser_scaling_v69=True)
    _, s_low_risk = leaf_value(low_risk, 7.0, model=FlatModel(), win_weight=15.0, boss_safe=True, kaiser_scaling_v69=True)
    assert s_low_safe > s_low_risk

    # Opt-in kaiser_pure_neural_v69 omits _boss_adjustment when model is provided on kaiser_v63
    _, s_pure = leaf_value(
        opt_defend, 7.0, model=FlatModel(), win_weight=15.0, boss_safe=True, kaiser_pure_neural_v69=True
    )
    expected_pure = round(0.15 * (80 * 0.30 + 15.0), 8)
    assert abs(s_pure - expected_pure) < 1e-6


