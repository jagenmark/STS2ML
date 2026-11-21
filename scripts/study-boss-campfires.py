"""Try healing and smithing at the same natural Act 2 campfire, then finish the boss fight."""

import argparse
import gzip
import hashlib
import json
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from sts2rl.act1 import save_json
from sts2rl.combat_outcome import outcome
from sts2rl.deck_policy import DeckPolicy
from sts2rl.encounter import EncounterModel
from sts2rl.native import (
    NativeError,
    NativeSession,
    ReplayFork,
    digest,
    legal_actions,
    selected_cards,
)
from sts2rl.provenance import boss_study_stamp
from sts2rl.run_bundle import load_bundle
from sts2rl.run_policy import RunPolicy, RunWeights, _hits

ROOT = Path(__file__).resolve().parents[1]


def alternate_upgrade(state, original, plan):
    """Compare marginal upgrade previews at a campfire that already chose to smith."""
    index = int(original.args["indices"])

    def value(card):
        up = card.get("after_upgrade") or {}
        before, after = card.get("stats") or {}, up.get("stats") or {}

        def gain(name):
            return after.get(name, 0) - before.get(name, 0)

        cheaper = max(0, card.get("cost", 0) - up.get("cost", card.get("cost", 0)))
        if plan == "cost":
            score = cheaper
        elif plan == "scaling":
            score = (
                6 * cheaper
                + 5 * _hits(card) * gain("poisonpower")
                + 12 * gain("poisonperturn")
                + 15 * gain("accelerant")
                + 9 * gain("strengthpower")
                + 7 * gain("accuracypower")
                + 12 * gain("afterimagepower")
                + 10 * gain("dexteritypower")
                + 5 * gain("strengthloss")
            )
        else:
            score = (
                5 * cheaper
                + gain("block")
                + 7 * gain("weakpower")
                + 6 * gain("strengthloss")
                + 13 * gain("intangiblepower")
                + 10 * gain("dexteritypower")
                + 12 * gain("afterimagepower")
            )
        return score, card["index"] == index

    chosen = max(state["cards"], key=value)
    return selected_cards(state, [chosen["index"]])


def measure(task):
    file, output, host, bundle, upgrades = task
    with gzip.open(file, "rt") as stream:
        row = json.load(stream)
    history = row["history"]
    map_steps = [i for i, cmd in enumerate(history) if cmd["action"] == "select_map_node"]
    rest, boss = map_steps[-2:]
    spec = row["specification"]
    report = {"seed": row["seed"], "boss": row["boss"], "boss_root": row["root"], "branches": {}}
    if (history[rest]["args"]["row"], history[boss]["args"]["row"]) != (14, 15):
        raise ValueError("Expected adjacent Act 2 campfire and boss nodes")
    _, settings = load_bundle(bundle)
    with tempfile.TemporaryDirectory(dir=output) as temp:
        with NativeSession(
            ROOT,
            Path(temp) / "host",
            host_path=host,
            timeout=90,
            act_list=spec.get("act_list", "default"),
        ) as game:
            game.restore(ReplayFork(spec, tuple(history), row["root"]))
            prefix = history[: rest + 1]
            state = game._request({"cmd": "training_restore", **spec, "history": prefix})
            if state["decision"] != "rest_site" or state["context"]["act"] != 2:
                report["ineligible"] = state["decision"]
                return report
            fork = ReplayFork(spec, tuple(prefix), digest(state))
            options = {
                o["option_id"]: o["index"]
                for o in state["options"]
                if o.get("is_enabled", True) and not o.get("is_locked")
            }
            report.update(
                rest_root=fork.expected_digest,
                hp=state["player"]["hp"],
                max_hp=state["player"]["max_hp"],
                options=sorted(options),
                potions=len(state["player"]["potions"]),
            )
            arms = ("SMITH", "cost", "scaling", "defense") if upgrades else ("HEAL", "SMITH")
            for arm in arms:
                target = "SMITH" if upgrades else arm
                if target not in options:
                    continue
                s = game.restore(fork)
                macro = RunPolicy(
                    RunWeights.load(settings["weights"]), macro_seed=7103 + row["index"]
                )
                actor = EncounterModel.load(settings["encounter_model"])
                deck = DeckPolicy.load(settings["deck_model"])
                if not report["branches"]:
                    chosen = deck.choose(s, macro).args.get("option_index")
                    report["default"] = next((k for k, v in options.items() if v == chosen), None)
                    if upgrades and report["default"] != "SMITH":
                        report["ineligible"] = "Campfire policy chose another option"
                        return report
                action = next(
                    a for a in legal_actions(s) if a.args.get("option_index") == options[target]
                )
                deck.observe(s, action)
                deck.to_upgrade = target == "SMITH"
                s = game.step(action)
                upgrade = None
                if s["decision"] == "card_select":
                    if target != "SMITH":
                        raise ValueError("Unexpected prompt after healing")
                    action = deck.choose(s, macro)
                    if upgrades and arm != "SMITH":
                        action = alternate_upgrade(s, action, arm)
                    indices = {int(i) for i in action.args["indices"].split(",")}
                    upgrade = [c["id"] for c in s["cards"] if c["index"] in indices]
                    s = game.step(action)
                if s["decision"] != "map_select":
                    raise ValueError("Campfire did not return to the map")
                boss_action = next(a for a in legal_actions(s) if a.command() == history[boss])
                s = game.step(boss_action)
                for _ in range(10):
                    if (
                        s["decision"] not in ("card_select", "card_reward")
                        or not s.get("in_combat")
                        or s["context"]["room_type"] != "Boss"
                    ):
                        break
                    s = game.step(actor.choose(s, macro))
                if (
                    s["decision"] != "combat_play"
                    or s["context"]["boss"]["id"] != row["boss"]
                    or s["round"] != 1
                ):
                    raise ValueError(
                        f"Expected first hand of {row['boss']}, got {s['decision']} in {s['context']}"
                    )
                report["branches"][arm] = {
                    "boss_root": digest(s),
                    "enter_hp": s["player"]["hp"],
                    "upgrade": upgrade,
                    **outcome(game, s, actor, macro),
                }
    return report


def checked(task):
    errors = []
    for _ in range(2):
        try:
            result = measure(task)
            break
        except (NativeError, ValueError, TimeoutError, StopIteration) as exc:
            errors.append(str(exc))
    else:
        result = {"seed": task[0].name.removesuffix(".json.gz"), "errors": errors}
    save_json(task[1] / (result["seed"] + ".json"), result)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", nargs="+", type=Path, required=True)
    for key in ("output", "host", "bundle", "seed-lock"):
        p.add_argument("--" + key, required=True, type=Path)
    p.add_argument("--workers", type=int, default=3)
    p.add_argument(
        "--upgrades", action="store_true", help="Compare upgrade targets on natural smith choices"
    )
    p.add_argument("--partition", required=True, choices=["training", "development"])
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    lock = json.loads(a.seed_lock.read_bytes())["seeds"]
    blocked = set(lock["test"]) | set(lock["development" if a.partition == "training" else "train"])
    files = [f for folder in a.source for f in sorted(folder.glob("*.json.gz"))]
    seeds = [f.name.removesuffix(".json.gz") for f in files]
    if not files or set(seeds) & blocked or len(set(seeds)) != len(seeds):
        raise ValueError("Expected unique, eligible non-test campfire roots")
    save_json(
        a.output / "design.json",
        {
            "partition": a.partition,
            "upgrades": a.upgrades,
            "seeds": seeds,
            "label_provenance": boss_study_stamp(a.bundle, a.host, __file__),
            "checkpoint": hashlib.sha256(a.bundle.read_bytes()).hexdigest(),
            "host": hashlib.sha256(a.host.read_bytes()).hexdigest(),
        },
    )
    with ProcessPoolExecutor(a.workers) as pool:
        list(
            pool.map(
                checked, [(f, a.output, a.host.resolve(), a.bundle, a.upgrades) for f in files]
            )
        )


if __name__ == "__main__":
    main()
