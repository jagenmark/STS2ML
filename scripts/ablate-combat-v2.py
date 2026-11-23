"""Run the learned-leaf calibration check and the paired Phase 2 ablation."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
import gzip
import hashlib
import json
from pathlib import Path
from statistics import fmean

import numpy as np

from sts2rl.combat_search_v2.planner import Config
from sts2rl.combat_search_v2.recording import observer_path
from sts2rl.combat_search_v2.seed_registry import load_registry, registry_sha256
from sts2rl.run_bundle import load_bundle
from sts2rl.run_evaluation import play_episode
from sts2rl.run_policy import RunWeights

ROOT = Path(__file__).resolve().parents[1]
CHAMPION = ROOT / "releases/silent-a10-v2-tactics/challenger/policy.json"
HOST_SHA = "7408d040c28416331279a84e299b52ff35086d80b4cb9711aefd0f91168d8f20"


@dataclass(frozen=True)
class Arm:
    name: str
    width: int = 8
    children: int = 256
    model: Path | None = None
    alpha: float = 0.0


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def planner_source_sha():
    folder = ROOT / "src/sts2rl/combat_search_v2"
    digest = hashlib.sha256()
    for path in sorted(folder.glob("*.py")):
        digest.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def save(path, data):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(path)


def read(path):
    return json.loads(path.read_bytes())


def _runs(parent):
    return sorted(parent.glob("attempt-*"))


def find_result(parent, lobby):
    for path in _runs(parent):
        if not (path / "result.json").is_file():
            continue
        row = read(path / "result.json")
        if (row["seed"], row["index"], row["act_list"]) != (lobby.seed, lobby.index, lobby.mode):
            raise ValueError("Paired rollout identity mismatch")
        if row["status"] == "complete" and (path / "combat-v2-recording.json.gz").is_file():
            return path, row
    return None


def partition_dev(rows):
    tuning, held = [], []
    for mode in ("default", "seeded"):
        group = [row for row in rows if row.split == "dev" and row.mode == mode]
        group.sort(key=lambda row: hashlib.sha256(f"phase2-ablation/{row.seed}".encode()).digest())
        tuning.extend(group[:26])
        held.extend(group[26:])
    return tuning, held


def execute(args, lobbies, arms, role, settings, weights):
    options = {}
    for arm in arms:
        folder = args.output / arm.name
        folder.mkdir(parents=True, exist_ok=True)
        config = folder / "config.json"
        payload = asdict(Config(width=arm.width, children=arm.children, value_win_weight=arm.alpha))
        if config.is_file() and read(config) != payload:
            raise ValueError(f"Existing arm configuration differs: {arm.name}")
        save(config, payload)
        options[arm.name] = {**settings, "record_combat_v2": True, "combat_search_v2": True,
                             "combat_search_v2_config": str(config.resolve()),
                             "combat_value_v2": str(arm.model) if arm.model else None}
    pending = [(arm, lobby) for lobby in lobbies for arm in arms
               if find_result(args.output / arm.name / lobby.seed, lobby) is None]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for _ in range(3):
            if not pending:
                break
            jobs = {}
            for arm, lobby in pending:
                parent = args.output / arm.name / lobby.seed
                folder = parent / f"attempt-{len(_runs(parent)):02d}"
                task = (ROOT, args.host, folder, lobby.seed, lobby.index, role, weights, None,
                        {**options[arm.name], "seeded_acts": lobby.mode == "seeded"})
                jobs[pool.submit(play_episode, task)] = arm, lobby
            pending = []
            for i, job in enumerate(as_completed(jobs), 1):
                row = job.result()
                if row["status"] != "complete":
                    pending.append(jobs[job])
                    print(jobs[job], row.get("error", row["status"]), flush=True)
                if i % 32 == 0 or i == len(jobs):
                    print(f"{i}/{len(jobs)} completed in pass, {len(pending)} retries pending", flush=True)
    if pending:
        raise ValueError(f"Unresolved episode errors: {pending}")


def floor(row):
    return 17 * (row["act"] - 1) + row["floor"]


def bootstrap(differences, lobbies):
    rng = np.random.default_rng(20261123)
    means = np.zeros(10000)
    for mode in ("default", "seeded"):
        group = np.array([value for value, lobby in zip(differences, lobbies) if lobby.mode == mode])
        if group.size:
            sampled = rng.integers(group.size, size=(len(means), len(group)))
            means += group[sampled].sum(axis=1) / len(lobbies)
    return np.quantile(means, [0.025, 0.975]).tolist()


def fights(path):
    with gzip.open(path / "combat-v2-recording.json.gz", "rt", encoding="utf-8") as stream:
        episodes = json.load(stream)["fights"]
    return {(f["act"], f["floor"], f["room_type"], tuple(f["formation"])): f for f in episodes
            if f["outcome"] in ("victory", "dead", "escape")}


def percentiles(values):
    return [float(p) for p in np.percentile(values, [50, 95])] if values else None


def search_metrics(paths):
    coverage = {act: Counter() for act in (1, 2, 3)}
    timing, searched, leaves = [], [], []
    oracle, fallbacks = Counter(), Counter()
    mismatches = Counter()
    for path in paths:
        census = read(path / "combat-v2-census.json")
        for act, counts in census.items():
            coverage[int(act)]["non_forced"] += counts.get("roots", 0)
        sidecar = path / "combat-search-v2.jsonl"
        with sidecar.open(encoding="utf-8") as stream:
            next(stream)
            for line in stream:
                row = json.loads(line)
                counts = coverage[row["act"]]
                counts["visits"] += 1
                timing.append(row["ns"] / 1e6)
                if row["fallback"]:
                    fallbacks[row["fallback"]] += 1
                else:
                    counts["covered"] += 1
                if row["attempts"]:
                    counts["searched"] += 1
                    searched.append(row["ns"] / 1e6)
                if row.get("leaf_ns") is not None:
                    leaves.append(row["leaf_ns"] / 1e6)
                counts["child_cap"] += bool(row.get("child_cap"))
                counts["depth_cap"] += bool(row.get("depth_cap"))
                if "oracle" in row:
                    mechanic, evidence, reason = row["oracle"]
                    oracle[evidence] += 1
                    if evidence == "mismatch":
                        mismatches[f"{mechanic}/{reason}"] += 1
    return {"coverage": coverage, "native": oracle, "mismatches": mismatches,
            "fallback": fallbacks, "decision_p50_p95_ms": percentiles(timing),
            "searched_p50_p95_ms": percentiles(searched), "first_leaf_p50_p95_ms": percentiles(leaves)}


def results_for(args, lobbies, arm):
    if arm == "champion":
        return [find_result(args.data / "dev" / lobby.seed, lobby) for lobby in lobbies]
    return [find_result(args.output / arm / lobby.seed, lobby) for lobby in lobbies]


def summarize_arm(paired, champion, lobbies, *, active):
    rows = [r for _, r in paired]
    base_rows = [r for _, r in champion]
    d = [floor(r) - floor(b) for r, b in zip(rows, base_rows)]
    matched = []
    won = []
    for (current, _), (base, _) in zip(paired, champion):
        current_fights, base_fights = fights(current), fights(base)
        for key in current_fights.keys() & base_fights.keys():
            a, b = current_fights[key], base_fights[key]
            hp = a["exit_hp"] - b["exit_hp"]
            matched.append(hp)
            if a["outcome"] == b["outcome"] == "victory":
                won.append(hp)
    return {"lobbies": len(rows), "mean_floor": fmean(map(floor, rows)), "floor_delta": fmean(d),
            "floor_delta_seed_ci95": bootstrap(d, lobbies), "floor_pair_wlt": [sum(v > 0 for v in d),
            sum(v < 0 for v in d), sum(v == 0 for v in d)],
            "act_clears": [sum(r[key] for r in rows) for key in ("a1_clear", "a2_clear", "win")],
            "matched_fights": len(matched), "matched_exit_hp_delta": fmean(matched) if matched else None,
            "matched_wins": len(won), "matched_win_hp_delta": fmean(won) if won else None,
            "search": search_metrics([path for path, _ in paired]) if active else None}


def factorial(args, lobbies):
    scores = {
        name: np.array([floor(row) for _, row in results_for(args, lobbies, name)])
        for name in ("heuristic-w8", "heuristic-w16", "learned-w8", "learned-w16")
    }
    h8, h16, l8, l16 = scores.values()
    contrasts = {"width_at_heuristic": h16 - h8, "width_at_learned": l16 - l8,
                 "learned_at_width8": l8 - h8, "learned_at_width16": l16 - h16,
                 "interaction": (l16 - l8) - (h16 - h8)}
    return {name: {"floor_delta": float(d.mean()), "seed_ci95": bootstrap(d, lobbies)}
            for name, d in contrasts.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("tune", "ablate"))
    parser.add_argument("--host", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    args.host = args.host.resolve(strict=True)
    args.model = args.model.resolve(strict=True)
    rows = load_registry()
    observer = observer_path(ROOT)
    freeze = read(args.model.parent / "selection-freeze.json")
    collection = read(args.data / "collection.json")
    if (sha(args.host) != HOST_SHA or sha(args.model) != freeze["artifact_sha256"]
            or registry_sha256(rows) != collection["registry_sha256"] or sha(CHAMPION) != collection["champion_sha256"]):
        parser.error("Pinned data, runtime, champion and model identities are required")
    tuning, held = partition_dev(rows)
    lobbies = tuning if args.stage == "tune" else held
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = {"version": 1, "host_sha256": HOST_SHA, "champion_sha256": sha(CHAMPION),
                "registry_sha256": registry_sha256(rows), "model_sha256": sha(args.model),
                "observer_sha256": sha(observer), "planner_source_sha256": planner_source_sha(),
                "workers": args.workers}
    if (path := args.output / "manifest.json").exists() and read(path) != manifest:
        raise ValueError("Existing ablation manifest differs")
    save(path, manifest)
    save(args.output / f"{args.stage}-lobbies.json", [asdict(lobby) for lobby in lobbies])
    role, settings = load_bundle(CHAMPION)
    settings["combat_v2_observer"] = str(observer)
    weights = asdict(RunWeights.load(settings["weights"]))
    if args.stage == "tune":
        arms = (Arm("alpha0", model=args.model), Arm("alpha12", model=args.model, alpha=12))
    else:
        alpha = read(args.output / "tune.json")["selected_alpha"]
        arms = (Arm("heuristic-w8"), Arm("heuristic-w16", width=16, children=512),
                Arm("learned-w8", model=args.model, alpha=alpha),
                Arm("learned-w16", width=16, children=512, model=args.model, alpha=alpha))
    execute(args, lobbies, arms, role, settings, weights)
    champion = results_for(args, lobbies, "champion")
    summary = {"champion": summarize_arm(champion, champion, lobbies, active=False)}
    for arm in arms:
        summary[arm.name] = summarize_arm(results_for(args, lobbies, arm.name), champion, lobbies, active=True)
    if args.stage == "tune":
        a, b = summary["alpha0"], summary["alpha12"]
        summary["selected_alpha"] = 12 if b["act_clears"][0] >= a["act_clears"][0] and (
            b["mean_floor"] > a["mean_floor"]) else 0
    else:
        summary["factorial"] = factorial(args, lobbies)
        wide = summary["heuristic-w16"]["search"]["coverage"]
        if sum(c["child_cap"] for c in wide.values()) > 0:
            fixed = Arm("heuristic-w16-fixed", width=16, children=256)
            execute(args, lobbies, [fixed], role, settings, weights)
            summary[fixed.name] = summarize_arm(results_for(args, lobbies, fixed.name), champion, lobbies, active=True)
    save(args.output / f"{args.stage}.json", summary)
    print(json.dumps({arm: {k: v for k, v in record.items() if k != "search"} if isinstance(record, dict)
                      else record for arm, record in summary.items()}), flush=True)


if __name__ == "__main__":
    main()
