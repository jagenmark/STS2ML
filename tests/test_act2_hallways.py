from types import SimpleNamespace

import pytest

from sts2rl.act2_action_ranker import action_features, rerank
from sts2rl.act2_hallways import HallwayPlans, formation_key
from sts2rl.encounter import EncounterModel, EncounterPolicy, STYLES
from sts2rl.native import legal_actions
from sts2rl.run_policy import IDENTITY, RunPolicy, RunWeights
from sts2rl.turn_planning import choose_turn
from test_teacher_status import hand


def hunter(*cards):
    obs = hand(*cards)
    obs["context"].update(act=2, room_type="Monster")
    obs["enemies"][0].update(id="MONSTER.HUNTER_KILLER", intents=[])
    obs["player_powers"] = [{"id": "POWER.TENDER_POWER", "amount": 1}]
    return obs


def test_formation_is_order_independent_and_keeps_duplicate_living_enemies():
    state = hunter()
    state["enemies"] = [
        {"id": "MONSTER.B", "hp": 5},
        {"id": "MONSTER.A", "hp": 2},
        {"id": "MONSTER.B", "hp": 1},
        {"id": "MONSTER.C", "hp": 0},
    ]
    assert formation_key(state) == "A+B+B"
    config = {"plans": {"paired": {"style": "guard"}}, "by_formation": {"A+B+B": "paired"}}
    selector = HallwayPlans(config, STYLES)
    assert selector.select(state, lambda _: {}) == {"style": "guard"}
    with pytest.raises(ValueError):
        HallwayPlans({**config, "by_room": {"Monster": "lost"}}, STYLES)


def test_third_act_combat_plans_and_action_ranker_do_not_change_earlier_acts_or_bosses():
    state = hunter(("CARD.STRIKE_SILENT", "AnyEnemy", {"damage": 6}))
    settings = {"version": 1, "runtime_identity": IDENTITY, "default": "engine"}
    variant = EncounterModel({**settings,
        "act3_hallways": {"plans": {"hold": {"style": "guard"}}, "by_room": {"Monster": "hold", "Elite": "hold"}},
        "act3_action_ranker": {"weights": {}, "scale": 1, "prior_scale": 1, "max_round": 2},
        "act3_intents": {"weight": 1, "table": {}},
    })
    base = RunPolicy(RunWeights())
    for act, room in ((1,"Monster"), (2,"Elite"), (3,"Elite"), (3,"Monster"), (3,"Boss")):
        state["context"].update(act=act, room_type=room)
        action = variant.choose(state, base)
        applies = act == 3 and room != "Boss"
        assert variant.rerank_fight == applies
        assert bool(variant.actor.intent_forecast) == applies
        assert variant.actor.style == STYLES["guard" if applies else "engine"]
        if not applies:
            assert action == EncounterModel(settings).choose(state, base)


def test_forecast_falls_back_to_current_attack_and_matches_distinct_public_move_signatures():
    from sts2rl.act3_combat import forecast_keys, predicted_damage

    enemy = {"id": "MONSTER.OWL_MAGISTRATE", "intents": [{"type": "Attack", "damage": 4, "hits": 6}]}
    table = {forecast_keys(enemy, 2)[1]: 0}
    assert predicted_damage(table, enemy, 3) == 0
    assert predicted_damage({}, enemy, 3) == 24
    enemy["intents"] = None
    assert predicted_damage(table, enemy, 3) == 0


def test_tender_uses_current_preview_and_spends_no_stack_on_a_potion():
    state = hunter(
        ("CARD.SINGLE", "AnyEnemy", {"damage": 4}),
        ("CARD.MULTI", "AnyEnemy", {"damage": 8, "calculatedhits": 3}),
    )
    enemy = state["enemies"][0]
    enemy["hp"] = 10
    for card, damage in zip(state["hand"], (4, 8), strict=True):
        card.update(type="Attack", damage_by_target=[{"target_index": 0, "total_damage": damage}])

    def policy(tender):
        return SimpleNamespace(
            tender=tender,
            weights=RunWeights(),
            combat_scores=lambda _, actions: [10.0] * (len(actions) - 1) + [0.0],
        )

    assert choose_turn(state, policy(False), depth=2).args["card_index"] == 0
    assert choose_turn(state, policy(True), depth=2).args["card_index"] == 1
    state["hand"] = state["hand"][1:]
    state["player"]["potions"] = [
        {
            "id": "POTION.FIRE_POTION",
            "index": 0,
            "target_type": "AnyEnemy",
            "can_use": True,
            "vars": {"Damage": 2},
        }
    ]
    p = policy(True)
    p.combat_scores = lambda *_: [10.0, 11.0, 0.0]
    assert choose_turn(state, p, depth=2).kind == "use_potion"


def test_generated_shivs_lose_output_in_public_tender_order():
    state = hunter(("CARD.BLADE_DANCE", "Self", {"cards": 3}))
    policy = EncounterPolicy(RunWeights(), style="engine", tender=True)
    actions = legal_actions(state)
    affected = policy.combat_scores(state, actions)[0]
    state["player_powers"] = []
    plain = policy.combat_scores(state, legal_actions(state))[0]
    assert plain - affected == pytest.approx(6.0)


def test_optional_ranking_only_changes_authorized_act_two_formations():
    state = hunter(("CARD.STRIKE_SILENT", "AnyEnemy", {"damage": 6}))
    state["hand"][0]["type"] = "Attack"
    cfg = {
        "version": 1,
        "runtime_identity": IDENTITY,
        "default": "engine",
        "act2_hallways": {
            "plans": {"trained": {"style": "guard", "tender": True}},
            "by_formation": {"HUNTER_KILLER": "trained"},
        },
        "act2_action_ranker": {
            "prior_scale": 0,
            "scale": 1,
            "weights": {"id/end": 100},
            "formations": ["HUNTER_KILLER"],
        },
    }
    model = EncounterModel(cfg)
    base = RunPolicy(RunWeights())
    assert model.choose(state, base).kind == "end_turn"
    assert model.actor.tender and model.rerank_fight
    for act, room in [(2, "Boss"), (3, "Monster"), (1, "Elite")]:
        state["context"].update(act=act, room_type=room)
        assert model.choose(state, base).kind == "play_card"
        assert not model.actor.tender and not model.rerank_fight
    state["context"].update(act=2, room_type="Monster")
    state["enemies"][0]["id"] = "MONSTER.OTHER"
    assert model.choose(state, base).kind == "play_card"


def test_action_features_and_margin_ignore_private_future_and_keep_first_choice_on_ties():
    state = hunter(("CARD.STRIKE_SILENT", "AnyEnemy", {"damage": 6}))
    state["hand"][0]["type"] = "Attack"
    policy = RunPolicy(RunWeights())
    legal = legal_actions(state)
    scores = policy.combat_scores(state, legal)
    features = action_features(state, legal, scores)
    state.update(seed="PRIVATE", rng={"next": 27}, draw_pile=[{"id": "CARD.NEVER_SEEN"}])
    legal = legal_actions(state)
    assert features == action_features(state, legal, scores)
    assert (
        rerank(
            {"prior_scale": 0, "scale": 1, "weights": {"id/end": 1}, "margin": 2},
            state,
            legal,
            legal[0],
            policy,
        )
        == legal[0]
    )


def test_swift_potion_reads_native_vars_and_respects_hand_capacity():
    state = hunter(("CARD.DEFEND_SILENT", "Self", {"block": 5}))
    state["player_powers"] = []
    state["enemies"][0]["intents"] = [
        {"type": "Attack", "damage": 16, "hits": 1, "total_damage": 16}
    ]
    state["player"].update(
        hp=10,
        block=0,
        deck=state["hand"] * 4,
        potions=[
            {
                "id": "POTION.SWIFT_POTION",
                "index": 0,
                "target_type": "Self",
                "can_use": True,
                "vars": {"Cards": 3},
            }
        ],
    )

    def points(enabled):
        policy = EncounterPolicy(RunWeights(), style="engine", draw_potions=enabled)
        actions = legal_actions(state)
        scores = policy.combat_scores(state, actions)
        return next(
            score
            for action, score in zip(actions, scores, strict=True)
            if action.kind == "use_potion"
        )

    assert points(True) > points(False) + 10
    state["hand"] = [{**state["hand"][0], "index": i} for i in range(10)]
    assert points(True) == points(False)


def test_lucky_tonic_does_not_count_a_multiattack_as_one_hit():
    state = hunter(("CARD.DEFEND_SILENT", "Self", {"block": 5}))
    state["player_powers"] = []
    state["player"].update(
        hp=12,
        block=0,
        potions=[
            {
                "id": "POTION.LUCKY_TONIC",
                "index": 0,
                "target_type": "Self",
                "can_use": True,
                "vars": {"BufferPower": 1},
            }
        ],
    )
    policy = EncounterPolicy(RunWeights(), style="engine", potion_effects=True)

    def points(hits):
        state["enemies"][0]["intents"] = [
            {"type": "Attack", "damage": 18 // hits, "hits": hits, "total_damage": 18}
        ]
        actions = legal_actions(state)
        return policy.combat_scores(state, actions)[1]

    assert points(1) > points(3) > 0
