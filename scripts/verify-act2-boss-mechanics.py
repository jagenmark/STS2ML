"""Check Kaiser Crab facing and Knowledge Demon's mandatory choice in the pinned game."""
import argparse
import gzip
import json
import tempfile
from pathlib import Path

from sts2rl.act1 import save_json
from sts2rl.encounter import EncounterModel
from sts2rl.native import NativeError, NativeSession, ReplayFork, legal_actions, selected_cards
from sts2rl.run_bundle import load_bundle
from sts2rl.run_policy import RunPolicy, RunWeights
from sts2rl.teacher import incoming

ROOT = Path(__file__).resolve().parents[1]


def restore(row):
    return ReplayFork(row["specification"], tuple(row["history"]), row["root"])


def enter_prompt(game, row, settings):
    state = game.restore(restore(row))
    actor = EncounterModel.load(settings["encounter_model"])
    macro = RunPolicy(RunWeights.load(settings["weights"]), macro_seed=7103 + row["index"])
    for _ in range(50):
        if state["decision"] == "card_select" and any(c["id"] == "CARD.DISINTEGRATION" for c in state["cards"]):
            return state
        state = game.step(actor.choose(state, macro))
    raise ValueError("First Knowledge Demon choice did not appear")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("openings", "old-host", "host", "bundle", "output"):
        p.add_argument("--"+key, type=Path, required=True)
    a = p.parse_args()
    _, settings = load_bundle(a.bundle)
    rows = []
    for file in sorted(a.openings.glob("*.json.gz")):
        with gzip.open(file, "rt") as stream:
            rows.append(json.load(stream))
    proof = {}
    with tempfile.TemporaryDirectory() as temp:
        demon = next(r for r in rows if r["boss"] == "KNOWLEDGE_DEMON_BOSS")
        data = {"seed": demon["seed"], "root": demon["root"], "choices": {}}
        mode = demon["specification"].get("act_list", "default")
        for label, host in (("old", a.old_host), ("fixed", a.host)):
            with NativeSession(ROOT, Path(temp)/label, host_path=host, act_list=mode, timeout=80) as game:
                s = enter_prompt(game, demon, settings)
                data[label] = {"minimum": s["min_select"], "maximum": s["max_select"],
                               "actions": [x.command() for x in legal_actions(s)]}
                if label == "fixed":
                    choices = [c["id"] for c in s["cards"]]
                    try:
                        game._request({"cmd":"action", "action":"skip_select", "args":{}})
                    except NativeError as exc:
                        data["native_skip_error"] = str(exc)
        for card_id in choices:
            with NativeSession(ROOT, Path(temp)/card_id, host_path=a.host, act_list=mode, timeout=80) as game:
                s = enter_prompt(game, demon, settings)
                index = next(c["index"] for c in s["cards"] if c["id"] == card_id)
                state = game.step(selected_cards(s, [index]))
                powers = [x["id"] for x in state["player_powers"]]
                expected = "POWER."+card_id.split(".")[-1]+"_POWER"
                if expected not in powers:
                    raise ValueError("Chosen curse did not appear in the next native state")
                data["choices"][card_id] = powers
        if data["old"]["minimum"] != 0 or data["fixed"]["minimum"] != 1 or not data.get("native_skip_error"):
            raise ValueError("Mandatory choice was not enforced")
        proof["knowledge_demon"] = data
        for row in (r for r in rows if r["boss"] == "KAISER_CRAB_BOSS"):
            s = row["opening"]
            cards = [c for c in s["hand"] if c["can_play"] and c["id"] in ("CARD.STRIKE_SILENT","CARD.BACKSTAB")]
            if not cards:
                continue
            card = cards[0]
            sides = {}
            with NativeSession(ROOT, Path(temp)/row["seed"], host_path=a.host, timeout=80,
                               act_list=row["specification"].get("act_list", "default")) as game:
                for enemy in s["enemies"]:
                    state = game.restore(restore(row))
                    action = next(x for x in legal_actions(state) if x.args == {"card_index":card["index"], "target_index":enemy["index"]})
                    after = game.step(action)
                    damage = {e["id"]: incoming(e) for e in after["enemies"]}
                    next_hand = game.step(next(x for x in legal_actions(after) if x.kind == "end_turn"))
                    sides[enemy["id"]] = {"intents": damage, "block": after["player"]["block"],
                                          "hp_next_turn": next_hand["player"]["hp"]}
            left, right = sides["MONSTER.CRUSHER"], sides["MONSTER.ROCKET"]
            savings = sum(right["intents"].values()) - sum(left["intents"].values())
            if savings > 0 and left["hp_next_turn"] - right["hp_next_turn"] == savings:
                proof["kaiser_crab"] = {"seed":row["seed"], "root":row["root"], "card":card["id"],
                                        "starting_hp":s["player"]["hp"], "target":sides}
                break
    if "kaiser_crab" not in proof:
        raise ValueError("No verified native facing example")
    save_json(a.output, proof)


if __name__ == "__main__":
    main()
