"""Freeze an Act 3 combat policy with optional learned forecasts and potion timing."""

import argparse
import json
import math
from pathlib import Path

from sts2rl.act1 import save_json
from sts2rl.run_bundle import freeze_bundle, load_bundle


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--intents", type=Path)
    p.add_argument("--forecast-weight", type=float, default=0)
    p.add_argument("--potion-timing", type=float, default=0)
    a = p.parse_args()
    if bool(a.intents) != bool(a.forecast_weight) or not all(
        math.isfinite(v) and v >= 0 for v in (a.forecast_weight, a.potion_timing)
    ):
        p.error(
            "A positive forecast weight requires a fitted table; weights must be finite and nonnegative"
        )
    role, opts = load_bundle(a.base)
    actor = json.loads(opts["encounter_model"].read_bytes())
    if a.intents:
        table = json.loads(a.intents.read_bytes())
        if not table or not all(
            isinstance(k, str) and math.isfinite(v) and v >= 0 for k, v in table.items()
        ):
            p.error("Expected nonnegative public damage estimates")
        actor["act3_intents"] = {"table": table, "weight": a.forecast_weight}
    if a.potion_timing:
        actor["act3_potion_timing"] = a.potion_timing
    a.output.mkdir(parents=True, exist_ok=False)
    save_json(a.output / "encounter.json", actor)
    opts["encounter_model"] = a.output / "encounter.json"
    freeze_bundle({"args": {**opts, "roles": [role]}}, a.output / "policy")


if __name__ == "__main__":
    main()
