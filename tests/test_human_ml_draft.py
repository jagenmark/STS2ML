"""Unit tests for the opt-in v6.8 Human-ML Contextual Residual MLP drafting policy."""

from __future__ import annotations

import json
import math
from pathlib import Path

from sts2rl.deck_policy import DeckPolicy
from sts2rl.human_ml_draft import (
    DEFAULT_MODEL_PATH,
    HumanMLDraftModel,
    extract_context_vec,
)
from sts2rl.run_bundle import freeze_bundle, load_bundle
from sts2rl.run_policy import IDENTITY, RunPolicy, RunWeights
from sts2rl.unified_draft import catalog


def _card(name: str, **fields):
    return {"id": "CARD." + name, **fields}


STARTER = (
    ["STRIKE_SILENT"] * 5
    + ["DEFEND_SILENT"] * 5
    + ["NEUTRALIZE", "SURVIVOR", "ASCENDERS_BANE"]
)
A2_BALANCED = STARTER + [
    "DAGGER_SPRAY",
    "PREDATOR",
    "LEADING_STRIKE",
    "HIDDEN_DAGGERS",
    "BACKFLIP",
    "LEG_SWEEP",
    "ACROBATICS",
    "FOOTWORK",
]
A2_SHIV = A2_BALANCED + ["BLADE_DANCE", "CLOAK_AND_DAGGER", "HIDDEN_DAGGERS"]
A2_POISON = A2_BALANCED + ["DEADLY_POISON", "NOXIOUS_FUMES", "BOUNCING_FLASK"]


def _score(
    model: HumanMLDraftModel,
    name: str,
    deck: list[str] = STARTER,
    *,
    act: int = 1,
    act_floor: int = 3,
    energy: int = 3,
    level: int = 0,
    stone_dex: float = 0.0,
    paper_krane: float = 0.0,
) -> float:
    z, ctx = extract_context_vec(
        [_card(c) for c in deck],
        act=act,
        act_floor=act_floor,
        max_energy=energy,
        stone_dex=stone_dex,
        paper_krane=paper_krane,
        hp=60.0,
        max_hp=70.0,
    )
    return model.score_card(_card(name, upgrades=level), z, ctx)


def test_artifact_catalog_finite_and_traps_rejected():
    model = HumanMLDraftModel.load(DEFAULT_MODEL_PATH)
    z, ctx = extract_context_vec(
        [_card(c) for c in STARTER], act=1, act_floor=3, max_energy=3, hp=60.0, max_hp=70.0
    )
    for name, row in catalog().items():
        for level in range(len(row["variants"])):
            val = model.score_card(_card(name, upgrades=level), z, ctx)
            assert math.isfinite(val), (name, level, val)
    for trap in (
        "GRAND_FINALE",
        "THE_GAMBIT",
        "PANIC_BUTTON",
        "CLASH",
        "NEUROSURGE",
        "BURY",
        "DEFRAGMENT",
        "SEVEN_STARS",
        "HIGH_FIVE",
        "SHROUD",
        "BULWARK",
        "FLANKING",
    ):
        assert _score(model, trap) == -1_000_000.0, trap
    assert _score(model, "BURY", energy=4) > -1_000_000.0
    assert _score(model, "ASCENDERS_BANE") == -1_000_000.0


def test_contextual_saturation_synergy_and_upgrades():
    model = HumanMLDraftModel.load(DEFAULT_MODEL_PATH)
    # Frontload attacks drop sharply from Act 1 Floor 3 to Act 2 Floor 5
    for name in ("DAGGER_SPRAY", "PREDATOR", "LEADING_STRIKE"):
        early = _score(model, name, STARTER, act=1, act_floor=3)
        mid = _score(model, name, A2_BALANCED, act=2, act_floor=5)
        assert early > mid + 1.5, (name, early, mid)

    # Poison payoffs jump sharply in a Poison deck
    for name in ("BUBBLE_BUBBLE", "ACCELERANT", "OUTBREAK"):
        base = _score(model, name, A2_BALANCED, act=2, act_floor=5)
        pois = _score(model, name, A2_POISON, act=2, act_floor=5)
        assert pois > base + 1.5, (name, base, pois)

    # Shiv payoffs jump in a Shiv deck
    for name in ("ACCURACY", "FAN_OF_KNIVES", "KNIFE_TRAP"):
        base = _score(model, name, A2_BALANCED, act=2, act_floor=5)
        shiv = _score(model, name, A2_SHIV, act=2, act_floor=5)
        assert shiv > base + 0.5, (name, base, shiv)

    # Upgraded high-impact cards outscore base versions (Afterimage+ only adds Innate, both > +4)
    for name in ("WELL_LAID_PLANS", "FOOTWORK", "TOOLS_OF_THE_TRADE", "PREPARED"):
        base = _score(model, name, A2_BALANCED, act=2, act_floor=5, level=0)
        up = _score(model, name, A2_BALANCED, act=2, act_floor=5, level=1)
        assert up > base + 0.3, (name, base, up)
    assert _score(model, "AFTERIMAGE", A2_BALANCED, act=2, act_floor=5, level=1) > 4.0

    # Top cards clearly beat SKIP in A2 balanced while low-tier cards lose to SKIP
    assert _score(model, "AFTERIMAGE", A2_BALANCED, act=2, act_floor=5) > 2.0
    assert _score(model, "FOOTWORK", A2_BALANCED, act=2, act_floor=5) > 1.0
    assert _score(model, "FLICK_FLACK", A2_BALANCED, act=2, act_floor=5) < -1.0
    assert _score(model, "SLICE", A2_BALANCED, act=2, act_floor=5) < -1.0


def test_deck_policy_card_reward_bundle_and_shop_routing():
    policy = DeckPolicy(
        {
            "version": 1,
            "runtime_identity": IDENTITY,
            "human_ml_draft_v68": True,
            "human_ml_draft_model": str(DEFAULT_MODEL_PATH),
            "human_ml_scope": ["card_reward", "bundle_select", "shop"],
            "human_ml_shop_scale": 4.5,
            "merchant": {"reserve": 1.0, "permanent": 1.1, "gold_curve": True, "potion_capacity": True},
        }
    )
    base = RunPolicy(RunWeights())
    player = {
        "hp": 60,
        "max_hp": 70,
        "gold": 120,
        "deck": [_card(c) for c in A2_BALANCED],
        "relics": [{"id": "RELIC.RING_OF_THE_SNAKE"}],
        "potions": [],
    }
    ctx = {"act": 2, "floor": 5}

    # 1. card_reward: picks AFTERIMAGE over GRAND_FINALE and FLICK_FLACK
    reward_state = {
        "runtime_identity": IDENTITY,
        "decision": "card_reward",
        "context": ctx,
        "player": player,
        "can_skip": True,
        "cards": [
            {"index": 0, "id": "CARD.GRAND_FINALE", "upgrades": 0},
            {"index": 1, "id": "CARD.AFTERIMAGE", "upgrades": 0},
            {"index": 2, "id": "CARD.FLICK_FLACK", "upgrades": 0},
        ],
    }
    action = policy.choose(reward_state, base)
    assert action.kind == "select_card_reward" and action.args["card_index"] == 1

    # 2. card_reward: skips when only traps/weak Act 2 cards offered
    skip_state = {
        **reward_state,
        "cards": [
            {"index": 0, "id": "CARD.GRAND_FINALE", "upgrades": 0},
            {"index": 1, "id": "CARD.FLICK_FLACK", "upgrades": 0},
            {"index": 2, "id": "CARD.SLICE", "upgrades": 0},
        ],
    }
    action_skip = policy.choose(skip_state, base)
    assert action_skip.kind == "skip_card_reward"

    # 3. shop: buys affordable AFTERIMAGE (110g) and refuses GRAND_FINALE / SLICE
    shop_state = {
        "runtime_identity": IDENTITY,
        "decision": "shop",
        "context": ctx,
        "player": player,
        "can_remove_card": False,
        "card_removal_cost": 75,
        "cards": [
            {"index": 0, "id": "CARD.GRAND_FINALE", "cost": 50, "is_stocked": True},
            {"index": 1, "id": "CARD.AFTERIMAGE", "cost": 110, "is_stocked": True},
            {"index": 2, "id": "CARD.SLICE", "cost": 40, "is_stocked": True},
        ],
        "relics": [],
        "potions": [],
    }
    shop_action = policy.choose(shop_state, base)
    assert shop_action.kind == "buy_card" and shop_action.args["card_index"] == 1

    shop_junk = {
        **shop_state,
        "cards": [
            {"index": 0, "id": "CARD.GRAND_FINALE", "cost": 50, "is_stocked": True},
            {"index": 1, "id": "CARD.SLICE", "cost": 40, "is_stocked": True},
        ],
    }
    assert policy.choose(shop_junk, base).kind == "leave_room"


def test_freeze_bundle_roundtrip_with_human_ml_model(tmp_path: Path):
    w_path = tmp_path / "weights.json"
    w_path.write_text(json.dumps(RunWeights().checkpoint()), encoding="utf-8")
    bundle = freeze_bundle(
        {
            "args": {
                "roles": ["candidate"],
                "weights": w_path,
                "human_ml_draft_model": DEFAULT_MODEL_PATH,
            }
        },
        tmp_path / "frozen",
    )
    role, opts = load_bundle(bundle)
    assert role == "candidate"
    assert opts["human_ml_draft_model"].name == "human_ml_draft_model.npz"
    loaded = HumanMLDraftModel.load(opts["human_ml_draft_model"])
    assert len(loaded.vocab) > 100
