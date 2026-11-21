"""Learn a first-action override from paired native Windup and Heavy Cleave continuations."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
from pathlib import Path
import runpy
from tempfile import TemporaryDirectory

from sts2rl.act1 import save_json
from sts2rl.combat_outcome import outcome
from sts2rl.encounter import EncounterModel
from sts2rl.mecha_knight import phase, rank_features
from sts2rl.native import NativeError, NativeSession, digest, legal_actions
from sts2rl.offer_policy import OfferModel
from sts2rl.run_bundle import freeze_bundle, load_bundle
from sts2rl.run_policy import RunPolicy, RunWeights

ROOT = Path(__file__).resolve().parents[1]
study = runpy.run_path(str(ROOT / "scripts/study-mecha-knight.py"))
read, read_case, restore, sha = (study[k] for k in ("read", "read_case", "restore", "sha"))


def collect_one(task):
    path, host, bundle, folder, stamp = task
    case = read_case(path)
    if case["partition"] != "train":
        raise ValueError("Counterfactual labels require training maps")
    _, opts = load_bundle(bundle)
    config = read(opts["encounter_model"])
    weights = RunWeights.load(opts["weights"])
    macro = RunPolicy(weights)
    positions = []
    errors = []
    serial = 0
    with TemporaryDirectory() as tmp:
        game = None

        def fresh():
            nonlocal serial
            serial += 1
            return NativeSession(
                ROOT,
                Path(tmp) / str(serial),
                host_path=host,
                act_list=case["spec"].get("act_list", "default"),
                timeout=75,
            )

        def at_start(stream=False):
            nonlocal game
            if game is None or game.closed:
                game = fresh()
            return restore(game, case, stream)

        def scout(stream=False):
            st = at_start(stream)
            actor = EncounterModel(config)
            prefix = []
            wind = 0
            sampled = set()
            found = []
            for _ in range(300):
                if st["decision"] == "game_over" or not st.get("in_combat"):
                    break
                played = actor.choose(st, macro)
                stage = phase(st, wind)
                if stage == "windup":
                    wind = st["round"]
                if stage and stage not in sampled:
                    legal = legal_actions(st)
                    if len(legal) >= 3:
                        priors = actor.actor.combat_scores(st, legal)
                        features = rank_features(st, legal, priors, stage)
                        order = sorted(
                            range(len(legal)),
                            key=lambda i: (
                                legal[i] != played,
                                legal[i].kind != "use_potion",
                                legal[i].kind != "end_turn",
                                -priors[i],
                            ),
                        )
                        arms = [
                            {
                                "command": legal[i].command(),
                                "prior": priors[i],
                                "features": features[i],
                            }
                            for i in order[:6]
                        ]
                        found.append(
                            {
                                "phase": stage,
                                "root": digest(st),
                                "history": list(prefix),
                                "arms": arms,
                            }
                        )
                        sampled.add(stage)
                if len(sampled) == 2:
                    break
                prefix.append(played.command())
                st = game.step(played)
            return found

        def branch(pos, command, stream):
            st = at_start(stream)
            actor = EncounterModel(config)
            for cmd in pos["history"]:
                if actor.actor is None and st["decision"] == "combat_play":
                    actor.choose(st, macro)
                st = game._request(cmd)
            game.state = st
            if digest(st) != pos["root"]:
                raise ValueError("Counterfactual root differs")
            baseline = actor.choose(st, macro)
            if baseline.command() != pos["arms"][0]["command"]:
                raise ValueError("The frozen baseline did not reproduce")
            action = next(a for a in legal_actions(st) if a.command() == command)
            result = outcome(game, game.step(action), actor, macro)
            return {**result, "terminal": digest(game.state)}

        try:
            try:
                found = scout()
            except NativeError:
                found = scout(True)
            for pos in found:
                arms = []
                for arm in pos["arms"]:
                    try:
                        try:
                            result = branch(pos, arm["command"], False)
                        except NativeError:
                            result = branch(pos, arm["command"], True)
                        arms.append({**arm, "outcome": result})
                    except (ValueError, NativeError, TimeoutError) as exc:
                        errors.append({"root": pos["root"], "error": str(exc)})
                        break
                if len(arms) == len(pos["arms"]):
                    positions.append({"phase": pos["phase"], "root": pos["root"], "arms": arms})
        except (ValueError, NativeError, TimeoutError) as exc:
            errors.append({"case": case["case"], "error": str(exc)})
        finally:
            if game is not None:
                game.close()
    save_json(
        folder / (case["case"] + ".json"),
        {
            "seed": case["seed"],
            "case": case["case"],
            "kind": case["kind"],
            "partition": case["partition"],
            "receipt": stamp,
            "positions": positions,
            "errors": errors,
        },
    )


def label(a):
    entries = read(a.cases / "index.json")
    if any(e["partition"] != "train" for e in entries):
        raise ValueError("Only training cases may be labeled")
    a.output.mkdir(parents=True, exist_ok=False)
    sources = [
        Path(__file__),
        ROOT / "scripts/study-mecha-knight.py",
        *sorted((ROOT / "src/sts2rl").glob("*.py")),
    ]
    receipt = {
        "teacher": sha(a.bundle),
        "host": sha(a.host),
        "cases": sha(a.cases / "index.json"),
        "source": {f.name: sha(f) for f in sources},
        "seeds": sorted({e["seed"] for e in entries}),
        "partition": "train",
    }
    save_json(a.output / "receipt.json", receipt)
    stamp = sha(a.output / "receipt.json")
    tasks = [
        (a.cases / (e["case"] + ".json.gz"), a.host.resolve(), a.bundle, a.output, stamp)
        for e in entries
    ]
    with ProcessPoolExecutor(a.workers) as pool:
        list(pool.map(collect_one, tasks))


def utility(r):
    return 60 * r["won"] + 0.7 * r["hp"] + 18 * (1 - r["remaining"]) + 2 * r["potions"] * r["won"]


def fit(a):
    rows = []
    seeds = set()
    roots = set()
    receipt = read(a.labels / "receipt.json")
    stamp = sha(a.labels / "receipt.json")
    if receipt["partition"] != "train" or receipt["teacher"] != sha(a.bundle):
        raise ValueError("Wrong training teacher")
    entries = read(a.cases / "index.json")
    expected = {e["case"]: e["seed"] for e in entries}
    got = {f.stem for f in a.labels.glob("*.json") if f.name != "receipt.json"}
    if (
        sha(a.cases / "index.json") != receipt["cases"]
        or set(expected) != got
        or len(expected) != len(entries)
    ):
        raise ValueError("The native label directory must contain every registered training case")
    for f in sorted(a.labels.glob("*.json")):
        if f.name == "receipt.json":
            continue
        r = read(f)
        if r["receipt"] != stamp or r["partition"] != "train" or r["seed"] not in receipt["seeds"]:
            raise ValueError("Unrecognized training label")
        if r["case"] != f.stem or expected[r["case"]] != r["seed"]:
            raise ValueError("Training case identity mismatch")
        for pos in r["positions"]:
            if pos["root"] in roots:
                continue
            roots.add(pos["root"])
            seeds.add(r["seed"])
            rows.append((r["seed"], pos))

    def model(group, ridge):
        return OfferModel.fit(
            [
                {
                    "arms": [
                        {
                            "features": v["features"],
                            "prior": 0.18 * v["prior"],
                            "return": utility(v["outcome"]),
                        }
                        for v in pos["arms"]
                    ]
                }
                for seed, pos in group
            ],
            ridge=ridge,
        )

    def split(seed):
        return int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16) % 4 == 0

    train = [r for r in rows if not split(r[0])]
    valid = [r for r in rows if split(r[0])]
    if not train or not valid:
        raise ValueError("Missing grouped validation cases")
    trials = []
    for ridge in (12, 48, 120):
        fit_model = model(train, ridge)
        for scale in (0.4, 0.8, 1.2):
            for margin in (1.5, 4.0):
                acc = 0
                wins = 0
                changes = 0
                for _, r in valid:
                    scores = [
                        0.18 * v["prior"] + scale * fit_model.predict(0, v["features"])
                        for v in r["arms"]
                    ]
                    best = max(range(len(scores)), key=scores.__getitem__)
                    if scores[best] <= scores[0] + margin:
                        best = 0
                    base, select = r["arms"][0]["outcome"], r["arms"][best]["outcome"]
                    acc += utility(select) - utility(base)
                    wins += select["won"] - base["won"]
                    changes += bool(best)
                trials.append((wins, acc, -changes, ridge, scale, margin))
    wins, gain, negchanges, ridge, scale, margin = max(trials)
    fitted = model(rows, ridge)
    role, opts = load_bundle(a.bundle)
    cfg = read(opts["encounter_model"])
    cfg["mecha_knight"] = {
        "ranker": {"weights": fitted.weights, "prior": 0.18, "scale": scale, "margin": margin}
    }
    a.output.mkdir(parents=True, exist_ok=False)
    save_json(a.output / "encounter.json", cfg)
    opts["encounter_model"] = a.output / "encounter.json"
    freeze_bundle({"args": {**opts, "roles": [role]}}, a.output / "policy")
    save_json(
        a.output / "fit.json",
        {
            "teacher": sha(a.bundle),
            "labels": stamp,
            "positions": len(rows),
            "seeds": sorted(seeds),
            "train_positions": len(train),
            "validation_positions": len(valid),
            "native_arms": sum(len(pos["arms"]) for _, pos in rows),
            "selected": {"ridge": ridge, "scale": scale, "margin": margin},
            "grouped_validation": {"wins": wins, "gain": gain, "changes": -negchanges},
            "roots": sorted(roots),
        },
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="mode", required=True)
    collect = sub.add_parser("label")
    f = sub.add_parser("fit")
    for k in ("host", "cases"):
        collect.add_argument("--" + k, type=Path, required=True)
    collect.add_argument("--workers", type=int, default=3)
    f.add_argument("--labels", type=Path, required=True)
    f.add_argument("--cases", type=Path, required=True)
    for q in (collect, f):
        for k in ("bundle", "output"):
            q.add_argument("--" + k, type=Path, required=True)
    a = p.parse_args()
    if a.mode == "label":
        label(a)
    else:
        fit(a)


if __name__ == "__main__":
    main()
