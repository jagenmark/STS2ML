"""Learn a tactical advantage model from paired real fights, grouped by game seed."""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import gzip
import hashlib
import json
from pathlib import Path
from random import Random
from statistics import fmean

import numpy as np

from sts2rl.act1 import save_json
from sts2rl.encounter import EncounterPolicy
from sts2rl.fight_rollout import fight
from sts2rl.native import NativeSession, ReplayFork, legal_actions
from sts2rl.return_policy import shortlist
from sts2rl.provenance import label_provenance, read_labeled_runs
from sts2rl.run_policy import IDENTITY, RunPolicy, RunWeights
from sts2rl.tactical_student import make_network, pack
from sts2rl.trajectory import natural_specification

ROOT = Path(__file__).resolve().parents[1]


def roots_from_trace(path, rng, limit):
    with path.open(encoding="utf-8") as f:
        first = json.loads(next(f))
        spec = natural_specification(first["command"])
        commands, fingerprints = [], [first["response_digest"]]
        act, row = 1, 0
        rooms = defaultdict(list)
        for line in f:
            entry = json.loads(line)
            cmd = entry["command"]
            if cmd["cmd"] == "get_map":
                continue
            if cmd["cmd"] != "action":
                raise ValueError("Unexpected control command in a full run")
            if cmd["action"] == "select_map_node":
                next_row = cmd["args"]["row"]
                if next_row < row:
                    act += 1
                row = next_row
            if cmd["action"] in ("play_card", "use_potion"):
                rooms[(act, row)].append(len(commands))
            commands.append(cmd)
            fingerprints.append(entry["response_digest"])
    # Use the full trace only to locate training decisions. The deployed network receives no trace or seed.
    chosen = []
    for (act, row), steps in rooms.items():
        bias = 3.0 * (act > 1) + 2 * (row >= 15) + rng.random() * 3
        for j, idx in enumerate(rng.sample(steps, min(len(steps), 3))):
            chosen.append((bias - j * 1.8, idx))
    chosen.sort(reverse=True)
    return [ReplayFork(spec, tuple(commands[:i]), fingerprints[i]) for _, i in chosen[: limit * 3]]


def collect(task):
    folder, source, host, weights, limit, index = task
    folder.mkdir(parents=True, exist_ok=False)
    prior, actor = RunPolicy(weights), EncounterPolicy(weights)
    provenance = label_provenance(weights, __file__)
    rows, errors = [], []
    session = None
    forks = roots_from_trace(source / "game/rpc.jsonl", Random(12401 + index), limit)
    try:
        for fork in forks:
            if len(rows) >= limit:
                break
            try:
                if session is None:
                    session = NativeSession(
                        ROOT,
                        folder / f"engine-{len(errors):03d}",
                        host_path=host,
                        ascension=10,
                        timeout=45,
                        act_list=fork.specification.get("act_list", "default"),
                    )
                state = session.restore(fork)
                if state["decision"] != "combat_play" or len(legal_actions(state)) < 3:
                    continue
                actions, choices = shortlist(state, prior, actor)
                if len(actions) < 2:
                    continue
                values, outcomes = [], []
                for j, a in enumerate(actions):
                    if j:
                        session.restore(fork)
                    end = fight(session, state, EncounterPolicy(weights), first=a)
                    outcome = (
                        25 * end["won"]
                        + 0.42 * end["hp"]
                        + 8 * (1 - end["remaining"])
                        + 1.25 * end["potions"]
                    )
                    values.append(round(outcome, 5))
                    outcomes.append(end)
                rows.append(
                    {
                        "seed": fork.specification["seed"],
                        "root": fork.expected_digest,
                        "label_provenance": provenance,
                        "act": state["context"]["act"],
                        "room": state["context"]["room_type"],
                        "choices": choices,
                        "returns": values,
                        "outcomes": outcomes,
                    }
                )
            except Exception as exc:
                errors.append({"root": fork.expected_digest, "message": str(exc)})
                if session is not None:
                    session.close()
                    session = None
    finally:
        if session is not None:
            session.close()
    with gzip.open(folder / "decisions.jsonl.gz", "wt", encoding="utf-8", compresslevel=2) as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    save_json(
        folder / "result.json",
        {"roots": len(rows), "fights": sum(len(r["returns"]) for r in rows), "errors": errors, "label_provenance": provenance},
    )
    return len(rows)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=("collect", "fit"))
    p.add_argument("--source", type=Path, nargs="+", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--host", type=Path)
    p.add_argument("--weights", type=Path, required=True)
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--seeds", type=int, default=180)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--roots", type=int, default=6)
    p.add_argument("--epochs", type=int, default=34)
    p.add_argument("--width", type=int, default=48)
    p.add_argument("--margin", type=float, default=1.0)
    args = p.parse_args()
    weights = RunWeights.load(args.weights)
    provenance = label_provenance(weights, __file__)
    if args.mode == "collect":
        args.output.mkdir(parents=True, exist_ok=False)
        if not args.host:
            p.error("Collection requires a native host")
        dirs = [
            f.parent
            for d in args.source
            for f in sorted(d.glob("run-*/result.json"))
            if (result := json.loads(f.read_text()))["status"] == "complete"
            and result.get("opening_partition") != "test"
        ]
        dirs = dirs[args.offset : args.offset + args.seeds]
        if len(dirs) != args.seeds:
            p.error("Insufficient complete games in source")
        tasks = [
            (args.output / f"run-{i:04d}", d, args.host, weights, args.roots, args.offset + i)
            for i, d in enumerate(dirs)
        ]
        with ProcessPoolExecutor(args.workers) as pool:
            for i, _ in enumerate(pool.map(collect, tasks), 1):
                if i % 10 == 0:
                    print(i, flush=True)
        return
    import torch
    from torch.nn import functional as F

    torch.set_num_threads(1)
    torch.manual_seed(54721)
    rng = Random(742)
    rows = list(read_labeled_runs(args.source, "decisions.jsonl.gz", provenance))
    if not rows or len({(r["seed"], r["root"]) for r in rows}) != len(rows):
        raise ValueError("Expected distinct native fight roots")
    args.output.mkdir(parents=True, exist_ok=False)
    parts = defaultdict(list)
    for r in rows:
        fold = int.from_bytes(hashlib.sha256(r["seed"].encode()).digest()[:4], "big") % 10
        parts["test" if fold == 0 else "val" if fold == 1 else "train"].append(r)
    train = parts["train"]
    vocab = {
        t: i + 1 for i, t in enumerate(sorted({a["token"] for r in train for a in r["choices"]}))
    }
    inputs = len(train[0]["choices"][0]["x"])
    model = make_network(args.width, inputs, len(vocab) + 1)
    opt = torch.optim.AdamW(model.parameters(), lr=0.0016, weight_decay=0.035)

    def batch(rows):
        x, t, m = pack(rows, vocab)
        y = torch.zeros_like(m, dtype=torch.float32)
        for i, r in enumerate(rows):
            v = np.array(r["returns"])
            y[i, : len(v)] = torch.tensor(np.clip(v - v.mean(), -16.0, 16.0), dtype=torch.float32)
        return x, t, m, y

    def pair_loss(pred, targets, mask):
        differences = targets.unsqueeze(2) - targets.unsqueeze(1)
        comparable = mask.unsqueeze(2) & mask.unsqueeze(1) & (differences > .40)
        if not comparable.any():
            return None
        logits = pred.unsqueeze(2) - pred.unsqueeze(1)
        weights = differences[comparable].clamp(max=8.).sqrt()
        return (F.softplus(-logits[comparable]) * weights).sum() / weights.sum()

    def metrics(rows):
        total = []
        comparisons = []
        gains = []
        changed = 0
        for start in range(0, len(rows), 64):
            subset = rows[start : start + 64]
            x, t, m, y = batch(subset)
            with torch.inference_mode():
                pred = model(x, t, m)
                centered = pred.masked_fill(~m, 0)
                centered = centered - (centered.sum(1) / m.sum(1)).unsqueeze(1)
                total.extend(F.smooth_l1_loss(centered[m], y[m], reduction="none").tolist())
                paired = pair_loss(centered, y, m)
                if paired is not None:
                    comparisons.append(float(paired))
                for i, r in enumerate(subset):
                    base = int(np.argmax([a["x"][42] for a in r["choices"]]))
                    best = int(pred[i].argmax())
                    select = best if pred[i, best] - pred[i, base] >= args.margin else base
                    gains.append(r["returns"][select] - r["returns"][base])
                    changed += select != base
        return {
            "roots": len(rows),
            "mae_huber": fmean(total) if total else None,
            "pair_loss": fmean(comparisons) if comparisons else None,
            "gain_over_greedy": fmean(gains) if gains else None,
            "changes": changed,
        }

    best = None
    best_weights = None
    for epoch in range(args.epochs):
        rng.shuffle(train)
        model.train()
        for start in range(0, len(train), 48):
            x, t, m, y = batch(train[start : start + 48])
            z = model(x, t, m)
            z = z.masked_fill(~m, 0)
            z = z - (z.sum(1) / m.sum(1)).unsqueeze(1)
            loss = .12 * F.smooth_l1_loss(z[m], y[m], beta=2.0)
            paired = pair_loss(z, y, m)
            if paired is not None:
                loss = loss + paired
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 3.0)
            opt.step()
        model.eval()
        val = metrics(parts["val"])
        metric = val["pair_loss"]
        if metric is not None and (best is None or metric < best):
            best = metric
            best_weights = {k: v.detach().clone() for k, v in model.state_dict().items()}
    if best_weights is None:
        raise ValueError("No separate validation game seeds")
    model.load_state_dict(best_weights)
    torch.save(
        {
            "version": 2, "feature_provenance": provenance["features"], "label_provenance": provenance,
            "runtime_identity": IDENTITY,
            "width": args.width,
            "inputs": inputs,
            "vocab": vocab,
            "weights": asdict(weights),
            "margin": args.margin,
            "state_dict": best_weights,
        },
        args.output / "returns.pt",
    )
    report = {
        "label_provenance": provenance,
        "seeds": len({r["seed"] for r in rows}),
        "roots": len(rows),
        "branches": sum(len(r["returns"]) for r in rows),
        "return_varies": sum(max(r["returns"]) > min(r["returns"]) for r in rows),
        "room_counts": dict(Counter(r["room"] for r in rows)),
        "train_roots": len(train),
        "val": metrics(parts["val"]),
        "test": metrics(parts["test"]),
    }
    save_json(args.output / "report.json", report)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
