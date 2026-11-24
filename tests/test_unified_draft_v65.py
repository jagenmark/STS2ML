"""Independent checks of the opt-in Silent draft scores and acquisition paths."""

from itertools import combinations
import math

import pytest

from sts2rl.deck_policy import DeckPolicy
from sts2rl.draft_v65 import cleanup, prohibited, role_context, wave_hand
from sts2rl.run_policy import IDENTITY, RunPolicy, RunWeights
from sts2rl.unified_draft import catalog, normalize


def card(name, **fields):
    return {"id": "CARD." + name, **fields}


STARTER = (
    ["STRIKE_SILENT"] * 5 + ["DEFEND_SILENT"] * 5 + ["NEUTRALIZE", "SURVIVOR", "ASCENDERS_BANE"]
)
MIDDLE = STARTER + "DASH PREDATOR DAGGER_SPRAY POISONED_STAB SKEWER ACROBATICS BACKFLIP".split()
ENGINE = (
    MIDDLE
    + "CALCULATED_GAMBLE ACROBATICS BACKFLIP DAGGER_THROW ADRENALINE BOUNCING_FLASK FOOTWORK".split()
)
DECKS = [(1, 2, STARTER), (2, 8, MIDDLE), (3, 10, ENGINE)]
ATTACKS = "PREDATOR DASH DAGGER_SPRAY POISONED_STAB SKEWER".split()
UTILITY = "PIERCING_WAIL CALCULATED_GAMBLE ACROBATICS EXPOSE".split()
ALL = (
    ATTACKS
    + UTILITY
    + """BACKFLIP AFTERIMAGE WELL_LAID_PLANS FOOTWORK ACCELERANT BLUR DODGE_AND_ROLL PACTS_END
    CORROSIVE_WAVE TOOLS_OF_THE_TRADE BURY FRIENDSHIP DEFRAGMENT ZAP BALL_LIGHTNING REAVE REAP
    HIGH_FIVE NEUROSURGE SHROUD BULWARK SEVEN_STARS""".split()
)


def model(**kwargs):
    return DeckPolicy(dict(version=1, runtime_identity=IDENTITY, **kwargs))


def grade(name, deck=STARTER, *, act=1, floor=2, energy=3, level=0, **context):
    info = role_context(list(map(card, deck)), energy)
    return model(unified_draft_v65=True).raw_card_value(
        card(name, upgrades=level), dict(act=act, floor=floor, max_energy=energy, **context), info
    )


@pytest.mark.parametrize(
    "length,sources", [(0, 0), (1, 0), (1, 1), (4, 2), (5, 4), (19, 1), (19, 6)]
)
def test_same_hand_exact(length, sources):
    deck = ["ACROBATICS"] * sources + ["PREDATOR"] * (length - sources)
    info = role_context(list(map(card, deck)), 3)[0]
    hands = list(combinations(range(length), min(4, length)))
    draws = [sum(i < sources for i in hand) * 3 for hand in hands]
    assert wave_hand(info) == pytest.approx(
        (sum(x > 0 for x in draws) / len(hands), sum(draws) / len(hands))
    )


def test_wave_cost_and_timing():
    deck = ["ACROBATICS"] + ["STRIKE_SILENT"] * 18
    assert grade("CORROSIVE_WAVE", deck) < 0 < grade("CORROSIVE_WAVE", ENGINE)
    for k in (
        "PREDATOR",
        "TOOLS_OF_THE_TRADE",
        "DARK_EMBRACE",
        "PALE_BLUE_DOT",
        "MACHINE_LEARNING",
    ):
        assert wave_hand(role_context([card(k)] * 4, 3)[0]) == (0, 0)
    assert wave_hand(role_context([card("PROPHESIZE")] * 4, 2)[0]) == (0, 0)
    assert wave_hand(role_context([card("PROPHESIZE")] * 4, 3)[0]) == (1, 24)


def test_frontload_and_role_saturation():
    assert min(map(grade, ATTACKS)) > max(map(grade, UTILITY))
    for name in [
        "ACROBATICS",
        "BACKFLIP",
        "CALCULATED_GAMBLE",
        "AFTERIMAGE",
        "WELL_LAID_PLANS",
        "FOOTWORK",
    ]:
        assert grade(name) > 0
    assert grade("ACROBATICS", STARTER + ["ACROBATICS"]) > 0
    assert grade("CALCULATED_GAMBLE", level=1) > grade("CALCULATED_GAMBLE")
    assert grade("CALCULATED_GAMBLE", ENGINE + ["CALCULATED_GAMBLE"]) < 0
    for name in ("ACROBATICS", "PIERCING_WAIL", "DAGGER_SPRAY", "SKEWER"):
        assert grade(name, STARTER + [name] * 4) < grade(name)
    assert grade("ACCELERANT", ENGINE) > 0 > grade("ACCELERANT")
    assert grade("EXPOSE", MIDDLE) > grade("EXPOSE") > grade("EXPOSE", MIDDLE + ["EXPOSE"] * 3)
    assert grade("LEG_SWEEP", paper_krane=True) > grade("LEG_SWEEP")
    assert grade("LEG_SWEEP", STARTER + ["SUCKER_PUNCH"] * 3) < grade("LEG_SWEEP")
    assert grade("DASH", STARTER + ["PREDATOR"] * 4) < grade("DASH", STARTER + ["DAGGER_THROW"] * 4)
    assert grade("NOXIOUS_FUMES", act=2) > grade("NOXIOUS_FUMES", floor=5)
    assert grade("AFTERIMAGE", act=2) > grade("AFTERIMAGE", STARTER + ["FOOTWORK"], act=2)
    assert grade("DODGE_AND_ROLL", stone_dex=1) - grade("DODGE_AND_ROLL") == pytest.approx(2)
    assert grade("BLUR", stone_dex=1) - grade("BLUR") > 1
    assert grade("BLUR", STARTER + ["DEFEND_SILENT"] * 3) > grade(
        "BLUR", STARTER + ["STRIKE_SILENT"] * 3
    )
    assert (
        grade("PACTS_END") < 0 < grade("PACTS_END", STARTER + ["BLADE_DANCE", "CLOAK_AND_DAGGER"])
    )
    assert grade("BURY") < 0 < grade("BURY", energy=4)
    assert grade("FRIENDSHIP", level=1) > grade("FRIENDSHIP")


def test_catalog_and_cleanup():
    variants = 0
    info = role_context(list(map(card, STARTER)), 3)
    for name, row in catalog().items():
        for level, static in enumerate(row["variants"]):
            c = card(name, upgrades=level)
            norm = normalize(c)
            score = grade(name, level=level)
            assert math.isfinite(score)
            text = row["description"].lower()
            if (
                static["star_cost"] > 0
                or static["stars_x"]
                or static["multiplayer_only"]
                or "ostydamage" in static["stats"]
                or any(
                    t in text
                    for t in (
                        "osty",
                        "[/gold]doom",
                        "[gold]doom",
                        "[gold]forge",
                        "sovereign blade",
                        "[gold]summon",
                    )
                )
                or name in {"GRAND_FINALE", "THE_GAMBIT", "PANIC_BUTTON", "CLASH", "NEUROSURGE"}
            ):
                assert prohibited(norm, 3, 3) and score < 0
                assert cleanup(c, 100, {"max_energy": 3}, info) < 0
            variants += 1
    assert (len(catalog()), variants) == (596, 1153)
    for name in ("DEFRAGMENT", "DUALCAST", "BARRAGE"):
        assert grade(name) < 0 < grade(name, STARTER + ["ZAP"])
    assert grade("VOLTAIC") < grade("VOLTAIC", STARTER + ["ZAP"]) < 0
    for name in ("ZAP", "BALL_LIGHTNING", "COLD_SNAP", "CONSUMING_SHADOW"):
        assert not prohibited(normalize(card(name)), 3, 0)
    assert not prohibited(normalize(card("HYPERBEAM")), 3, 0)
    assert cleanup(card("DASH"), 4.25, {"max_energy": 3}, info) == 4.25


def test_reward_shop_equality_and_bundles(monkeypatch):
    p = model(unified_draft_v65=True, merchant={"reserve": 1, "permanent": 1})
    state = dict(
        context={"act": 1, "floor": 2},
        player=dict(deck=list(map(card, STARTER)), gold=150, potions=[], hp=55, max_hp=70),
    )
    actual, captured = p.raw_card_value, []

    def record(*args):
        captured.append(actual(*args))
        return captured[-1]

    monkeypatch.setattr(p, "raw_card_value", record)
    for name in (
        "ACROBATICS",
        "CALCULATED_GAMBLE",
        "ZAP",
        "HIGH_FIVE",
        "BURY",
        "DEATHBRINGER",
        "BULWARK",
        "SEVEN_STARS",
    ):
        for level, static in enumerate(catalog()[name]["variants"]):
            c = card(name, index=0, upgrades=level, cost=static["cost"])
            captured.clear()
            reward = p.choose(dict(state, decision="card_reward", cards=[c], can_skip=True), None)
            shop = dict(
                index=0,
                name=catalog()[name]["name"] + "+" * level,
                is_stocked=True,
                cost=30,
                card_cost=static["cost"],
            )
            action = p.choose(
                dict(
                    state,
                    decision="shop",
                    cards=[shop],
                    relics=[],
                    potions=[],
                    card_removal_available=False,
                ),
                None,
            )
            assert len(captured) == 2 and captured[0] == captured[1]
            if captured[0] < 0:
                assert reward.kind == "skip_card_reward" and action.kind == "leave_room"
    bundles = [{"cards": [card("HIGH_FIVE"), card("DASH")]}, {"cards": [card("DASH")]}]
    base = RunPolicy(RunWeights())
    for policy in (p, model(trap_cleanup_v65=True)):
        assert policy.choose(dict(state, decision="bundle_select", bundles=bundles), base).args == {
            "bundle_index": 1
        }


def test_surgical_profile_uses_control_scorers(tmp_path):
    from pathlib import Path
    import runpy

    from sts2rl.deployed_controller import DeployedController

    root = Path(__file__).resolve().parents[1]
    build = runpy.run_path(str(root / "scripts/build-batch1-challengers.py"))["build_batch1_bundle"]
    base = root / "releases/silent-a10-mecha-knight/challenger/policy.json"
    control, arm = [
        DeployedController.from_bundle(build(base, tmp_path / tag, profile=tag))
        for tag in ("v64_control", "trap_cleanup_v65")
    ]

    def public(name, **fields):
        c = normalize(card(name))
        return card(
            name,
            **{k: c[k] for k in ("cost", "stats", "description", "type", "costs_x", "target_type")},
            keywords=sorted(c["keywords"]),
            **fields,
        )

    state = dict(
        runtime_identity=IDENTITY,
        context=dict(act=1, floor=2),
        decision="card_reward",
        player=dict(
            deck=list(map(public, STARTER)), hp=55, max_hp=70, relics=[], potions=[], gold=55
        ),
        can_skip=True,
    )
    for name, expected in [
        ("AFTERIMAGE", "select_card_reward"),
        ("WELL_LAID_PLANS", "select_card_reward"),
        ("GRAND_FINALE", "skip_card_reward"),
        ("BULWARK", "skip_card_reward"),
        ("HIGH_FIVE", "skip_card_reward"),
        ("BURY", "skip_card_reward"),
        ("DASH", "select_card_reward"),
    ]:
        offer = dict(state, cards=[public(name, index=0)])
        assert arm.choose(offer, None).kind == expected
        if name in {"AFTERIMAGE", "WELL_LAID_PLANS", "GRAND_FINALE"}:
            assert control.choose(offer, None).kind != expected
        if name == "DASH":
            values = []
            for controller in (control, arm):
                explanation = {}
                controller.strategy.choose(offer, controller.policy, explanation=explanation)
                values.append([o["total"] for o in explanation["options"]])
            assert values[0] == values[1]
    shop = dict(
        state,
        decision="shop",
        cards=[dict(name="Bulwark", index=0, is_stocked=True, cost=1)],
        card_removal_available=False,
        relics=[],
        potions=[],
    )
    assert arm.choose(shop, None).kind == "leave_room"
