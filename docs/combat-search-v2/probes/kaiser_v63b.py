"""Paired Kaiser v63/v63b evaluation on the historical entrants or locked CSV8DEV."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import gzip
import hashlib
import json
import os
from pathlib import Path
import runpy
import zipfile

from kaiser import DOC, ROOT, episode, locked
from sts2rl.run_bundle import load_bundle

LOCK_SHA = "84fe749806766c98e525e695f7f421f01697cfb99024bd8eaff8cfa04f9f969e"


def archived_entries():
    with zipfile.ZipFile(DOC / "kaiser-conversion-receipts.zip") as z:
        rows = (json.loads(line) for panel in ("audit", "dev") for line in
                gzip.decompress(z.read(f"{panel}/treatment.jsonl.gz")).splitlines())
        return {r["seed"]: r for r in rows if r["opening"]}


def cohort(panel):
    if panel == "diagnostic":
        entries = archived_entries()
        audit = locked("audit")
        dev = [row for row in locked("dev") if row[1] in entries]
        assert len(audit) == 45 and len(dev) == 40 and len(entries) == 85
        return audit + dev
    data = (DOC / "csv8dev-lock.json").read_bytes()
    assert hashlib.sha256(data).hexdigest() == LOCK_SHA
    rows = json.loads(data)
    assert rows == [[i, f"CSV8DEV_{mode.upper()}_{i:04d}", mode] for i in range(192)
                    for mode in ("default", "seeded")]
    return rows


def metrics(view, action, facing, eligible, fallback, counts):
    live = {e["index"]: e for e in view["enemies"] if e["hp"] > 0}
    if eligible and fallback and action.kind == "play_card" and len(live) == 2:
        target = live.get(action.args.get("target_index"))
        card = next(c for c in view["hand"] if c["index"] == action.args["card_index"])
        if target and card["type"] == "Attack":
            counts["fallback_attack_" + target["id"][8:]] += 1
    rocket = next((e for e in live.values() if e["id"] == "MONSTER.ROCKET"), None)
    if action.kind != "end_turn" or not rocket:
        return
    phase = (view["round"] - 1) % 5
    if phase not in (1, 3) or not any("damage" in i for i in rocket["intents"]):
        return
    counts["rocket_big_intents"] += 1
    counts["rocket_big_weak"] += any(p["id"] == "POWER.WEAK_POWER" and p["amount"] > 0
                                      for p in rocket["powers"])
    if len(live) == 2:
        assert facing in live, (view["round"], facing)
        counts["two_arm_big"] += 1
        counts["two_arm_big_faced"] += facing == rocket["index"]
    else:
        counts["solo_big"] += 1


def run_pair(job):
    bundle, out, triple = job
    arms = ("v63", "v63b") if triple[0] % 2 == 0 else ("v63b", "v63")
    for arm in arms:
        row = episode((bundle, out / arm, triple, False, "treatment"), kaiser_metrics=metrics)
        if row[1] != "complete" or row[2]:
            raise RuntimeError(row)
    return triple[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("panel", choices=("diagnostic", "dev"))
    p.add_argument("out", type=Path)
    p.add_argument("--workers", type=int, choices=[12], required=True)
    args = p.parse_args()
    protocol = runpy.run_path(str(ROOT / "scripts/verify-silent-v6.py"))
    assert protocol["sha"](Path(os.environ["CSV2DEV_HOST"]).read_bytes()) == protocol["HOST_SHA"]
    assert protocol["sha"]((ROOT / "artifacts/upstreams/sts2-cli/lib/sts2.dll").read_bytes()) == protocol["GAME_SHA"]
    assert not os.getenv("DOTNET_STARTUP_HOOKS") and all(
        os.getenv(k) == "1" for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS"))
    out = args.out.resolve()
    rows = cohort(args.panel)
    assert len(rows) == len({r[1] for r in rows})
    out.mkdir(parents=True, exist_ok=False)
    build = runpy.run_path(str(ROOT / "scripts/build-batch1-challengers.py"))["build_batch1_bundle"]
    bundle = build(ROOT / "releases/silent-a10-mecha-knight/challenger/policy.json",
                   out / "arm4", profile="all_v2_search_v6")
    assert protocol["sha"](bundle.read_bytes()) == protocol["PINS"]["v6"]
    config = json.loads(Path(load_bundle(bundle)[1]["combat_search_v2_config"]).read_bytes())
    for arm in ("v63", "v63b"):
        (out / arm).mkdir()
        switches = {"kaiser_v63": True}
        if arm == "v63b":
            switches["kaiser_v63b"] = True
        (out / arm / "kaiser_config.json").write_text(json.dumps({**config, **switches}))
    with ProcessPoolExecutor(args.workers) as pool:
        jobs = [pool.submit(run_pair, (bundle, out, t)) for t in rows]
        for job in as_completed(jobs):
            print(job.result(), flush=True)


if __name__ == "__main__":
    main()
