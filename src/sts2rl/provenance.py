"""Portable identities for the code and weights that produce training targets and inputs."""
from functools import lru_cache
import gzip
import hashlib
import json
from pathlib import Path


@lru_cache(maxsize=None)
def _source_hash(names):
    root = Path(__file__).resolve().parent
    sources = {}
    for name in names:
        # Universal newlines keep Linux and Windows checkouts compatible.
        sources[name] = (root / (name + ".py")).read_text(encoding="utf-8")
    return _digest(sources)


def _digest(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(payload).hexdigest()


def draft_scorer_hash():
    return _source_hash(("card_effects", "combat_effects", "encounter_draft", "native",
                         "offer_policy", "run_policy", "strategy"))


def mc_provenance(continuation):
    return {"continuation": continuation, "code_sha256": _source_hash(("teacher", "combat_effects", "enemy_forecast", "native")),
            "weights_sha256": None}  # This continuation has no learned checkpoint.


def feature_provenance(weights, *, planner=False):
    modules = ("card_effects", "combat_effects", "enemy_forecast", "native", "run_policy", "tactical_student", "teacher", "turn_planning")
    if not planner:
        modules += ("encounter", "return_policy")
    return {"schema": "turn-planner-v2" if planner else "combat-return-v2",
            "code_sha256": _source_hash(modules), "weights_sha256": _digest(weights.checkpoint())}


def label_provenance(weights, collector, *, outcome_collector=None):
    script = Path(collector).read_text(encoding="utf-8")
    sources = [script, _source_hash(("fight_rollout",))]
    if outcome_collector is not None:
        sources.append(Path(outcome_collector).read_text(encoding="utf-8"))
    return {"features": feature_provenance(weights), "teacher_sha256": _digest(sources)}


def planner_provenance(weights, late, deck_effects):
    return {"features": feature_provenance(weights, planner=True),
            "late_teacher_weights_sha256": _digest(late.checkpoint()) if late else None,
            "teacher_deck_effects": deck_effects}


def require_provenance(record, key, expected):
    if record.get(key) != expected:
        raise ValueError(f"Missing or mismatched {key}. Recollect labels with matching code and weights "
                         "in a fresh directory, or reproduce historical data with its original checkout.")


def read_encounter_runs(folders, collector, weights=None):
    from .run_policy import RunWeights

    stamp = label_provenance(weights, collector) if weights is not None else None
    for folder in folders:
        for path in sorted(folder.glob("run-*/labels.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            if "policy_weights" not in record:
                raise ValueError("Missing encounter outcome weights. Recollect with the current teacher.")
            expected = label_provenance(RunWeights(**record["policy_weights"]), collector)
            if stamp is None:
                stamp = expected
            require_provenance(record, "label_provenance", expected)
            require_provenance(record, "label_provenance", stamp)
            for row in record["roots"]:
                require_provenance(row, "label_provenance", stamp)
            yield path, record["roots"]


def read_labeled_runs(folders, filename, expected):
    for folder in folders:
        for path in sorted(folder.glob("run-*/" + filename)):
            result = path.with_name("result.json")
            if not result.exists():
                continue  # The collector writes its completion record last.
            require_provenance(json.loads(result.read_text(encoding="utf-8")), "label_provenance", expected)
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                for line in stream:
                    row = json.loads(line)
                    require_provenance(row, "label_provenance", expected)
                    yield row
