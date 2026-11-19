import pytest

from sts2rl.encounter_draft import WeakEncounterPool
from sts2rl.offer_policy import OfferModel
from sts2rl.run_policy import IDENTITY, RunPolicy, RunWeights
from sts2rl.strategy import StrategyModel
from sts2rl.survival_route import SurvivalRouter


def test_public_pool_counts_resolved_map_fights():
    ctx = {"act": 1, "act_name": "Underdocks", "floor": 1}
    pool = WeakEncounterPool({"decision": "event_choice", "context": ctx})

    def enter(room, *ids, action="select_map_node"):
        pool.observe(
            action,
            {
                "context": {**ctx, "room_type": room},
                "enemies": [{"id": "MONSTER." + name} for name in ids],
            },
        )

    assert pool.group_probability == 0.5
    enter("Monster", "SEAPUNK")
    enter("Shop")
    enter("Elite", "TERROR_EEL")
    enter("Event")
    enter("Monster", "SCRIPTED", action="choose_option")
    assert pool.normal_count == 1
    assert pool.group_probability == pytest.approx(2 / 3)
    enter("Monster", "SLUDGE_SPINNER")
    assert pool.group_probability == 1.0
    enter("Monster", "TOADPOLE", "TOADPOLE")
    assert pool.group_probability is None
    assert pool.normal_count == 3


def test_unknown_history_abstains_and_act_transition_expires_pool():
    ctx = {"act": 1, "act_name": "Overgrowth", "floor": 8}
    pool = WeakEncounterPool({"decision": "map_select", "context": ctx})
    assert pool.group_probability is pool.normal_count is None
    pool = WeakEncounterPool({"decision": "event_choice", "context": {**ctx, "floor": 1}})
    assert pool.group_probability == 0.25
    pool.observe(
        "select_map_node",
        {"context": {**ctx, "room_type": "Monster"}, "enemies": [{"id": "MONSTER.UNRECOGNIZED"}]},
    )
    assert pool.group_probability is None
    pool = WeakEncounterPool({"decision": "event_choice", "context": {**ctx, "floor": 1}})
    pool.observe("skip_card_reward", {"context": {"act": 2}})
    assert pool.group_probability is None


@pytest.mark.parametrize("floor", [4, 14])
def test_all_draft_options_explain_exact_deployed_scores(floor):
    ctx = {
        "act": 1,
        "act_name": "Underdocks",
        "floor": floor,
        "room_type": "Monster",
        "boss": {"id": "LAGAVULIN_MATRIARCH_BOSS"},
    }
    cards = [
        {
            "index": 0,
            "id": "CARD.DAGGER_SPRAY",
            "cost": 1,
            "type": "Attack",
            "description": "Deal damage to ALL enemies twice.",
            "stats": {"damage": 4},
        },
        {"index": 1, "id": "CARD.DEFEND_SILENT", "cost": 1, "type": "Skill", "stats": {"block": 5}},
    ]
    state = {
        "runtime_identity": IDENTITY,
        "decision": "card_reward",
        "context": ctx,
        "player": {"hp": 40, "max_hp": 70, "deck": []},
        "cards": cards,
        "can_skip": True,
    }
    policy = RunPolicy(RunWeights())
    model = StrategyModel(
        {"matchup/pool/area": 1.2, "card:take": 0.2},
        ["card"],
        0.55,
        card_offsets={"DAGGER_SPRAY": [0.1, 0.0, 0.0]},
    )
    opening = OfferModel({"card:DAGGER_SPRAY": 0.3, "skip": 0.2})
    trace = {}
    chosen = model.choose(state, policy, opening, group_probability=1, explanation=trace)
    assert model.choose(state, policy, opening, group_probability=1) == chosen
    assert trace["chosen_action"] == chosen.command()
    assert len(trace["options"]) == 3
    for option in trace["options"]:
        assert sum(option["prior_base_parts"].values()) == pytest.approx(option["prior_base"])
        assert option["prior"] == pytest.approx(
            option["prior_base"] + sum(x["points"] for x in option["prior_terms"].values())
        )
        assert option["strategy"] == pytest.approx(
            sum(x["points"] for x in option["strategy_terms"].values())
        )
        assert option["total"] == option["prior"] + option["strategy"] + option["card_offset"]
    assert max(trace["options"], key=lambda o: o["total"])["action"] == chosen.command()
    assert trace["options"][0]["strategy_terms"]["matchup/pool/area"]["points"] == pytest.approx(
        0.66
    )


def test_sandpit_escape_reserves_energy_and_preserves_lethal_and_free_cards():
    from sts2rl.native import Action
    from sts2rl.sandpit import escape_action

    enemy = {
        "id": "MONSTER.THE_INSATIABLE",
        "index": 0,
        "hp": 20,
        "block": 0,
        "powers": [{"id": "POWER.SANDPIT_POWER", "amount": 4}],
    }
    hit = {"id": "CARD.STRIKE_SILENT", "index": 0, "cost": 1, "stats": {"damage": 6}}
    escape = {"id": "CARD.FRANTIC_ESCAPE", "index": 1, "cost": 1, "stats": {}}
    state = {"decision": "combat_play", "enemies": [enemy], "energy": 1, "hand": [hit, escape]}
    attack = Action("attack", "play_card", {"card_index": 0, "target_index": 0}, "test")
    run = Action("escape", "play_card", {"card_index": 1}, "test")
    end = Action("end", "end_turn", {}, "test")
    actions = [attack, run, end]
    assert escape_action(state, actions, attack, 3) == attack
    assert escape_action(state, actions, attack, 4) == run
    assert escape_action(state, actions, end, 4) == run
    enemy["hp"] = 6
    assert escape_action(state, actions, attack, 4) == attack
    enemy["hp"] = 20
    hit["cost"] = 0
    assert escape_action(state, actions, attack, 4) == attack
    hit["cost"] = 1
    enemy["powers"].append({"id": "POWER.POISON_POWER", "amount": 20})
    assert escape_action(state, actions, attack, 4) == attack


def test_route_values_change_at_fourth_normal_fight():
    ctx = {"act": 1, "act_name": "Underdocks"}
    choices = [{"row": 7, "col": 0, "type": "Monster"}, {"row": 7, "col": 1, "type": "RestSite"}]
    state = {
        "decision": "map_select",
        "runtime_identity": IDENTITY,
        "context": ctx,
        "choices": choices,
        "player": {"hp": 45, "max_hp": 70, "gold": 70},
    }
    model = SurvivalRouter(
        {
            "version": 3,
            "cells": {},
            "boss_coefficients": {"1": [0, 2, 1, 1, 1, 1, 1]},
            "act1_context": {
                "rooms": {
                    "Underdocks/Monster/weak": [100, 0, 0, 0, 40, 0, 0, 0, 0],
                    "Underdocks/Monster/regular": [100, 70, -200, 0, 0, 0, 0, 0, 0],
                },
                "blend": 1.0,
                "unknown_fight_probability": {},
            },
        }
    )
    assert model.choose(state, [choices], normal_count=2).args["col"] == 0
    assert model.choose(state, [choices], normal_count=3).args["col"] == 1
