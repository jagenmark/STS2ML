"""Compare every legal opening play on sampled turns against native continuations."""

import argparse
from collections import defaultdict
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
    path, position, host, config, weights_path, output, receipt, act, rounds = args
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
            if state["context"]["act"] != act or state["context"]["room_type"] not in (
                "Monster",
                "Elite",
            ):
                raise ValueError("Incorrect native hallway or elite opening")
            actor, macro = EncounterModel(config), RunPolicy(weights)
            plays = 0
            for _ in range(55):
                if not state.get("in_combat") or state["decision"] == "game_over":
                    break
                if state["decision"] == "combat_play":
                    turn = state["round"]
                    if turn > max(rounds):
                        break
                    # The same fixed turn positions sample both full hands and card ordering with Tender.
                    if turn == 2 and "r2" in snapshots:
                        plays += 1
                    slot = "r2-middle" if turn == 2 and plays == 2 else f"r{turn}"
                    if (
                        turn in rounds
                        and (act == 2 or slot != "r2-middle")
                        and slot not in snapshots
                        and len(legal_actions(state)) >= 3
                    ):
                        snapshots[slot] = game.fork()
                state = game.step(actor.choose(state, macro))
            for slot, fork in snapshots.items():
                state = game.restore(fork)
                legal = legal_actions(state)
                actor, macro = EncounterModel(config), RunPolicy(weights)
                original = actor.choose(state, macro)
                priors = actor.actor.combat_scores(state, legal)
                features = action_features(state, legal, priors, tactical=act == 3)
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
    for k in ("host", "bundle", "seed-lock", "output"):
        p.add_argument("--" + k, type=Path, required=True)
    p.add_argument("--openings", nargs="+", required=True, type=Path)
    p.add_argument("--formation", default="HUNTER_KILLER")
    p.add_argument("--act", type=int, choices=(2, 3), default=2)
    p.add_argument("--rounds", type=int, nargs="+", default=[1, 2, 3, 4])
    p.add_argument("--cap-per-formation", type=int)
    p.add_argument("--workers", type=int, default=3)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    _, cfg = load_bundle(a.bundle)
    config = json.loads(cfg["encounter_model"].read_bytes())
    lock = json.loads(a.seed_lock.read_bytes())["seeds"]
    reserved = set(lock["development"]) | set(lock["test"])
    if not all(1 <= turn <= 4 for turn in a.rounds) or (
        a.cap_per_formation is not None and a.cap_per_formation < 1
    ):
        p.error("Use rounds 1–4 and a positive sample cap")
    grouped = defaultdict(dict)
    for path in sorted(path for folder in a.openings for path in folder.glob("*.json.gz")):
        with gzip.open(path, "rt") as f:
            row = json.load(f)
        if row["seed"] in reserved or row.get("act", 2) != a.act:
            raise ValueError("Held seed in supervised combat collection")
        for i, start in enumerate(row["starts"]):
            form, seed = start["formation"], row["seed"]
            if a.formation != "all" and form != a.formation:
                continue
            choice = (start["root"], path, i)
            if seed not in grouped[form] or choice < grouped[form][seed]:
                grouped[form][seed] = choice
    cases = [
        case for group in grouped.values() for case in sorted(group.values())[: a.cap_per_formation]
    ]
    if not cases:
        raise ValueError("No native openings match the requested formation")

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
            "act": a.act,
            "rounds": sorted(set(a.rounds)),
            "sources": {
                p.name: checksum(p)
                for p in [Path(__file__), *sorted((ROOT / "src/sts2rl").glob("*.py"))]
            },
        },
    )
    receipt = checksum(a.output / "receipt.json")
    tasks = [
        (p, i, a.host.resolve(), config, cfg["weights"], a.output, receipt, a.act, a.rounds)
        for _, p, i in sorted(cases)
    ]
    with ProcessPoolExecutor(a.workers) as pool:
        list(pool.map(label, tasks))


if __name__ == "__main__":
    main()
