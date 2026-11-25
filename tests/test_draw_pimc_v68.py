"""Unit tests for opt-in v6.8 PIMC draw-card search and carryover leaf valuation."""

from __future__ import annotations

from sts2rl.combat_search_v2.planner import Config, search
from sts2rl.combat_search_v2.state import (
    Card,
    Enemy,
    Intent,
    Move,
    Projection,
    State,
    Variant,
)
from sts2rl.combat_search_v2.transitions import legal
from sts2rl.combat_search_v2.value import leaf_value


def _v(name: str, kind: str, cost: int, target: str = "None", up: int = 0, keywords=()):
    return Variant(name, kind, cost, target, up, keywords)


def _projected(hand, draw, *, energy=3, hp=50, block=0, enemy_hp=45, enemy_dmg=10, powers=(), enemy_powers=()):
    st = State(
        act=1,
        floor=5,
        room="Monster",
        round=1,
        hp=hp,
        max_hp=70,
        block=block,
        energy=energy,
        max_energy=3,
        hand=tuple(Card(i, v) for i, v in enumerate(hand)),
        draw=tuple(sorted(draw)),
        discard=(),
        exhaust=(),
        play=(),
        powers=powers,
        relics=(),
        enemies=(
            Enemy(
                slot=0,
                name="SHRINKER_BEETLE",
                hp=enemy_hp,
                max_hp=enemy_hp,
                block=0,
                powers=enemy_powers,
                intents=(Intent("SingleAttack", enemy_dmg, 1),) if enemy_dmg else (Intent("Buff", None, 1),),
                preview_strength=0,
                preview_weak=False,
            ),
        ),
        potions=(),
        next_slot=len(hand),
        silent_cards_v66=True,
        silent_cards_v67=True,
    )
    return Projection(
        state=st,
        hand_indices=tuple(range(len(hand))),
        enemy_indices=(0,),
        potion_indices=(),
        prompt_indices=(),
        playable=tuple(True for _ in hand),
        formation=("SHRINKER_BEETLE",),
    )


def test_pimc_picks_backflip_over_defend_and_eliminates_champion_fallback():
    backflip = _v("BACKFLIP", "Skill", 1, "Self")
    defend = _v("DEFEND_SILENT", "Skill", 1, "Self")
    strike = _v("STRIKE_SILENT", "Attack", 1, "AnyEnemy")
    neut = _v("NEUTRALIZE", "Attack", 0, "AnyEnemy")
    blade = _v("BLADE_DANCE", "Skill", 1, "Self")
    proj = _projected(
        hand=(backflip, defend),
        draw=(neut, blade, strike, strike, defend, defend),
        energy=2,
        enemy_dmg=10,
    )
    roots = legal(proj.state)
    m_backflip = Move("play_card", 0, -1)
    m_defend = Move("play_card", 1, -1)

    # Without PIMC: champion=Backflip aborts with "champion continuation unresolved"
    cfg_off = Config(silent_cards_v67=True, power_leaf_v62=True)
    res_off_bf = search(proj, roots, m_backflip, cfg_off)
    assert res_off_bf.fallback == "champion continuation unresolved"

    # Without PIMC: champion=Defend can NEVER choose Backflip
    res_off_def = search(proj, roots, m_defend, cfg_off)
    assert res_off_def.choice == m_defend

    # With PIMC: even when champion=Defend, search chooses Backflip cleanly with no fallback!
    cfg_on = Config(silent_cards_v67=True, power_leaf_v62=True, draw_pimc_v68=True, value_v68=True)
    res_on = search(proj, roots, m_defend, cfg_on)
    assert res_on.fallback == ""
    assert res_on.choice == m_backflip

    # And when champion=Backflip, no fallback occurs either
    res_on_bf = search(proj, roots, m_backflip, cfg_on)
    assert res_on_bf.fallback == ""
    assert res_on_bf.choice == m_backflip


def test_pimc_handles_prepared_and_adrenaline_cleanly():
    prepared = _v("PREPARED", "Skill", 0, "Self")
    adrenaline = _v("ADRENALINE", "Skill", 0, "Self", keywords=("Exhaust",))
    strike = _v("STRIKE_SILENT", "Attack", 1, "AnyEnemy")
    defend = _v("DEFEND_SILENT", "Skill", 1, "Self")
    proj = _projected(
        hand=(prepared, adrenaline, strike),
        draw=(strike, strike, defend, defend, defend),
        energy=1,
        enemy_dmg=5,
    )
    roots = legal(proj.state)
    cfg = Config(silent_cards_v67=True, power_leaf_v62=True, draw_pimc_v68=True, value_v68=True)
    res = search(proj, roots, Move("play_card", 2, 0), cfg)
    assert res.fallback == ""
    assert res.choice in (Move("play_card", 0, -1), Move("play_card", 1, -1))


def test_pimc_respects_guaranteed_survival_over_risky_draw():
    # Player at 5 HP vs 10 dmg: Defend+Defend guarantees survival (0 dmg taken).
    # Prepared/Acrobatics (cost 1) leaves only 1 energy -> risks death if draw misses block!
    acro = _v("ACROBATICS", "Skill", 1, "Self")
    defend = _v("DEFEND_SILENT", "Skill", 1, "Self")
    strike = _v("STRIKE_SILENT", "Attack", 1, "AnyEnemy")
    proj = _projected(
        hand=(acro, defend, defend),
        draw=(strike, strike, strike, strike, strike, defend),
        energy=2,
        hp=5,
        enemy_hp=60,
        enemy_dmg=10,
    )
    roots = legal(proj.state)
    cfg = Config(silent_cards_v67=True, power_leaf_v62=True, draw_pimc_v68=True, value_v68=True)
    res = search(proj, roots, Move("play_card", 0, -1), cfg)
    assert res.fallback == ""
    assert res.choice in (Move("play_card", 1, -1), Move("play_card", 2, -1))


def test_value_v68_blur_carryover_debuffs_and_retain():
    base_state = _projected(hand=(), draw=(), enemy_hp=60, enemy_dmg=0).state
    # 1. Blur with 20 leftover block at completed leaf gets higher valuation under value_v68
    blur_st = State(
        **{
            **{f: getattr(base_state, f) for f in base_state.__dataclass_fields__},
            "outcome": "completed",
            "block": 20,
            "powers": (("BLUR", 1),),
        }
    )
    _, old_blur = leaf_value(blur_st, 7.0, power_leaf_v62=True, value_v68=False)
    _, new_blur = leaf_value(blur_st, 7.0, power_leaf_v62=True, value_v68=True)
    assert new_blur > old_blur + 3.0

    # 2. Vulnerable left on living enemy gets positive credit under value_v68
    no_vuln = State(
        **{**{f: getattr(base_state, f) for f in base_state.__dataclass_fields__}, "outcome": "completed"}
    )
    with_vuln = State(
        **{
            **{f: getattr(base_state, f) for f in base_state.__dataclass_fields__},
            "outcome": "completed",
            "enemies": (
                Enemy(
                    slot=0,
                    name="SHRINKER_BEETLE",
                    hp=60,
                    max_hp=60,
                    block=0,
                    powers=(("VULNERABLE", 2),),
                    intents=(Intent("Buff", None, 1),),
                    preview_strength=0,
                    preview_weak=False,
                ),
            ),
        }
    )
    _, old_v0 = leaf_value(no_vuln, 7.0, power_leaf_v62=True, value_v68=False)
    _, old_v1 = leaf_value(with_vuln, 7.0, power_leaf_v62=True, value_v68=False)
    _, new_v0 = leaf_value(no_vuln, 7.0, power_leaf_v62=True, value_v68=True)
    _, new_v1 = leaf_value(with_vuln, 7.0, power_leaf_v62=True, value_v68=True)
    assert old_v1 == old_v0
    assert new_v1 > new_v0 + 2.5

    # 3. Retaining Piercing Wail outscores retaining Strike under value_v68
    ret_strike = State(
        **{
            **{f: getattr(base_state, f) for f in base_state.__dataclass_fields__},
            "outcome": "completed",
            "hand": (Card(0, _v("STRIKE_SILENT", "Attack", 1, "AnyEnemy")),),
        }
    )
    ret_wail = State(
        **{
            **{f: getattr(base_state, f) for f in base_state.__dataclass_fields__},
            "outcome": "completed",
            "hand": (Card(0, _v("PIERCING_WAIL", "Skill", 1, "AllEnemies")),),
        }
    )
    assert leaf_value(ret_wail, 7.0, power_leaf_v62=True, value_v68=True) > leaf_value(
        ret_strike, 7.0, power_leaf_v62=True, value_v68=True
    )
