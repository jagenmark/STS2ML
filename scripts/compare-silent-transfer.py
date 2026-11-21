"""Compare an A10-selected Mecha-only challenger on the registered A7 transfer lobbies."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import gzip
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys

from sts2rl.act1 import save_json
from sts2rl.run_evaluation import act_start

ROOT = Path(__file__).resolve().parents[1]
audit = runpy.run_path(str(ROOT / "scripts/measure-act3-encounters.py"))


def compare_one(task):
    return audit["check"](task)


def run(a):
    seed_lock = json.loads(a.seed_lock.read_bytes())
    rows = json.loads((a.verified / "games.json").read_bytes())
    config = json.loads((a.baseline.parent / "config.json").read_bytes())
    if (
        config["ascension"] != 7
        or config["seed_lock"] != hashlib.sha256(a.seed_lock.read_bytes()).hexdigest()
        or [r["seed"] for r in rows] != seed_lock["seeds"]["test"]
    ):
        raise ValueError("Unverified or mismatched A7 benchmark")
    starts = [r for r in rows if r["a2_clear"]]
    spots = sorted(
        (r for r in rows if not r["a2_clear"]),
        key=lambda r: hashlib.sha256(("mecha-a7-prefix-v1/" + r["seed"]).encode()).digest(),
    )[:16]
    entries = []
    for row in sorted(starts + spots, key=lambda r: r["index"]):
        folder = a.baseline / f"run-{row['index']:04d}"
        root = act_start(folder / "game/rpc.jsonl", 3).expected_digest if row["a2_clear"] else None
        entries.append(
            {
                "index": row["index"],
                "seed": row["seed"],
                "act_list": "seeded",
                "ascension": 7,
                "map_digest": root,
            }
        )
    a.output.mkdir(parents=True, exist_ok=False)
    save_json(a.output / "entries.json", entries)
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/play-silent-lobbies.py"),
            "--entries",
            str(a.output / "entries.json"),
            "--bundle",
            str(a.bundle),
            "--host",
            str(a.host),
            "--workers",
            str(a.workers),
            "--output",
            str(a.output / "played"),
        ],
        check=True,
    )
    jobs = [
        (
            a.baseline / f"run-{e['index']:04d}",
            a.output / "played" / e["seed"],
            a.verify_host.resolve(),
            e,
            "mecha",
        )
        for e in entries
    ]
    with ProcessPoolExecutor(a.workers) as pool:
        pairs = list(pool.map(compare_one, jobs))
    summary = audit["summarize"](rows, pairs)
    summary.update(
        ascension=7,
        full_lobby_replays=len(entries),
        nonentrant_spot_checks=len(spots),
        bundle_sha256=hashlib.sha256(a.bundle.read_bytes()).hexdigest(),
        win_seeds=[r["seed"] for r in pairs if r["challenger"]["win"]],
    )
    save_json(a.output / "pairs.json", pairs)
    save_json(a.output / "summary.json", summary)
    with gzip.open(a.output / "changed-histories.jsonl.gz", "wt", encoding="utf-8") as stream:
        for row in pairs:
            if row["first_difference"] is not None:
                spec, actions, hashes = audit["physical"](a.output / "played" / row["seed"], 7)
                stream.write(
                    json.dumps(
                        {"spec": spec, "history": actions, "expected_digest": hashes[-1]},
                        separators=(",", ":"),
                    )
                    + "\n"
                )
    print(json.dumps(summary))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for k in ("seed-lock", "verified", "baseline", "bundle", "host", "verify-host", "output"):
        p.add_argument("--" + k, type=Path, required=True)
    p.add_argument("--workers", type=int, default=3)
    run(p.parse_args())


if __name__ == "__main__":
    main()
