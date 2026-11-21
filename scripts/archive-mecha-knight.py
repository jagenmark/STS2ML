"""Build or verify the portable Mecha Knight and native A7 transfer research archive."""

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import runpy
import subprocess
import sys
from tempfile import TemporaryDirectory
import zipfile

from sts2rl.native import digest
from sts2rl.run_bundle import load_bundle

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "releases/silent-a10-mecha-knight"
previous = runpy.run_path(str(ROOT / "scripts/archive-act3-encounters.py"))
pack_histories, verify_games, native_sample = (
    previous[x] for x in ("pack_histories", "verify_games", "native_sample")
)


def read(path):
    return json.loads(path.read_bytes())


def sha(data):
    return hashlib.sha256(data).hexdigest()


def build(study, archive, histories=None):
    with (
        TemporaryDirectory() as tmp,
        zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED, compresslevel=5) as z,
    ):
        hashes = {}

        def add(path, name):
            if name in hashes:
                raise ValueError("Repeated archive path")
            data = path.read_bytes()
            hashes[name] = sha(data)
            z.writestr(name, data)

        def tree(folder, prefix):
            files = sorted(f for f in folder.rglob("*") if f.is_file())
            if not files:
                raise ValueError(f"Missing archive input {folder}")
            for f in files:
                add(f, prefix + "/" + f.relative_to(folder).as_posix())

        for f in sorted(RELEASE.iterdir()):
            if f.is_file() and f.name != "archive.json" and f.suffix in (".json", ".md"):
                add(f, f.name)
        tree(ROOT / "releases/silent-a10-act3-encounters/combat", "models/incumbent")
        tree(RELEASE / "challenger", "models/challenger")
        tree(study / "ranked", "training/ranked")
        for f in ("train-cases", "screen-cases", "screen", "action-labels"):
            tree(study / f, "training/" + f)
        for f in ("development-cases", "development", "ranked-development"):
            tree(study / f, "development/" + f)
        for cohort, base in (("main", "main-baseline"), ("replication", "replication-joined")):
            prefix = "evaluation/" + cohort
            held = study / ("held-" + cohort)
            add(held / "games.jsonl.gz", prefix + "/games.jsonl.gz")
            add(study / ("held-" + cohort + "-audit.json"), prefix + "/audit.json")
            tree(study / (cohort + "-report"), prefix + "/challenger")
            tree(study / (cohort + "-practice-cases"), prefix + "/practice-cases")
            tree(study / (cohort + "-practice"), prefix + "/practice")
            dest = (histories or Path(tmp)) / (cohort + ".jsonl.gz")
            if histories is None:
                pack_histories(study, cohort, base, ("challenger",), dest)
            add(dest, prefix + "/histories.jsonl.gz")
        for prefix, raw in (("a7", "a7-benchmark"), ("a7-replication", "a7-replication")):
            tree(study / (prefix + "-report"), "evaluation/" + prefix)
            add(study / raw / "config.json", "evaluation/" + prefix + "/config.json")
        for prefix in ("a7", "a7-replication"):
            for name in (
                "entries.json",
                "pairs.json",
                "summary.json",
                "changed-histories.jsonl.gz",
            ):
                add(
                    study / (prefix + "-finalist") / name,
                    "evaluation/" + prefix + "/finalist/" + name,
                )
        tree(study / "difficulty-report", "evaluation/difficulty-pairing")
        add(study / "difficulty-pairing/config.json", "evaluation/difficulty-pairing/config.json")
        add(study / "crossover-histories.jsonl.gz", "evaluation/crossover-histories.jsonl.gz")
        z.writestr(
            "manifest.json", json.dumps({"format": "mecha-knight-1", "sha256": hashes}, indent=2)
        )


def verify_transfer(root, name):
    registry = read(root / (name + "-seed-lock.json"))
    directory = root / "evaluation" / name
    summary, games = read(directory / "summary.json"), read(directory / "games.json")
    config = read(directory / "config.json")
    if summary["registry_sha256"] != config["seed_lock"] or config["seed_lock"] != sha(
        (root / (name + "-seed-lock.json")).read_bytes()
    ):
        raise ValueError("A7 seed receipt changed")
    if config["bundle"] != registry["policy_sha256"] or config["bundle"] != sha(
        (root / "models/incumbent/policy.json").read_bytes()
    ):
        raise ValueError("A7 model receipt changed")
    seeds = registry["seeds"]["test"]
    with gzip.open(directory / "histories.jsonl.gz", "rt", encoding="utf-8") as f:
        for index, (seed, game, line) in enumerate(zip(seeds, games, f, strict=True)):
            row = json.loads(line)
            if (
                game["index"] != index
                or game["seed"] != seed
                or game["terminal"] != row["expected_digest"]
                or row["spec"]
                != {"seed": seed, "act_list": "seeded", "ascension": registry["ascension"]}
                or any(a.get("cmd") != "action" for a in row["history"])
            ):
                raise ValueError("Invalid A7 physical history")
    stats = {
        "lobbies": len(games),
        "native_terminal_replays": len(games),
        "act2_entries": sum(r["a1_clear"] for r in games),
        "act3_entries": sum(r["a2_clear"] for r in games),
        "act3_bosses_reached": sum(any(a == 3 for a, f in r["boss_fights"]) for r in games),
        "wins": sum(r["win"] for r in games),
    }
    if any(summary[k] != v for k, v in stats.items()) or summary["win_seeds"] != [
        r["seed"] for r in games if r["win"]
    ]:
        raise ValueError("A7 summary disagrees with completed games")
    return stats


def verify_finalist(root, name):
    folder = root / "evaluation" / name
    baseline = read(folder / "games.json")
    comp = folder / "finalist"
    pairs = read(comp / "pairs.json")
    expected = {g["seed"] for g in baseline if g["a2_clear"]}
    if {p["seed"] for p in pairs if p["origin_map"]} != expected or len(pairs) != len(
        expected
    ) + 16:
        raise ValueError("A7 finalist audit omitted an entrant or spot check")
    with gzip.open(comp / "changed-histories.jsonl.gz", "rt", encoding="utf-8") as stream:
        changed = {r["spec"]["seed"]: r for line in stream if (r := json.loads(line))}
    indexed = {p["seed"]: p for p in pairs}
    if set(changed) != {p["seed"] for p in pairs if p["first_difference"]}:
        raise ValueError("A7 changed-history set differs from the verified comparisons")
    with gzip.open(folder / "histories.jsonl.gz", "rt", encoding="utf-8") as stream:
        for game, line in zip(baseline, stream, strict=True):
            pair = indexed.get(game["seed"])
            if pair is None:
                continue
            physical = json.loads(line)
            for k, path in enumerate((physical, changed.get(game["seed"], physical))):
                if (
                    digest([path["spec"], path["history"], path["expected_digest"]])
                    != pair["terminal_replays"][k]["history"]
                ):
                    raise ValueError("A7 comparison differs from its verified physical path")
    summary = read(comp / "summary.json")
    reference = runpy.run_path(str(ROOT / "scripts/measure-act3-encounters.py"))["summarize"](
        baseline, pairs
    )
    if any(summary[k] != v for k, v in reference.items()):
        raise ValueError("A7 finalist summary mismatch")
    return {arm: summary[arm] for arm in ("incumbent", "challenger")}


def verify(archive, repeat=False, host=None):
    with TemporaryDirectory() as tmp, zipfile.ZipFile(archive) as z:
        root = Path(tmp)
        names = z.namelist()
        manifest = json.loads(z.read("manifest.json"))
        if (
            manifest["format"] != "mecha-knight-1"
            or len(names) != len(set(names))
            or set(names) != (set(manifest["sha256"]) | {"manifest.json"})
        ):
            raise ValueError("Archive inventory mismatch")
        for name, h in manifest["sha256"].items():
            f = PurePosixPath(name)
            if (
                f.is_absolute()
                or ".." in f.parts
                or "\\" in name
                or ":" in name
                or sha(z.read(name)) != h
            ):
                raise ValueError("Invalid archive entry " + name)
        z.extractall(root)
        selection = read(root / "selection.json")
        for name in ("incumbent", "challenger"):
            p = root / "models" / name / "policy.json"
            load_bundle(p)
            if sha(p.read_bytes()) != selection[name + "_sha256"]:
                raise ValueError("Frozen model mismatch")
        results = {
            c: verify_games(root, c, c + "-seed-lock.json", ("challenger",))
            for c in ("main", "replication")
        }
        transfer = {
            c: verify_transfer(root, c) for c in ("a7", "a7-replication", "difficulty-pairing")
        }
        for c in ("a7", "a7-replication"):
            verify_finalist(root, c)
        if (
            read(root / "a7-seed-lock.json")["seeds"]["test"]
            != read(root / "difficulty-pairing-seed-lock.json")["seeds"]["test"]
        ):
            raise ValueError("A7/A10 crossover inventories differ")
        fit_delta = None
        if repeat:
            args = [
                "fit",
                "--labels",
                root / "training/action-labels",
                "--cases",
                root / "training/screen-cases",
                "--bundle",
                root / "models/incumbent/policy.json",
                "--output",
                root / "refit",
            ]
            subprocess.run(
                [sys.executable, str(ROOT / "scripts/train-mecha-actions.py"), *map(str, args)],
                check=True,
            )
            old, new = (
                read(root / path / "encounter.json")["mecha_knight"]["ranker"]
                for path in ("training/ranked", "refit")
            )
            a, b = old.pop("weights"), new.pop("weights")
            if (
                old != new
                or a.keys() != b.keys()
                or any(not math.isclose(a[k], b[k], rel_tol=1e-9, abs_tol=1e-9) for k in a)
            ):
                raise ValueError("Ranked model refit changed")
            fit_delta = max(abs(a[k] - b[k]) for k in a)
        sample = native_sample(root, host, "main", "challenger") if host else None
    print(
        json.dumps(
            {
                "files": len(names),
                "archive_sha256": sha(archive.read_bytes()),
                "a10": results,
                "a7": transfer,
                "refit_max_error": fit_delta,
                "native_sample": sample,
            }
        )
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=("build", "verify"))
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--study", type=Path)
    p.add_argument(
        "--histories",
        type=Path,
        help="Previously packed cohort histories, checked against independent replay receipts during verification",
    )
    p.add_argument("--refit", action="store_true")
    p.add_argument("--host", type=Path)
    a = p.parse_args()
    if a.mode == "build":
        if a.study is None:
            p.error("build requires --study")
        build(a.study, a.archive, a.histories)
    verify(a.archive, a.refit, a.host)


if __name__ == "__main__":
    main()
