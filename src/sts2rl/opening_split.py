"""Reproducible train/test seed lists for naturally reached late-act openings."""
import hashlib
import json

from .run_evaluation import act_start


def select_openings(directories, act, act_list, partition, count, lock=None):
    paths = {}
    split = {"version": 1, "act": act, "act_list": act_list, "train": [], "test": []}
    for directory in directories:
        for path in sorted(directory.glob("run-*/result.json")):
            row = json.loads(path.read_text(encoding="utf-8"))
            if (row["ascension"] != 10 or row["status"] != "complete"
                    or not row["a1_clear" if act == 2 else "a2_clear"]):
                continue
            seed = row["seed"]
            trace = path.parent / "game/rpc.jsonl"
            fork = act_start(trace, act)
            if (fork.specification["seed"] != seed or fork.specification["ascension"] != 10
                    or fork.specification.get("act_list", "default") != act_list):
                raise ValueError(f"Opening identity or act-list mismatch for {seed} in {directory}")
            if seed in paths:
                raise ValueError(f"Duplicate curriculum opening seed {seed}")
            paths[seed] = str(trace)
            # Membership depends only on the game seed, including across acts,
            # copied archives, changed prefixes and overlapping subsets.
            hashed = hashlib.sha256(("silent-late-split-v1/" + seed).encode()).digest()
            group = "test" if int.from_bytes(hashed[:8], "big") % 4 == 0 else "train"
            split[group].append({"seed": seed, "opening_sha256": fork.expected_digest})
    for group in ("train", "test"):
        split[group].sort(key=lambda entry: hashlib.sha256(entry["seed"].encode()).digest())
    if lock is not None and json.loads(lock.read_text(encoding="utf-8")) != split:
        raise ValueError("Opening split differs from the locked seeds, partitions or native opening hashes")
    available = split[partition]
    if count > len(available):
        raise ValueError(f"Requested {count} {partition} seeds, but the fixed split contains {len(available)}")
    return [(entry["seed"], paths[entry["seed"]]) for entry in available[:count]], split
