"""Calibrate public beta Silent pick rates against matched, native-training card offers."""

import argparse
import hashlib
from html.parser import HTMLParser
import json
import math
from pathlib import Path
from statistics import fmean

from sts2rl.act1 import save_json
from sts2rl.strategy import StrategyModel

SOURCE = "https://sts2.fun/cards?character=SILENT&patch=beta-v0.111"


class CardTable(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rates = {}
        self.patch = None

    def handle_starttag(self, tag, attrs):
        row = dict(attrs)
        if (
            tag == "option"
            and "selected" in row
            and str(row.get("value", "")).startswith(("beta-", "main-"))
        ):
            self.patch = row["value"]
        if tag != "tr" or row.get("data-cardclass") != "Silent":
            return
        acts = json.loads(row["data-act-data"])
        ascensions = json.loads(row["data-asc-data"])
        if len(acts) != 3 or len(ascensions) != 4:
            raise ValueError("Unexpected act or ascension groups in the source table")
        total, picks = int(row["data-offered"]), int(row["data-picked"])
        if total < 20:
            return
        key = row["data-card"] + ("+" if row["data-upgraded"] == "1" else "")
        overall = (picks + 6) / (total + 24)

        def log_odds(probability):
            return math.log(probability / (1 - probability))

        def shrunk(group):
            return (group["picked"] + 24 * overall) / (group["offered"] + 24)

        # Act and ascension are exposed as separate marginals. Shrink the act adjustment.
        a10 = log_odds(shrunk(ascensions[-1]))
        self.rates[key] = [a10 + 0.65 * (log_odds(shrunk(act)) - log_odds(overall)) for act in acts]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--html", type=Path, required=True)
    p.add_argument("--strategy", required=True, type=Path)
    p.add_argument("--labels", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    html = args.html.read_text(encoding="utf-8")
    table = CardTable()
    table.feed(html)
    if table.patch != "beta-v0.111" or "A10+" not in html or len(table.rates) < 65:
        raise ValueError("Expected the beta v0.111 Silent table with A10 and act splits")
    model = StrategyModel.load(args.strategy)
    groups = {"train": [], "validation": []}
    for f in sorted(args.labels.glob("run-*/labels.json")):
        for row in json.loads(f.read_text())["roots"]:
            if row["kind"] != "card":
                continue
            group = int.from_bytes(hashlib.sha256(row["group"].encode()).digest()[:4], "big") % 5
            arms = []
            for arm in row["arms"]:
                features = arm["features"]
                card = next(
                    (
                        k[5:]
                        for k in features
                        if k.startswith("card:") and k not in ("card:take", "card:skip")
                    ),
                    None,
                )
                observed = table.rates.get(card)
                score = arm["prior"] + model.strength * model.predict(0, features)
                arms.append((score, observed[row["act"] - 1] if observed else None, arm["return"]))
            groups["validation" if group == 0 else "train"].append(arms)

    def gain(offers, weight, reference):
        delta = []
        for arms in offers:
            base = max(arms, key=lambda a: a[0])
            choice = max(
                arms, key=lambda a: a[0] + (weight * (a[1] - reference) if a[1] is not None else 0)
            )
            delta.append(choice[2] - base[2])
        return fmean(delta)

    grid = [
        (weight, math.log(r / (1 - r)))
        for weight in (0, 1, 2.5, 4.0, 6.0)
        for r in (0.18, 0.26, 0.34)
    ]
    fitted = max(grid, key=lambda x: gain(groups["train"], *x) - 0.008 * x[0])
    args.output.mkdir(parents=True, exist_ok=False)
    report = {
        "source": SOURCE,
        "sha256": hashlib.sha256(args.html.read_bytes()).hexdigest(),
        "card_and_upgrade_rows": len(table.rates),
        "matched_native_offers": {k: len(v) for k, v in groups.items()},
        "models": {},
    }
    for name, (weight, reference) in {
        "fitted": fitted,
        "moderate": (2.5, math.log(0.26 / 0.74)),
        "strong": (6.0, math.log(0.26 / 0.74)),
    }.items():
        model.card_offsets = {
            k: [round(weight * (v - reference), 6) for v in by_act]
            for k, by_act in table.rates.items()
        }
        model.save(args.output / f"{name}.json")
        report["models"][name] = {
            "weight": weight,
            "pick_reference": 1 / (1 + math.exp(-reference)),
            "native_return_gain": {
                part: gain(offers, weight, reference) for part, offers in groups.items()
            },
        }
    save_json(args.output / "report.json", report)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
