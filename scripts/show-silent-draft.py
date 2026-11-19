"""Print draft totals and the largest differences between the top two options."""

import argparse
import gzip
import json
from pathlib import Path


def points(option):
    if "prior_base_parts" in option:
        values = {"base/" + k: v for k, v in option["prior_base_parts"].items()}
    else:
        values = {"prior/base": option["prior_base"]}
    values["card offset"] = option["card_offset"]
    for stage in ("prior", "strategy"):
        for key, term in option[stage + "_terms"].items():
            values[f"{stage}/{key}"] = term["points"]
    return values


def show(row, limit, compare=None):
    ctx = row["context"]
    boss = (ctx.get("boss") or {}).get("name", "?")
    print(f"{row['seed']} | step {row['step']} | {ctx['act_name']} floor {ctx['floor']} | {boss}")
    print(f"{'card':<28}{'prior':>10}{'strategy':>11}{'offset':>10}{'total':>10}")
    options = sorted(row["options"], key=lambda opt: -opt["total"])
    for option in options:
        label = option["card"].removeprefix("CARD.")
        chosen = " *" if option["action"] == row["chosen_action"] else ""
        print(
            f"{label:<28}{option['prior']:>10.3f}{option['strategy']:>11.3f}"
            f"{option['card_offset']:>10.3f}{option['total']:>10.3f}{chosen}"
        )
    selected = options[:2]
    if compare:
        by_name = {o["card"].removeprefix("CARD.").upper(): o for o in options}
        names = [name.upper().removeprefix("CARD.").replace(" ", "_") for name in compare]
        if any(name not in by_name for name in names):
            print("Requested pair does not appear in this offer.")
            return
        selected = [by_name[name] for name in names]
    if len(selected) == 2 and limit:
        winner, runner = (points(opt) for opt in selected)
        keys = sorted(set(winner) | set(runner))
        diffs = [(k, winner.get(k, 0.0) - runner.get(k, 0.0)) for k in keys]
        print(f"{selected[0]['card']} vs {selected[1]['card']}")
        for key, value in sorted(diffs, key=lambda pair: -abs(pair[1]))[:limit]:
            if value:
                print(f"  {value:+.3f}  {key}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path", type=Path, help="An episode's draft-scores.jsonl.gz or one JSON decision"
    )
    parser.add_argument("--step", type=int, help="Only print this zero-based native action step")
    parser.add_argument(
        "--terms", type=int, default=5, help="Maximum number of feature differences to show"
    )
    parser.add_argument(
        "--compare",
        nargs=2,
        metavar=("FIRST", "SECOND"),
        help="Show how individual terms favor FIRST over SECOND, including skip",
    )
    args = parser.parse_args()
    opener = gzip.open if args.path.suffix == ".gz" else open
    found = False
    with opener(args.path, "rt", encoding="utf-8") as stream:
        rows = [json.load(stream)] if args.path.suffix == ".json" else map(json.loads, stream)
        for row in rows:
            if args.step is None or args.step == row["step"]:
                if found:
                    print()
                show(row, args.terms, args.compare)
                found = True
    if not found:
        parser.exit(1, "No matching draft in this file.\n")


if __name__ == "__main__":
    main()
