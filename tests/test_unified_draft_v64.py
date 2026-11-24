"""Regress the shared public raw valuation, including every pinned card variant."""

import gzip
import json
import math
import os
from pathlib import Path

import pytest

from sts2rl.deck_policy import DeckPolicy, deck_context
from sts2rl.run_policy import IDENTITY
from sts2rl.unified_draft import FORCE_SKIP, catalog, effects, normalize, public_context


def card(name, **fields):
    return {"id": "CARD." + name, **fields}


def model(**config):
    return DeckPolicy(dict(version=1, runtime_identity=IDENTITY, unified_draft_v64=True, **config))


STARTER = (
    [card("DEFEND_SILENT")] * 5
    + [card("STRIKE_SILENT")] * 5
    + [card("NEUTRALIZE"), card("SURVIVOR")]
)


def grade(name, extra=(), act=1, energy=3, level=0, deck=STARTER):
    info = deck_context([*deck, *map(card, extra)], unified_draft_v64=True)
    return model().raw_card_value(
        card(name, upgrades=level), dict(act=act, floor=5, max_energy=energy), info
    )


def test_all_catalog_variants():
    models = catalog()
    assert len(models) == 596 and sum(len(r["variants"]) - 1 for r in models.values()) == 557
    star = set()
    multiplayer = set()
    x_cost = set()
    for name, row in models.items():
        for level, static in enumerate(row["variants"]):
            value = grade(name, level=level)
            assert math.isfinite(value)
            if static["star_cost"] > 0 or static["stars_x"]:
                star.add(name)
                assert value < -50
            if static["multiplayer_only"]:
                multiplayer.add(name)
                assert value < -50
            if static["costs_x"]:
                x_cost.add(name)
            if name in FORCE_SKIP or static["card_type"] in ("Curse", "Status", "Quest"):
                assert value < 0
    assert {
        "COMET",
        "SEVEN_STARS",
        "DEVASTATE",
        "ASTRAL_PULSE",
        "CLOAK_OF_STARS",
        "DYING_STAR",
        "PARTICLE_WALL",
        "STARDUST",
    } <= star
    assert {"BLADE_SYMPHONY", "CONCOCT", "FADE", "FLANKING", "SNEAKY"} <= multiplayer
    assert x_cost == set(
        "CASCADE DIRGE ERADICATE HEAVENLY_DRILL MALAISE MULTI_CAST SKEWER TEMPEST VOLLEY WHIRLWIND".split()
    )


@pytest.mark.parametrize("act", (1, 2, 3))
def test_draw_and_engines(act):
    for name in (
        "BACKFLIP",
        "ACROBATICS",
        "PREDATOR",
        "CALCULATED_GAMBLE",
        "AFTERIMAGE",
        "WELL_LAID_PLANS",
        "TOOLS_OF_THE_TRADE",
        "EXPOSE",
        "PIERCING_WAIL",
        "MASTER_PLANNER",
        "APOTHEOSIS",
        "ALCHEMIZE",
        "SCRAWL",
    ):
        assert grade(name, act=act) > 2, name
    assert grade("BOUNCING_FLASK", act=act) > 0
    assert grade("CALCULATED_GAMBLE", level=1) > grade("CALCULATED_GAMBLE")
    assert normalize(card("CALCULATED_GAMBLE"))["after_upgrade"]["keywords"] == {
        "Exhaust",
        "Retain",
    }


def test_synergy_and_support():
    def norm(deck):
        return deck_context(list(map(card, deck)), unified_draft_v64=True)[0]

    assert norm(["CALCULATED_GAMBLE"])["draw"] == norm(["CALCULATED_GAMBLE"])["discard"] == 4
    assert norm(["DEFEND_SILENT"])["block"] == norm(["TOOLS_OF_THE_TRADE"])["discard"] == 1
    assert norm(["BOUNCING_FLASK"])["poison"] == 9 and norm(["BUBBLE_BUBBLE"])["poison"] == 0
    assert norm(["CAPTURE_SPIRIT", "SEEKER_STRIKE"])["draw"] == 0
    assert grade("CORROSIVE_WAVE") < 0 < grade("CORROSIVE_WAVE", ["CALCULATED_GAMBLE"])
    assert grade("PACTS_END") < 0 < grade("PACTS_END", ["BLADE_DANCE", "CLOAK_AND_DAGGER"])
    assert grade("PACTS_END", ["PIERCING_WAIL"] * 3) > 0
    for name in ("TACTICIAN", "REFLEX"):
        assert grade(name, deck=[]) < 0 < grade(name, ["SURVIVOR"] * 5, deck=[])
    assert grade("SPEEDSTER", ["BACKFLIP"] * 3) > grade("SPEEDSTER", ["SURVIVOR"] * 3)
    assert grade("BUBBLE_BUBBLE", ["BUBBLE_BUBBLE"]) < 0 < grade("BUBBLE_BUBBLE", ["DEADLY_POISON"])
    assert grade("ACCELERANT", ["BOUNCING_FLASK"] * 3, level=1) < 30
    assert grade("ACCELERANT", ["BOUNCING_FLASK"] * 3 + ["ACCELERANT"]) < grade(
        "ACCELERANT", ["BOUNCING_FLASK"] * 3
    )
    assert grade("FINISHER", ["BLADE_DANCE"]) > grade("FINISHER", ["DEFEND_SILENT"])
    assert grade("FLECHETTES", ["DEFEND_SILENT"]) > grade("FLECHETTES", ["STRIKE_SILENT"])


def test_dex_and_density():
    info = deck_context(STARTER, unified_draft_v64=True)

    def score(name, dex):
        return model().raw_card_value(card(name), dict(act=2, stone_dex=dex), info)

    assert score("DODGE_AND_ROLL", 1) - score("DODGE_AND_ROLL", 0) == pytest.approx(2.0)
    assert score("BLUR", 1) - score("BLUR", 0) > 1
    assert grade("BLUR", ["DEFEND_SILENT"] * 2) > grade("BLUR", ["STRIKE_SILENT"] * 2)
    assert grade("DODGE_AND_ROLL", ["FOOTWORK"]) > grade("DODGE_AND_ROLL")


def test_energy_thresholds_and_signed_stats():
    assert grade("BURY", energy=3) < 0 < grade("BURY", energy=4)
    assert (
        public_context({"context": {}, "player": {"relics": [{"id": "RELIC.PRISMATIC_GEM"}]}})[
            "max_energy"
        ]
        == 4
    )
    assert grade("FRIENDSHIP", level=1) > grade("FRIENDSHIP")
    assert (
        grade("NEUROSURGE") < 0
        and grade("BRIGHTEST_FLAME") < 0
        and grade("CRASH_LANDING", act=2) < 0
    )
    assert grade("BANSHEES_CRY") < 0 and grade("RIGHT_HAND_HAND") < 0
    for name in ("BANSHEES_CRY", "HEAVENLY_DRILL", "RIGHT_HAND_HAND"):
        assert effects(normalize(card(name))).energy == 0
    assert grade("HEAVENLY_DRILL") < 3
    assert grade("METEOR_STRIKE", energy=4) < 0 < grade("METEOR_STRIKE", energy=5)


def test_offer_routing_and_ties(monkeypatch):
    policy = model(
        scope=["shop", "rest_site"], merchant={"reserve": 1, "permanent": 1, "shop_fixes_v4": True}
    )
    assert {"shop", "card_reward", "bundle_select"} <= policy.scope
    state = {
        "context": {"act": 2, "floor": 5},
        "player": {"deck": STARTER, "gold": 150, "potions": [], "hp": 40, "max_hp": 70},
    }
    values = []
    actual = policy.raw_card_value

    def record(c, ctx, info):
        values.append(actual(c, ctx, info))
        return values[-1]

    monkeypatch.setattr(policy, "raw_card_value", record)
    for name in ("CALCULATED_GAMBLE", "WELL_LAID_PLANS", "EXPOSE", "THE_GAMBIT", "PANIC_BUTTON"):
        row = catalog()[name]
        for level, static in enumerate(row["variants"]):
            fields = dict(
                index=0,
                stats=static["stats"],
                keywords=static["keywords"],
                after_upgrade=None if level else {"cost": row["variants"][1]["cost"]},
            )
            reward = card(name, upgrades=level, cost=static["cost"], **fields)
            values.clear()
            policy.choose(dict(state, decision="card_reward", cards=[reward], can_skip=True), None)
            shop = dict(
                fields, name=row["name"], cost=37, card_cost=static["cost"], is_stocked=True
            )
            action = policy.choose(
                dict(
                    state,
                    decision="shop",
                    cards=[shop],
                    relics=[],
                    potions=[],
                    card_removal_available=False,
                    card_removal_cost=999,
                ),
                None,
            )
            assert len(values) == 2 and values[0] == values[1]
            if name in FORCE_SKIP:
                assert action.kind == "leave_room"
    monkeypatch.setattr(policy, "raw_card_value", lambda *args: 0.0)
    offer = dict(state, decision="card_reward", cards=[card("CLASH", index=0)])
    assert policy.choose(dict(offer, can_skip=True), None).kind == "skip_card_reward"
    assert policy.choose(dict(offer, can_skip=False), None).kind == "select_card_reward"
    sizes = []

    def marginal(c, ctx, info):
        sizes.append(info[0]["n"])
        return -10 if info[1].get(c["id"].split(".")[-1]) else -1

    monkeypatch.setattr(policy, "raw_card_value", marginal)
    bundles = [{"cards": [card("BLUR"), card("BLUR")]}, {"cards": [card("BLUR"), card("FOOTWORK")]}]
    assert policy.choose(dict(state, decision="bundle_select", bundles=bundles), None).args == {
        "bundle_index": 1
    }
    assert sizes == [len(STARTER), len(STARTER) + 1] * 2


@pytest.mark.skipif(not os.getenv("CSV2DEV_HOST"), reason="requires pinned native host")
def test_wax_fan_historical_differential(tmp_path):
    from dataclasses import replace
    from sts2rl.combat_search_v2.integration import CombatSearchV2, _difference
    from sts2rl.combat_search_v2.planner import Config
    from sts2rl.combat_search_v2.state import project, root_move
    from sts2rl.combat_search_v2.transitions import advance
    from sts2rl.native import NativeSession, digest

    root = Path(__file__).resolve().parents[1]
    data = json.loads(gzip.decompress((root / "tests/fixtures/v64-wax-fan.json.gz").read_bytes()))
    steps = {s["index"]: s for s in data["steps"]}
    assert len(steps) == 13
    search = CombatSearchV2(Config(wax_fan_v64=True))
    with NativeSession(root, tmp_path / "native", host_path=os.environ["CSV2DEV_HOST"]) as session:
        public = session.reset(data["seed"])
        for index, command in enumerate(data["history"]):
            search._observe_wax(public)
            after = session._request(command)
            if index in steps:
                step = steps[index]
                assert (digest(public), digest(after)) == (step["before"], step["after"])
                p = project(public, late_prompts=True)
                move = root_move(p, command["action"], command["args"])
                actual = project(after).state
                state = replace(p.state, **step["witness"])
                assert _difference(advance(state, move), actual) == "board/relics"
                assert search._melted_fan
                assert not _difference(advance(replace(state, melted_fan=True), move), actual)
            public = after
