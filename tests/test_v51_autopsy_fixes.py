from copy import deepcopy
import gzip
import hashlib
import json
import os
from pathlib import Path
import runpy
from shutil import copytree
from types import SimpleNamespace

import pytest

from sts2rl.deployed_controller import DeployedController
from sts2rl.native import NativeSession, digest, legal_actions
from sts2rl.run_bundle import V51_SWITCHES, freeze_bundle, load_bundle
from sts2rl.run_policy import IDENTITY
from test_teacher_status import hand
from test_v5_lategame_autopsy import camp

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "releases/silent-a10-v2-tactics/challenger/policy.json"


def controller(*flags):
    actor = DeployedController.from_bundle(BUNDLE)
    for flag in flags:
        setattr(actor.policy, flag, True)
    return actor


def reward(name, stats, deck):
    return dict(decision="card_reward", runtime_identity=IDENTITY, can_skip=True, in_combat=False,
                context={"act": 2, "floor": 7}, player=dict(deck=deck, hp=60, max_hp=70, gold=100),
                cards=[dict(index=3, id="CARD." + name, cost=1, type="Power", stats=stats)])


@pytest.mark.parametrize("name,stats,deck", [
    ("ACCELERANT", {"accelerant": 1}, [{"id": "CARD.SNAKEBITE", "stats": {"poisonpower": 8}}]),
    ("ACCURACY", {"accuracypower": 4}, [{"id": "CARD.BLADE_DANCE", "stats": {"cards": 4}}]),
    ("PHANTOM_BLADES", {"phantombladespower": 9}, [{"id": "CARD.BLADE_DANCE", "stats": {"cards": 4}}]),
    ("INFINITE_BLADES", {}, []),
])
def test_first_free_scaling_copy_and_frozen_skip(name, stats, deck):
    state = reward(name, stats, deck)
    base, fixed = controller(), controller("v51_draft_fixes")
    assert base.choose(state, None).kind == "skip_card_reward"
    assert fixed.choose(state, None).args == {"card_index": 3}
    explanation = {}
    fixed.strategy.choose(state, fixed.policy, explanation=explanation)
    take = explanation["options"][0]
    assert take["prior"] == pytest.approx(sum(take["prior_base_parts"].values()))
    assert take["prior_base_parts"]["v51_scaling"] > 0
    state["player"]["deck"].append(state["cards"][0])
    assert base.choose(state, None) == fixed.choose(state, None)


@pytest.mark.parametrize("name,stats,deck", [
    ("ACCELERANT", {"accelerant": 1}, []),
    ("ACCELERANT", {"accelerant": 1}, [{"id": "CARD.BUBBLE_BUBBLE", "stats": {"poisonpower": 12}}]),
    ("ACCURACY", {"accuracypower": 4}, []),
    ("PHANTOM_BLADES", {"phantombladespower": 9}, []),
    ("NOXIOUS_FUMES", {"poisonperturn": 2}, []),
])
def test_unsupported_or_already_priced_reward_terms_unchanged(name, stats, deck):
    state = reward(name, stats, deck)
    scores = []
    for actor in (controller(), controller("v51_draft_fixes")):
        exp = {}
        actor.strategy.choose(state, actor.policy, explanation=exp)
        scores.append([v["total"] for v in exp["options"]])
    assert scores[0] == scores[1]


def test_shop_still_buys_from_its_own_grade():
    state = reward("ACCELERANT", {"accelerant": 1}, [{"id": "CARD.SNAKEBITE", "stats": {"poisonpower": 12}}])
    state.update(decision="shop", relics=[], potions=[])
    state["cards"][0].update(card_cost=1, cost=60, is_stocked=True)
    state["player"].update(relics=[], potions=[])
    for actor in (controller(), controller("v51_draft_fixes")):
        assert actor.choose(state, None).kind == "buy_card"


def boss_state(name, *cards):
    state = hand(*cards)
    state["context"].update(act=2, floor=16, room_type="Boss", boss={"id": name + "_BOSS"})
    state["enemies"][0].update(id="MONSTER." + name, hp=240, max_hp=320, intents=[])
    state["player"].update(hp=55, deck=[], block=0, relics=[])
    return state


def test_expensive_escape_banked_at_two_but_preserves_kill_and_lethal_block():
    state = boss_state("THE_INSATIABLE", ("CARD.STRIKE_SILENT", "AnyEnemy", {"damage": 6}),
                       ("CARD.FRANTIC_ESCAPE", "Self", {}), ("CARD.DEFEND_SILENT", "Self", {"block": 8}))
    state["energy"] = 2
    state["hand"][0].update(type="Attack", cost=1)
    state["hand"][1].update(type="Status", cost=2)
    state["hand"][2].update(type="Skill", cost=1)
    e = state["enemies"][0]
    e["powers"] = [{"id": "POWER.SANDPIT_POWER", "amount": 2}]
    base, fixed = controller(), controller("v51_boss_tactics")
    base.combat_v2 = fixed.combat_v2 = None
    assert base.choose(state, None).args["card_index"] == 0
    assert fixed.choose(state, None).args["card_index"] == 1
    e["hp"] = 5
    assert fixed.choose(state, None).args["card_index"] == 0
    e.update(hp=240, intents=[{"type": "Attack", "damage": 10, "total_damage": 10}])
    state["player"]["hp"] = 5
    assert fixed.choose(state, None).args["card_index"] == 2


def test_sloth_values_the_last_slot_and_only_counts_executed_cards():
    state = boss_state("KNOWLEDGE_DEMON", ("CARD.STRIKE_SILENT", "AnyEnemy", {"damage": 6}),
                       ("CARD.PREDATOR", "AnyEnemy", {"damage": 13}))
    state["hand"][0].update(type="Attack", cost=0)
    state["hand"][1].update(type="Attack", cost=2, id="CARD.DASH")
    state["player_powers"] = [{"id": "POWER.SLOTH_POWER", "amount": 3}]

    def choose_outside_search(fallback):
        fixed = controller("v51_boss_tactics")
        fixed.combat_v2 = SimpleNamespace(shadow=False, last_fallback=fallback,
                                         choose=lambda state, frozen, legal: frozen,
                                         observe=lambda *args: None)
        for _ in range(2):
            proposed = fixed.choose(state, None)
            forced = legal_actions(state)[0]
            assert proposed.kind == "play_card"
            fixed.observe(state, forced, state)
        return fixed

    covered = choose_outside_search("")
    assert covered.choose(state, None).args["card_index"] == 0
    fallback = choose_outside_search("unsupported power")
    assert fallback.choose(state, None).args["card_index"] == 1
    assert fallback.encounter.sloth_plays == 2
    fallback.observe(state, legal_actions(state)[-1], state)
    assert fallback.encounter.sloth_plays == 2
    state["round"] += 1
    fallback.observe(state, legal_actions(state)[0], state)
    assert fallback.encounter.sloth_plays == 1
    state["player_powers"] = []
    assert fallback.choose(state, None).args["card_index"] == 0


def test_ornate_prices_observed_removal_debt_only_with_hp_to_spare():
    state = camp(hp=70)
    state.update(decision="event_choice", event_name="This or That?", options=[
        {"index": 0, "text_key": "THIS_OR_THAT.pages.INITIAL.options.PLAIN", "vars": {"Gold": 66, "HpLoss": 6},
         "description": "Lose {HpLoss} HP. Gain {Gold} Gold."},
        {"index": 1, "text_key": "THIS_OR_THAT.pages.INITIAL.options.ORNATE",
         "description": "Add {Curse} to your Deck. Obtain a random Relic."},
    ])
    base, fixed = controller(), controller("v51_macro_fixes")
    assert base.choose(state, None).args["option_index"] == 1
    assert fixed.choose(state, None).args["option_index"] == 0
    state["player"]["hp"] = 6
    assert fixed.choose(state, None).args["option_index"] == 1
    state["player"].update(hp=70, relics=[{"id": "RELIC.ECTOPLASM"}])
    assert fixed.choose(state, None).args["option_index"] == 1


def test_candle_respects_rest_threshold_and_ancient_reward_identity():
    actor = controller("v51_macro_fixes")
    for state, idx in [(camp(), 2), (camp(hp=50), 0), (camp(enabled=False), 1), (camp(charges=1), 1)]:
        action = actor.choose(state, None)
        assert action.args["option_index"] == idx
        assert actor.deck_model.to_upgrade == (idx == 1)
        assert (actor.policy.selection == "upgrade") == (idx == 1)
    state = camp()
    state.update(decision="event_choice", event_name="Darv", options=[
        {"index": 0, "text_key": "DARV.pages.INITIAL.options.PHILOSOPHERS_STONE",
         "description": "Gain energy each turn. ALL enemies start with Strength.", "vars": {"StrengthPower": 1}},
        {"index": 1, "text_key": "DARV.pages.INITIAL.options.VELVET_CHOKER",
         "description": "Gain energy each turn. You can play at most 6 cards."},
    ])
    state["context"]["floor"] = 1
    assert actor.choose(state, None) == controller().choose(state, None)
    assert actor.choose(state, None).args["option_index"] == 0


def test_ancient_is_taken_only_from_the_later_act_entrance():
    state = camp()
    state.update(decision="map_select", choices=[
        {"row": 1, "col": 0, "type": "Monster"}, {"row": 0, "col": 3, "type": "Ancient"}])
    game = SimpleNamespace(public_map=lambda: [])
    for flag, idx in [(False, 0), (True, 1)]:
        actor = controller()
        actor.policy.v51_macro_fixes = flag
        actor.late_router = actor.router = SimpleNamespace(choose=lambda s, rows: legal_actions(s)[0])
        assert actor.choose(state, game) == legal_actions(state)[idx]
    early = deepcopy(state)
    early["context"].update(act=1)
    assert actor.choose(early, game) == legal_actions(early)[0]


# Built independently using the builder AND source at efd9877. Each manifest hashes every payload.
HISTORICAL = {
    "survival": "6fcc9f4eda1b954adc7e75394638854f910ab5943cd88bc83124c4ef89a73ccc",
    "scorer": "dc1d62c46166f378f445fa50c37f524667dad6e0e21f219047d1a0202683e9bb",
    "shop": "9d6b70d38cbf1161aa90e7e08cf06daa9a4c945b07747c777ce5eab5e78bbf59",
    "all": "c4826d98bccb51aad4f3e60306c5484ee3bb2c98b6d6637861560a23e3cb239e",
    "route": "bb8d6ed5b1510cabd65793c19ac7ffa2ebf86f654c824a6cce90d1b53526c7b4",
    "draft": "975a879d7712bfc6858a3630ff6fa5b0c1ac4bca64c162fe52944a460b0c31fc",
    "batch2": "de15992ab6727d1eab2bd2f0fbf2ef91e993a05a474fd76c98b095f887c7de8f",
    "all_v2": "f509f829ed779b5f4f8b9ade78a48b763f945a7303bffc178bb6cd84f836f896",
    "all_v2_clean": "6996d1f963c9af3f7aebf347570f5e1fc3ec73154863ed04a6749bbc75814212",
    "all_v2_tactics": "768db8b1e973070706feafefa718289d213c469b9651cad078a49c6a1caac816",
    "all_v2_mech": "3561464f0d17bb18bcc11b48c724fec1a956a90a96aa9c82abda950d16ca72f1",
    "all_v2_mech_v3": "0ccf0136312c48e8b02f1268518f003827f1305b78235373bb613cb51ca8fc5d",
    "all_v2_p1_v4": "8636337a6082264bffffe9a79b50528bdf30ed9096b74ff33fd20a8e844fa51b",
    "all_v2_search_v5": "a686db12c8b217bd476ea5c8e60cf6f486b060665536ef9354e8f09c21c81fcb",
    "all_v2_search_heur_v5": "85de8c968e2b973a2928719bedab2697ddd305e0c55c2654064fcf5f9ebd93c4",
}


def test_all_historical_profile_bytes_and_frozen_payloads(tmp_path):
    builder = runpy.run_path(str(ROOT / "scripts/build-batch1-challengers.py"))
    assert set(builder["PROFILES"]) == set(HISTORICAL)
    for name, expected in HISTORICAL.items():
        p = builder["build_batch1_bundle"](ROOT / "releases/silent-a10-mecha-knight/challenger/policy.json",
                                           tmp_path / name, profile=name)
        assert hashlib.sha256(p.read_bytes()).hexdigest() == expected
        load_bundle(p)
        if name == "all_v2_search_v5":
            assert {f.name: f.read_bytes() for f in p.parent.iterdir()} == {
                f.name: f.read_bytes() for f in BUNDLE.parent.iterdir()
            }


def test_panel_lock_and_deployable_arms(tmp_path):
    mod = runpy.run_path(str(ROOT / "scripts/collect-v51-autopsy.py"))
    spec = mod["locked_experiment"]()
    role, opts = load_bundle(BUNDLE)
    for arm, flags in spec["arms"].items():
        path = freeze_bundle({"args": {**opts, "roles": [role], **dict.fromkeys(flags, True)}}, tmp_path / arm)
        policy = DeployedController.from_bundle(path).policy
        assert {k for k in V51_SWITCHES if getattr(policy, k)} == set(flags)
        if not flags:
            assert path.read_bytes() == BUNDLE.read_bytes()


@pytest.mark.skipif(not os.getenv("CSV2DEV_HOST"), reason="requires the pinned native host")
def test_flags_off_match_frozen_winning_action_and_response_bytes(tmp_path):
    path = tmp_path / "explicit-false" / "policy.json"
    copytree(BUNDLE.parent, path.parent)
    path.write_text(json.dumps({**json.loads(path.read_bytes()), **dict.fromkeys(V51_SWITCHES, False)}))
    actor = DeployedController.from_bundle(path, macro_seed=7203)
    receipt = ROOT / "docs/evidence/silent-a10-v5-win-V5DIAG_0100.jsonl.gz"
    with NativeSession(ROOT, tmp_path / "episode", host_path=os.environ["CSV2DEV_HOST"]) as game:
        state = game.reset("V5DIAG_0100")
        with gzip.open(receipt) as stream:
            for record in map(json.loads, stream):
                if record["command"]["cmd"] != "action":
                    continue
                action = actor.choose(state, game)
                assert action.command() == record["command"]
                after = game.step(action)
                assert digest(after) == record["response_digest"]
                actor.observe(state, action, after)
                state = after
        assert state["decision"] == "game_over" and state["victory"] is True
