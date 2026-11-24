"""Recompute metrics and parity checks from the compact v63b receipt archive."""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import zipfile

from kaiser_attack_replay import BoardTranscript
from kaiser_v63b import archived_entries, cohort
from report_kaiser import comparison, summarize


def read_rows(archive, path):
    return [json.loads(line) for line in gzip.decompress(archive.read(path)).splitlines()]


def errors(row):
    return [(step, record["oracle"], record["formation"], record["replay"]["before"], record["replay"]["after"])
            for step, record in row.get("errors", [])]


def measure(rows, witnesses):
    stats = summarize(rows)
    counts = Counter()
    moves = Counter()
    attack_rows = {w["seed"]: w for w in witnesses}
    assert set(attack_rows) == {r["seed"] for r in rows if r["opening"]}
    for r in rows:
        assert r["status"] == "complete" and not r["abandoned"] and not r["error"]
        counts.update(r["kaiser_metrics"])
        if not r["opening"]:
            continue
        w = attack_rows[r["seed"]]
        assert all(r[k] == w[k] for k in ("commands", "public_boards"))
        for e in w["events"]:
            moves[e["move"]] += 1
            counts["big_executed"] += 1
            counts["big_weakened"] += e["weak"]
            counts["big_faced"] += e["facing"] in ("Right", None)
            if e["opening_facing"] is None:
                counts["big_solo_at_opening"] += 1
            else:
                counts["big_two_at_opening"] += 1
                counts["big_preturned"] += e["opening_facing"] == "ROCKET"
    stats["big_faced_pct_all"] = 100 * counts["big_faced"] / counts["big_executed"]
    stats["big_preturned_pct_two_at_opening"] = 100 * counts["big_preturned"] / counts["big_two_at_opening"]
    stats["big_weak_pct_all"] = 100 * counts["big_weakened"] / counts["big_executed"]
    stats["fallback_rocket_pct"] = (100 * counts["fallback_attack_ROCKET"]
                                    / (counts["fallback_attack_CRUSHER"] + counts["fallback_attack_ROCKET"]))
    stats["executed_by_move"] = dict(moves)
    stats["kaiser_actions"] = dict(counts)
    stats["kaiser_mismatches"] = sum(1 for r in rows for _, _, formation, *_ in errors(r)
                                     if set(formation).intersection(("CRUSHER", "ROCKET")))
    stats["mismatch_lobbies"] = {r["seed"]: len(errors(r)) for r in rows if errors(r)}
    return stats


def compile_report(path):
    result = {}
    old = archived_entries()
    with zipfile.ZipFile(path) as archive:
        trial = json.loads(archive.read("trial-boards.json"))
        for panel in ("diagnostic", "dev"):
            expected = {t[1] for t in cohort(panel)}
            witness = read_rows(archive, panel + "/executed.jsonl.gz")
            data = {}
            stats = {}
            for arm in ("v63", "v63b"):
                rows = read_rows(archive, f"{panel}/{arm}.jsonl.gz")
                assert len(rows) == len(expected) and {r["seed"] for r in rows} == expected
                data[arm] = {r["seed"]: r for r in rows}
                stats[arm] = measure(rows, [w for w in witness if w["arm"] == arm])
            paired = comparison(list(data["v63"].values()), list(data["v63b"].values()))
            same = exact_boards = 0
            cosmetic = {}
            for seed in expected:
                a, b = data["v63"][seed], data["v63b"][seed]
                if panel == "diagnostic":
                    assert all(a[k] == old[seed][k] for k in
                               ("commands", "steps", "native", "late_fights", "coverage", "opening"))
                if not a["opening"]:
                    assert all(a[k] == b[k] for k in
                               ("commands", "steps", "act", "floor", "win", "native", "late_fights"))
                    assert errors(a) == errors(b)
                    if a["public_boards"] == b["public_boards"]:
                        exact_boards += 1
                    else:
                        witness = trial[seed]
                        series = BoardTranscript()
                        series.digests = [v.encode() for v in witness["reference_digests"]]
                        series.trial = {int(i): v for i, v in witness["trial"].items()}
                        cosmetic[seed] = {}
                        for arm, r in (("v63", a), ("v63b", b)):
                            found = series.verify(r["public_boards"])
                            assert found["original_entrant_number"] == witness[arm]["original_entrant_number"]
                            cosmetic[seed][arm] = found["original_entrant_number"]
                    same += 1
            paired["identical_non_kaiser_commands_and_outcomes"] = same
            paired["identical_non_kaiser_raw_boards"] = exact_boards
            paired["trial_entrant_number_only"] = cosmetic
            result[panel] = {**stats, "paired": paired}
        for key in ("qualification", "cohort-proof"):
            result[key] = json.loads(archive.read(key + ".json"))
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive", type=Path)
    print(json.dumps(compile_report(p.parse_args().archive), indent=2))
