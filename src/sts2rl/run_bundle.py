"""Portable inference parameters for a reproducible Silent A10 evaluation."""
import hashlib
import json
from pathlib import Path
from shutil import copyfile

from .run_policy import IDENTITY

MODEL_FILES = ("weights", "room_model", "late_room_model", "offer_model", "late_weights", "tactical_student", "micro",
               "strategy_model", "encounter_model", "return_model", "deck_model", "boss_search")
SWITCHES = ("turn_search", "combat_search", "deck_effects")
OPTIONAL_SWITCHES = ("combat_search_deployed", "combat_search_v2", "combat_search_v2_shadow")
OPTIONAL_MODEL_FILES = ("combat_search_v2_config", "combat_value_v2")


def freeze_bundle(manifest, destination):
    """Copy the inference settings of a single-role native run to a portable directory."""
    args = manifest["args"]
    roles = args.get("roles") or []
    if len(roles) != 1 or roles[0] not in ("candidate", "hybrid", "student", "micro") or not args.get("weights"):
        raise ValueError("Freeze a single trained inference role with explicit run weights")
    sources = {k: Path(args[k]).resolve(strict=True) for k in (*MODEL_FILES, *OPTIONAL_MODEL_FILES)
               if args.get(k)}
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    files = {}
    for key, source in sources.items():
        name = key + source.suffix
        target = destination / name
        copyfile(source, target)
        files[key] = {"name": name, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
    policy = {"version": 1, "runtime_identity": IDENTITY, "actor": roles[0], "files": files,
              **{key: args.get(key, False) for key in SWITCHES}}
    for key in OPTIONAL_SWITCHES:
        if args.get(key):
            policy[key] = True
    path = destination / "policy.json"
    path.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8", newline="\n")
    load_bundle(path)
    return path


def load_bundle(path):
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1 or data.get("runtime_identity") != IDENTITY:
        raise ValueError("Incompatible Silent A10 inference bundle")
    if data.get("actor") not in ("candidate", "hybrid", "student", "micro"):
        raise ValueError("Unknown bundle actor")
    settings = {k: data.get(k, False) for k in SWITCHES}
    for key in OPTIONAL_SWITCHES:
        if key in data:
            settings[key] = data[key]
    if any(type(v) is not bool for v in settings.values()):
        raise ValueError("Invalid inference switches")
    for key, entry in data["files"].items():
        if key not in (*MODEL_FILES, *OPTIONAL_MODEL_FILES) or Path(entry["name"]).name != entry["name"]:
            raise ValueError("Invalid model filename in bundle")
        model_path = path.parent / entry["name"]
        if hashlib.sha256(model_path.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError(f"Checkpoint checksum mismatch for {key}")
        if key == "combat_value_v2":
            from .combat_search_v2.artifact import CombatValueModel

            CombatValueModel.load(model_path)
        settings[key] = model_path
    if "weights" not in settings:
        raise ValueError("Inference bundle requires run weights")
    return data["actor"], settings
