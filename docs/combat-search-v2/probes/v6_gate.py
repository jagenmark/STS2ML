"""Stream 24 CSV2DEV physical receipts per mode and discard full RPC logs after hashing."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import phase1_gate as gate


def episode(job):
    variant, config, bundle, mode, index = job
    load = gate.load_bundle

    def settings(path):
        role, options = load(path)
        options["combat_search_v2"] = variant == "active" and bundle == gate.BUNDLES[0]
        options["combat_search_v2_shadow"] = variant in ("shadow", "shadow6")
        if variant == "shadow6":
            options["combat_search_v2_config"] = str(config)
        return role, options

    with TemporaryDirectory() as tmp, patch.object(gate, "load_bundle", settings):
        directory = Path(tmp)
        receipt = gate.episode((Path(os.environ["CSV2DEV_HOST"]), directory, bundle, mode,
                                index, False, False, False))
        counts = Counter()
        for path in directory.rglob("combat-search-v2.jsonl"):
            with path.open() as stream:
                next(stream)
                for line in stream:
                    if oracle := json.loads(line).get("oracle"):
                        counts[oracle[1]] += 1
        return receipt, counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("variant", choices=("off", "active", "shadow", "shadow6"))
    parser.add_argument("output", type=Path)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    if args.variant == "shadow6" and not args.config:
        parser.error("shadow6 requires --config pointing to the opt-in search settings")
    jobs = [(args.variant, args.config, bundle, mode, i) for i in range(6)
            for bundle in gate.BUNDLES for mode in ("default", "seeded")]
    with ProcessPoolExecutor(12) as pool:
        rows = list(pool.map(episode, jobs))
    args.output.write_text(json.dumps(rows))
