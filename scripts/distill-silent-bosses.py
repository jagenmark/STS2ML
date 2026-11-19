"""Distill successful native boss continuations into a public tactical ranker."""

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import gzip
import hashlib
import json
from pathlib import Path
from random import Random
from statistics import fmean

from sts2rl.act1 import save_json
from sts2rl.encounter import EncounterPolicy
from sts2rl.native import NativeSession, legal_actions
from sts2rl.return_policy import shortlist
from sts2rl.run_policy import IDENTITY, RunPolicy, RunWeights
from sts2rl.tactical_student import make_network, pack
from sts2rl.trajectory import strategy_roots

ROOT = Path(__file__).resolve().parents[1]


def end_value(row):
    return 30 * row["won"] + 0.2 * row["hp"] + 6 * (1 - row["remaining"]) + 0.2 * row["potions"]


def collect(task):
    source, labels, folder, host, weights = task
    folder.mkdir(parents=True, exist_ok=False)
    by_digest = {r["root"]: r for r in labels}
    examples = []
    errors = []
    prior = RunPolicy(weights)
    feature_actor = EncounterPolicy(weights)
    seen = set()
    for state, fork in strategy_roots(source):
        row = by_digest.get(fork.expected_digest)
        if row is None:
            continue
        ranked = sorted(row["styles"], key=lambda s: end_value(row["styles"][s]), reverse=True)
        # Keep the best observed continuation and, when it wins too, a second distinct policy.
        eligible = [s for s in ranked if row["styles"][s]["won"]][:2] or ranked[:1]
        for j, style in enumerate(eligible):
            samples = []
            added = set()
            try:
                with NativeSession(
                    ROOT,
                    folder / f"fight-{row['act']}-{j}-{fork.expected_digest[:6]}",
                    host_path=host,
                    ascension=10,
                    timeout=45,
                    act_list=fork.specification.get("act_list", "default"),
                ) as g:
                    s = g.restore(fork)
                    teacher = EncounterPolicy(weights, style=style)
                    for _ in range(600):
                        if s["decision"] == "game_over" or not s.get("in_combat"):
                            end = s["decision"] != "game_over" or s.get("victory") is True
                            if end != row["styles"][style]["won"] or (
                                end and s["player"]["hp"] != row["styles"][style]["hp"]
                            ):
                                raise ValueError(
                                    "Replayed teacher trajectory did not reproduce its fight outcome"
                                )
                            break
                        action = teacher(s)
                        if s["decision"] == "combat_play" and len(legal_actions(s)) >= 3:
                            acts, choices = shortlist(s, prior, feature_actor)
                            label = next((i for i, a in enumerate(acts) if a.id == action.id), None)
                            key = (action.snapshot, action.id)
                            if label is not None and key not in seen and key not in added:
                                margin = end_value(row["styles"][style]) - end_value(
                                    row["styles"]["balanced"]
                                )
                                weight = (1.0 if row["styles"][style]["won"] else 0.55) * (
                                    1 + min(2.0, max(0, margin) / 12)
                                )
                                samples.append(
                                    {
                                        "seed": row["seed"],
                                        "choices": choices,
                                        "label": label,
                                        "weight": weight,
                                        "won": row["styles"][style]["won"],
                                    }
                                )
                                added.add(key)
                        s = g.step(action)
                    else:
                        raise ValueError("Boss teacher exceeded action budget")
                seen.update(added)
                examples.extend(samples)
            except Exception as exc:
                errors.append({"root": fork.expected_digest, "style": style, "error": str(exc)})
    with gzip.open(folder / "expert.jsonl.gz", "wt", encoding="utf-8", compresslevel=2) as f:
        for e in examples:
            f.write(json.dumps(e, separators=(",", ":")) + "\n")
    save_json(folder / "result.json", {"decisions": len(examples), "errors": errors})
    return len(examples)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=("collect", "fit"))
    for k in ("source", "weights", "output"):
        p.add_argument("--" + k, type=Path, required=True)
    p.add_argument("--labels", type=Path)
    p.add_argument("--host", type=Path)
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--width", type=int, default=48)
    p.add_argument("--epochs", type=int, default=28)
    p.add_argument("--margin", type=float, default=0.35)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    weights = RunWeights.load(args.weights)
    if args.mode == "collect":
        if not args.host or not args.labels:
            p.error("Collection requires --host and --labels")
        sources = {
            r["seed"]: f.parent
            for f in args.source.glob("run-*/result.json")
            if (r := json.loads(f.read_text()))["status"] == "complete"
        }
        tasks = []
        for pth in sorted(args.labels.glob("run-*/labels.json")):
            labels = json.loads(pth.read_text())["roots"]
            if labels:
                tasks.append(
                    (
                        sources[labels[0]["seed"]],
                        labels,
                        args.output / pth.parent.name,
                        args.host,
                        weights,
                    )
                )
        with ProcessPoolExecutor(args.workers) as pool:
            for i, _ in enumerate(pool.map(collect, tasks), 1):
                if i % 20 == 0:
                    print(i, flush=True)
        return
    import torch
    from torch.nn import functional as F

    torch.set_num_threads(1)
    torch.manual_seed(381823)
    rng = Random(84765)
    partitions = {"train": [], "val": [], "test": []}
    for f in sorted(args.source.glob("run-*/expert.jsonl.gz")):
        if not f.with_name("result.json").exists():
            continue
        with gzip.open(f, "rt", encoding="utf-8") as stream:
            for line in stream:
                r = json.loads(line)
                n = int.from_bytes(hashlib.sha256(r["seed"].encode()).digest()[:4], "big") % 10
                partitions["test" if n == 0 else "val" if n == 1 else "train"].append(r)
    train = partitions["train"]
    vocab = {
        t: i + 1 for i, t in enumerate(sorted({a["token"] for r in train for a in r["choices"]}))
    }
    inputs = len(train[0]["choices"][0]["x"])
    net = make_network(args.width, inputs, len(vocab) + 1)
    opt = torch.optim.AdamW(net.parameters(), lr=0.0015, weight_decay=0.025)

    def metrics(rows):
        losses = []
        matches = prior = 0
        for i in range(0, len(rows), 64):
            subset = rows[i : i + 64]
            x, t, m = pack(subset, vocab)
            labels = torch.tensor([r["label"] for r in subset])
            with torch.inference_mode():
                logits = net(x, t, m)
                losses.extend(F.cross_entropy(logits, labels, reduction="none").tolist())
                matches += int((logits.argmax(1) == labels).sum())
                prior += int((x[:, :, 42].masked_fill(~m, -100).argmax(1) == labels).sum())
        return {
            "n": len(rows),
            "teacher_matches": matches,
            "base_matches": prior,
            "cross_entropy": fmean(losses) if losses else None,
        }

    best = 1e9
    selected = None
    for _ in range(args.epochs):
        rng.shuffle(train)
        net.train()
        for i in range(0, len(train), 64):
            rows = train[i : i + 64]
            x, t, m = pack(rows, vocab)
            labels = torch.tensor([r["label"] for r in rows])
            w = torch.tensor([r["weight"] for r in rows])
            logits = net(x, t, m)
            loss = (w * F.cross_entropy(logits, labels, reduction="none")).sum() / w.sum()
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 3.0)
            opt.step()
        net.eval()
        v = metrics(partitions["val"])["cross_entropy"]
        if v is not None and v < best:
            best = v
            selected = {k: v.detach().clone() for k, v in net.state_dict().items()}
    if selected is None:
        raise ValueError("Missing distinct validation games")
    net.load_state_dict(selected)
    torch.save(
        {
            "version": 1,
            "runtime_identity": IDENTITY,
            "width": args.width,
            "inputs": inputs,
            "vocab": vocab,
            "weights": asdict(weights),
            "margin": args.margin,
            "rooms": ["Boss"],
            "state_dict": selected,
        },
        args.output / "boss-student.pt",
    )
    report = {
        "seeds": len({r["seed"] for part in partitions.values() for r in part}),
        "counts": {k: len(v) for k, v in partitions.items()},
        "training_outcomes": dict(Counter(str(r["won"]) for r in train)),
        "val": metrics(partitions["val"]),
        "test": metrics(partitions["test"]),
    }
    save_json(args.output / "report.json", report)
    print(report)


if __name__ == "__main__":
    main()
