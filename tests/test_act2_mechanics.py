"""Unit tests for opt-in Act 2 combat mechanics (act2_mechanics) in turn_planning & encounter."""

from __future__ import annotations

from sts2rl.encounter import EncounterModel, EncounterPolicy
from sts2rl.native import legal_actions
from sts2rl.run_policy import IDENTITY, RunPolicy, RunWeights
from sts2rl.turn_planning import choose_turn, choose_turn_survival


def _combat_state(
    enemies,
    hand,
    *,
    hp=40,
    max_hp=70,
    block=0,
    energy=3,
    player_powers=(),
    room="Monster",
    act=2,
    boss=None,
):
    ctx = {"act": act, "floor": 10, "room_type": room}
    if boss:
        ctx["boss"] = {"id": boss}
    return {
        "runtime_identity": IDENTITY,
        "observation_version": 2,
        "decision": "combat_play",
        "in_combat": True,
        "round": 2,
        "energy": energy,
        "context": ctx,
        "player": {
            "hp": hp,
            "max_hp": max_hp,
            "block": block,
            "potions": [],
            "deck": list(hand),
            "relics": [],
        },
        "player_powers": list(player_powers),
        "enemies": enemies,
        "hand": hand,
    }


def _attack(idx, cid, dmg, cost=1, *, hits=1):
    return {
        "index": idx,
        "id": cid,
        "type": "Attack",
        "cost": cost,
        "can_play": True,
        "target_type": "AnyEnemy",
        "stats": {"damage": dmg, "repeat": hits},
        "damage_by_target": [],
    }


def test_parafright_illusion_minion_does_not_block_obscura_lethal():
    """Killing The Obscura clears combat even when minion Parafright has ILLUSION_POWER."""
    enemies = [
        {
            "index": 0,
            "id": "MONSTER.PARAFRIGHT",
            "hp": 21,
            "max_hp": 21,
            "block": 0,
            "intents": [{"type": "Attack", "damage": 20}],
            "powers": [
                {"id": "POWER.ILLUSION_POWER", "amount": 1},
                {"id": "POWER.MINION_POWER", "amount": 1},
            ],
        },
        {
            "index": 1,
            "id": "MONSTER.THE_OBSCURA",
            "hp": 10,
            "max_hp": 129,
            "block": 0,
            "intents": [{"type": "Attack", "damage": 10}],
            "powers": [],
        },
    ]
    hand = [_attack(0, "CARD.STRIKE_SILENT", 12, cost=1)]
    state = _combat_state(enemies, hand, hp=15, energy=1)
    pol = EncounterPolicy(RunWeights(), style="engine", mechanics=True, act2_mechanics=True)
    act = choose_turn(state, pol, survival_priority=True)
    assert act.kind == "play_card"
    assert act.args["target_index"] == 1


def test_parafright_nonlethal_chip_penalized_vs_obscura():
    """Non-lethal attack should target The Obscura instead of wasting chip damage on Parafright."""
    enemies = [
        {
            "index": 0,
            "id": "MONSTER.PARAFRIGHT",
            "hp": 21,
            "max_hp": 21,
            "block": 0,
            "intents": [{"type": "Attack", "damage": 17}],
            "powers": [
                {"id": "POWER.ILLUSION_POWER", "amount": 1},
                {"id": "POWER.MINION_POWER", "amount": 1},
            ],
        },
        {
            "index": 1,
            "id": "MONSTER.THE_OBSCURA",
            "hp": 90,
            "max_hp": 129,
            "block": 0,
            "intents": [{"type": "Attack", "damage": 7}],
            "powers": [],
        },
    ]
    hand = [_attack(0, "CARD.STRIKE_SILENT", 9, cost=1)]
    state = _combat_state(enemies, hand, hp=50, energy=1)
    pol = EncounterPolicy(RunWeights(), style="engine", mechanics=True, act2_mechanics=True)
    actions = legal_actions(state)
    scores = pol.combat_scores(state, actions)
    s_para = next(s for a, s in zip(actions, scores) if a.args.get("target_index") == 0)
    s_obs = next(s for a, s in zip(actions, scores) if a.args.get("target_index") == 1)
    assert s_obs > s_para


def test_curl_up_prefers_big_attack_before_chip():
    """With CURL_UP_POWER=18, survival beam plays heavy hit BEFORE 3-dmg chip to kill before Curl Up."""
    enemies = [
        {
            "index": 0,
            "id": "MONSTER.LOUSE_PROGENITOR",
            "hp": 15,
            "max_hp": 139,
            "block": 0,
            "intents": [{"type": "Attack", "damage": 23}],
            "powers": [{"id": "POWER.CURL_UP_POWER", "amount": 18}],
        }
    ]
    hand = [
        _attack(0, "CARD.NEUTRALIZE", 3, cost=0),
        _attack(1, "CARD.PREDATOR", 15, cost=2),
    ]
    state = _combat_state(enemies, hand, hp=10, energy=2)
    pol = EncounterPolicy(RunWeights(), style="engine", mechanics=True, act2_mechanics=True)
    act = choose_turn(state, pol, survival_priority=True)
    assert act.kind == "play_card"
    assert act.args["card_index"] == 1


def test_kaiser_crab_surrounded_facing_survival_flip():
    """Facing Crusher while Rocket swings for 57 from behind: survival search flips facing to Rocket to live."""
    enemies = [
        {
            "index": 0,
            "id": "MONSTER.CRUSHER",
            "hp": 150,
            "max_hp": 219,
            "block": 0,
            "intents": [{"type": "Buff"}],
            "powers": [
                {"id": "POWER.BACK_ATTACK_LEFT_POWER", "amount": 1},
                {"id": "POWER.CRAB_RAGE_POWER", "amount": 1},
            ],
        },
        {
            "index": 1,
            "id": "MONSTER.ROCKET",
            "hp": 180,
            "max_hp": 209,
            "block": 0,
            "intents": [{"type": "Attack", "damage": 57}],
            "powers": [
                {"id": "POWER.BACK_ATTACK_RIGHT_POWER", "amount": 1},
                {"id": "POWER.CRAB_RAGE_POWER", "amount": 1},
            ],
        },
    ]
    hand = [_attack(0, "CARD.STRIKE_SILENT", 6, cost=1)]
    state = _combat_state(
        enemies,
        hand,
        hp=45,
        energy=1,
        player_powers=[{"id": "POWER.SURROUNDED_POWER", "amount": 1}],
        room="Boss",
        boss="KAISER_CRAB_BOSS",
    )
    pol = EncounterPolicy(RunWeights(), style="engine", mechanics=True, act2_mechanics=True)
    actions = legal_actions(state)
    wrong = next(a for a in actions if a.args.get("target_index") == 0)
    chosen = choose_turn_survival(state, pol, wrong, facing=0)
    assert chosen.kind == "play_card"
    assert chosen.args["target_index"] == 1


def test_kaiser_crab_rage_prevents_suicidal_ally_kill():
    """Killing Crusher enrages Rocket (+5 Str -> 31 dmg >= 28 HP); survival search avoids killing Crusher."""
    enemies = [
        {
            "index": 0,
            "id": "MONSTER.CRUSHER",
            "hp": 6,
            "max_hp": 219,
            "block": 0,
            "intents": [{"type": "Buff"}],
            "powers": [
                {"id": "POWER.BACK_ATTACK_LEFT_POWER", "amount": 1},
                {"id": "POWER.CRAB_RAGE_POWER", "amount": 1},
            ],
        },
        {
            "index": 1,
            "id": "MONSTER.ROCKET",
            "hp": 180,
            "max_hp": 209,
            "block": 0,
            "intents": [{"type": "Attack", "damage": 26}],
            "powers": [
                {"id": "POWER.BACK_ATTACK_RIGHT_POWER", "amount": 1},
                {"id": "POWER.CRAB_RAGE_POWER", "amount": 1},
            ],
        },
    ]
    hand = [_attack(0, "CARD.STRIKE_SILENT", 8, cost=1)]
    state = _combat_state(
        enemies,
        hand,
        hp=28,
        energy=1,
        player_powers=[{"id": "POWER.SURROUNDED_POWER", "amount": 1}],
        room="Boss",
        boss="KAISER_CRAB_BOSS",
    )
    pol = EncounterPolicy(RunWeights(), style="engine", mechanics=True, act2_mechanics=True)
    actions = legal_actions(state)
    kill_crusher = next(a for a in actions if a.args.get("target_index") == 0)
    # Facing Rocket (1): Rocket deals 26 (< 28) if Crusher lives, but 26 + 5 = 31 (>= 28) if Crusher dies!
    chosen = choose_turn_survival(state, pol, kill_crusher, facing=1)
    assert chosen.args.get("target_index") != 0


def test_encounter_model_kaiser_crab_runs_survival_when_act2_mechanics_enabled():
    """EncounterModel with act2_mechanics=True runs survival_search even on Kaiser Crab facing plans."""
    enc = EncounterModel.from_data(
        {
            "version": 1,
            "runtime_identity": IDENTITY,
            "default": "engine",
            "survival_search": True,
            "survival_beam": True,
            "act2_mechanics": True,
            "act2_boss_plans": {
                "KAISER_CRAB_BOSS": {
                    "facing": 1.75,
                    "focus": "MONSTER.CRUSHER",
                    "focus_bonus": 50,
                    "search": "beam",
                }
            },
        }
    )
    enemies = [
        {
            "index": 0,
            "id": "MONSTER.CRUSHER",
            "hp": 150,
            "max_hp": 219,
            "block": 0,
            "intents": [{"type": "Buff"}],
            "powers": [
                {"id": "POWER.BACK_ATTACK_LEFT_POWER", "amount": 1},
                {"id": "POWER.CRAB_RAGE_POWER", "amount": 1},
            ],
        },
        {
            "index": 1,
            "id": "MONSTER.ROCKET",
            "hp": 180,
            "max_hp": 209,
            "block": 0,
            "intents": [{"type": "Attack", "damage": 57}],
            "powers": [
                {"id": "POWER.BACK_ATTACK_RIGHT_POWER", "amount": 1},
                {"id": "POWER.CRAB_RAGE_POWER", "amount": 1},
            ],
        },
    ]
    hand = [_attack(0, "CARD.STRIKE_SILENT", 6, cost=1)]
    state = _combat_state(
        enemies,
        hand,
        hp=45,
        energy=1,
        player_powers=[{"id": "POWER.SURROUNDED_POWER", "amount": 1}],
        room="Boss",
        boss="KAISER_CRAB_BOSS",
    )
    base = RunPolicy(RunWeights())
    enc.prepare(state, base)
    enc.boss_tactics.facing = 0
    action = enc.choose(state, base)
    assert action.kind == "play_card"
    assert action.args["target_index"] == 1


def test_crab_rage_grants_99_block_on_ally_death_preventing_fake_clear():
    """Killing one 6-HP crab gives the surviving crab 99 Block immediately, so 2 Strikes do NOT clear."""
    enemies = [
        {
            "index": 0,
            "id": "MONSTER.CRUSHER",
            "hp": 6,
            "max_hp": 219,
            "block": 0,
            "intents": [{"type": "Buff"}],
            "powers": [
                {"id": "POWER.BACK_ATTACK_LEFT_POWER", "amount": 1},
                {"id": "POWER.CRAB_RAGE_POWER", "amount": 1},
            ],
        },
        {
            "index": 1,
            "id": "MONSTER.ROCKET",
            "hp": 6,
            "max_hp": 209,
            "block": 0,
            "intents": [{"type": "Attack", "damage": 12}],
            "powers": [
                {"id": "POWER.BACK_ATTACK_RIGHT_POWER", "amount": 1},
                {"id": "POWER.CRAB_RAGE_POWER", "amount": 1},
            ],
        },
    ]
    # 10 HP: killing Crusher leaves Rocket alive with 99 Block and 12+6=18 dmg (fatal!).
    # Killing Rocket FIRST leaves Crusher idle (0 dmg, survives!).
    hand = [
        _attack(0, "CARD.STRIKE_SILENT", 6, cost=1),
        _attack(1, "CARD.STRIKE_SILENT", 6, cost=1),
    ]
    state = _combat_state(
        enemies,
        hand,
        hp=10,
        energy=2,
        player_powers=[{"id": "POWER.SURROUNDED_POWER", "amount": 1}],
        room="Boss",
        boss="KAISER_CRAB_BOSS",
    )
    pol = EncounterPolicy(RunWeights(), style="engine", mechanics=True, act2_mechanics=True)
    act = choose_turn(state, pol, survival_priority=True, facing=1)
    assert act.kind == "play_card"
    assert act.args["target_index"] == 1


def test_curl_up_triggers_after_full_multihit_attack_and_dedup_preserves_expose_order():
    """Multi-hit attack resolves all hits before Curl Up; beam dedup keeps Strike->Expose->Strike clear."""
    # 1. Multi-hit 8x3 kills a 24-HP Louse with Curl Up 18 BEFORE Curl Up adds Block.
    louse_24 = [
        {
            "index": 0,
            "id": "MONSTER.LOUSE_PROGENITOR",
            "hp": 24,
            "max_hp": 139,
            "block": 0,
            "intents": [{"type": "Attack", "damage": 30}],
            "powers": [{"id": "POWER.CURL_UP_POWER", "amount": 18}],
        }
    ]
    skewer_hand = [
        _attack(0, "CARD.RIDDLE_WITH_HOLES", 8, cost=1, hits=3),
        {
            "index": 1,
            "id": "CARD.DEFEND_SILENT",
            "type": "Skill",
            "cost": 1,
            "can_play": True,
            "target_type": "Self",
            "stats": {"block": 12},
        },
    ]
    st1 = _combat_state(louse_24, skewer_hand, hp=10, energy=1)
    pol = EncounterPolicy(RunWeights(), style="engine", mechanics=True, act2_mechanics=True)
    act1 = choose_turn(st1, pol, survival_priority=True)
    assert act1.kind == "play_card"
    assert act1.args["card_index"] == 0

    # 2. Against 12-HP Louse with Curl Up 18, Strike(6)->Expose->Strike(6) clears; dedup must not drop it.
    louse_12 = [{**louse_24[0], "hp": 12}]
    expose_hand = [
        {
            "index": 0,
            "id": "CARD.EXPOSE",
            "type": "Skill",
            "cost": 0,
            "can_play": True,
            "target_type": "AnyEnemy",
            "stats": {"power": 2},
        },
        _attack(1, "CARD.STRIKE_SILENT", 6, cost=1),
        _attack(2, "CARD.STRIKE_SILENT", 6, cost=1),
    ]
    st2 = _combat_state(louse_12, expose_hand, hp=10, energy=2)
    act2 = choose_turn(st2, pol, survival_priority=True)
    assert act2.kind == "play_card"
    assert act2.args["card_index"] in (1, 2)  # Must play Strike BEFORE Expose to pop then clear Curl Up!


def test_greedy_obscura_lethal_beats_parafright_and_kaiser_beam_respects_facing_cost():
    """Greedy scorer kills Obscura over Parafright when both are lethal; Kaiser beam avoids +19 back-attack dmg."""
    # 1. Greedy Parafright vs Obscura lethal
    enemies = [
        {
            "index": 0,
            "id": "MONSTER.PARAFRIGHT",
            "hp": 8,
            "max_hp": 21,
            "block": 0,
            "intents": [{"type": "Attack", "damage": 17}],
            "powers": [
                {"id": "POWER.ILLUSION_POWER", "amount": 1},
                {"id": "POWER.MINION_POWER", "amount": 1},
            ],
        },
        {
            "index": 1,
            "id": "MONSTER.THE_OBSCURA",
            "hp": 8,
            "max_hp": 129,
            "block": 0,
            "intents": [{"type": "Buff"}],
            "powers": [],
        },
    ]
    st_obs = _combat_state(enemies, [_attack(0, "CARD.STRIKE_SILENT", 9, cost=1)], hp=50, energy=1)
    pol = EncounterPolicy(RunWeights(), style="engine", mechanics=True, act2_mechanics=True)
    assert pol.combat(st_obs, legal_actions(st_obs)).args["target_index"] == 1

    # 2. Kaiser beam must NOT spend 19 HP for a +5 focus_bonus when facing Rocket saves 19 damage.
    crabs = [
        {
            "index": 0,
            "id": "MONSTER.CRUSHER",
            "hp": 150,
            "max_hp": 219,
            "block": 0,
            "intents": [{"type": "Buff"}],
            "powers": [
                {"id": "POWER.BACK_ATTACK_LEFT_POWER", "amount": 1},
                {"id": "POWER.CRAB_RAGE_POWER", "amount": 1},
            ],
        },
        {
            "index": 1,
            "id": "MONSTER.ROCKET",
            "hp": 180,
            "max_hp": 209,
            "block": 0,
            "intents": [{"type": "Attack", "damage": 38}],
            "powers": [
                {"id": "POWER.BACK_ATTACK_RIGHT_POWER", "amount": 1},
                {"id": "POWER.CRAB_RAGE_POWER", "amount": 1},
            ],
        },
    ]
    st_crab = _combat_state(
        crabs,
        [_attack(0, "CARD.STRIKE_SILENT", 6, cost=1)],
        hp=70,
        energy=1,
        player_powers=[{"id": "POWER.SURROUNDED_POWER", "amount": 1}],
        room="Boss",
        boss="KAISER_CRAB_BOSS",
    )
    enc = EncounterModel.from_data(
        {
            "version": 1,
            "runtime_identity": IDENTITY,
            "default": "engine",
            "survival_search": True,
            "survival_beam": True,
            "act2_mechanics": True,
            "act2_boss_plans": {
                "KAISER_CRAB_BOSS": {
                    "facing": 1.75,
                    "focus": "MONSTER.CRUSHER",
                    "focus_bonus": 5,
                    "search": "beam",
                }
            },
        }
    )
    base = RunPolicy(RunWeights())
    enc.prepare(st_crab, base)
    enc.boss_tactics.facing = 1  # Facing Rocket (38 dmg); attacking Crusher would flip to 57 dmg!
    assert enc.choose(st_crab, base).args["target_index"] == 1

