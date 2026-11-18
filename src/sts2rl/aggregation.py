"""Audited training-only aggregation; evaluation folders never become labels."""
import hashlib
import json
from pathlib import Path

from .native import canonical_json, digest


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _source_chain(experiment):
    chain = []
    seen = set()
    while experiment:
        folder = Path(experiment).resolve()
        if folder in seen:
            raise ValueError("Cycle in aggregate experiment ancestry")
        seen.add(folder)
        source = read_json(folder / "config.json")
        if read_json(folder / "status.json")["stage"] != "complete":
            raise ValueError("Aggregation requires a completed source experiment")
        chain.append((folder, source))
        experiment = source.get("aggregate_from")
    return reversed(chain)


def _game_hash(config):
    hashes = {k.replace("\\", "/"): v for k, v in config["runtime_sha256"].items()}
    return hashes["artifacts/upstreams/sts2-cli/lib/sts2.dll"]


def _episode_groups(config):
    prefix = config["prefix"]
    collection = [digest(f"{prefix}{i:06d}") for i in range(config["runs"])]
    evaluation = {digest(f"{prefix}EVAL{i:06d}") for i in range(config.get("evaluate", 0))}
    return collection, evaluation


def aggregate_source(experiment, config):
    paths = []
    used_groups = set()
    labeled_groups = set()
    manifest = None
    decisions = 0
    # fit_micro fingerprints the JSON array of all rows in training-file order.
    # Keep its running prefix so checking each generation needs only one pass.
    dataset = hashlib.sha256(b"[")
    for folder, source in _source_chain(experiment):
        if source.get("aggregation") != manifest:
            raise ValueError("Aggregate ancestor differs from the recorded source manifest")
        for key in ("sampler", "ascension", "macro_sha256"):
            if source.get(key) != config.get(key):
                raise ValueError("Aggregation source mismatch: " + key)
        if _game_hash(source) != _game_hash(config):
            raise ValueError("Aggregation source game assembly mismatch")

        collection, evaluation = _episode_groups(source)
        if used_groups.intersection(collection) or used_groups.intersection(evaluation):
            raise ValueError("Overlapping collection/evaluation seeds in aggregate ancestry")
        used_groups.update(collection)
        used_groups.update(evaluation)
        files = {}
        for index, group in enumerate(collection):
            run = folder / f"run-{index:05d}"
            result = read_json(run / "result.json")
            if result.get("status") != "complete" or result.get("group") != group or result.get("index") != index:
                raise ValueError("Aggregation source has incomplete/mismatched episodes")
            path = run / "teacher.jsonl"
            file_hash = hashlib.sha256()
            with path.open("rb") as stream:
                for line in stream:
                    file_hash.update(line)
                    row = json.loads(line)
                    if (row.get("group") != group or row.get("sampler") != config["sampler"]
                            or row.get("ascension") != config["ascension"]):
                        raise ValueError("Aggregation rows disagree with their episode/profile")
                    if decisions:
                        dataset.update(b",")
                    dataset.update(canonical_json(row))
                    decisions += 1
                    labeled_groups.add(group)
            files[str(path.relative_to(folder))] = file_hash.hexdigest()
            paths.append(path)

        report = read_json(folder / "model/report.json")
        fitted = dataset.copy()
        fitted.update(b"]")
        if fitted.hexdigest() != report["dataset_sha256"]:
            raise ValueError("Source dataset differs from its fitted dataset")
        split = report["split"]
        if set(split) != labeled_groups or set(split.values()) != {"train", "validation", "test"}:
            raise ValueError("Source split does not match its labeled seed groups or partitions")
        parent = manifest
        manifest = {"experiment": str(folder), "dataset_sha256": fitted.hexdigest(),
                    "split": split, "decisions": decisions, "files": files}
        if parent:
            if any(split[group] != part for group, part in parent["split"].items()):
                raise ValueError("Source moved an inherited seed group between partitions")
            manifest["parent"] = parent

    collection, evaluation = _episode_groups(config)
    if used_groups.intersection(collection):
        raise ValueError("New collection seeds overlap source collection/evaluation seeds")
    if used_groups.intersection(evaluation) or evaluation.intersection(collection):
        raise ValueError("New evaluation seeds overlap previously used seeds")
    return paths, manifest["split"], manifest
