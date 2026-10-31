"""Public combat encoder + legal-action scorer, distilled from native MC labels."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
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
from .native import ACT1_PROFILES, ASSEMBLY_VERSION, CURRICULUM_SAMPLER, SAMPLER, digest, legal_actions, runtime_identity
from .teacher import equivalent_groups

KINDS = ("play_card", "end_turn", "use_potion", "select_cards", "skip_select",
         "select_card_reward", "skip_card_reward", "select_bundle")


def micro_vocabulary(states, *, condition_ascension=False):
    base = combat_vocabulary(states, condition_ascension=condition_ascension)
    return Vocabulary((*base.tokens, *("action:" + k for k in KINDS)))


def collate_micro(states, vocab, device="cpu", *, condition_ascension=False):
    batch = collate_combat(states, vocab, condition_ascension=condition_ascension)
    choices = [legal_actions(s) for s in states]
    b, e = batch["entities"].shape
    a = max(map(len, choices))
    batch.update(action_kind=torch.zeros((b, a), dtype=torch.long),
                 action_mask=torch.zeros((b, a), dtype=torch.bool),
                 source=torch.zeros((b, a, e)), target=torch.zeros((b, a, e)))
    for row, (state, actions) in enumerate(zip(states, choices, strict=True)):
        entities = combat_entities(state, condition_ascension=condition_ascension)
        for j, action in enumerate(actions):
            if action.kind not in KINDS:
                raise ValueError("Micro policy only accepts combat decisions")
            batch["action_kind"][row, j] = vocab.encode("action:" + action.kind)
            batch["action_mask"][row, j] = True
            args = action.args
            selected = set(map(int, args["indices"].split(","))) if "indices" in args else set()
            for k, entity in enumerate(entities):
                index = entity.attributes.get("index")
                source = ((entity.zone == "hand" and action.kind == "play_card" and index == args["card_index"])
                          or (entity.zone == "potion" and "potion_index" in args and index == args["potion_index"])
                          or (entity.zone == "selection_card" and index in selected))
                if entity.zone == "selection_card" and action.kind in ("select_card_reward", "select_bundle"):
                    source = index == args.get("card_index", args.get("bundle_index"))
                target = entity.zone == "enemy" and "target_index" in args and index == args["target_index"]
                batch["source"][row, j, k] = float(source)
                batch["target"][row, j, k] = float(target)
    return {k: v.to(device) for k, v in batch.items()}


class MicroPolicy(nn.Module):
    def __init__(self, vocab_size, width=64, dropout=0):
        super().__init__()
        self.encoder = CombatStateEncoder(vocab_size, width, dropout)
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
        scale = 200 if row.get("sampler") in ACT1_PROFILES else 170
        if not bool(torch.isfinite(q).all()) or bool(((q < 0) | (q > scale + 1e-5)).any()):
            raise ValueError("Invalid curriculum return")
        multiplicity = {a.id: len(group) for group in equivalent_groups(row["observation"], actions) for a in group}
        # Equal physical copies share probability rather than multiplying the
        # probability of an action's effect merely because more copies are held.
        logits = q / temperature - torch.tensor([math.log(multiplicity[a.id]) for a in actions])
        targets[i, :len(actions)] = logits.softmax(0)
        values.append(float((targets[i, :len(actions)] * q).sum()) / scale)
    return targets.to(device), torch.tensor(values, device=device)


def partition_records(records, *, inherited_split=None):
    groups = sorted({r["group"] for r in records}, key=lambda g: digest(["micro-split-v1", g]))
    if len(groups) < 10:
        raise ValueError("At least ten independent episode seeds required for train/validation/test")
    split = dict(inherited_split or {})
    if set(split) - set(groups) or any(s not in ("train", "validation", "test") for s in split.values()):
        raise ValueError("Inherited split contains missing groups or invalid partitions")
    new_groups = [g for g in groups if g not in split]
    if new_groups:
        if len(new_groups) < 10:
            raise ValueError("Aggregation requires at least ten new independent seed groups")
        n = max(1, len(new_groups) // 10)
        split.update({g: ("test" if i < n else "validation" if i < 2*n else "train") for i, g in enumerate(new_groups)})
    if set(split.values()) != {"train", "validation", "test"}:
        raise ValueError("Every dataset partition must contain a seed group")
    return {s: [r for r in records if split[r["group"]] == s] for s in ("train", "validation", "test")}, split


def curriculum_scope(records, partitions):
    """Difficulty metadata must agree with observed native state, in every split.

    Seed-group splitting is independent of difficulty, so the same seed at two
    ascensions cannot leak across partitions. Require each difficulty in all
    splits instead of silently training/evaluating on different distributions.
    """
    for row in records:
        identity = runtime_identity(row.get("ascension"))
        if row["observation"].get("runtime_identity") != identity:
            raise ValueError("Teacher ascension metadata disagrees with native runtime identity")
    ascensions = sorted({r["ascension"] for r in records})
    for name, rows in partitions.items():
        if {r["ascension"] for r in rows} != set(ascensions):
            raise ValueError(f"Every curriculum ascension must occur in the {name} split; collect more independent seeds")
    return ascensions


def choose_micro_action(state, logits):
    """Choose the most probable effect, then one of its interchangeable copies.

    Teacher targets divide mass among duplicates. Argmax over individual copies
    would incorrectly favor a unique end_turn over several equally good attacks.
    """
    actions = legal_actions(state)
    indices = {a.id: i for i, a in enumerate(actions)}
    groups = equivalent_groups(state, actions)
    best = max(groups, key=lambda group: float(torch.logsumexp(
        logits[[indices[a.id] for a in group]], dim=0)))
    return max(best, key=lambda a: float(logits[indices[a.id]]))


@torch.inference_mode()
def evaluate_micro(model, records, vocab, device, *, condition_ascension=False):
    model.eval()
    total, regret, correct = 0.0, 0.0, 0
    for start in range(0, len(records), 32):
        rows = records[start:start+32]
        logits, _ = model(collate_micro([r["observation"] for r in rows], vocab, device, condition_ascension=condition_ascension))
        targets, _ = teacher_targets(rows, device)
        total += float(-(targets * F.log_softmax(logits, -1)).sum())
        for i, row in enumerate(rows):
            action = choose_micro_action(row["observation"], logits[i])
            chosen = next(j for j, a in enumerate(row["actions"]) if a["id"] == action.id)
            q = [row["estimates"][a["id"]]["mean_return"] for a in row["actions"]]
            regret += max(q) - q[chosen]
            correct += q[chosen] >= max(q) - 1e-6
    return {"decisions": len(records), "teacher_cross_entropy": total / len(records),
            "teacher_best_action_agreement": correct / len(records),
            "mean_estimated_regret": regret / len(records)}


def fit_micro(paths, output, *, epochs=20, device="cpu", width=64, inherited_split=None):
    if epochs < 1:
        raise ValueError("Positive epoch count required")
    torch.set_num_threads(2)
    torch.manual_seed(42)
    rng = random.Random(42)
    records = [json.loads(line) for path in paths for line in path.read_text(encoding="utf-8").splitlines()]
    profiles = {r.get("sampler") for r in records}
    if len(profiles) != 1 or not profiles <= {SAMPLER, *ACT1_PROFILES} or any(r.get("schema_version") != 1 for r in records):
        raise ValueError("Unqualified or incompatible teacher data")
    profile = next(iter(profiles))
    if profile != CURRICULUM_SAMPLER and any(
        r["observation"].get("runtime_identity") != runtime_identity(10) or r.get("ascension", 10) != 10
        for r in records
    ):
        raise ValueError("Legacy teacher profile requires ascension 10 runtime identity")
    partitions, split = partition_records(records, inherited_split=inherited_split)
    conditioned = profile == CURRICULUM_SAMPLER
    ascensions = curriculum_scope(records, partitions) if conditioned else [10]
    vocab = micro_vocabulary([r["observation"] for r in partitions["train"]], condition_ascension=conditioned)
    dropout = 0.1 if profile in ACT1_PROFILES else 0
    model = MicroPolicy(len(vocab), width, dropout).to(device)
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
        batches.append((collate_micro([r["observation"] for r in rows], vocab, device, condition_ascension=conditioned),
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
        metrics = evaluate_micro(model, partitions["validation"], vocab, device, condition_ascension=conditioned)
        history.append({"epoch": epoch, **metrics})
        if metrics["teacher_cross_entropy"] < best:
            best = metrics["teacher_cross_entropy"]
            checkpoint = {"micro_version": 3 if conditioned else 2, "sampler": profile, "assembly_version": ASSEMBLY_VERSION,
                          "dropout": dropout,
                          "vocabulary": vocab.to_dict(), "width": width, "best_epoch": epoch,
                          "state_dict": {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}}
            if conditioned:
                checkpoint["trained_ascensions"] = ascensions
            torch.save(checkpoint, output / "best.pt")
        (output / "progress.json").write_text(json.dumps(history[-1], indent=2), encoding="utf-8")
        print(json.dumps(history[-1]), flush=True)
    checkpoint = torch.load(output / "best.pt", map_location="cpu", weights_only=True)
    model.load_state_dict(checkpoint["state_dict"])
    report = {"sampler": profile, "dataset_sha256": digest(records), "decisions": len(records),
              "condition_ascension": conditioned, "trained_ascensions": ascensions,
              "split_groups": dict(Counter(split.values())), "split": split,
              "inherited_split_groups": len(inherited_split or {}),
              "split_decisions": {k: len(v) for k, v in partitions.items()},
              "coverage_by_split": {k: {
                  "ascension_decisions": dict(Counter(str(r.get("ascension", 10)) for r in rows)),
                  "teacher_monsters": dict(Counter(m for r in rows for m in r.get("monster_ids", []))),
                  "floors": dict(Counter(str(r["floor"]) for r in rows if "floor" in r))}
                  for k, rows in partitions.items()},
              "epochs": epochs, "best_epoch": checkpoint["best_epoch"], "device": device,
              "action_selection": "aggregate-equivalent-action-probabilities-v2",
              "seconds": time.perf_counter() - started, "history": history,
              "test": evaluate_micro(model, partitions["test"], vocab, device, condition_ascension=conditioned),
              "limitations": ["Offline imitation metrics, not Act 1 clear rate",
                              "Monte Carlo values under a heuristic continuation, not optimal values",
                              "Value predicts local fight return, not whole-run victory"]}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def load_micro(path, *, device="cpu"):
    torch.set_num_threads(2)
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    if checkpoint.get("micro_version") not in (1, 2, 3) or checkpoint.get("assembly_version") != ASSEMBLY_VERSION:
        raise ValueError("Incompatible micro checkpoint")
    if checkpoint.get("sampler") not in (SAMPLER, *ACT1_PROFILES):
        raise ValueError("Unqualified micro training scope")
    conditioned = checkpoint["micro_version"] == 3
    if conditioned != (checkpoint["sampler"] == CURRICULUM_SAMPLER):
        raise ValueError("Micro version and curriculum profile disagree")
    ascensions = checkpoint.get("trained_ascensions", []) if conditioned else [10]
    if not ascensions or len(set(ascensions)) != len(ascensions):
        raise ValueError("Missing/invalid trained ascensions")
    identities = [runtime_identity(a) for a in ascensions]
    vocab = Vocabulary.from_dict(checkpoint["vocabulary"])
    model = MicroPolicy(len(vocab), checkpoint["width"], checkpoint.get("dropout", 0)).to(device)
    model.load_state_dict(checkpoint["state_dict"], strict=True)
    model.eval()

    @torch.inference_mode()
    def policy(state):
        if state.get("runtime_identity") not in identities:
            raise ValueError("Micro policy requires its qualified native runtime identity")
        inputs = state
        if checkpoint["micro_version"] == 1:
            inputs = deepcopy(state)
            inputs.pop("public_combat_history", None)
            inputs.pop("selection_source", None)
        logits, _ = model(collate_micro([inputs], vocab, device, condition_ascension=conditioned))
        return choose_micro_action(state, logits[0])

    return policy
