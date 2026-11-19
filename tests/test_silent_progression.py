import json
import runpy
from pathlib import Path

import pytest

from sts2rl.deck_policy import DeckPolicy, deck_context
from sts2rl.encounter import EncounterPolicy
from sts2rl.native import digest, legal_actions
from sts2rl.run_evaluation import act_start
from sts2rl.run_policy import IDENTITY, RunWeights
from sts2rl.selections import selection_goal
from sts2rl.survival_route import SurvivalRouter
from sts2rl.trajectory import natural_specification, map_combat_openings


def test_seeded_trace_keeps_native_lobby_profile_and_first_hand(tmp_path):
    start = {
        "cmd": "training_restore",
        "seed": "MIX",
        "ascension": 10,
        "history": [],
        "act_list": "seeded",
    }
    assert natural_specification(start)["act_list"] == "seeded"
    with pytest.raises(ValueError):
        natural_specification({**start, "encounter": "FIXTURE"})
    path = tmp_path / "game"
    path.mkdir()

    def enter(row):
        return {"cmd": "action", "action": "select_map_node", "args": {"col": 2, "row": row}}

    attack = {"cmd": "action", "action": "play_card", "args": {"card_index": 0, "target_index": 0}}
    trace = [start, enter(16), attack, enter(0), enter(1), {"cmd": "get_map"}, attack]
    (path / "rpc.jsonl").write_text(
        "\n".join(
            json.dumps({"command": c, "response_digest": digest(i)}) for i, c in enumerate(trace)
        )
    )
    [(_, fork)] = map_combat_openings(tmp_path, 2, 1)
    assert fork.specification["act_list"] == "seeded"
    assert fork.history == (enter(16), attack, enter(0), enter(1))
    assert fork.expected_digest == digest(4)


def test_paired_report_requires_both_terminal_replays():
    compare = runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "scripts/compare-silent-bundles.py")
    )["compare"]

    def result(seed, clear):
        return {
            "seed": seed,
            "status": "complete",
            "a1_clear": clear,
            "a2_clear": False,
            "win": False,
            "boss_fights": [[1, 17]],
            "act_names": ["Overgrowth"],
        }

    rows = {
        "incumbent": [result("A", False), result("B", True)],
        "challenger": [result("A", True), result("B", False)],
    }
    report = compare(rows, {("incumbent", "A"), ("challenger", "A"), ("challenger", "B")})
    assert report["paired_verified"] == 1
    assert report["discordance"]["a1_clear"] == {"incumbent": 0, "challenger": 1}
    assert report["arms"]["incumbent"]["unresolved"] == ["B"]


def test_merchant_compares_affordable_baskets_before_purchasing():
    from sts2rl.merchant import merchant_choice

    state = {
        "decision": "shop",
        "context": {"act": 1, "floor": 6},
        "player": {"hp": 65, "max_hp": 70, "deck": [], "gold": 130, "potions": []},
        "cards": [{"index": 0, "is_stocked": True, "cost": 80}],
        "relics": [
            {
                "index": 0,
                "is_stocked": True,
                "cost": 120,
                "name": "Kunai",
                "description": "Gain Dexterity.",
            }
        ],
        "potions": [],
    }
    assert merchant_choice(state, lambda _: 0.0, reserve=1.0, permanent=1.1).kind == "buy_relic"
    state["player"]["gold"] = 79
    assert merchant_choice(state, lambda _: 0.0, reserve=1.0, permanent=1.1).kind == "leave_room"


def test_shop_obeys_native_procurement_and_can_spend_on_removal():
    state = {
        "decision": "shop",
        "player": {"gold": 90, "potions": [{}, {}]},
        "card_removal_cost": 75,
        "card_removal_available": True,
        "potions": [{"index": 0, "is_stocked": True, "cost": 50, "can_procure": True}],
    }
    actions = [a.kind for a in legal_actions(state)]
    assert actions == ["buy_potion", "leave_room", "remove_card"]
    state["potions"][0]["can_procure"] = False
    state["player"]["gold"] = 70
    assert [a.kind for a in legal_actions(state)] == ["leave_room"]
    # Historical observations use their original two-slot contract.
    state["potions"][0].pop("can_procure")
    assert [a.kind for a in legal_actions(state)] == ["leave_room"]


def test_restoration_combines_natural_history_at_act_three_only(tmp_path):
    def action(row):
        return {"cmd": "action", "action": "select_map_node", "args": {"col": 1, "row": row}}

    spec = {
        "cmd": "training_restore",
        "seed": "CHECK",
        "ascension": 10,
        "history": [action(1), action(16)],
    }
    commands = [spec, action(0), action(1), action(15), {"cmd": "get_map"}, action(0)]
    path = tmp_path / "trace.jsonl"
    path.write_text(
        "\n".join(
            json.dumps({"command": c, "response_digest": digest(i)}) for i, c in enumerate(commands)
        )
    )
    fork = act_start(path, 3)
    assert fork.specification == {"seed": "CHECK", "ascension": 10}
    assert list(fork.history) == spec["history"] + commands[1:4]
    assert fork.expected_digest == digest(3)


def test_survival_router_vetoes_an_elite_beyond_the_next_fork():
    stats = {
        "Elite": [100, 75, -1000, 0, 25, 0, 0, 10, 0],
        "Unknown": [100, 1, -90, 600, 3, 4, 5, 6, 2],
    }
    router = SurvivalRouter(
        {"cells": stats, "boss_coefficients": {"2": [-3, 2, 0.4, 0.4, 0.4, 0.2, 0.15]}}
    )
    choices = [{"row": 3, "col": i, "type": "Unknown"} for i in (0, 1)]
    state = {
        "decision": "map_select",
        "runtime_identity": IDENTITY,
        "context": {"act": 2},
        "choices": choices,
        "player": {"hp": 24, "max_hp": 70, "gold": 85},
    }
    graph = [
        [{**c, "children": [{"row": 4, "col": c["col"]}]} for c in choices],
        [
            {"row": 4, "col": 0, "type": "Elite", "children": [{"row": 5, "col": 0}]},
            {"row": 4, "col": 1, "type": "Unknown", "children": [{"row": 5, "col": 0}]},
        ],
        [{"row": 5, "col": 0, "type": "Boss"}],
    ]
    assert router.choose(state, graph).args["col"] == 1


def test_poison_payoff_and_contextual_selection():
    model = DeckPolicy({"version": 1, "runtime_identity": IDENTITY})
    poison = {"id": "CARD.DEADLY_POISON", "cost": 1, "type": "Skill", "stats": {"poisonpower": 5}}
    double = {"id": "CARD.ACCELERANT", "cost": 1, "type": "Power", "stats": {"accelerant": 1}}
    ctx = {"act": 2, "floor": 8}
    assert (
        model.grade(double, ctx, deck_context([poison] * 3))
        > model.grade(double, ctx, deck_context([])) + 10
    )
    state = {
        "decision": "event_choice",
        "options": [{"index": 0, "description": "Choose a card to Transform."}],
    }
    assert selection_goal(state, legal_actions(state)[0]) == "remove"
    state["options"][0]["description"] = "Choose a card to Upgrade."
    assert selection_goal(state, legal_actions(state)[0]) == "upgrade"


def test_boss_scorer_can_spend_a_potion_with_no_damage_variable():
    state = {
        "runtime_identity": IDENTITY,
        "decision": "combat_play",
        "observation_version": 2,
        "in_combat": True,
        "round": 4,
        "energy": 0,
        "hand": [],
        "player_powers": [],
        "context": {"act": 1, "floor": 17, "room_type": "Boss"},
        "player": {
            "hp": 4,
            "max_hp": 70,
            "block": 0,
            "deck": [],
            "potions": [
                {
                    "index": 0,
                    "id": "POTION.GHOST_IN_A_JAR",
                    "can_use": True,
                    "target_type": "Self",
                    "vars": {"IntangiblePower": 1},
                }
            ],
        },
        "enemies": [
            {
                "index": 0,
                "id": "MONSTER.VANTOM",
                "hp": 90,
                "max_hp": 180,
                "block": 0,
                "powers": [],
                "intents": [{"type": "Attack", "damage": 20}],
            }
        ],
    }
    assert EncounterPolicy(RunWeights())(state).kind == "use_potion"


def test_isolate_prioritizes_a_follower_until_the_leader_is_in_reach():
    from test_micro import state as combat_state

    state = combat_state()
    state["runtime_identity"] = IDENTITY
    state["context"].update(room_type="Boss", floor=17)
    state["player"]["deck"] = list(state["hand"])
    target = {
        "hp": 60,
        "max_hp": 60,
        "block": 0,
        "intents": [],
        "index": 0,
        "id": "MONSTER.KIN_FOLLOWER",
        "powers": [{"id": "POWER.MINION_POWER", "amount": 1}],
    }
    leader = {
        **target,
        "index": 1,
        "hp": 195,
        "max_hp": 195,
        "id": "MONSTER.KIN_PRIEST",
        "powers": [],
    }
    state["enemies"] = [target, leader]
    assert EncounterPolicy(RunWeights(), style="balanced")(state).args["target_index"] == 1
    isolate = EncounterPolicy(RunWeights(), style="isolate")
    assert isolate(state).args["target_index"] == 0
    leader["hp"] = 6
    assert isolate(state).args["target_index"] == 1
