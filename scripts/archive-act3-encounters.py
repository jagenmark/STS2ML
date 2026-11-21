"""Package the Act 3 experiment, verify natural game histories, and reproduce both fits."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import runpy
import subprocess
import sys
import tempfile
import zipfile

import numpy as np

from sts2rl.native import digest
from sts2rl.run_bundle import load_bundle
from sts2rl.trajectory import natural_specification

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "releases/silent-a10-act3-encounters"
ROOM_SOURCES = (
    "local-train-1/incumbent",
    "elite-paths/seek_elites",
    "elite-paths/seek_hard_elites",
    "global-training-results/tempo",
    "global-training-results/guard",
    "global-training-results/pressure",
)
COHORTS = {
    "primary": ("seed-lock.json", "baseline-test", ("combat",)),
    "secondary": ("route-seed-lock.json", "route-test-baseline", ("combat", "route")),
}
TRAIN_DATA = (
    "train-maps",
    "development-maps",
    "training-roots",
    "elite-roots",
    "hard-elite-roots",
    "style-labels",
    "action-labels",
    "forecasts",
    "elite-search",
)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def lines(path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        yield from map(json.loads, stream)


def history(folder):
    with (folder / "game/rpc.jsonl").open(encoding="utf-8") as stream:
        start = json.loads(next(stream))
        spec = natural_specification(start["command"])
        commands, terminal = [], start["response_digest"]
        for line in stream:
            row = json.loads(line)
            if row["command"]["cmd"] == "action":
                commands.append(row["command"])
                terminal = row["response_digest"]
            elif row["command"]["cmd"] != "get_map":
                raise ValueError("Unrecognized lobby history")
    return {"actions": commands, "terminal": terminal, "sha256": digest([spec, commands, terminal])}


def pack_histories(study, cohort, base, arms, dest):
    audits = {r["seed"] for r in read(study / f"held-{cohort}-audit.json")}
    with gzip.open(dest, "wt", encoding="utf-8", compresslevel=6) as stream:
        for game in lines(study / f"held-{cohort}/games.jsonl.gz"):
            seed, idx = game["seed"], game["index"]
            first = history(study / base / "candidate" / f"run-{idx:04d}")
            paths, uses = [first], {"incumbent": 0}
            for arm in arms:
                uses[arm] = 0
                if seed in audits:
                    candidate = history(study / f"{cohort}-{arm}" / seed)
                    if candidate["sha256"] != first["sha256"]:
                        existing = next(
                            (i for i, v in enumerate(paths) if v["sha256"] == candidate["sha256"]),
                            None,
                        )
                        if existing is None:
                            existing = len(paths)
                            paths.append(candidate)
                        uses[arm] = existing
            stream.write(
                json.dumps(
                    {"seed": seed, "index": idx, "arms": uses, "paths": paths},
                    separators=(",", ":"),
                )
                + "\n"
            )


def build(study, archive):
    with (
        tempfile.TemporaryDirectory() as tmp,
        zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED, compresslevel=6) as out,
    ):
        hashes = {}

        def add(path, name):
            if name in hashes:
                raise ValueError("Duplicate archive name " + name)
            data = path.read_bytes()
            hashes[name] = sha(data)
            out.writestr(name, data)

        def tree(path, name, pattern="**/*"):
            files = sorted(p for p in path.glob(pattern) if p.is_file())
            if not files:
                raise ValueError("No inputs in " + str(path))
            for f in files:
                add(f, f"{name}/{f.relative_to(path).as_posix()}")

        for arm, folder in (
            ("incumbent", ROOT / "releases/silent-a10-boss-conversion/challenger"),
            ("combat", RELEASE / "combat"),
            ("route", RELEASE / "route"),
        ):
            load_bundle(folder / "policy.json")
            tree(folder, "models/" + arm)
        for filename in (
            "seed-lock.json",
            "route-seed-lock.json",
            "protocol.json",
            "selection.json",
            "screening.json",
            "training-findings.json",
            "soul-nexus-example.json",
            "soul-nexus-probe.json",
            "mecha-knight.json",
            "fight-diagnostic-lock.json",
            "fight-diagnostics.json",
            "combat-fit.json",
            "route-fit.json",
            "benchmark.json",
            "README.md",
        ):
            add(RELEASE / filename, filename)
        for name in TRAIN_DATA:
            tree(study / name, "training/" + name)
        for part in ("training", "development"):
            tree(study / ("reserve-verified-" + part), "experiments/soul-nexus/" + part)
        for index in (0, 1):
            tree(
                study / "reserve-development" / ("openings-" + str(index)),
                "experiments/soul-nexus/development-openings-" + str(index),
            )
        for f in ("plans.json", "search-elite-examples.py"):
            add(study / f, "training/" + f)
        for source in (*ROOM_SOURCES, "pool-training/incumbent", "pool-training/seek_elites"):
            tree(study / source, "room-observations/" + source, "*/result.json")
        for name, folder in (
            ("pool-route", "pool-route"),
            ("ranked", "ranked"),
            ("forecast", "forecast"),
            ("elite-sampling", "diagnostic-route"),
        ):
            tree(study / folder / "policy", "experiments/" + name)
        for name in (
            "held-natural-roots",
            "held-probe-roots",
            "held-natural-fights",
            "held-elite-fights",
            "held-diagnostic-retries",
        ):
            tree(study / name, "evaluation/fight-diagnostic/" + name)
        add(study / "retry-diagnostic.py", "evaluation/fight-diagnostic/retry-diagnostic.py")
        tree(study / "diagnostic-paths", "evaluation/fight-diagnostic/alternate-lobbies")
        for cohort, (lock, base, arms) in COHORTS.items():
            prefix = "evaluation/" + cohort
            tree(study / ("held-" + cohort), prefix)
            add(study / f"held-{cohort}-audit.json", prefix + "/audit.json")
            for arm in arms:
                directory = (
                    "primary-report" if cohort == "primary" else "secondary-" + arm + "-report"
                )
                tree(study / directory, prefix + "/" + arm)
            packed = Path(tmp) / (cohort + ".gz")
            pack_histories(study, cohort, base, arms, packed)
            add(packed, prefix + "/histories.jsonl.gz")
        manifest = {
            "format": 1,
            "experiment": "silent-a10-act3-encounters",
            "selection_commit": "a332027",
            "sha256": hashes,
        }
        out.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")


def verify_games(root, cohort, lock, arms):
    base = root / "evaluation" / cohort
    seeds = read(root / lock)["seeds"]["test"]
    checked = {r["seed"] for r in read(base / "audit.json")}
    pairs = {arm: {p["seed"]: p for p in read(base / arm / "pairs.json")} for arm in arms}
    totals = {}
    for arm in arms:
        if set(pairs[arm]) != checked:
            raise ValueError("Missing audited seeds")
        totals[arm] = {
            side: dict.fromkeys(("first", "second", "win"), 0)
            for side in ("incumbent", "challenger")
        }
    count, arrivals = 0, 0
    for game, row in zip(
        lines(base / "games.jsonl.gz"), lines(base / "histories.jsonl.gz"), strict=True
    ):
        idx, seed = game["index"], game["seed"]
        if [idx, seed] != [count, seeds[count]] or (row["index"], row["seed"]) != (idx, seed):
            raise ValueError("Natural lobby inventory mismatch")
        count += 1
        spec = {"seed": seed, "ascension": 10, "act_list": "seeded"}
        arrivals += game["a2_clear"]
        for physical in row["paths"]:
            if digest([spec, physical["actions"], physical["terminal"]]) != physical["sha256"]:
                raise ValueError("Physical history mismatch on " + seed)
        for arm in arms:
            pair = pairs[arm].get(seed)
            if pair is None:
                if game["a2_clear"] or row["arms"][arm] != 0:
                    raise ValueError("Changed history without a replay")
                continue
            if bool(pair["origin_map"]) != game["a2_clear"]:
                raise ValueError("Paired Act 3 entry mismatch")
            for label, key, i in (("incumbent", "incumbent", 0), ("challenger", arm, 1)):
                actual = row["paths"][row["arms"][key]]
                receipt = pair["terminal_replays"][i]
                if (
                    actual["sha256"] != receipt["history"]
                    or actual["terminal"] != receipt["terminal"]
                    or len(actual["actions"]) != receipt["actions"]
                ):
                    raise ValueError("Independent native receipt mismatch")
                for k in totals[arm][label]:
                    totals[arm][label][k] += int(pair[label][k])
    if count != len(seeds):
        raise ValueError("Incomplete cohort")
    for arm in arms:
        reported = read(base / arm / "summary.json")["full"]
        if reported["lobbies"] != count or reported["act3_entries"] != arrivals:
            raise ValueError("Aggregate lobby count mismatch")
        for side, stats in totals[arm].items():
            if any(reported[side][k] != n for k, n in stats.items()):
                raise ValueError("Boss or victory counts differ from individual outcomes")
    return totals


def refit(root):
    model = root / "models/incumbent/policy.json"
    params = read(root / "combat-fit.json")["parameters"]

    def run(script, *args):
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / script), *map(str, args)], check=True
        )

    run(
        "fit-act2-hallways.py",
        "--labels",
        root / "training/style-labels",
        "--bundle",
        model,
        "--seed-lock",
        root / "seed-lock.json",
        "--mode",
        params["mode"],
        "--ridge",
        params["ridge"],
        "--min-cases",
        params["min_cases"],
        "--margin",
        params["margin"],
        "--fit-inventory",
        root / "combat-fit.json",
        "--output",
        root / "refit-combat",
    )
    run(
        "fit-act3-route.py",
        "--maps",
        root / "training/train-maps",
        "--base",
        model,
        "--source",
        *(root / "room-observations" / p for p in ROOM_SOURCES),
        "--output",
        root / "refit-route",
    )
    if (root / "refit-route/policy/policy.json").read_bytes() != (
        root / "models/route/policy.json"
    ).read_bytes():
        raise ValueError("Route refit changed")
    a = read(root / "models/combat/encounter_model.json")
    b = read(root / "refit-combat/policy/encounter_model.json")
    linear_a, linear_b = (d["act3_hallways"].pop("linear") for d in (a, b))
    if a != b or linear_a.keys() != linear_b.keys():
        raise ValueError("Combat refit structure changed")
    maximum = 0.0
    for plan, x in linear_a.items():
        y = linear_b[plan]
        if x.keys() != y.keys():
            raise ValueError("Combat feature inventory changed")
        values = [x[k] for k in x]
        fitted = [y[k] for k in x]
        np.testing.assert_allclose(values, fitted, atol=1e-9, rtol=1e-9)
        maximum = max(maximum, max(abs(i - j) for i, j in zip(values, fitted, strict=True)))
    return maximum


def native_sample(root, host, cohort="primary", arm="combat"):
    pairs = read(root / "evaluation" / cohort / arm / "pairs.json")
    changed = [r for r in pairs if r["first_difference"] is not None]
    case = next(
        (r for r in changed if r["challenger"]["first"] and not r["incumbent"]["first"]),
        changed[0] if changed else pairs[0],
    )
    entries = [e for e in read(root / "evaluation" / cohort / "audit.json") if e["seed"] == case["seed"]]
    path = root / "native-sample.json"
    path.write_text(json.dumps(entries), encoding="utf-8")
    target = root / "native-sample"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/play-silent-lobbies.py"),
            "--entries",
            str(path),
            "--bundle",
            str(root / "models" / arm / "policy.json"),
            "--host",
            str(host.resolve()),
            "--workers",
            "1",
            "--output",
            str(target),
        ],
        check=True,
    )
    run = target / case["seed"]
    physical = history(run)
    receipt = case["terminal_replays"][1]
    if physical["sha256"] != receipt["history"] or physical["terminal"] != receipt["terminal"]:
        raise ValueError("Newly played native lobby diverged from its archived history")
    return {
        "seed": case["seed"],
        "physical_history": physical["sha256"],
        "actions": len(physical["actions"]),
        "win": read(run / "result.json")["win"],
    }


def verify(path, repeat, host):
    with zipfile.ZipFile(path) as z, tempfile.TemporaryDirectory() as tmp:
        manifest = json.loads(z.read("manifest.json"))
        names = z.namelist()
        if (
            manifest["format"] != 1
            or len(names) != len(set(names))
            or set(names) != set(manifest["sha256"]) | {"manifest.json"}
        ):
            raise ValueError("Archive inventory mismatch")
        for name, expected in manifest["sha256"].items():
            f = PurePosixPath(name)
            if (
                f.is_absolute()
                or ".." in f.parts
                or "\\" in name
                or ":" in name
                or sha(z.read(name)) != expected
            ):
                raise ValueError("Invalid archive entry " + name)
        root = Path(tmp)
        z.extractall(root)
        selection = read(root / "selection.json")
        for arm in ("incumbent", "combat", "route"):
            p = root / "models" / arm / "policy.json"
            load_bundle(p)
            expected = (
                selection["incumbent_sha256"]
                if arm == "incumbent"
                else selection["arms"][arm]["policy_sha256"]
            )
            if sha(p.read_bytes()) != expected:
                raise ValueError("Frozen checkpoint mismatch")
        protected = set()
        for lock in ("seed-lock.json", "route-seed-lock.json"):
            if sha((root / lock).read_bytes()) != selection["registry_sha256"][lock]:
                raise ValueError("Changed seed registry")
            held = read(root / lock)["seeds"]["test"]
            if set(held) & protected or len(set(held)) != len(held):
                raise ValueError("Test seed overlap")
            protected.update(held)
        for split in ("train", "development"):
            seeds = {r["seed"] for r in read(root / "training" / (split + "-maps") / "index.json")}
            if protected & seeds:
                raise ValueError("Training, development or test maps overlap")
            protected.update(seeds)
        totals = {c: verify_games(root, c, lock, arms) for c, (lock, base, arms) in COHORTS.items()}
        diagnostic = runpy.run_path(str(ROOT / "scripts/report-act3-fights.py"))["summarize"]
        if diagnostic(
            root / "evaluation/fight-diagnostic",
            root / "fight-diagnostic-lock.json",
            root / "seed-lock.json",
        ) != read(root / "fight-diagnostics.json"):
            raise ValueError("Paired fight results differ from the published diagnostic")
        published = read(root / "benchmark.json")
        for cohort, arms in totals.items():
            for arm, scores in arms.items():
                result = published["cohorts"][cohort][arm]["test"]["full"]
                for side, counts in scores.items():
                    if any(result[side][key] != value for key, value in counts.items()):
                        raise ValueError("Published summary differs from audited lobbies")
        delta = refit(root) if repeat else None
        sample = native_sample(root, host) if host else None
    print(
        json.dumps(
            {
                "files": len(names),
                "sha256": sha(path.read_bytes()),
                "scores": totals,
                "refit_max_coefficient_error": delta,
                "native_sample": sample,
            }
        )
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=("build", "verify"))
    p.add_argument("--study", type=Path)
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--refit", action="store_true")
    p.add_argument(
        "--host", type=Path, help="Re-run one archived natural lobby using the frozen policy"
    )
    a = p.parse_args()
    if a.mode == "build":
        if not a.study:
            p.error("build requires --study")
        build(a.study, a.archive)
    verify(a.archive, a.refit, a.host)


if __name__ == "__main__":
    main()
