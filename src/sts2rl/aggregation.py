"""Audited training-only aggregation; evaluation folders never become labels."""
import hashlib
import json
from pathlib import Path

from .native import digest


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def aggregate_source(experiment, config):
    experiment = Path(experiment).resolve()
    source = read_json(experiment / "config.json")
    status = read_json(experiment / "status.json")
    report = read_json(experiment / "model/report.json")
    if status["stage"] != "complete":
        raise ValueError("Aggregation requires a completed source experiment")
    for key in ("sampler", "ascension", "macro_sha256"):
        if source.get(key) != config.get(key):
            raise ValueError("Aggregation source mismatch: " + key)
    game_key = "artifacts/upstreams/sts2-cli/lib/sts2.dll"
    def game_hash(c):
        return {k.replace("\\", "/"): v for k, v in c["runtime_sha256"].items()}[game_key]
    if game_hash(source) != game_hash(config):
        raise ValueError("Aggregation source game assembly mismatch")
    # Include only the original collection. Neither online evaluation labels nor
    # quarantined attempts nor earlier ancestor copies are picked up by this glob.
    paths, rows = [], []
    for index in range(source["runs"]):
        folder = experiment / f"run-{index:05d}"
        result = read_json(folder / "result.json")
        group = digest(f"{source['prefix']}{index:06d}")
        if result.get("status") != "complete" or result.get("group") != group or result.get("index") != index:
            raise ValueError("Aggregation source has incomplete/mismatched episodes")
        path = folder / "teacher.jsonl"
        part = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        if any(r.get("group") != group or r.get("sampler") != config["sampler"] or r.get("ascension") != config["ascension"] for r in part):
            raise ValueError("Aggregation rows disagree with their episode/profile")
        paths.append(path)
        rows.extend(part)
    if digest(rows) != report["dataset_sha256"]:
        raise ValueError("Source dataset differs from its fitted dataset; aggregate ancestors explicitly first")
    if set(report["split"]) != {r["group"] for r in rows}:
        raise ValueError("Source split does not match its labeled seed groups")
    new_groups = {digest(f"{config['prefix']}{i:06d}") for i in range(config["runs"])}
    old_groups = {digest(f"{source['prefix']}{i:06d}") for i in range(source["runs"])}
    old_eval = {digest(f"{source['prefix']}EVAL{i:06d}") for i in range(source.get("evaluate", 0))}
    if new_groups & (old_groups | old_eval):
        raise ValueError("New collection seeds overlap source collection/evaluation seeds")
    new_eval = {digest(f"{config['prefix']}EVAL{i:06d}") for i in range(config.get("evaluate", 0))}
    if new_eval & (old_groups | old_eval | new_groups):
        raise ValueError("New evaluation seeds overlap previously used seeds")
    manifest = {"experiment": str(experiment), "dataset_sha256": digest(rows),
                "split": report["split"], "decisions": len(rows),
                "files": {str(p.relative_to(experiment)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
    return paths, report["split"], manifest
