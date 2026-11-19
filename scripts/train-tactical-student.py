"""Distill visible-hand planning and optionally aggregate student-visited trajectories."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import random

import torch
from torch.nn import functional as F

from sts2rl.act1 import save_json
from sts2rl.native import digest
from sts2rl.run_policy import IDENTITY
from sts2rl.tactical_student import make_network, pack, read_training_runs


def batches(rows, vocab):
    for i in range(0, len(rows), 128):
        batch = rows[i:i + 128]
        yield (*pack(batch, vocab), torch.tensor([r["label"] for r in batch]))


@torch.inference_mode()
def evaluate(model, batches):
    model.eval()
    count = correct = 0
    loss = 0.
    for x, token, mask, labels in batches:
        scores = model(x, token, mask)
        correct += int((scores.argmax(1) == labels).sum())
        count += len(labels)
        loss += float(F.cross_entropy(scores, labels, reduction="sum"))
    return {"decisions": count, "agreement": correct / count, "cross_entropy": loss / count}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("collections", type=Path, nargs="+", help="Role folders with native action labels")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--width", type=int, default=48)
    p.add_argument("--epochs", type=int, default=24)
    args = p.parse_args()
    torch.set_num_threads(1)
    torch.manual_seed(174)
    rng = random.Random(174)
    runs = read_training_runs(args.collections)
    if not runs or any(w != runs[0][2] for _, _, w in runs):
        raise ValueError("Expected training rows with consistent action-feature weights")
    parts = {"train": [], "validation": [], "test": []}
    split = {}
    for seed, rows, _ in runs:
        bucket = int(digest(["silent-planner-split", seed])[:8], 16) % 10
        part = "validation" if bucket == 0 else "test" if bucket == 1 else "train"
        parts[part].extend(rows)
        split[seed] = part
    if any(not p for p in parts.values()):
        raise ValueError("Collect additional independent game seeds for three nonempty partitions")
    train = parts["train"]
    symbols = sorted({a["token"] for row in train for a in row["choices"]})
    vocab = {key: i + 1 for i, key in enumerate(symbols)}
    inputs = len(train[0]["choices"][0]["x"])
    model = make_network(args.width, inputs, len(vocab) + 1)
    opt = torch.optim.AdamW(model.parameters(), lr=.002, weight_decay=.01)
    args.output.mkdir(parents=True, exist_ok=False)
    rng.shuffle(train)
    train_batches = list(batches(train, vocab))
    val_batches = list(batches(parts["validation"], vocab))
    best_loss, best_state, best_epoch = float("inf"), None, 0
    history = []
    for epoch in range(1, args.epochs + 1):
        model.train()
        rng.shuffle(train_batches)
        for x, token, mask, labels in train_batches:
            opt.zero_grad(set_to_none=True)
            scores = model(x, token, mask)
            loss = F.cross_entropy(scores, labels)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 2.)
            opt.step()
        val = evaluate(model, val_batches)
        history.append(val)
        if val["cross_entropy"] < best_loss:
            best_loss, best_epoch = val["cross_entropy"], epoch
            best_state = copy.deepcopy(model.state_dict())
    model.load_state_dict(best_state)
    checkpoint = args.output / "best.pt"
    torch.save({"version": 1, "runtime_identity": IDENTITY, "feature_weights": runs[0][2],
                "width": args.width, "inputs": inputs, "vocab": vocab, "state_dict": best_state}, checkpoint)
    report = {"training_seeds": len(runs), "splits": split, "decisions": {k: len(v) for k, v in parts.items()},
              "source_collections": list(map(str, args.collections)), "teacher": "visible-hand planner",
              "student_teacher_disagreements": sum(r["label"] != r["executed"] for _, rows, _ in runs for r in rows),
              "parameters": sum(p.numel() for p in model.parameters()), "best_epoch": best_epoch,
              "validation": history[best_epoch - 1], "test": evaluate(model, batches(parts["test"], vocab)),
              "sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest()}
    save_json(args.output / "report.json", report)
    print(json.dumps({k: v for k, v in report.items() if k != "splits"}))


if __name__ == "__main__":
    main()
