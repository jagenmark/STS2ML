"""Fit matchup-aware draft residuals to complete, paired native card continuations."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
from statistics import mean
from tempfile import TemporaryDirectory

from sts2rl.act1 import save_json
from sts2rl.encounter_draft import matchup_features
from sts2rl.native import NativeSession, digest, legal_actions
from sts2rl.offer_policy import OfferModel
from sts2rl.run_bundle import load_bundle
from sts2rl.run_policy import RunPolicy, RunWeights
from sts2rl.strategy import StrategyModel
from sts2rl.trajectory import early_draft_contexts, strategy_roots

ROOT = Path(__file__).resolve().parents[1]


def sources(folders):
    result = {}
    for parent in folders:
        for path in sorted(parent.glob("run-*/result.json")):
            row = json.loads(path.read_bytes())
            if row["status"] != "complete" or row.get("opening_partition") == "test":
                continue
            if path.with_name("strategy.jsonl.gz").is_file():
                if row["seed"] in result:
                    raise ValueError(f"Duplicate training seed {row['seed']}")
                result[row["seed"]] = path.parent
    return result


def annotate(task):
    seed, source, host, output = task
    metadata = json.loads((source / "result.json").read_bytes())
    with (source / "game/rpc.jsonl").open(encoding="utf-8") as stream:
        mode = json.loads(next(stream))["command"].get("act_list", "default")
    odds = {}
    error = None
    try:
        with (
            TemporaryDirectory() as tmp,
            NativeSession(
                ROOT,
                Path(tmp) / "game",
                host_path=host,
                act_list=mode,
            ) as game,
        ):
            for root, probability in early_draft_contexts(game, source):
                odds[root] = probability
    except (ValueError, RuntimeError, TimeoutError) as exc:
        error = str(exc)
    save_json(output / f"{seed}.json", {"seed": metadata["seed"], "odds": odds, "error": error})


def seal(args):
    """Bind a previously recorded collection recipe to its completed, numbered shards."""
    files = [args.labels / f"run-{i:04d}" / "labels.json" for i in range(args.count)]
    if args.count < 1 or not all(f.is_file() for f in files):
        raise ValueError("The requested prefix has incomplete label shards")
    teacher = json.loads(args.receipt.read_bytes())
    if not teacher.get("teacher_sources") or not teacher.get("reference_files"):
        raise ValueError("Missing fingerprints for the collecting teacher")
    ledger = {
        f.relative_to(args.labels).as_posix(): sha256(f.read_bytes()).hexdigest() for f in files
    }
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump({"version": 1, "teacher": teacher, "shards": ledger}, stream, indent=2)
        stream.write("\n")


def training_rows(args):
    role, settings = load_bundle(args.bundle)
    if role != "candidate":
        raise ValueError("Expected the challenger strategy baseline")
    policy = RunPolicy(RunWeights.load(settings["weights"]))
    base = StrategyModel.load(settings["strategy_model"])
    opening = OfferModel.load(settings["offer_model"])
    parents = sources(args.source)
    train, validation = [], []
    data_hash = sha256()
    excluded = 0
    seen = set()
    ledger = json.loads(args.receipt.read_bytes())
    expected = ledger["teacher"]
    if (
        expected["reference_sha256"] != sha256(args.bundle.read_bytes()).hexdigest()
        or expected["seed_lock_sha256"] != sha256(args.seed_lock.read_bytes()).hexdigest()
    ):
        raise ValueError("Label reference bundle or seed lock differs from the collecting recipe")
    label_files = ledger["shards"]
    if ledger.get("version") != 1 or not label_files:
        raise ValueError("Missing a sealed training-label inventory")
    protected = {
        seed
        for values in json.loads(args.seed_lock.read_bytes())["seeds"].values()
        for seed in values
    }
    for name, fingerprint in sorted(label_files.items()):
        file = args.labels / name
        if not (
            len(Path(name).parts) == 2
            and Path(name).parts[0].startswith("run-")
            and Path(name).name == "labels.json"
        ):
            raise ValueError("Unexpected label shard path")
        raw = file.read_bytes()
        hash_value = sha256(raw)
        if hash_value.hexdigest() != fingerprint:
            raise ValueError(f"Training labels changed after collection: {name}")
        data_hash.update(hash_value.digest())
        labels = json.loads(raw)
        seed = labels["seed"]
        if seed in protected or seed in seen or seed not in parents:
            raise ValueError(f"Invalid or overlapping training seed {seed}")
        seen.add(seed)
        roots = {
            r["root"]: r
            for r in labels["roots"]
            if r["kind"] == "card" and (r["act"] == 1) == (args.stage == "opening")
        }
        if not roots:
            continue
        contexts = (
            json.loads((args.contexts / f"{seed}.json").read_bytes())
            if args.stage == "opening"
            else {"error": None, "odds": {}}
        )
        for state, fork in strategy_roots(parents[seed]):
            row = roots.pop(fork.expected_digest, None)
            if row is None:
                continue
            if contexts["error"] and fork.expected_digest not in contexts["odds"]:
                excluded += 1
                continue
            probability = contexts["odds"].get(fork.expected_digest)
            trace = {}
            base.choose(state, policy, opening, group_probability=probability, explanation=trace)
            actions = {a.id: a for a in legal_actions(state)}
            scores = {digest(o["action"]): o["total"] for o in trace["options"]}
            cards = {c["index"]: c for c in state["cards"]}
            if set(actions) != {a["id"] for a in row["arms"]}:
                raise ValueError("Incomplete candidate set in a matched draft root")
            arms = []
            for label in row["arms"]:
                action = actions[label["id"]]
                card = cards.get(action.args.get("card_index"))
                features = (
                    matchup_features(card, state["player"]["deck"], state["context"], probability)
                    if card
                    else {}
                )
                if not args.shared:
                    features = {
                        k: v
                        for k, v in features.items()
                        if not k.startswith(("matchup/opening/", "matchup/late/"))
                    }
                arms.append(
                    {
                        "prior": scores[digest(action.command())],
                        "features": features,
                        "return": label["return"],
                    }
                )
            split = int.from_bytes(sha256(seed.encode()).digest()[:4], "big") % 5
            (validation if split == 0 else train).append(
                {"group": seed, "root": row["root"], "arms": arms}
            )
        if roots:
            raise ValueError("Unmatched native training roots")
    return (
        base,
        train,
        validation,
        {
            "label_files": len(label_files),
            "labels_sha256": data_hash.hexdigest(),
            "excluded_contexts": excluded,
            "receipt_sha256": sha256(args.receipt.read_bytes()).hexdigest(),
        },
    )


def fit(args):
    model, train, validation, audit = training_rows(args)
    if not train or not validation:
        raise ValueError("Need disjoint training and validation seeds")
    reports = []
    residuals = {}
    for ridge in (4.0, 16.0, 64.0):
        residual = OfferModel.fit(train, ridge=ridge)
        residuals[ridge] = residual
        for scale in (0.0, 0.25, 0.75, 1.5):
            gains = []
            changed = 0
            for root in validation:
                options = root["arms"]
                old = max(options, key=lambda a: a["prior"])
                new = max(
                    options, key=lambda a: a["prior"] + scale * residual.predict(0, a["features"])
                )
                gains.append(new["return"] - old["return"])
                changed += old is not new
            reports.append(
                {"ridge": ridge, "scale": scale, "changed": changed, "gain": mean(gains)}
            )
    best = max(reports, key=lambda x: (x["gain"], -x["scale"], x["ridge"]))
    for name, ridge, scale in (
        ("selected", best["ridge"], best["scale"]),
        ("regularized", 64.0, 0.75),
    ):
        fitted = StrategyModel(
            dict(model.weights),
            model.kinds,
            model.strength,
            model.strengths_by_kind,
            model.card_offsets,
        )
        multiplier = model.strengths_by_kind.get("card", model.strength)
        fitted.weights.update(
            {
                key: scale * value / multiplier
                for key, value in residuals[ridge].weights.items()
                if scale and value
            }
        )
        fitted.save(args.output / f"{name}.json")
    save_json(
        args.output / "fit.json",
        {
            **audit,
            "train_roots": len(train),
            "validation_roots": len(validation),
            "stage": args.stage,
            "shared": args.shared,
            "train_seeds": sorted({r["group"] for r in train}),
            "validation_seeds": sorted({r["group"] for r in validation}),
            "grid": reports,
            "selected": best,
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    inventory = sub.add_parser("seal")
    for flag in ("labels", "receipt", "output"):
        inventory.add_argument("--" + flag, required=True, type=Path)
    inventory.add_argument("--count", required=True, type=int)
    context = sub.add_parser("contexts")
    context.add_argument("--host", required=True, type=Path)
    context.add_argument("--seeds", required=True, type=int)
    context.add_argument("--workers", default=3, type=int)
    fit_parser = sub.add_parser("fit")
    for flag in ("labels", "bundle", "receipt", "seed-lock"):
        fit_parser.add_argument("--" + flag, required=True, type=Path)
    fit_parser.add_argument("--contexts", type=Path, help="Required for Act 1 pool features")
    fit_parser.add_argument("--stage", default="opening", choices=("opening", "late"))
    fit_parser.add_argument(
        "--shared", action="store_true", help="Also fit shared capability and card effects"
    )
    for child in (context, fit_parser):
        child.add_argument("--source", required=True, type=Path, nargs="+")
        child.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.mode == "seal":
        seal(args)
        return
    if args.mode == "fit" and args.stage == "opening" and args.contexts is None:
        parser.error("Act 1 training requires reconstructed public pool contexts")
    args.output.mkdir(parents=True, exist_ok=False)
    if args.mode == "fit":
        fit(args)
    else:
        tasks = [
            (seed, src, args.host.resolve(), args.output)
            for seed, src in list(sources(args.source).items())[: args.seeds]
        ]
        with ProcessPoolExecutor(args.workers) as pool:
            list(pool.map(annotate, tasks))


if __name__ == "__main__":
    main()
