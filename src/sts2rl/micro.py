"""Public combat encoder + legal-action scorer, distilled from native MC labels."""
from __future__ import annotations

from collections import Counter
import json
import math
from pathlib import Path
import random
import time

import torch
from torch import nn
from torch.nn import functional as F

from .combat import CombatStateEncoder, collate_combat, combat_entities, combat_vocabulary
from .encoding import Vocabulary
from .native import ASSEMBLY_VERSION, SAMPLER, digest, legal_actions
from .teacher import equivalent_groups

KINDS = ("play_card", "end_turn", "use_potion", "select_cards", "skip_select")


def micro_vocabulary(states):
    base = combat_vocabulary(states)
    return Vocabulary((*base.tokens, *("action:" + k for k in KINDS)))


def collate_micro(states, vocab, device="cpu"):
    batch = collate_combat(states, vocab)
    choices = [legal_actions(s) for s in states]
    b, e = batch["entities"].shape
    a = max(map(len, choices))
    batch.update(action_kind=torch.zeros((b, a), dtype=torch.long),
                 action_mask=torch.zeros((b, a), dtype=torch.bool),
                 source=torch.zeros((b, a, e)), target=torch.zeros((b, a, e)))
    for row, (state, actions) in enumerate(zip(states, choices, strict=True)):
        entities = combat_entities(state)
        for j, action in enumerate(actions):
            if action.kind not in KINDS:
                raise ValueError("Micro policy only accepts combat decisions")
            batch["action_kind"][row, j] = vocab.encode("action:" + action.kind)
            batch["action_mask"][row, j] = True
            args = action.args
            selected = set(map(int, args["indices"].split(","))) if "indices" in args else set()
            for k, entity in enumerate(entities):
                index = entity.attributes.get("index")
                source = ((entity.zone == "hand" and "card_index" in args and index == args["card_index"])
                          or (entity.zone == "potion" and "potion_index" in args and index == args["potion_index"])
                          or (entity.zone == "selection_card" and index in selected))
                target = entity.zone == "enemy" and "target_index" in args and index == args["target_index"]
                batch["source"][row, j, k] = float(source)
                batch["target"][row, j, k] = float(target)
    return {k: v.to(device) for k, v in batch.items()}


class MicroPolicy(nn.Module):
    def __init__(self, vocab_size, width=64):
        super().__init__()
        self.encoder = CombatStateEncoder(vocab_size, width)
        self.scorer = nn.Sequential(nn.Linear(width * 4 + 1, width), nn.GELU(), nn.Linear(width, 1))
        self.value = nn.Sequential(nn.Linear(width, width), nn.GELU(), nn.Linear(width, 1), nn.Sigmoid())

    def forward(self, batch):
        pooled, entities = self.encoder(batch)
        source = torch.bmm(batch["source"], entities)
        target = torch.bmm(batch["target"], entities)
        kind = self.encoder.embedding(batch["action_kind"])
        context = pooled[:, None].expand(-1, kind.shape[1], -1)
        count = batch["source"].sum(-1, keepdim=True)
        logits = self.scorer(torch.cat((context, source, target, kind, count), -1)).squeeze(-1)
        return logits.masked_fill(~batch["action_mask"], -1e9), self.value(pooled).squeeze(-1)


def teacher_targets(records, device="cpu", temperature=2.0):
    if temperature <= 0:
        raise ValueError("Positive teacher temperature required")
    width = max(len(r["actions"]) for r in records)
    targets, values = torch.zeros((len(records), width)), []
    for i, row in enumerate(records):
        actions = legal_actions(row["observation"])
        if [a.id for a in actions] != [a["id"] for a in row["actions"]]:
            raise ValueError("Teacher actions do not match the native action contract")
        estimates = row["estimates"]
        q = torch.tensor([estimates[a.id]["mean_return"] for a in actions], dtype=torch.float32)
        if not bool(torch.isfinite(q).all()) or bool(((q < 0) | (q > 170)).any()):
            raise ValueError("Invalid starter-curriculum return")
        multiplicity = {a.id: len(group) for group in equivalent_groups(row["observation"], actions) for a in group}
        # Equal physical copies share probability rather than multiplying the
        # probability of an action's effect merely because more copies are held.
        logits = q / temperature - torch.tensor([math.log(multiplicity[a.id]) for a in actions])
        targets[i, :len(actions)] = logits.softmax(0)
        values.append(float((targets[i, :len(actions)] * q).sum()) / 170)
    return targets.to(device), torch.tensor(values, device=device)


def partition_records(records):
    groups = sorted({r["group"] for r in records}, key=lambda g: digest(["micro-split-v1", g]))
    if len(groups) < 10:
        raise ValueError("At least ten independent episode seeds required for train/validation/test")
    n = max(1, len(groups) // 10)
    split = {g: ("test" if i < n else "validation" if i < 2*n else "train") for i, g in enumerate(groups)}
    return {s: [r for r in records if split[r["group"]] == s] for s in ("train", "validation", "test")}, split


@torch.inference_mode()
def evaluate_micro(model, records, vocab, device):
    model.eval()
    total, regret, correct = 0.0, 0.0, 0
    for start in range(0, len(records), 32):
        rows = records[start:start+32]
        logits, _ = model(collate_micro([r["observation"] for r in rows], vocab, device))
        targets, _ = teacher_targets(rows, device)
        total += float(-(targets * F.log_softmax(logits, -1)).sum())
        for row, chosen in zip(rows, logits.argmax(-1).tolist(), strict=True):
            q = [row["estimates"][a["id"]]["mean_return"] for a in row["actions"]]
            regret += max(q) - q[chosen]
            correct += q[chosen] >= max(q) - 1e-6
    return {"decisions": len(records), "teacher_cross_entropy": total / len(records),
            "teacher_best_action_agreement": correct / len(records),
            "mean_estimated_regret": regret / len(records)}


def fit_micro(paths, output, *, epochs=20, device="cpu", width=64):
    if epochs < 1:
        raise ValueError("Positive epoch count required")
    torch.set_num_threads(2)
    torch.manual_seed(42)
    rng = random.Random(42)
    records = [json.loads(line) for path in paths for line in path.read_text(encoding="utf-8").splitlines()]
    if any(r.get("sampler") != SAMPLER or r.get("schema_version") != 1 for r in records):
        raise ValueError("Unqualified or incompatible teacher data")
    partitions, split = partition_records(records)
    vocab = micro_vocabulary([r["observation"] for r in partitions["train"]])
    model = MicroPolicy(len(vocab), width).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=0.01)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    started, best, history = time.perf_counter(), math.inf, []
    # Encode once: CPU feature collation can otherwise dominate this small fit.
    batches = []
    training = list(partitions["train"])
    rng.shuffle(training)
    for start in range(0, len(training), 32):
        rows = training[start:start+32]
        batches.append((collate_micro([r["observation"] for r in rows], vocab, device),
                        *teacher_targets(rows, device)))
    for epoch in range(1, epochs + 1):
        model.train()
        rng.shuffle(batches)
        for batch, target, value in batches:
            optimizer.zero_grad(set_to_none=True)
            logits, prediction = model(batch)
            loss = -(target * F.log_softmax(logits, -1)).sum(-1).mean() + 0.1 * F.mse_loss(prediction, value)
            if not bool(torch.isfinite(loss)):
                raise ValueError("Non-finite micro loss")
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1)
            optimizer.step()
        metrics = evaluate_micro(model, partitions["validation"], vocab, device)
        history.append({"epoch": epoch, **metrics})
        if metrics["teacher_cross_entropy"] < best:
            best = metrics["teacher_cross_entropy"]
            checkpoint = {"micro_version": 1, "sampler": SAMPLER, "assembly_version": ASSEMBLY_VERSION,
                          "vocabulary": vocab.to_dict(), "width": width, "best_epoch": epoch,
                          "state_dict": {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}}
            torch.save(checkpoint, output / "best.pt")
        (output / "progress.json").write_text(json.dumps(history[-1], indent=2), encoding="utf-8")
        print(json.dumps(history[-1]), flush=True)
    checkpoint = torch.load(output / "best.pt", map_location="cpu", weights_only=True)
    model.load_state_dict(checkpoint["state_dict"])
    report = {"sampler": SAMPLER, "dataset_sha256": digest(records), "decisions": len(records),
              "split_groups": dict(Counter(split.values())), "split": split,
              "split_decisions": {k: len(v) for k, v in partitions.items()},
              "epochs": epochs, "best_epoch": checkpoint["best_epoch"], "device": device,
              "seconds": time.perf_counter() - started, "history": history,
              "test": evaluate_micro(model, partitions["test"], vocab, device),
              "limitations": ["Starter-beetle scenarios, not Act 1 clear rate",
                              "Monte Carlo values under a heuristic continuation, not optimal values",
                              "Value predicts local fight return, not whole-run victory"]}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def load_micro(path, *, device="cpu"):
    torch.set_num_threads(2)
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    if checkpoint.get("micro_version") != 1 or checkpoint.get("assembly_version") != ASSEMBLY_VERSION:
        raise ValueError("Incompatible micro checkpoint")
    if checkpoint.get("sampler") != SAMPLER:
        raise ValueError("Unqualified micro training scope")
    vocab = Vocabulary.from_dict(checkpoint["vocabulary"])
    model = MicroPolicy(len(vocab), checkpoint["width"]).to(device)
    model.load_state_dict(checkpoint["state_dict"], strict=True)
    model.eval()

    @torch.inference_mode()
    def policy(state):
        logits, _ = model(collate_micro([state], vocab, device))
        return legal_actions(state)[int(logits[0].argmax())]

    return policy
