"""Strict JSONL I/O and deterministic connected run/seed split groups."""

from __future__ import annotations

from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path

from .schema import SchemaError, validate_record


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def deduplicate_records(records: list[dict]) -> list[dict]:
    unique = {}
    for record in records:
        key = (record["run_id"], record["decision_id"])
        if key in unique and canonical_json(unique[key]) != canonical_json(record):
            raise SchemaError(f"conflicting duplicate decision {key}")
        unique.setdefault(key, record)
    return list(unique.values())


def load_records(path: str | Path) -> list[dict]:
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    records, seen = [], {}
    with opener(path, "rt", encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                record = validate_record(json.loads(line))
                key = (record["run_id"], record["decision_id"])
                if key in seen:
                    if canonical_json(record) != seen[key]:
                        raise SchemaError("conflicting duplicate run_id/decision_id")
                    continue
                seen[key] = canonical_json(record)
                records.append(record)
            except (ValueError, TypeError) as error:
                raise SchemaError(f"{path.name}:{line_no}: {error}") from error
    if not records:
        raise SchemaError(f"no decision records in {path}")
    return records


def write_records(path: str | Path, records: list[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "wt", encoding="utf-8") as stream:
        for record in records:
            validate_record(record)
            stream.write(canonical_json(record) + "\n")


def dataset_digest(records: list[dict]) -> str:
    digest = hashlib.sha256()
    for record in sorted(records, key=lambda r: (r["run_id"], r["decision_id"])):
        digest.update(canonical_json(record).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def validate_dataset(records: list[dict]) -> None:
    """Reject contradictions within runs, including duplicates supplied in memory."""
    outcomes, run_context, decisions = {}, {}, {}
    for record in records:
        validate_record(record)
        run_id = record["run_id"]
        context = (
            record["game_version"],
            record["observation"]["character"],
            record["observation"]["ascension"],
        )
        if run_id in run_context and run_context[run_id] != context:
            raise SchemaError(f"conflicting character/version/ascension within run {run_id}")
        run_context[run_id] = context
        outcome = record.get("outcome")
        if outcome is not None:
            if run_id in outcomes and outcomes[run_id] != outcome:
                raise SchemaError(f"conflicting outcome labels within run {run_id}")
            outcomes[run_id] = outcome
        key = (run_id, record["decision_id"])
        if key in decisions:
            raise SchemaError(f"duplicate decision {key}; deduplicate through load_records first")
        decisions[key] = True


def grouped_split(
    records: list[dict],
    *,
    seed: int = 42,
    validation_fraction: float = 0.15,
    test_fraction: float = 0.15,
) -> tuple[dict[str, list[dict]], dict]:
    """Connect shared run IDs AND shared seed groups, then hash each component.

    Group assignment is independent of row order. It is not stratified, and
    fractions are approximate at group level. Never split decisions randomly.
    Adding a bridge between two previously separate components legitimately
    changes their partition; retain the produced manifest for reproducibility.
    """
    if not (
        0 < validation_fraction < 1
        and 0 < test_fraction < 1
        and validation_fraction + test_fraction < 1
    ):
        raise ValueError("validation/test fractions must be positive and sum to less than 1")
    parent: dict[str, str] = {}

    def find(key: str) -> str:
        parent.setdefault(key, key)
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(a: str, b: str) -> None:
        a, b = find(a), find(b)
        if a != b:
            parent[max(a, b)] = min(a, b)

    for record in records:
        union("run:" + record["run_id"], "group:" + record["split_group"])
    assignments = {}
    partitions = {"train": [], "validation": [], "test": []}
    for record in records:
        key = find("run:" + record["run_id"])
        if key not in assignments:
            value = int.from_bytes(hashlib.sha256(f"{seed}:{key}".encode()).digest()[:8]) / 2**64
            assignments[key] = (
                "test"
                if value < test_fraction
                else "validation"
                if value < test_fraction + validation_fraction
                else "train"
            )
        partitions[assignments[key]].append(record)
    manifest = {
        "method": "sha256-connected-run-and-seed-groups-v1",
        "seed": seed,
        "validation_fraction": validation_fraction,
        "test_fraction": test_fraction,
        "dataset_sha256": dataset_digest(records),
        "assignments": dict(sorted(assignments.items())),
        "counts": {name: len(rows) for name, rows in partitions.items()},
        "group_counts": dict(Counter(assignments.values())),
    }
    return partitions, manifest


def audit_records(records: list[dict]) -> dict:
    return {
        "decisions": len(records),
        "runs": len({r["run_id"] for r in records}),
        "split_groups": len({r["split_group"] for r in records}),
        "policy_labels": sum(r.get("chosen_action_id") is not None for r in records),
        "value_labels": sum(r.get("outcome") is not None for r in records),
        "versions": dict(Counter(r["game_version"] for r in records)),
        "characters": dict(Counter(r["observation"]["character"] for r in records)),
        "state_quality": dict(Counter(r["observation"]["state_quality"] for r in records)),
        "sources": dict(Counter(r["source"] for r in records)),
        "decision_types": dict(Counter(r["observation"]["decision_type"] for r in records)),
        "dataset_sha256": dataset_digest(records),
    }
