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


def boss_study_stamp(bundle, host, collector):
    modules = ("act2_action_ranker", "act2_bosses", "act2_hallways", "card_effects", "combat_effects",
               "combat_outcome", "deck_policy", "encounter", "enemy_forecast", "native",
               "run_policy", "sandpit", "selections", "teacher", "turn_planning")
    return {"schema": "native-act2-boss-continuation-v1", "actor_code_sha256": _source_hash(modules),
            "bundle_sha256": hashlib.sha256(Path(bundle).read_bytes()).hexdigest(),
            "native_host_sha256": hashlib.sha256(Path(host).read_bytes()).hexdigest(),
            "collector_sha256": hashlib.sha256(Path(collector).read_text(encoding="utf-8").encode()).hexdigest()}


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


HEADLESS_PATCHES = (
    "scripts/headless-runtime-identity.patch",
    "scripts/headless-public-observation.patch",
    "scripts/headless-training.patch",
    "scripts/headless-a10-run.patch",
    "scripts/headless-combat-completion.patch",
    "scripts/headless-public-shop-and-events.patch",
    "scripts/headless-selection-race.patch",
    "scripts/headless-seeded-acts.patch",
    "scripts/headless-gardener-math.patch",
    "scripts/headless-confirm-async-end.patch",
    "scripts/headless-knowledge-choice.patch",
)


def headless_patch_digest(root=None, *, host_path=None):
    """Canonical ordered digest of the native patch chain, helper C# files, and optional host DLL."""
    repo_root = Path(root).resolve() if root is not None else Path(__file__).resolve().parents[2]
    entries = []
    for rel in HEADLESS_PATCHES:
        path = repo_root / rel
        if not path.is_file():
            raise FileNotFoundError(f"Missing pinned headless patch: {path}")
        normalized = path.read_text(encoding="utf-8").encode("utf-8")
        entries.append([rel, hashlib.sha256(normalized).hexdigest()])
    helpers_dir = repo_root / "scripts/headless"
    if helpers_dir.is_dir():
        for helper in sorted(helpers_dir.glob("*.cs")):
            rel = helper.relative_to(repo_root).as_posix()
            normalized = helper.read_text(encoding="utf-8").encode("utf-8")
            entries.append([rel, hashlib.sha256(normalized).hexdigest()])
    patch_sha = _digest(entries)
    result = {"schema": "headless-patch-chain-v1", "entries": entries, "patch_chain_sha256": patch_sha}
    if host_path is not None:
        result["host_dll_sha256"] = hashlib.sha256(Path(host_path).read_bytes()).hexdigest()
    return result


def strategy_label_provenance(
    bundle_path,
    *,
    continuation="legacy",
    host_path=None,
    root=None,
    collector=None,
    style=None,
    room_model=None,
    unified_draft=False,
    deck_size_penalty=0.12,
    horizon="act",
):
    """Provenance stamp binding macro strategy labels to their continuation bundle and patch chain."""
    bundle_path = Path(bundle_path).resolve()
    bundle_data = json.loads(bundle_path.read_text(encoding="utf-8"))
    modules = (
        "deck_policy",
        "deployed_controller",
        "encounter",
        "merchant",
        "offer_policy",
        "routing",
        "run_policy",
        "selections",
        "strategy",
        "survival_route",
        "turn_planning",
    )
    stamp = {
        "schema": "strategy-continuation-v1",
        "continuation": continuation,
        "code_sha256": _source_hash(modules),
        "bundle_sha256": hashlib.sha256(bundle_path.read_bytes()).hexdigest(),
        "bundle_files": bundle_data.get("files", {}),
        "style": style,
        "room_model_sha256": (
            hashlib.sha256(Path(room_model).read_bytes()).hexdigest()
            if room_model is not None
            else None
        ),
        "unified_draft": bool(unified_draft),
        "deck_size_penalty": float(deck_size_penalty),
    }
    if horizon != "act":
        stamp["horizon"] = horizon
    if collector is not None:
        stamp["collector_sha256"] = hashlib.sha256(
            Path(collector).read_text(encoding="utf-8").encode("utf-8")
        ).hexdigest()
    if host_path is not None or root is not None:
        patch_info = headless_patch_digest(root, host_path=host_path)
        stamp["patch_chain_sha256"] = patch_info["patch_chain_sha256"]
        if "host_dll_sha256" in patch_info:
            stamp["host_dll_sha256"] = patch_info["host_dll_sha256"]
    return stamp
