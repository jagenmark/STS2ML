"""Summarize paired CSV13DEV results comparing v6.7 A control vs v6.8 Human-ML Draft arms."""

from __future__ import annotations

import argparse
from collections import Counter
import gzip
import json
from pathlib import Path

from report_v64 import paired, summarize
from v68 import ARMS


def load_arm(run: Path, arm: str, rows):
    return [
        json.loads(gzip.decompress((run / arm / (seed + ".json.gz")).read_bytes()))
        for _, seed, _ in rows
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()

    manifest = json.loads((args.run / "manifest.json").read_bytes())
    rows = manifest["cohort"]
    records = {arm: load_arm(args.run, arm, rows) for arm in ARMS}
    summaries = {arm: summarize(records[arm]) for arm in ARMS}

    print(f"=== CSV13DEV PAIRED BENCHMARK (N = {len(rows)} lobbies per arm) ===\n")
    hdr = f"{'Metric':34s} | {'control (v6.7A)':>16s} | {'ml_reward':>16s} | {'ml_full':>16s}"
    print(hdr)
    print("-" * len(hdr))

    def row_line(label, fn):
        vals = [fn(summaries[a]) for a in ARMS]
        print(f"{label:34s} | {vals[0]:>16s} | {vals[1]:>16s} | {vals[2]:>16s}")

    row_line("Mean global floor", lambda s: f"{s['mean_floor']:.3f}")
    row_line("Act 1 clears", lambda s: f"{s['a1_clears']} / {s['n']}")
    row_line("Act 2 clears / entries", lambda s: f"{s['a2_clears']} / {s['a2_entries']}")
    row_line("Act 3 boss entries", lambda s: f"{s['a3_entries']}")
    row_line("Full wins", lambda s: f"{s['wins']}")
    row_line(
        "Matches / 100 combat dec",
        lambda s: f"{100 * s['native']['match'] / s['latency_n']:.2f}",
    )
    row_line("Native mismatches", lambda s: f"{s['native'].get('mismatch', 0)}")
    row_line("Latency p50 / p95 (ms)", lambda s: f"{s['p50_ms']:.1f} / {s['p95_ms']:.1f}")
    for act in (1, 2, 3):

        def _skip_fmt(s, a=act):
            d = s["reward_skip"].get(a)
            if not d or not d["optional"]:
                return "n/a"
            return f"{100 * d['skips'] / d['optional']:.1f}% ({d['skips']}/{d['optional']})"

        row_line(f"Skip rate Act {act}", _skip_fmt)
    for act in (1, 2, 3):

        def _deck_fmt(s, a=act):
            d = s["deck_size"].get(str(a), s["deck_size"].get(a))
            return f"{d['mean']:.1f} (n={d['n']})" if d else "n/a"

        row_line(f"Mean deck size Act {act}", _deck_fmt)
    row_line(
        "Hard-skip voluntary picks",
        lambda s: f"{s['hard_skip_audit']['voluntary']} / {s['hard_skip_audit']['offered']}",
    )
    for boss in ("CRUSHER+ROCKET", "KNOWLEDGE_DEMON", "THE_INSATIABLE"):
        row_line(
            f"Boss {boss}",
            lambda s, b=boss: (
                f"{s['bosses'][b][0]}/{s['bosses'][b][1]}" if b in s["bosses"] else "0/0"
            ),
        )

    print("\n=== PAIRED FLOOR DELTAS vs control (v6.7 A) ===")
    pair_res = {}
    for arm in ("ml_reward", "ml_full"):
        p = paired(records["control"], records[arm])
        pair_res[arm] = p
        print(
            f"  {arm:10s}: delta = {p['delta']:+.3f} floors | 95% CI [{p['ci95'][0]:+.3f}, {p['ci95'][1]:+.3f}] "
            f"| W/L/T = {p['w']}/{p['l']}/{p['t']} | sign_p = {p['sign_p']:.4f}"
        )
    p_fm = paired(records["ml_reward"], records["ml_full"])
    print(
        f"  ml_full vs ml_reward: delta = {p_fm['delta']:+.3f} | 95% CI [{p_fm['ci95'][0]:+.3f}, {p_fm['ci95'][1]:+.3f}] "
        f"| W/L/T = {p_fm['w']}/{p_fm['l']}/{p_fm['t']}"
    )

    print("\n=== CARD REWARD PICK RATES (Top differences vs control) ===")
    c_cr = summaries["control"]["cards"]["card_reward"]
    m_cr = summaries["ml_full"]["cards"]["card_reward"]
    diffs = []
    for cid in set(c_cr) | set(m_cr):
        co = c_cr.get(cid, {}).get("offered", 0)
        mo = m_cr.get(cid, {}).get("offered", 0)
        cp = c_cr.get(cid, {}).get("picked", 0)
        mp = m_cr.get(cid, {}).get("picked", 0)
        if co >= 10 and mo >= 10:
            cr = cp / co
            mr = mp / mo
            diffs.append((mr - cr, cid, cr, cp, co, mr, mp, mo))
    diffs.sort(reverse=True)
    print("  Most INCREASED by ML:")
    for d, cid, cr, cp, co, mr, mp, mo in diffs[:12]:
        print(f"    {cid:20s}: ctrl {100*cr:5.1f}% ({cp:2d}/{co:2d}) -> ml {100*mr:5.1f}% ({mp:2d}/{mo:2d}) [{100*d:+5.1f}pp]")
    print("  Most DECREASED by ML:")
    for d, cid, cr, cp, co, mr, mp, mo in diffs[-12:]:
        print(f"    {cid:20s}: ctrl {100*cr:5.1f}% ({cp:2d}/{co:2d}) -> ml {100*mr:5.1f}% ({mp:2d}/{mo:2d}) [{100*d:+5.1f}pp]")

    # Check trap picks
    traps = ("GRAND_FINALE", "THE_GAMBIT", "PANIC_BUTTON", "CLASH", "NEUROSURGE")
    print("\n=== TRAP PICK AUDIT (card_reward / shop) ===")
    for arm in ARMS:
        cr_map = summaries[arm]["cards"]["card_reward"]
        sh_map = summaries[arm]["cards"].get("shop", {})
        t_str = ", ".join(
            f"{t}:{cr_map.get(t, {}).get('picked', 0)}/{cr_map.get(t, {}).get('offered', 0)}"
            f"(shop {sh_map.get(t, {}).get('picked', 0)}/{sh_map.get(t, {}).get('offered', 0)})"
            for t in traps
            if cr_map.get(t, {}).get("offered", 0) or sh_map.get(t, {}).get("offered", 0)
        )
        print(f"  {arm:10s}: {t_str}")

    # Shop purchase volume check
    print("\n=== SHOP CARD BUYS ===")
    for arm in ARMS:
        sh_map = summaries[arm]["cards"].get("shop", {})
        tot_b = sum(v["picked"] for v in sh_map.values())
        tot_o = sum(v["offered"] for v in sh_map.values())
        top5 = Counter({k: v["picked"] for k, v in sh_map.items() if v["picked"] > 0}).most_common(6)
        print(f"  {arm:10s}: bought {tot_b}/{tot_o} offered cards | top: {top5}")

    if args.json_out:
        payload = {"manifest": manifest, "summaries": summaries, "paired": pair_res}
        args.json_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
