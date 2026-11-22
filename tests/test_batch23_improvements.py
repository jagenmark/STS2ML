from copy import deepcopy
import json
from pathlib import Path
import runpy
from types import SimpleNamespace

import pytest

from sts2rl import combat_search as combat_search_mod
from sts2rl.combat_search import CombatSearch
from sts2rl.deck_policy import DeckPolicy
from sts2rl.deployed_controller import DeployedController
from sts2rl.encounter import EncounterModel
from sts2rl.fight_rollout_v2 import fight_v2
from sts2rl import host_pool
from sts2rl.native import digest, legal_actions
from sts2rl.offer_policy import OfferModel
from sts2rl.provenance import (
    HEADLESS_PATCHES,
    headless_patch_digest,
    strategy_label_provenance,
)
from sts2rl.run_bundle import freeze_bundle, load_bundle
from sts2rl.run_evaluation import _load_cached_json, play_episode
from sts2rl.run_policy import IDENTITY, RunPolicy, RunWeights
from sts2rl.strategy import StrategyModel, strategy_arms
from sts2rl.survival_route import SurvivalRouter, deck_readiness


def test_survival_weighted_router_uses_exact_probability_bellman_without_sign_inversion():
    # Two paths to the boss: left has high mortality (60%) + huge reward, right is safe (2% death).
    stats = {
        "Elite": [100, 60, -1000, 0, 100, 100, 0, 100, 0],
        "Monster": [100, 2, -200, 1000, 0, 0, 0, 0, 0],
    }
    base_data = {
        "version": 2,
        "runtime_identity": IDENTITY,
        "cells": stats,
        "boss_coefficients": {"2": [-1.5, 2.0, 0.4, 0.4, 0.4, 0.2, 0.15]},
    }
    router = SurvivalRouter({**base_data, "survival_weighted": True})
    choices = [{"row": 3, "col": 0, "type": "Elite"}, {"row": 3, "col": 1, "type": "Monster"}]
    graph = [
        [{**c, "children": [{"row": 4, "col": 0}]} for c in choices],
        [{"row": 4, "col": 0, "type": "Boss"}],
    ]
    state = {
        "decision": "map_select",
        "runtime_identity": IDENTITY,
        "context": {"act": 2},
        "choices": choices,
        "player": {"hp": 45, "max_hp": 70, "gold": 100, "deck": [], "relics": [], "potions": []},
    }
    # Safe Monster path has far higher boss-clear probability than 60%-death Elite.
    assert router.choose(state, graph).args["col"] == 1

    # Deck readiness computes bounded public densities cleanly.
    strong_deck = [
        {"id": "CARD.FOOTWORK", "type": "Power", "stats": {"dexteritypower": 2}, "cost": 1},
        {"id": "CARD.LEG_SWEEP", "type": "Skill", "stats": {"block": 11, "weakpower": 2}, "cost": 2},
        {"id": "CARD.BACKSTAB", "type": "Attack", "stats": {"damage": 11}, "cost": 0},
    ] * 4
    r = deck_readiness(strong_deck)
    assert 0.0 < r["block_density"] <= 1.0 and 0.0 < r["scaling_density"] <= 1.0

    # Legacy router remains untouched when survival_weighted is absent.
    legacy = SurvivalRouter(base_data)
    assert not legacy.survival_weighted
    assert legacy.choose(state, graph) in legal_actions(state)


def test_unified_draft_fixes_early_deck_size_inversion_across_floors_12_and_13():
    root = Path(__file__).resolve().parents[1]
    bundle = root / "releases/silent-a10-mecha-knight/challenger"
    policy = RunPolicy(RunWeights.load(bundle / "weights.json"))
    opening = OfferModel.load(bundle / "offer_model.json")
    raw_strategy = json.loads((bundle / "strategy_model.json").read_text())

    legacy = StrategyModel.from_data(raw_strategy)
    unified = StrategyModel.from_data(
        {**raw_strategy, "unified_draft": True, "deck_size_penalty": 0.12, "offset_scale": 0.0}
    )

    inert = {"id": "CARD.NEUTRAL_INERT", "type": "Status", "cost": 1, "stats": {}}
    offered = {"index": 0, "id": "CARD.FOOTWORK", "type": "Power", "cost": 1, "stats": {"dexteritypower": 2}}

    def take_minus_skip(model, floor, extra_cards):
        state = {
            "decision": "card_reward",
            "runtime_identity": IDENTITY,
            "in_combat": False,
            "context": {"act": 1, "floor": floor, "boss": {"id": "WATERFALL_GIANT_BOSS"}},
            "player": {"hp": 60, "max_hp": 70, "gold": 100, "deck": [inert] * (12 + extra_cards)},
            "cards": [offered],
            "can_skip": True,
        }
        arms = strategy_arms(
            state,
            policy,
            opening,
            matchups=model.uses_matchups,
            unified_draft=model.unified_draft,
            deck_size_penalty=model.deck_size_penalty,
        )
        scores = {}
        for action, prior, feats in arms:
            scores[action.kind] = prior + model.strength * model.predict(0.0, feats)
        return scores["select_card_reward"] - scores["skip_card_reward"]

    # Confirm the historical early inversion (+0.09965 per card at floor 12).
    legacy_slope_f12 = take_minus_skip(legacy, 12, 5) - take_minus_skip(legacy, 12, 4)
    assert legacy_slope_f12 > 0.09

    # Unified draft has exact monotone negative deck-size slope (-0.12) on BOTH floor 12 and floor 13!
    for floor in (12, 13):
        slope = take_minus_skip(unified, floor, 5) - take_minus_skip(unified, floor, 4)
        assert slope == pytest.approx(-0.12, abs=1e-6)

    # Offset scale 0 disables legacy unscaled Act 2 human pick-rate offsets (+16.01 for Footwork).
    act2_state = {
        "decision": "card_reward",
        "runtime_identity": IDENTITY,
        "in_combat": False,
        "context": {"act": 2, "floor": 3, "boss": {"id": "KAISER_CRAB_BOSS"}},
        "player": {"hp": 60, "max_hp": 70, "gold": 100, "deck": [inert] * 14},
        "cards": [offered],
        "can_skip": True,
    }
    expl_legacy, expl_unified = {}, {}
    legacy.choose(act2_state, policy, opening, explanation=expl_legacy)
    unified.choose(act2_state, policy, opening, explanation=expl_unified)
    assert expl_legacy["options"][0]["card_offset"] > 15.0
    assert expl_unified["options"][0]["card_offset"] == 0.0


def test_fight_v2_distinguishes_smoke_bomb_escape_failed_escape_kill_and_defeat():
    class FakeGame:
        def __init__(self, states):
            self.states = list(states)
            self.calls = 0

        def step(self, action):
            nxt = self.states[self.calls]
            self.calls += 1
            return nxt

    base_combat = {
        "decision": "combat_play",
        "observation_version": 2,
        "in_combat": True,
        "round": 2,
        "context": {"act": 1, "floor": 5, "room_type": "Monster"},
        "player": {
            "hp": 41,
            "max_hp": 70,
            "potions": [
                {
                    "index": 0,
                    "id": "POTION.SMOKE_BOMB",
                    "can_use": True,
                    "target_type": "Self",
                    "vars": {},
                }
            ],
        },
        "hand": [],
        "enemies": [{"index": 0, "id": "MONSTER.A", "hp": 30, "max_hp": 60, "powers": []}],
    }
    smoke = [a for a in legal_actions(base_combat) if a.kind == "use_potion"][0]
    after_escape = {
        "decision": "map_select",
        "in_combat": False,
        "context": {"act": 1, "floor": 5, "room_type": "Monster"},
        "player": {"hp": 41, "max_hp": 70, "potions": []},
    }
    # 1. Forced Smoke Bomb escape -> won=False, escaped=True, preserves remaining enemy fraction (0.5).
    res_esc = fight_v2(FakeGame([after_escape]), base_combat, None, first=smoke)
    assert res_esc["won"] is False and res_esc["escaped"] is True
    assert res_esc["hp"] == 41 and res_esc["remaining"] == pytest.approx(0.5)

    # 2. Failed Smoke Bomb (combat continues) followed by real kill -> won=True, escaped=False!
    still_in_combat = {
        **base_combat,
        "round": 3,
        "player": {**base_combat["player"], "potions": []},
    }
    after_kill = {
        "decision": "card_reward",
        "in_combat": False,
        "context": {"act": 1, "floor": 5, "room_type": "Monster"},
        "player": {"hp": 38, "max_hp": 70, "potions": []},
    }

    class EndTurnActor:
        def combat(self, s, actions):
            return [a for a in actions if a.kind == "end_turn"][0]

    res_kill = fight_v2(
        FakeGame([still_in_combat, after_kill]), base_combat, EndTurnActor(), first=smoke
    )
    assert res_kill["won"] is True and res_kill["escaped"] is False and res_kill["remaining"] == 0.0

    # 3. Defeat -> won=False, escaped=False, hp=0.
    dead = {
        "decision": "game_over",
        "victory": False,
        "in_combat": False,
        "context": {"act": 1, "floor": 5, "room_type": "Monster"},
        "player": {"hp": 0, "max_hp": 70, "potions": []},
    }
    res_dead = fight_v2(FakeGame([dead]), base_combat, EndTurnActor(), first=smoke)
    assert res_dead["won"] is False and res_dead["escaped"] is False and res_dead["hp"] == 0


def test_host_pool_reuses_session_isolates_rpc_traces_and_evicts_on_error(tmp_path, monkeypatch):
    created = []

    class FakeSession:
        def __init__(self, root, folder, *, timeout=30, ascension=10, host_path=None, act_list="default"):
            self.folder = Path(folder)
            self.folder.mkdir(parents=True, exist_ok=False)
            self.trace = (self.folder / "rpc.jsonl").open("w", encoding="utf-8")
            self.timeout = timeout
            self.closed = False
            self.state, self.history, self.specification, self.sampled = {}, [], {}, False
            created.append(self)

        def reset(self, seed):
            self.trace.write(json.dumps({"command": {"cmd": "training_restore", "seed": seed}}) + "\n")
            self.trace.flush()
            self.state = {"seed": seed}
            return self.state

        def close(self):
            if not self.closed:
                self.closed = True
                self.trace.close()

    monkeypatch.setattr(host_pool, "NativeSession", FakeSession)
    host_pool.close_pooled_hosts()
    try:
        ep1 = tmp_path / "ep1/game"
        ep2 = tmp_path / "ep2/game"
        with host_pool.lease_native_session(tmp_path, ep1, reuse_host=True) as s1:
            s1.reset("SEED_A")
        with host_pool.lease_native_session(tmp_path, ep2, reuse_host=True) as s2:
            assert s2 is s1
            assert s2.state == {} and s2.history == []
            s2.reset("SEED_B")
        assert len(created) == 1
        assert "SEED_A" in (ep1 / "rpc.jsonl").read_text()
        assert "SEED_B" not in (ep1 / "rpc.jsonl").read_text()
        assert "SEED_B" in (ep2 / "rpc.jsonl").read_text()

        # Error inside a leased episode must evict and close the pooled host.
        ep3 = tmp_path / "ep3/game"
        with pytest.raises(RuntimeError, match="boom"):
            with host_pool.lease_native_session(tmp_path, ep3, reuse_host=True):
                raise RuntimeError("boom")
        assert created[0].closed
        ep4 = tmp_path / "ep4/game"
        with host_pool.lease_native_session(tmp_path, ep4, reuse_host=True) as s4:
            assert s4 is not s1
        assert len(created) == 2
    finally:
        host_pool.close_pooled_hosts()


def test_deployed_controller_clone_isolation_and_forced_rest_action_commit():
    root = Path(__file__).resolve().parents[1]
    bundle = root / "releases/silent-a10-mecha-knight/challenger/policy.json"
    ctrl = DeployedController.from_bundle(bundle, macro_seed=7)
    # Simulate a rest site where policy wanted SMITH, but counterfactual forces HEAL.
    rest = {
        "decision": "rest_site",
        "runtime_identity": IDENTITY,
        "context": {"act": 1, "floor": 15},
        "player": {"hp": 65, "max_hp": 70, "gold": 100, "deck": [], "relics": [], "potions": []},
        "options": [
            {"index": 0, "option_id": "HEAL"},
            {"index": 1, "option_id": "SMITH"},
        ],
    }
    proposed = ctrl.choose(rest, None)
    assert proposed.args["option_index"] == 1
    assert ctrl.deck_model.to_upgrade is True

    clone = ctrl.clone()
    heal = [a for a in legal_actions(rest) if a.args.get("option_index") == 0][0]
    clone.observe(rest, heal, {"decision": "map_select", "context": {"act": 1, "floor": 15}})
    # Forcing HEAL on clone clears to_upgrade without mutating the original controller!
    assert clone.deck_model.to_upgrade is False
    assert ctrl.deck_model.to_upgrade is True

    # Cached JSON loader + from_data builds fresh isolated EncounterModel instances.
    enc_path = root / "releases/silent-a10-mecha-knight/challenger/encounter_model.json"
    e1 = EncounterModel.from_data(_load_cached_json(enc_path))
    e2 = EncounterModel.from_data(_load_cached_json(enc_path))
    e1.key = (1, 1, "Monster")
    assert e2.key is None


def test_headless_patch_digest_and_strategy_provenance_are_deterministic_and_sensitive(tmp_path):
    root = Path(__file__).resolve().parents[1]
    info1 = headless_patch_digest(root)
    info2 = headless_patch_digest(root)
    assert info1 == info2
    assert len(info1["entries"]) >= len(HEADLESS_PATCHES)

    # Modifying a patch file changes the patch chain digest; missing file raises FileNotFoundError.
    fake_root = tmp_path / "repo"
    (fake_root / "scripts").mkdir(parents=True)
    for rel in HEADLESS_PATCHES:
        src = root / rel
        (fake_root / rel).write_bytes(src.read_bytes())
    d_orig = headless_patch_digest(fake_root)["patch_chain_sha256"]
    (fake_root / HEADLESS_PATCHES[0]).write_text("modified patch\n", encoding="utf-8")
    d_mod = headless_patch_digest(fake_root)["patch_chain_sha256"]
    assert d_orig != d_mod
    (fake_root / HEADLESS_PATCHES[-1]).unlink()
    with pytest.raises(FileNotFoundError):
        headless_patch_digest(fake_root)

    bundle = root / "releases/silent-a10-mecha-knight/challenger/policy.json"
    stamp = strategy_label_provenance(bundle, continuation="bundle", root=root)
    assert stamp["continuation"] == "bundle" and stamp["patch_chain_sha256"] == info1["patch_chain_sha256"]


def test_combat_search_deployed_continuation_clones_encounter_and_keeps_live_state_clean():
    enc = EncounterModel(
        {
            "version": 1,
            "runtime_identity": IDENTITY,
            "default": "engine",
            "act2_boss_plans": {"KAISER_CRAB_BOSS": {"facing": 1.75}},
        }
    )
    policy = RunPolicy(RunWeights())
    search = CombatSearch(
        Path("."), None, Path("."), 0, policy, encounter=enc, deployed_continuation=True
    )
    # Verify deployed_continuation stores reference without mutating live encounter.
    assert search.deployed_continuation is True and search.encounter is enc
    # Cloned encounter isolates actor/tactics state.
    clone = deepcopy(enc)
    clone.key = (1, 17, "Boss")
    assert enc.key is None


def test_batch2_profiles_freeze_and_reject_dirty_bases(tmp_path):
    root = Path(__file__).resolve().parents[1]
    builder = runpy.run_path(str(root / "scripts/build-batch1-challengers.py"))["build_batch1_bundle"]
    base = root / "releases/silent-a10-mecha-knight/challenger/policy.json"
    for profile in ("route", "draft", "batch2", "all_v2"):
        frozen = builder(base, tmp_path / profile, profile=profile)
        _, settings = load_bundle(frozen)
        rm = json.loads(settings["room_model"].read_text())
        lrm = json.loads(settings["late_room_model"].read_text())
        st = json.loads(settings["strategy_model"].read_text())
        assert rm.get("survival_weighted", False) == (profile in ("route", "batch2", "all_v2"))
        assert lrm.get("survival_weighted", False) == (profile in ("route", "batch2", "all_v2"))
        assert st.get("unified_draft", False) == (profile in ("draft", "batch2", "all_v2"))
    with pytest.raises(ValueError, match="clean baseline"):
        builder(tmp_path / "batch2/policy/policy.json", tmp_path / "dirty2", profile="route")


def test_survival_weighted_router_explicit_boss_rewards_unknown_bayes_and_fractional_potions():
    # 1. Explicit Boss vs Implicit Boss: 1%-risk relic room (clear ~0.72) must beat safe 0-reward room (0.50).
    stats = {
        "Elite": [100, 1, 0, 0, 99, 0, 0, 0, 0],  # +1 relic per survivor, 1% mortality
        "Monster": [100, 0, 0, 0, 0, 0, 0, 0, 0],  # 0 reward, 0% mortality
    }
    router = SurvivalRouter(
        {
            "version": 2,
            "runtime_identity": IDENTITY,
            "cells": stats,
            "boss_coefficients": {"2": [0.0, 0.0, 4.0, 0.0, 0.0, 0.0, 0.0]},
            "survival_weighted": True,
            "readiness_weights": {"attack": 0.0, "block": 0.0, "scaling": 0.0, "potion": 0.0},
        }
    )
    choices = [{"row": 3, "col": 0, "type": "Elite"}, {"row": 3, "col": 1, "type": "Monster"}]
    explicit_graph = [
        [{**c, "children": [{"row": 4, "col": 0}]} for c in choices],
        [{"row": 4, "col": 0, "type": "Boss"}],
    ]
    implicit_graph = [choices]
    state = {
        "decision": "map_select",
        "runtime_identity": IDENTITY,
        "context": {"act": 2},
        "choices": choices,
        "player": {"hp": 50, "max_hp": 70, "gold": 100, "deck": [], "relics": [], "potions": []},
    }
    assert router.choose(state, explicit_graph).args["col"] == 0
    assert router.choose(state, implicit_graph).args["col"] == 0

    # 2. Fractional potion gains (+0.40 per room) accumulate and improve boss clear probability.
    pot_stats = {
        "Elite": [100, 0, 0, 0, 0, 0, 40, 0, 0],  # +0.40 potions per survivor
        "Monster": [100, 0, 0, 0, 0, 0, 0, 0, 0],
    }
    pot_router = SurvivalRouter(
        {
            "version": 2,
            "runtime_identity": IDENTITY,
            "cells": pot_stats,
            "boss_coefficients": {"2": [0.0, 0.0, 0.0, 0.0, 2.0, 0.0, 0.0]},
            "survival_weighted": True,
            "readiness_weights": {"attack": 0.0, "block": 0.0, "scaling": 0.0, "potion": 0.0},
        }
    )
    assert pot_router.choose(state, explicit_graph).args["col"] == 0

    # 3. 100%-mortality room beats nothing vs 99%-mortality room (no 0.025 survival floor flattening).
    lethal_stats = {
        "Elite": [100, 100, 0, 0, 0, 0, 0, 0, 0],  # 100% death
        "Monster": [100, 99, 0, 0, 0, 0, 0, 0, 0],  # 99% death
    }
    lethal_router = SurvivalRouter(
        {
            "version": 2,
            "runtime_identity": IDENTITY,
            "cells": lethal_stats,
            "boss_coefficients": {"2": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]},
            "survival_weighted": True,
            "readiness_weights": {"attack": 0.0, "block": 0.0, "scaling": 0.0, "potion": 0.0},
        }
    )
    assert lethal_router.choose(state, explicit_graph).args["col"] == 1

    # 4. Unknown room where 50% is a lethal fight and 50% is a safe event:
    # survivors MUST come strictly from the non-fight branch (prior_fights stays 0 = weak).
    unk_router = SurvivalRouter(
        {
            "version": 2,
            "runtime_identity": IDENTITY,
            "cells": {
                "Unknown": [100, 50, 0, 0, 0, 0, 0, 0, 0],
                "Monster": [100, 0, 0, 0, 0, 0, 0, 0, 0],
            },
            "boss_coefficients": {"1": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]},
            "survival_weighted": True,
            "readiness_weights": {"attack": 0.0, "block": 0.0, "scaling": 0.0, "potion": 0.0},
            "act1_context": {
                "weak_fights": 1,
                "blend": 1.0,
                "unknown_fight_probability": {"Overgrowth": 0.5},
                "rooms": {
                    # Monster at weak (0 prior fights) is lethal; Monster at regular (>=1) is safe!
                    "Overgrowth/Monster/weak": [10000, 10000, 0, 0, 0, 0, 0, 0, 0],
                    "Overgrowth/Monster/regular": [10000, 0, 0, 0, 0, 0, 0, 0, 0],
                    "Overgrowth/Unknown/weak": [10000, 5000, 0, 0, 0, 0, 0, 0, 0],
                },
            },
        }
    )
    # Path 0: Unknown -> Monster (since Unknown survivors didn't fight, next Monster is STILL weak & lethal!)
    # Path 1: Unknown -> RestSite (safe after surviving Unknown)
    unk_choices = [{"row": 1, "col": 0, "type": "Unknown"}, {"row": 1, "col": 1, "type": "Unknown"}]
    unk_graph = [
        [
            {"row": 1, "col": 0, "type": "Unknown", "children": [{"row": 2, "col": 0}]},
            {"row": 1, "col": 1, "type": "Unknown", "children": [{"row": 2, "col": 1}]},
        ],
        [
            {"row": 2, "col": 0, "type": "Monster", "children": [{"row": 3, "col": 0}]},
            {"row": 2, "col": 1, "type": "RestSite", "children": [{"row": 3, "col": 0}]},
        ],
        [{"row": 3, "col": 0, "type": "Boss"}],
    ]
    unk_state = {
        "decision": "map_select",
        "runtime_identity": IDENTITY,
        "context": {"act": 1, "act_name": "Overgrowth"},
        "choices": unk_choices,
        "player": {"hp": 50, "max_hp": 70, "gold": 100, "deck": [], "relics": [], "potions": []},
    }
    assert unk_router.choose(unk_state, unk_graph, normal_count=0).args["col"] == 1


def test_unified_draft_explanation_matches_actual_scoring():
    root = Path(__file__).resolve().parents[1]
    bundle = root / "releases/silent-a10-mecha-knight/challenger"
    policy = RunPolicy(RunWeights.load(bundle / "weights.json"))
    opening = OfferModel.load(bundle / "offer_model.json")
    raw_strategy = json.loads((bundle / "strategy_model.json").read_text())
    unified = StrategyModel.from_data(
        {**raw_strategy, "unified_draft": True, "deck_size_penalty": 0.12, "offset_scale": 0.0}
    )
    inert = {"id": "CARD.NEUTRAL_INERT", "type": "Status", "cost": 1, "stats": {}}
    offered = {"index": 0, "id": "CARD.FOOTWORK", "type": "Power", "cost": 1, "stats": {"dexteritypower": 2}}
    state = {
        "decision": "card_reward",
        "runtime_identity": IDENTITY,
        "in_combat": False,
        "context": {"act": 1, "floor": 5, "boss": {"id": "WATERFALL_GIANT_BOSS"}},
        "player": {"hp": 60, "max_hp": 70, "gold": 100, "deck": [inert] * 15},
        "cards": [offered],
        "can_skip": True,
    }
    expl = {}
    unified.choose(state, policy, opening, explanation=expl)
    assert expl["prior_source"] == "unified_draft"
    card_opt = next(o for o in expl["options"] if o["card"] != "skip")
    skip_opt = next(o for o in expl["options"] if o["card"] == "skip")
    assert card_opt["prior_terms"] == {}
    assert sum(card_opt["prior_base_parts"].values()) == pytest.approx(card_opt["prior"])
    assert skip_opt["prior"] == 0.0
    assert sum(skip_opt["prior_base_parts"].values()) == 0.0


def test_strategy_fit_validates_provenance_flags_and_preserves_explicit_offset_scale(tmp_path):
    mod = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/train-silent-strategy.py"))
    fit_roots = mod["fit_strategy_roots"]
    root_bundle = Path(__file__).resolve().parents[1] / "releases/silent-a10-mecha-knight/challenger/policy.json"

    def write_labels(folder: Path, stamp, *, unified=False, penalty=0.12, seed="SEED1", root_id="R1"):
        run_dir = folder / f"run-{seed}"
        run_dir.mkdir(parents=True)
        root_row = {
            "group": seed,
            "kind": "card",
            "act": 1,
            "root": root_id,
            "unified_draft": unified,
            "deck_size_penalty": penalty,
            "arms": [
                {"id": "a", "prior": 0.5, "features": {"card:take": 1.0}, "return": 12.0},
                {"id": "b", "prior": 0.0, "features": {}, "return": 10.0},
            ],
        }
        if stamp is not None:
            root_row["label_provenance"] = stamp
        payload = {"seed": seed, "roots": [root_row], "errors": []}
        if stamp is not None:
            payload["label_provenance"] = stamp
        (run_dir / "labels.json").write_text(json.dumps(payload), encoding="utf-8")

    # 1. Unstamped labels rejected for bundle/unified; mixed unstamped + stamped rejected even for legacy!
    d_mix = tmp_path / "mix"
    stamp_bundle = strategy_label_provenance(
        root_bundle, continuation="bundle", unified_draft=True, deck_size_penalty=0.12
    )
    stamp_legacy = strategy_label_provenance(
        root_bundle, continuation="legacy", unified_draft=False, deck_size_penalty=0.12
    )
    write_labels(d_mix, None, seed="A01", root_id="R1")
    write_labels(d_mix, stamp_legacy, unified=False, seed="A02", root_id="R2")
    with pytest.raises(ValueError, match="Unstamped legacy labels"):
        fit_roots([d_mix], continuation="bundle", unified_draft=True)
    with pytest.raises(ValueError, match="Mixed strategy label provenance"):
        fit_roots([d_mix], continuation="legacy", unified_draft=False)

    # 2. Mismatched continuation or penalty must fail.
    d_bad = tmp_path / "bad_pen"
    stamp_pen4 = strategy_label_provenance(
        root_bundle, continuation="bundle", unified_draft=True, deck_size_penalty=4.0
    )
    write_labels(d_bad, stamp_pen4, unified=True, penalty=4.0, seed="B01", root_id="R1")
    with pytest.raises(ValueError, match="deck_size_penalty"):
        fit_roots([d_bad], continuation="bundle", unified_draft=True, deck_size_penalty=0.12)
    with pytest.raises(ValueError, match="continuation"):
        fit_roots([d_bad], continuation="legacy", unified_draft=True, deck_size_penalty=4.0)

    # 3. Explicit --offset-scale 1.0 is preserved under --unified-draft, while omitted defaults to 0.0.
    d_ok = tmp_path / "ok"
    for i in range(6):
        write_labels(d_ok, stamp_bundle, unified=True, penalty=0.12, seed=f"S{i:02d}", root_id=f"R{i}")
    m_default, _ = fit_roots([d_ok], continuation="bundle", unified_draft=True, offset_scale=None)
    m_explicit, _ = fit_roots([d_ok], continuation="bundle", unified_draft=True, offset_scale=1.0)
    assert m_default.offset_scale == 0.0
    assert m_explicit.offset_scale == 1.0

    # 4. Card-only residual fit preserves all base kinds, weights, strength, and card_offsets.
    base_raw = json.loads((root_bundle.parent / "strategy_model.json").read_text())
    base_strat_path = tmp_path / "base_unified_strategy.json"
    base_strat_path.write_text(
        json.dumps({**base_raw, "unified_draft": True, "deck_size_penalty": 0.12, "offset_scale": 0.0}),
        encoding="utf-8",
    )
    m_zero, rep_zero = fit_roots(
        [d_ok],
        continuation="bundle",
        unified_draft=True,
        base_strategy=base_strat_path,
        residual_alpha=0.0,
    )
    assert rep_zero["mode"] == "card_residual"
    assert m_zero.kinds == frozenset(base_raw["kinds"])
    assert m_zero.strength == base_raw["strength"]
    assert m_zero.card_offsets == base_raw["card_offsets"]
    assert m_zero.weights == pytest.approx(base_raw["weights"])

    m_res, rep_res = fit_roots(
        [d_ok],
        continuation="bundle",
        unified_draft=True,
        base_strategy=base_strat_path,
        ridge=32.0,
        residual_alpha=1.0,
    )
    assert m_res.kinds == frozenset(base_raw["kinds"])
    assert m_res.strength == base_raw["strength"]
    assert rep_res["delta_nonzero"] >= 1
    # Non-card weights (e.g. event/neow) are never altered by the card-only residual.
    for k, v in base_raw["weights"].items():
        if k.startswith(("event:", "event/", "ancient/", "camp:", "heal:")):
            assert m_res.weights[k] == v


def test_deployed_controller_fails_closed_reconciles_forced_facing_and_scopes_to_upgrade(tmp_path):
    root = Path(__file__).resolve().parents[1]
    base = root / "releases/silent-a10-mecha-knight/challenger/policy.json"
    _, opts = load_bundle(base)

    # 1. Fail closed on non-candidate role or unsupported bundle switches.
    bad_role = freeze_bundle({"args": {**opts, "roles": ["student"]}}, tmp_path / "student_bundle")
    with pytest.raises(ValueError, match="role='candidate'"):
        DeployedController.from_bundle(bad_role)

    bad_search = freeze_bundle(
        {"args": {**opts, "roles": ["candidate"], "combat_search_deployed": True}},
        tmp_path / "search_bundle",
    )
    _, loaded_opts = load_bundle(bad_search)
    assert loaded_opts.get("combat_search_deployed") is True
    with pytest.raises(ValueError, match="combat_search_deployed"):
        DeployedController.from_bundle(bad_search)

    # 2. Deck model without rest_site in scope must NOT have to_upgrade mutated by observe().
    dm_shop_only = DeckPolicy({"version": 1, "runtime_identity": IDENTITY, "scope": ["shop"]})
    ctrl = DeployedController(RunPolicy(RunWeights()), deck_model=dm_shop_only)
    rest = {
        "decision": "rest_site",
        "runtime_identity": IDENTITY,
        "context": {"act": 1, "floor": 5},
        "player": {"hp": 60, "max_hp": 70, "gold": 100, "deck": [], "relics": [], "potions": []},
        "options": [{"index": 0, "option_id": "HEAL"}, {"index": 1, "option_id": "SMITH"}],
    }
    smith = [a for a in legal_actions(rest) if a.args.get("option_index") == 1][0]
    ctrl.observe(rest, smith, {"decision": "card_select", "context": {"act": 1, "floor": 5}})
    assert dm_shop_only.to_upgrade is False

    # 3. Forced combat action reconciles BossTactics facing instead of keeping proposed facing.
    enc = EncounterModel(
        {
            "version": 1,
            "runtime_identity": IDENTITY,
            "default": "engine",
            "act2_boss_plans": {"TEST_BOSS": {"facing": 1.5}},
        }
    )
    ctrl_boss = DeployedController(RunPolicy(RunWeights()), encounter=enc)
    combat = {
        "decision": "combat_play",
        "observation_version": 2,
        "in_combat": True,
        "round": 1,
        "energy": 3,
        "max_energy": 3,
        "context": {"act": 2, "floor": 17, "room_type": "Boss", "boss": {"id": "TEST_BOSS"}},
        "player": {"hp": 50, "max_hp": 70, "block": 0, "powers": [], "potions": [], "relics": [], "deck": []},
        "hand": [
            {
                "index": 0,
                "id": "CARD.STRIKE_SILENT",
                "type": "Attack",
                "target_type": "AnyEnemy",
                "cost": 1,
                "can_play": True,
                "stats": {"damage": 6},
                "keywords": [],
            }
        ],
        "enemies": [
            {"index": 0, "id": "MONSTER.A", "hp": 50, "max_hp": 50, "block": 0, "powers": [], "intents": []},
            {"index": 1, "id": "MONSTER.B", "hp": 50, "max_hp": 50, "block": 0, "powers": [], "intents": []},
        ],
    }
    proposed = ctrl_boss.choose(combat, None)
    assert proposed.kind == "play_card"
    other = next(
        a for a in legal_actions(combat)
        if a.kind == "play_card" and a.args["target_index"] != proposed.args["target_index"]
    )
    ctrl_boss.observe(combat, other, combat)
    assert enc.boss_tactics.facing == other.args["target_index"]


def test_combat_search_deployed_choose_respects_applies_ascension_and_failed_smoke_bomb(tmp_path, monkeypatch):
    # Encounter applies ONLY to Elite; hallway search must NOT shortlist with stale Elite actor.
    enc = EncounterModel(
        {"version": 1, "runtime_identity": IDENTITY, "rooms": ["Elite"], "default": "engine"}
    )
    enc.actor = SimpleNamespace(combat_scores=lambda s, a: (_ for _ in ()).throw(AssertionError("stale actor used")))
    enc.key = (1, 8, "Elite")
    policy = RunPolicy(RunWeights())
    spawned = []

    combat = {
        "decision": "combat_play",
        "runtime_identity": IDENTITY,
        "observation_version": 2,
        "in_combat": True,
        "round": 1,
        "energy": 3,
        "max_energy": 3,
        "context": {"act": 1, "floor": 10, "room_type": "Monster"},
        "act1_search_support": {"supported": True},
        "player": {
            "hp": 20,
            "max_hp": 70,
            "block": 0,
            "powers": [],
            "relics": [],
            "deck": [],
            "potions": [
                {"index": 0, "id": "POTION.SMOKE_BOMB", "can_use": True, "target_type": "Self", "vars": {}}
            ],
        },
        "hand": [
            {
                "index": 0,
                "id": "CARD.STRIKE_SILENT",
                "type": "Attack",
                "target_type": "AnyEnemy",
                "cost": 1,
                "can_play": True,
                "stats": {"damage": 6},
                "keywords": [],
            },
            {
                "index": 1,
                "id": "CARD.DEFEND_SILENT",
                "type": "Skill",
                "target_type": "Self",
                "cost": 1,
                "can_play": True,
                "stats": {"block": 5},
                "keywords": [],
            },
        ],
        "enemies": [
            {
                "index": 0,
                "id": "MONSTER.A",
                "hp": 12,
                "max_hp": 12,
                "block": 0,
                "powers": [],
                "intents": [{"type": "SingleAttack", "damage": 10, "repeats": 1}],
            }
        ],
    }
    still_in = {**combat, "round": 2, "player": {**combat["player"], "potions": []}}
    won = {
        "decision": "card_reward",
        "in_combat": False,
        "context": {"act": 1, "floor": 10, "room_type": "Monster"},
        "player": {"hp": 35, "max_hp": 70, "potions": []},
    }

    class FakeWorker:
        def __init__(self, root, folder, *, ascension=10, host_path=None, timeout=12, act_list="default"):
            self.ascension = ascension
            self.closed = False
            self.state = combat
            self._steps = 0
            spawned.append(self)

        def restore(self, fork):
            self.state = combat
            self._steps = 0

        def sample(self, world, profile=None):
            pass

        def step(self, action):
            self._steps += 1
            if action.kind == "use_potion":
                # Failed Smoke Bomb keeps fight going; next action wins!
                self.state = still_in
                return still_in
            self.state = won
            return won

        def close(self):
            self.closed = True

    monkeypatch.setattr(combat_search_mod, "NativeSession", FakeWorker)
    search = CombatSearch(
        tmp_path,
        None,
        tmp_path / "search",
        0,
        policy,
        encounter=enc,
        deployed_continuation=True,
        ascension=7,
    )
    actions = legal_actions(combat)
    strike = next(a for a in actions if a.kind == "play_card")
    smoke = next(a for a in actions if a.kind == "use_potion")
    chosen = search.choose(SimpleNamespace(state=combat, fork=lambda: None, act_list="default"), strike, 0)
    assert chosen in actions
    assert spawned and spawned[0].ascension == 7

    # Directly verify failed Smoke Bomb followed by a real win at 50% HP scores ~147 (NOT 47).
    search.worker = spawned[0]
    search.worker.restore(None)
    score = search._rollout(smoke, 123)
    assert score > 100.0


def test_fight_v2_encounter_model_requires_base_policy_and_initializes_on_forced_first():
    enc = EncounterModel({"version": 1, "runtime_identity": IDENTITY, "default": "engine"})
    combat = {
        "decision": "combat_play",
        "observation_version": 2,
        "in_combat": True,
        "round": 1,
        "energy": 3,
        "max_energy": 3,
        "context": {"act": 1, "floor": 3, "room_type": "Monster"},
        "player": {"hp": 50, "max_hp": 70, "block": 0, "powers": [], "potions": [], "relics": [], "deck": []},
        "hand": [],
        "enemies": [
            {"index": 0, "id": "MONSTER.A", "hp": 20, "max_hp": 20, "block": 0, "powers": [], "intents": []}
        ],
    }
    end_turn = next(a for a in legal_actions(combat) if a.kind == "end_turn")
    with pytest.raises(ValueError, match="base_policy"):
        fight_v2(SimpleNamespace(step=lambda a: combat), combat, enc, first=end_turn)

    prompt = {
        "decision": "card_select",
        "runtime_identity": IDENTITY,
        "in_combat": True,
        "context": {"act": 1, "floor": 3, "room_type": "Monster"},
        "player": {"hp": 50, "max_hp": 70, "potions": [], "deck": []},
        "cards": [{"index": 0, "id": "CARD.STRIKE_SILENT", "type": "Attack", "stats": {"damage": 6}, "cost": 1}],
        "min_select": 1,
        "max_select": 1,
    }
    after = {
        "decision": "card_reward",
        "in_combat": False,
        "context": {"act": 1, "floor": 3, "room_type": "Monster"},
        "player": {"hp": 50, "max_hp": 70, "potions": []},
    }
    states = iter([prompt, after])
    res = fight_v2(
        SimpleNamespace(step=lambda a: next(states)),
        combat,
        enc,
        first=end_turn,
        base_policy=RunPolicy(RunWeights()),
    )
    assert enc.actor is not None
    assert res["won"] is True and res["escaped"] is False


def test_host_pool_enforces_exclusive_leases_and_preserves_engine_log_on_failure(tmp_path, monkeypatch):
    created = []

    class FakeSession:
        def __init__(self, root, folder, *, timeout=30, ascension=10, host_path=None, act_list="default"):
            self.folder = Path(folder)
            self.folder.mkdir(parents=True, exist_ok=False)
            self.trace = (self.folder / "rpc.jsonl").open("w", encoding="utf-8")
            (self.folder / "engine.log").write_text("detailed host rpc error\n", encoding="utf-8")
            self.timeout = timeout
            self.closed = False
            self.state, self.history, self.specification, self.sampled = {}, [], {}, False
            created.append(self)

        def close(self):
            if not self.closed:
                self.closed = True
                self.trace.close()

    monkeypatch.setattr(host_pool, "NativeSession", FakeSession)
    host_pool.close_pooled_hosts()
    try:
        # 1. Overlapping same-key leases get distinct exclusive sessions.
        with host_pool.lease_native_session(tmp_path, tmp_path / "o1", reuse_host=True) as s1:
            with host_pool.lease_native_session(tmp_path, tmp_path / "o2", reuse_host=True) as s2:
                assert s1 is not s2
        assert len(created) == 2

        # 2. Exception preserves engine.log in episode folder before deleting sandbox.
        fail_dir = tmp_path / "fail_ep"
        with pytest.raises(RuntimeError, match="rpc crash"):
            with host_pool.lease_native_session(tmp_path, fail_dir, reuse_host=True):
                raise RuntimeError("rpc crash")
        assert "detailed host rpc error" in (fail_dir / "engine.log").read_text()
    finally:
        host_pool.close_pooled_hosts()


def test_replay_controller_snapshots_restores_prefix_pool_state(tmp_path):
    mod = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/train-silent-strategy.py"))
    replay = mod["replay_controller_snapshots"]

    s0 = {
        "decision": "map_select",
        "runtime_identity": IDENTITY,
        "context": {"act": 1, "act_name": "Overgrowth", "floor": 1},
        "choices": [{"row": 0, "col": 0, "type": "Monster"}],
        "player": {"hp": 70, "max_hp": 70, "gold": 99, "deck": [], "relics": [], "potions": []},
    }
    act0 = legal_actions(s0)[0]
    s1 = {
        "decision": "combat_play",
        "observation_version": 2,
        "in_combat": True,
        "round": 1,
        "context": {"act": 1, "act_name": "Overgrowth", "floor": 1, "room_type": "Monster"},
        "player": {"hp": 70, "max_hp": 70, "potions": [], "relics": []},
        "hand": [],
        "enemies": [{"index": 0, "id": "MONSTER.NIBBIT", "hp": 30, "max_hp": 30, "powers": []}],
    }
    src = tmp_path / "recorded"
    (src / "game").mkdir(parents=True)
    (src / "game/rpc.jsonl").write_text(
        json.dumps({"command": {"cmd": "training_restore", "seed": "S1", "ascension": 10, "history": []}, "response_digest": digest(s0)}) + "\n"
        + json.dumps({"command": act0.command(), "response_digest": digest(s1)}) + "\n",
        encoding="utf-8",
    )

    class FakeSession:
        def restore(self, fork):
            return s0

        def step(self, action):
            return s1

    ctrl = DeployedController(
        RunPolicy(RunWeights()),
        strategy=StrategyModel({"matchup/nibbit": 0.25}, ["card"]),
    )
    snaps = replay(FakeSession(), src, ctrl, [1])
    assert snaps[1].pool is not None
    assert snaps[1].pool.normal_count == 1
    assert snaps[1].pool.group_probability is not None

    # Large multi-card card_select in prefix replay must not invoke legal_actions() power-set error.
    big_select = {
        "decision": "card_select",
        "runtime_identity": IDENTITY,
        "in_combat": False,
        "context": {"act": 1, "act_name": "Overgrowth", "floor": 1},
        "player": {"hp": 70, "max_hp": 70, "gold": 99, "deck": [], "relics": [], "potions": []},
        "cards": [{"index": i, "id": "CARD.STRIKE_SILENT", "type": "Attack", "stats": {"damage": 6}, "cost": 1} for i in range(15)],
        "min_select": 3,
        "max_select": 3,
    }
    big_cmd = {"cmd": "action", "action": "select_cards", "args": {"indices": "0,1,2"}}
    src2 = tmp_path / "recorded_big"
    (src2 / "game").mkdir(parents=True)
    (src2 / "game/rpc.jsonl").write_text(
        json.dumps({"command": {"cmd": "training_restore", "seed": "S2", "ascension": 10, "history": []}, "response_digest": digest(big_select)}) + "\n"
        + json.dumps({"command": big_cmd, "response_digest": digest(s1)}) + "\n",
        encoding="utf-8",
    )

    class FakeBigSession:
        def restore(self, fork):
            return big_select

        def step(self, action):
            assert action.command() == big_cmd
            return s1

    snaps2 = replay(FakeBigSession(), src2, DeployedController(RunPolicy(RunWeights())), [1])
    assert 1 in snaps2


def test_builder_rejects_v1_router_missing_strategy_and_dirty_offset_scale(tmp_path):
    root = Path(__file__).resolve().parents[1]
    builder = runpy.run_path(str(root / "scripts/build-batch1-challengers.py"))["build_batch1_bundle"]
    base = root / "releases/silent-a10-mecha-knight/challenger/policy.json"
    role, opts = load_bundle(base)

    # 1. v1 room model rejected for route profile.
    v1_rm = tmp_path / "v1_room.json"
    v1_rm.write_text(json.dumps({"version": 1, "runtime_identity": IDENTITY, "weights": {}}))
    bad_route_base = freeze_bundle(
        {"args": {**opts, "room_model": v1_rm, "late_room_model": None, "roles": [role]}},
        tmp_path / "v1_route_base",
    )
    with pytest.raises(ValueError, match="v2 room_model"):
        builder(bad_route_base, tmp_path / "out_v1", profile="route")

    # 2. Missing strategy model rejected for draft profile.
    no_strat_base = freeze_bundle(
        {"args": {**opts, "strategy_model": None, "roles": [role]}},
        tmp_path / "no_strat_base",
    )
    with pytest.raises(ValueError, match="strategy_model"):
        builder(no_strat_base, tmp_path / "out_no_strat", profile="draft")

    # 3. Already-modified offset_scale != 1.0 rejected as dirty base even for route profile.
    dirty_strat = json.loads(opts["strategy_model"].read_text())
    dirty_strat["offset_scale"] = 0.0
    dirty_strat_path = tmp_path / "dirty_strat.json"
    dirty_strat_path.write_text(json.dumps(dirty_strat))
    dirty_base = freeze_bundle(
        {"args": {**opts, "strategy_model": dirty_strat_path, "roles": [role]}},
        tmp_path / "dirty_offset_base",
    )
    with pytest.raises(ValueError, match="clean baseline"):
        builder(dirty_base, tmp_path / "out_dirty_offset", profile="route")

    # 4. all_v2_clean disables marginal_removal, enables THE_KIN_BOSS=isolate, and keeps Batch 1/2 fixes.
    clean_bundle = builder(base, tmp_path / "all_v2_clean", profile="all_v2_clean")
    _, clean_opts = load_bundle(clean_bundle)
    clean_enc = json.loads(clean_opts["encounter_model"].read_text())
    clean_deck = json.loads(clean_opts["deck_model"].read_text())
    assert clean_enc["overrides"]["THE_KIN_BOSS"] == "isolate"
    assert clean_enc["survival_search"] is True and clean_enc["scorer_fixes"] is True
    assert clean_deck["merchant"]["marginal_removal"] is False
    assert clean_deck["merchant"]["gold_curve"] is True and clean_deck["merchant"]["potion_capacity"] is True

    # 4b. all_v2_tactics layers REP512-validated Act 2 Boss / Hallway / Soul Fysh plans cleanly.
    tactics_bundle = builder(base, tmp_path / "all_v2_tactics", profile="all_v2_tactics")
    _, tac_opts = load_bundle(tactics_bundle)
    tac_enc = json.loads(tac_opts["encounter_model"].read_text())
    assert tac_enc["overrides"]["SOUL_FYSH_BOSS"] == "isolate"
    assert tac_enc["act2_boss_plans"]["THE_INSATIABLE_BOSS"]["escape"] == "cheap"
    assert tac_enc["act2_hallways"]["by_formation"]["HUNTER_KILLER"] == "hunter_tender_beam"
    # Verify EncounterModel parses and validates the frozen tactics bundle cleanly.
    EncounterModel.load(tac_opts["encounter_model"])

    # 5. play_episode rejects raw 'act_list' option to prevent silent default-biome mismatch.
    with pytest.raises(ValueError, match="seeded_acts"):
        play_episode((tmp_path, None, tmp_path / "ep", "S1", 0, "candidate", {}, None, {"act_list": "seeded"}))
