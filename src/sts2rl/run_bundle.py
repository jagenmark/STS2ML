"""Portable inference parameters for a reproducible Silent A10 evaluation."""
import hashlib
import json
from pathlib import Path

from .run_policy import IDENTITY

MODEL_FILES = ("weights", "room_model", "late_room_model", "offer_model", "late_weights", "tactical_student", "micro")
SWITCHES = ("turn_search", "combat_search", "deck_effects")


def load_bundle(path):
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1 or data.get("runtime_identity") != IDENTITY:
        raise ValueError("Incompatible Silent A10 inference bundle")
    if data.get("actor") not in ("candidate", "hybrid", "student", "micro"):
        raise ValueError("Unknown bundle actor")
    settings = {k: data.get(k, False) for k in SWITCHES}
    if any(type(v) is not bool for v in settings.values()):
        raise ValueError("Invalid inference switches")
    for key, entry in data["files"].items():
        if key not in MODEL_FILES or Path(entry["name"]).name != entry["name"]:
            raise ValueError("Invalid model filename in bundle")
        model_path = path.parent / entry["name"]
        if hashlib.sha256(model_path.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError(f"Checkpoint checksum mismatch for {key}")
        settings[key] = model_path
    if "weights" not in settings:
        raise ValueError("Inference bundle requires run weights")
    return data["actor"], settings
