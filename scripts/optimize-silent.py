"""Search compact Silent A10 policy weights with paired native runs, or evaluate a frozen policy."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
from random import Random
from statistics import fmean
import sys

from sts2rl.act1 import save_json
from sts2rl.native import digest
from sts2rl.opening_split import select_openings
from sts2rl.run_bundle import load_bundle
from sts2rl.run_evaluation import run_batch
from sts2rl.run_policy import RunWeights

ROOT = Path(__file__).resolve().parents[1]


def progress_value(row):
    # A dense training signal when full-game wins are rare. Report all three
    # clear rates separately in evaluation; floor resets at each act boundary.
    return (100 * row["win"] + 20 * (row["act"] - 1) + row["floor"]
            + (1 - row["boss_hp_fraction"] if row["boss_hp_fraction"] is not None else 0))


def summarize(rows):
    ok = [r for r in rows if r["status"] == "complete"]
    return {"attempted": len(rows), "complete": len(ok),
            "errors": dict(Counter(r.get("error", r["status"]) for r in rows if r["status"] != "complete")),
            "act1_clears": sum(r["a1_clear"] for r in rows), "act2_clears": sum(r["a2_clear"] for r in rows),
            "wins": sum(r["win"] for r in ok), "mean_progress": fmean(map(progress_value, ok)) if ok else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("train", "evaluate", "collect-late", "check-late"))
    parser.add_argument("--host", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prefix", help="Namespace for fresh full-game seeds")
    parser.add_argument("--seeds", type=int, default=8)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--weights", type=Path)
    parser.add_argument("--bundle", type=Path, help="Load the actor and verify its portable inference files")
    parser.add_argument("--late-weights", type=Path, help="Switch to these fitted weights after clearing Act 1")
    parser.add_argument("--act2-starts", nargs="+", type=Path, help="Train on real Act 2 openings from these role directories")
    parser.add_argument("--opening-split", type=Path, help="Verify this pool against an earlier opening-split.json")
    parser.add_argument("--curriculum-act", type=int, choices=(2,3), default=2, help="Which natural opening to load from the training traces")
    parser.add_argument("--micro", type=Path, help="Include this neural combat checkpoint in evaluation")
    parser.add_argument("--room-model", type=Path, help="Use a fitted visible-map model for candidate routes")
    parser.add_argument("--late-room-model", type=Path, help="Use rooms fitted on later acts after the first boss")
    parser.add_argument("--offer-model", type=Path, help="Use a ranker fitted to counterfactual opening/reward choices")
    parser.add_argument("--strategy-model", type=Path, help="Rank public macro choices using matched native continuation returns")
    parser.add_argument("--encounter-model", type=Path, help="Select a trained combat style from the public fight opening")
    parser.add_argument("--return-model", type=Path, help="Consult a tactical model trained on counterfactual fight outcomes")
    parser.add_argument("--deck-model", type=Path, help="Evaluate attack, defense and persistent effects against the current deck")
    parser.add_argument("--turn-search", action="store_true", help="Plan affordable card sequences in the visible hand")
    parser.add_argument("--combat-search", action="store_true", help="Add bounded Act 1 sampled fight search to the candidate")
    parser.add_argument("--deck-effects", action="store_true", help="Score persistent effects using current deck and enemy intents")
    parser.add_argument("--boss-search", type=Path, help="Compare combat policies in independently sampled Act 1 boss fights")
    parser.add_argument("--tactical-student", type=Path)
    parser.add_argument("--label-turns", action="store_true", help="Save the planner's choice on the actor's training states")
    parser.add_argument("--roles", nargs="+", choices=("baseline", "prior", "candidate", "micro", "student", "hybrid", "original-macro", "original-combat", "no-route", "no-offer", "no-turn", "no-late"),
                        default=None)
    parser.add_argument("--population", type=int, default=9)
    parser.add_argument("--generations", type=int, default=5)
    parser.add_argument("--record-rooms", action="store_true", help="Save public resource changes after each chosen map node")
    parser.add_argument("--seeded-acts", action="store_true", help="Use the standard lobby act selector on the fully unlocked profile")
    parser.add_argument("--record-strategy", action="store_true", help="Save public macro decisions and boss openings")
    parser.add_argument("--explain-drafts", action="store_true",
                        help="Write each strategy card reward's component scores to draft-scores.jsonl.gz")
    args = parser.parse_args()
    actor = "candidate"
    if args.bundle:
        actor, settings = load_bundle(args.bundle)
        for key, value in settings.items():
            if not getattr(args, key):
                setattr(args, key, value)
    if args.roles is None:
        args.roles = [actor] if args.mode in ("collect-late", "check-late") else ["baseline", actor]
    if args.mode == "check-late" and not args.act2_starts:
        parser.error("Conditional checks require --act2-starts training trace directories")
    if not args.act2_starts and not args.prefix:
        parser.error("Fresh full-game runs require a seed --prefix")
    if args.mode == "collect-late" and (not args.act2_starts or not args.label_turns):
        parser.error("Late tactical collection requires --act2-starts and --label-turns")
    if min(args.workers, args.seeds, args.generations) < 1 or args.population < 4:
        parser.error("Invalid budget")
    if "micro" in args.roles and not args.micro:
        parser.error("--micro is required for the micro role")
    if {"student", "hybrid"}.intersection(args.roles) and not args.tactical_student:
        parser.error("--tactical-student is required for neural tactical roles")
    if "hybrid" in args.roles and not args.turn_search:
        parser.error("The hybrid uses --turn-search in Act 1")
    if len(set(args.roles)) != len(args.roles):
        parser.error("Roles must be unique")
    starts = []
    opening_split = partition = None
    if args.opening_split and not args.act2_starts:
        parser.error("--opening-split requires --act2-starts")
    if args.mode == "check-late" and args.label_turns:
        parser.error("check-late uses held-out seeds; collect training labels with collect-late")
    if args.act2_starts:
        if args.mode == "evaluate" or (args.mode != "check-late" and args.late_weights):
            parser.error("Use check-late to evaluate late overrides on a curriculum opening")
        partition = "test" if args.mode == "check-late" else "train"
        needed = args.seeds * (args.generations if args.mode == "train" else 1)
        try:
            starts, opening_split = select_openings(args.act2_starts, args.curriculum_act,
                "seeded" if args.seeded_acts else "default", partition, needed, args.opening_split)
        except ValueError as exc:
            parser.error(str(exc))
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    if opening_split is not None:
        save_json(output / "opening-split.json", opening_split)
    default = RunWeights()
    weights = RunWeights.load(args.weights) if args.weights else default
    def file_hash(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest() if path else None

    manifest = {"args": vars(args), "command": sys.argv[1:], "host_sha256": file_hash(args.host),
                "game_sha256": hashlib.sha256((ROOT / "artifacts/upstreams/sts2-cli/lib/sts2.dll").read_bytes()).hexdigest(),
                "godot_sha256": file_hash(args.host.parent / "GodotSharp.dll"),
                "selector_fix_local_task": os.getenv("STS2_SELECTOR_FIX_LOCAL_TASK"),
                "weights": weights.checkpoint(), "late_sha256": file_hash(args.late_weights),
                "curriculum_seeds": [s for s, _ in starts[:args.seeds * args.generations]],
                "opening_partition": partition, "opening_split_sha256": digest(opening_split) if opening_split else None,
                "room_sha256": file_hash(args.room_model), "late_room_sha256": file_hash(args.late_room_model),
                "offer_sha256": file_hash(args.offer_model),
                "micro_sha256": file_hash(args.micro), "student_sha256": file_hash(args.tactical_student)}
    for key in ("strategy_model", "encounter_model", "deck_model", "return_model", "boss_search"):
        manifest[key + "_sha256"] = file_hash(getattr(args, key))
    save_json(output / "config.json", json.loads(json.dumps(manifest, default=str)))
    options = {"curriculum_act": args.curriculum_act, "rooms": args.record_rooms, "record_strategy": args.record_strategy, "seeded_acts": args.seeded_acts,
               "strategy_model": str(args.strategy_model.resolve()) if args.strategy_model else None,
               "encounter_model": str(args.encounter_model.resolve()) if args.encounter_model else None,
               "return_model": str(args.return_model.resolve()) if args.return_model else None,
               "deck_model": str(args.deck_model.resolve()) if args.deck_model else None,
               "boss_search": str(args.boss_search.resolve()) if args.boss_search else None,
               "room_model": str(args.room_model.resolve()) if args.room_model else None,
               "late_room_model": str(args.late_room_model.resolve()) if args.late_room_model else None,
               "offer_model": str(args.offer_model.resolve()) if args.offer_model else None, "turn_search": args.turn_search,
               "combat_search": args.combat_search, "label_turns": args.label_turns, "deck_effects": args.deck_effects,
               "late_weights": str(args.late_weights.resolve()) if args.late_weights else None,
               "tactical_student": str(args.tactical_student.resolve()) if args.tactical_student else None}
    options["opening_partition"] = partition
    options["explain_drafts"] = args.explain_drafts
    if args.explain_drafts:
        from sts2rl.provenance import draft_scorer_hash
        options["draft_scorer_sha256"] = draft_scorer_hash()
        options["draft_model_hashes"] = {
            key: file_hash(getattr(args, key)) for key in ("weights", "strategy_model", "offer_model", "late_weights")
        }
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        if args.mode != "train":
            specs = [(role, asdict(default if role == "prior" else weights), args.micro.resolve() if role == "micro" else None)
                     for role in args.roles]
            rows = run_batch(pool, ROOT, args.host, output, specs, args.prefix, args.seeds, options, starts)
            common = set.intersection(*[{r["seed"] for r in rows if r["role"] == role and r["status"] == "complete"}
                                        for role in args.roles])
            report = {"roles": {role: summarize([r for r in rows if r["role"] == role]) for role in args.roles},
                      "start_act": args.curriculum_act if starts else 1,
                      "paired_seeds": len(common),
                      "paired": {role: summarize([r for r in rows if r["role"] == role and r["seed"] in common]) for role in args.roles}}
            save_json(output / "report.json", report)
            print(json.dumps(report), flush=True)
            return

        # Cross-entropy method in log-weight space. Each generation shares
        # fresh training seeds. Elites are averaged only on common complete runs.
        rng = Random(20261119)
        center = {k: math.log(v) for k, v in asdict(weights).items()}
        spreads = {k: .48 for k in center}
        for gen in range(args.generations):
            params = [center.copy()]
            for _ in range(args.population - 1):
                params.append({k: max(-3, min(4, rng.gauss(m, spreads[k]))) for k, m in center.items()})
            specs = [(f"p{i:02d}", {k: math.exp(x) for k, x in p.items()}, None) for i, p in enumerate(params)]
            folder = output / f"gen-{gen:02d}"
            generation_starts = starts[gen * args.seeds:(gen + 1) * args.seeds]
            rows = run_batch(pool, ROOT, args.host, folder, specs, f"{args.prefix}G{gen:02d}S", args.seeds,
                             options, starts=generation_starts)
            common = set.intersection(*[{r["seed"] for r in rows if r["role"] == role and r["status"] == "complete"}
                                        for role, _, _ in specs])
            if len(common) < max(2, math.ceil(args.seeds * .5)):
                raise RuntimeError(f"Only {len(common)} complete paired training seeds in generation {gen}")
            scores = [fmean(progress_value(r) for r in rows if r["role"] == role and r["seed"] in common)
                      for role, _, _ in specs]
            ranked = sorted(range(len(params)), key=lambda i: scores[i], reverse=True)
            elites = ranked[:max(2, args.population // 3)]
            for k in center:
                avg = fmean(params[i][k] for i in elites)
                var = fmean((params[i][k] - avg) ** 2 for i in elites)
                center[k] = .25 * center[k] + .75 * avg
                spreads[k] = max(.18, .4 * spreads[k] + .6 * math.sqrt(var))
            weights = RunWeights(**{k: math.exp(m) for k, m in center.items()})
            summary = {"generation": gen, "common": len(common), "scores": scores, "elites": elites,
                       "population": [w for _, w, _ in specs], "spreads": spreads.copy(),
                       "statuses": dict(Counter(r["status"] for r in rows))}
            save_json(folder / "training.json", summary)
            save_json(folder / "weights.json", weights.checkpoint())
            save_json(output / "weights.json", weights.checkpoint())
            print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
