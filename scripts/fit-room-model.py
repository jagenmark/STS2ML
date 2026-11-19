"""Fit expected room returns using only completed episodes from a training directory."""
import argparse
import json
from pathlib import Path

from sts2rl.routing import RoomModel


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collections", nargs="+", type=Path, help="Training role directories containing run-*/result.json")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    episodes = [json.loads(p.read_text()) for directory in args.collections for p in sorted(directory.glob("run-*/result.json"))]
    if len({e["seed"] for e in episodes}) != len(episodes):
        parser.error("Expected one trajectory per training seed")
    model = RoomModel.fit(episodes)
    model.save(args.output)
    print(json.dumps({"training_seeds": len(episodes),
                      "transitions": sum(len(e["rooms"]) for e in episodes if e["status"] == "complete")}))


if __name__ == "__main__":
    main()
