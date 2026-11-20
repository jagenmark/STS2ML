"""Compare every legal opening play on sampled turns against native continuations."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from sts2rl.act1 import save_json
from sts2rl.act2_action_ranker import action_features
from sts2rl.combat_outcome import outcome
from sts2rl.encounter import EncounterModel
from sts2rl.native import NativeSession, ReplayFork, legal_actions
from sts2rl.run_bundle import load_bundle
from sts2rl.run_policy import RunPolicy, RunWeights

ROOT = Path(__file__).resolve().parents[1]


def label(args):
    path, position, host, config, weights_path, output, receipt = args
    with gzip.open(path, "rt") as stream:
        group = json.load(stream)
    entry = group["starts"][position]
    spec = group["specification"]
    opening = ReplayFork(spec, tuple(group["history"][: entry["step"]]), entry["root"])
    weights = RunWeights.load(weights_path)
    decisions, error = [], None
    snapshots = {}
    try:
        with (
            TemporaryDirectory() as tmp,
            NativeSession(
                ROOT, Path(tmp) / "native", host_path=host, act_list=spec.get("act_list", "default")
            ) as game,
        ):
            state = game.restore(opening)
            actor, macro = EncounterModel(config), RunPolicy(weights)
            plays = 0
            for _ in range(55):
                if not state.get("in_combat") or state["decision"] == "game_over":
                    break
                if state["decision"] == "combat_play":
                    turn = state["round"]
                    if turn > 4:
                        break
                    # The same fixed turn positions sample both full hands and card ordering with Tender.
                    if turn == 2 and "r2" in snapshots:
                        plays += 1
                    slot = "r2-middle" if turn == 2 and plays == 2 else f"r{turn}"
                    if slot not in snapshots and len(legal_actions(state)) >= 3:
                        snapshots[slot] = game.fork()
                state = game.step(actor.choose(state, macro))
            for slot, fork in snapshots.items():
                state = game.restore(fork)
                legal = legal_actions(state)
                actor, macro = EncounterModel(config), RunPolicy(weights)
                original = actor.choose(state, macro)
                priors = actor.actor.combat_scores(state, legal)
                features = action_features(state, legal, priors)
                arms = []
                for i, action in enumerate(legal):
                    restored = game.restore(fork)
                    branch, branch_macro = EncounterModel(config), RunPolicy(weights)
                    branch.choose(restored, branch_macro)
                    result = outcome(game, game.step(action), branch, branch_macro)
                    arms.append(
                        {
                            "id": action.id,
                            "command": action.command(),
                            "features": features[i],
                            "prior": priors[i],
                            "outcome": result,
                        }
                    )
                decisions.append(
                    {
                        "digest": fork.expected_digest,
                        "slot": slot,
                        "baseline": original.id,
                        "arms": arms,
                    }
                )
    except (ValueError, RuntimeError, TimeoutError) as exc:
        error = str(exc)
    save_json(
        output / (entry["root"] + ".json"),
        {
            "seed": group["seed"],
            "formation": entry["formation"],
            "opening": entry["root"],
            "decisions": decisions,
            "error": error,
            "receipt_sha256": receipt,
        },
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for k in ("host", "bundle", "seed-lock", "openings", "output"):
        p.add_argument("--" + k, type=Path, required=True)
    p.add_argument("--formation", default="HUNTER_KILLER")
    p.add_argument("--workers", type=int, default=3)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    _, cfg = load_bundle(a.bundle)
    config = json.loads(cfg["encounter_model"].read_bytes())
    lock = json.loads(a.seed_lock.read_bytes())["seeds"]
    reserved = set(lock["development"]) | set(lock["test"])
    cases = []
    for path in sorted(a.openings.glob("*.json.gz")):
        with gzip.open(path, "rt") as f:
            row = json.load(f)
        if row["seed"] in reserved:
            raise ValueError("Held seed in supervised combat collection")
        entries = [
            (s["root"], i) for i, s in enumerate(row["starts"]) if s["formation"] == a.formation
        ]
        if entries:
            root, pos = min(entries)
            cases.append((root, path, pos))

    def checksum(path):
        return sha256(path.read_bytes()).hexdigest()

    save_json(
        a.output / "receipt.json",
        {
            "host": checksum(a.host),
            "bundle": checksum(a.bundle),
            "seed_lock": checksum(a.seed_lock),
            "roots": [root for root, _, _ in sorted(cases)],
            "formation": a.formation,
            "sources": {
                p.name: checksum(p)
                for p in [Path(__file__), *sorted((ROOT / "src/sts2rl").glob("*.py"))]
            },
        },
    )
    receipt = checksum(a.output / "receipt.json")
    tasks = [
        (p, i, a.host.resolve(), config, cfg["weights"], a.output, receipt)
        for _, p, i in sorted(cases)
    ]
    with ProcessPoolExecutor(a.workers) as pool:
        list(pool.map(label, tasks))


if __name__ == "__main__":
    main()
