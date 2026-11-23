"""Fit expected room returns using only completed episodes from a training directory."""
import argparse
import json
from pathlib import Path

from sts2rl.routing import RoomModel


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collections", nargs="+", type=Path, help="Training role directories containing run-*/result.json")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--survival", action="store_true", help="Fit room mortality, survivor rewards and boss opening values")
    parser.add_argument(
        "--base", type=Path,
        help="Retain a v2 SurvivalRouter's settings while refitting its global statistics",
    )
    args = parser.parse_args()
    if args.base and not args.survival:
        parser.error("--base requires --survival")
    episodes = []
    unconfirmed = 0
    for directory in args.collections:
        for path in sorted(directory.glob("run-*/result.json")):
            row = json.loads(path.read_text(encoding="utf-8"))
            partition = row.get("opening_partition")
            if partition == "test":
                parser.error("Room fitting requires training trajectories; this collection contains held-out opening seeds")
            if args.base and (partition != "train" or row.get("ascension") != 10):
                parser.error("--base requires A10 trajectories explicitly marked as training")
            log = path.parent / "game/engine.log"
            # Early headless builds could issue rewards after failed combat
            # initialization. Exclude the entire affected training trajectory.
            if row["status"] == "complete" and log.exists() and any(
                "Post-combat:" in line and "IsPreFinished=False" in line
                for line in log.read_text(encoding="utf-8", errors="replace").splitlines()
            ):
                row["status"] = "unconfirmed_combat"
            if row["status"] == "unconfirmed_combat":
                unconfirmed += 1
            episodes.append(row)
    if len({e["seed"] for e in episodes}) != len(episodes):
        parser.error("Expected one trajectory per training seed")
    if args.survival:
        from sts2rl.survival_route import SurvivalRouter
        model = SurvivalRouter.fit(episodes, damped_boss_fit=args.base is not None)
        if args.base:
            base = json.loads(args.base.read_text(encoding="utf-8"))
            if (
                base.get("version") != model.data["version"]
                or base.get("runtime_identity") != model.data["runtime_identity"]
            ):
                parser.error("Expected a compatible v2 SurvivalRouter base")
            model = SurvivalRouter.from_data({**base, **model.data})
    else:
        model = RoomModel.fit(episodes)
    model.save(args.output)
    print(json.dumps({"training_seeds": len(episodes), "unconfirmed_episodes_excluded": unconfirmed,
                      "transitions": sum(len(e["rooms"]) for e in episodes if e["status"] == "complete")}))


if __name__ == "__main__":
    main()
