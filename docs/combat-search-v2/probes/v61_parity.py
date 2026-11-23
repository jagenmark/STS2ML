"""Compare complete frozen-v5 physical transcripts across two PYTHONPATHs."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from sts2rl.run_bundle import load_bundle
from sts2rl.run_evaluation import play_episode
from sts2rl.run_policy import RunWeights

ROOT = Path(__file__).resolve().parents[3]
POLICY = ROOT / "releases/silent-a10-v2-tactics/challenger/policy.json"


def episode(job):
    seed, mode, index = job
    role, settings = load_bundle(POLICY)
    actions = hashlib.sha256()

    def observe(public, action):
        actions.update(json.dumps([action.snapshot, action.command()], sort_keys=True, separators=(",", ":")).encode())
        return action

    with TemporaryDirectory() as tmp:
        folder = Path(tmp) / "episode"
        row = play_episode((ROOT, Path(os.environ["CSV2DEV_HOST"]), folder, seed, index, role,
                            asdict(RunWeights.load(settings["weights"])), None,
                            {**settings, "seeded_acts": mode == "seeded", "compact_combat_summary": True}),
                           decision_hook=observe)
        if row["status"] != "complete" or row.get("abandoned"):
            raise ValueError(row)
        rpc = hashlib.sha256()
        trace, = folder.rglob("rpc.jsonl")
        with trace.open(encoding="utf8") as stream:
            for line in stream:
                entry = json.loads(line)
                rpc.update(json.dumps([entry["command"], entry["response_digest"]], sort_keys=True).encode())
        return [seed, row["steps"], row["act"], row["floor"], row["win"], actions.hexdigest(), rpc.hexdigest()]


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("output", type=Path)
    args = p.parse_args()
    panel = json.loads((ROOT / "docs/combat-search-v2/v61-cohorts.json").read_bytes())["CENSUS"]
    jobs = [(seed, mode, i) for i, seed, mode in panel if i < 6]
    with ProcessPoolExecutor(12) as pool:
        rows = list(pool.map(episode, jobs))
    args.output.write_bytes(json.dumps(rows, separators=(",", ":")).encode())
