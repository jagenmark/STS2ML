"""Export the exact portable policy settings from a completed native evaluation."""

import argparse
import json
from pathlib import Path

from sts2rl.run_bundle import freeze_bundle


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", required=True, type=Path, help="The evaluation's config.json")
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    print(freeze_bundle(json.loads(args.run.read_text(encoding="utf-8")), args.output))


if __name__ == "__main__":
    main()
