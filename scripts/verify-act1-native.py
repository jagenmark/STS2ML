"""Local native regression probes. Fixtures are never training/evaluation runs."""
import argparse
import json
from pathlib import Path

from sts2rl.act1 import MacroPolicy
from sts2rl.native import ACT1_SAMPLER, NativeError, NativeSession, digest, legal_actions
from sts2rl.teacher import combat_result, heuristic


def fixture(game, encounter, *, deck=None, potions=None):
    game.reset("ACT1QUALIFICATION001")
    if deck is not None or potions is not None:
        game._request({"cmd": "set_player", **({"deck": deck} if deck else {}),
                       **({"potions": potions} if potions else {})})
    game.state = game._request({"cmd": "enter_room", "type": "monster", "encounter": encounter})
    return game.state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    results = []
    deck = ["STRIKE_SILENT"] * 4 + ["DEFEND_SILENT"] * 4 + ["NEUTRALIZE", "SURVIVOR",
            "ASCENDERS_BANE", "CLOAK_AND_DAGGER", "BACKFLIP", "LEG_SWEEP"]
    encounters = ("SHRINKER_BEETLE_WEAK", "NIBBITS_WEAK", "FUZZY_WURM_CRAWLER_WEAK",
                  "SLIMES_WEAK", "INKLETS_NORMAL", "PHROG_PARASITE_ELITE")
    with NativeSession(root, output / "sampling") as game:
        for encounter in encounters:
            traces = []
            for repeat, sample in enumerate((17, 17, 91)):
                state = fixture(game, encounter, deck=deck, potions=["ATTACK_POTION"])
                before = digest(state)
                if repeat == 1:
                    game._request({"cmd": "set_draw_order", "cards": [
                        c["id"].split(".", 1)[1] for c in reversed(state["draw_pile"])]})
                game.sample(sample, profile=ACT1_SAMPLER)
                assert digest(game.state) == before
                trace = []
                for _ in range(256):
                    trace.append(digest(game.state))
                    if combat_result(game.state, profile=ACT1_SAMPLER) is not None:
                        break
                    game.step(heuristic(game.state))
                else:
                    raise AssertionError("Fixture rollout truncated: " + encounter)
                traces.append(digest(trace))
            assert traces[0] == traces[1], "Hidden draw permutation changed labels: " + encounter
            assert traces[0] != traces[2], "Chance samples did not vary: " + encounter
            results.append({"encounter": encounter, "hidden_order_invariance": True, "chance_variation": True})
        state = fixture(game, "SHRINKER_BEETLE_WEAK", deck=["ROLLING_BOULDER"] * 5 + ["DEFEND_SILENT"] * 5)
        boulder = next(c for c in state["hand"] if c["id"] == "CARD.ROLLING_BOULDER")
        game.step(next(a for a in legal_actions(state) if a.args.get("card_index") == boulder["index"]))
        before = sum(e["hp"] for e in game.state["enemies"])
        game.step(next(a for a in legal_actions(game.state) if a.kind == "end_turn"))
        assert sum(e["hp"] for e in game.state["enemies"]) < before, "Native boulder damage must execute"
        assert game.state["round"] == 2
    with NativeSession(root, output / "shop-rest") as game:
        game.reset("ACT1SHOPQUALIFY001")
        game._request({"cmd": "set_player", "gold": 999})
        game.state = game._request({"cmd": "enter_room", "type": "shop"})
        purchased = []
        for kind, inventory in (("buy_relic", "relics"), ("buy_potion", "potions"), ("buy_card", "deck")):
            before = len(game.state["player"][inventory])
            action = next(a for a in legal_actions(game.state) if a.kind == kind)
            game.step(action)
            macro = MacroPolicy(1)
            while game.state["decision"] != "shop":
                game.step(macro(game.state))
            assert len(game.state["player"][inventory]) == before + 1
            purchased.append(kind)
        game._request({"cmd": "set_player", "hp": 10})
        game.state = game._request({"cmd": "enter_room", "type": "rest_site"})
        action = MacroPolicy(1)(game.state)
        game.step(action)
        assert game.state["player"]["hp"] > 10, "Low-HP macro must actually rest"
    with NativeSession(root, output / "draw-knowledge") as game:
        state = fixture(game, "SHRINKER_BEETLE_WEAK", potions=["DISTILLED_CHAOS"])
        assert not state["act1_search_support"]["supported"]
        try:
            game.sample(1, profile=ACT1_SAMPLER)
            raise AssertionError("Remembered draw-order risk accepted")
        except NativeError as exc:
            assert "draw knowledge" in str(exc)
    report = {"passed": True, "profile": ACT1_SAMPLER, "fixtures": results,
              "rolling_boulder_native_damage": True, "shop_effects": purchased,
              "low_hp_rest": True, "unsupported_draw_knowledge_rejected": True,
              "limitation": "Finite regression fixtures; broad sampler is experimental, not a proof for every Act 1 mechanic"}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
