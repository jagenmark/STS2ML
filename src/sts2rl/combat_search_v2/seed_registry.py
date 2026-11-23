"""Locked Phase 2 natural-lobby registry. Rows preserve each mode's macro index."""
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path

LOCK = Path(__file__).resolve().parents[3] / "docs/combat-search-v2/phase2-seed-lock.json"
CONFIRMATION_LOCK = LOCK.with_name("phase2-confirmation-lock.json")
SPLITS = ("train", "dev", "test")
COUNTS = (716, 154, 154)
SALT = "silent-a10-csv2-phase2-natural-v1"


@dataclass(frozen=True, slots=True)
class Lobby:
    seed: str
    index: int
    mode: str
    split: str


def registry():
    rows = []
    for mode, prefix in (("default", "CSV2DATA_DEF_"), ("seeded", "CSV2DATA_SED_")):
        seeds = [f"{prefix}{i:04d}" for i in range(sum(COUNTS))]
        ranked = sorted(seeds, key=lambda seed: hashlib.sha256(f"{SALT}/{seed}".encode()).digest())
        split_by_seed = dict(zip(ranked, (split for split, n in zip(SPLITS, COUNTS) for _ in range(n))))
        rows.extend(Lobby(seed, index, mode, split_by_seed[seed]) for index, seed in enumerate(seeds))
    return rows


def registry_sha256(rows):
    canonical = json.dumps([asdict(row) for row in rows], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def load_registry(path=LOCK):
    rows = registry()
    expected = {"version": 1, "salt": SALT, "count": len(rows),
                "counts_per_mode": dict(zip(SPLITS, COUNTS)), "sha256": registry_sha256(rows)}
    if json.loads(Path(path).read_bytes()) != expected:
        raise ValueError("Phase 2 lobby registry checksum mismatch")
    return rows


def confirmation_registry():
    return [Lobby(f"CSV2DATA_CONFIRM_{tag}_{index:04d}", index, mode, "test")
            for mode, tag in (("default", "DEF"), ("seeded", "SED")) for index in range(154)]


def load_confirmation_registry(path=CONFIRMATION_LOCK):
    rows = confirmation_registry()
    expected = {"version": 1, "count": len(rows), "counts_per_mode": {"test": 154},
                "sha256": registry_sha256(rows)}
    if json.loads(Path(path).read_bytes()) != expected:
        raise ValueError("Phase 2 confirmation registry checksum mismatch")
    if {row.seed for row in rows}.intersection(row.seed for row in load_registry()):
        raise ValueError("Phase 2 confirmation seeds overlap the natural registry")
    return rows
