"""Reproducible offline imitation training; this is not online reinforcement learning."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import random

import torch
from torch.nn import functional as F

from .data import audit_records, grouped_split, validate_dataset
from .encoding import Vocabulary, collate_records
from .model import MacroPolicyValue, ModelConfig, policy_value_loss
from .schema import validate_record


@dataclass(frozen=True)
class TrainConfig:
    epochs: int = 10
    batch_size: int = 32
    learning_rate: float = 3e-4
    weight_decay: float = 0.01
    value_weight: float = 0.5
    seed: int = 42
    d_model: int = 128
    n_heads: int = 4
    n_layers: int = 3
    dropout: float = 0.0
    device: str = "cpu"
    threads: int = 2
    allow_mixed_versions: bool = False

    def __post_init__(self) -> None:
        if min(self.epochs, self.batch_size, self.threads) < 1:
            raise ValueError("epochs, batch size and threads must be positive")
        if (
            not all(
                math.isfinite(x) for x in (self.learning_rate, self.weight_decay, self.value_weight)
            )
            or self.learning_rate <= 0
            or self.weight_decay < 0
            or self.value_weight < 0
        ):
            raise ValueError("invalid optimizer/loss configuration")


def _action_key(candidate: dict) -> str:
    return f"{candidate['kind']}:{candidate.get('entity_id')}:{candidate.get('upgrades')}"


def fit_baselines(records: list[dict]) -> dict:
    """Offer-conditioned smoothed pick rates; no final-deck win-rate ranking."""
    offered: Counter = Counter()
    picked: Counter = Counter()
    for record in records:
        chosen = record.get("chosen_action_id")
        if chosen is None:
            continue
        for candidate in record["candidates"]:
            key = _action_key(candidate)
            offered[key] += 1
            picked[key] += int(candidate["action_id"] == chosen)
    # One outcome per run avoids making the outcome base rate depend on run length.
    outcomes = {r["run_id"]: r["outcome"] for r in records if r.get("outcome") is not None}
    return {
        "pick_rates": {key: (picked[key] + 1) / (count + 2) for key, count in offered.items()},
        "outcome_base_rate": sum(outcomes.values()) / len(outcomes) if outcomes else None,
    }


@torch.inference_mode()
def evaluate(
    model: MacroPolicyValue,
    records: list[dict],
    vocab: Vocabulary,
    *,
    batch_size: int = 64,
    device: str = "cpu",
    baselines: dict | None = None,
) -> dict:
    model.eval()
    sums = Counter()
    run_correct: dict[str, list[float]] = defaultdict(list)
    value_classes = Counter()
    for start in range(0, len(records), batch_size):
        rows = records[start : start + batch_size]
        batch = collate_records(rows, vocab, device)
        outputs = model(batch)
        pmask, vmask = batch["policy_mask"], batch["value_mask"]
        if bool(pmask.any()):
            logits, targets = outputs["policy_logits"][pmask], batch["policy_targets"][pmask]
            sums["policy_labels"] += int(pmask.sum())
            sums["policy_nll"] += float(F.cross_entropy(logits, targets, reduction="sum"))
            sums["policy_correct"] += float((logits.argmax(-1) == targets).sum())
        if bool(vmask.any()):
            targets = batch["value_targets"][vmask]
            values = outputs["value_logits"][vmask]
            sums["value_labels"] += int(vmask.sum())
            sums["value_bce"] += float(
                F.binary_cross_entropy_with_logits(values, targets, reduction="sum")
            )
            sums["value_brier"] += float(((values.sigmoid() - targets) ** 2).sum())
            value_classes.update(int(value) for value in targets.cpu().tolist())
        for i, record in enumerate(rows):
            if record.get("chosen_action_id") is not None:
                candidates = record["candidates"]
                target = next(
                    j
                    for j, a in enumerate(candidates)
                    if a["action_id"] == record["chosen_action_id"]
                )
                predicted = int(outputs["policy_logits"][i].argmax())
                run_correct[record["run_id"]].append(float(predicted == target))
                sums["uniform_accuracy"] += 1 / len(candidates)
                sums["uniform_nll"] += math.log(len(candidates))
                if baselines:
                    scores = [baselines["pick_rates"].get(_action_key(a), 0.5) for a in candidates]
                    best = max(scores)
                    tied = [j for j, score in enumerate(scores) if score == best]
                    sums["frequency_accuracy"] += (1 / len(tied)) if target in tied else 0
            if (
                record.get("outcome") is not None
                and baselines
                and baselines["outcome_base_rate"] is not None
            ):
                sums["base_brier"] += (baselines["outcome_base_rate"] - record["outcome"]) ** 2
    pn, vn = int(sums["policy_labels"]), int(sums["value_labels"])
    return {
        "decisions": len(records),
        "runs": len({r["run_id"] for r in records}),
        "policy_labels": pn,
        "value_labels": vn,
        "policy_accuracy": sums["policy_correct"] / pn if pn else None,
        "policy_nll": sums["policy_nll"] / pn if pn else None,
        "policy_accuracy_run_mean": sum(sum(v) / len(v) for v in run_correct.values())
        / len(run_correct)
        if run_correct
        else None,
        "uniform_policy_accuracy": sums["uniform_accuracy"] / pn if pn else None,
        "uniform_policy_nll": sums["uniform_nll"] / pn if pn else None,
        "frequency_baseline_accuracy": sums["frequency_accuracy"] / pn
        if pn and baselines
        else None,
        "value_bce": sums["value_bce"] / vn if vn else None,
        "value_brier": sums["value_brier"] / vn if vn else None,
        "outcome_base_rate_brier": sums["base_brier"] / vn
        if vn and baselines and baselines["outcome_base_rate"] is not None
        else None,
        "value_label_counts": dict(value_classes),
        "interpretation": "offline imitation/outcome metrics; not native game win rate",
    }


def train(records: list[dict], output_dir: str | Path, config: TrainConfig) -> dict:
    validate_dataset(records)
    if len({r["game_version"] for r in records}) > 1 and not config.allow_mixed_versions:
        raise ValueError(
            "mixed game versions: filter one version or explicitly enable mixed-version training"
        )
    partitions, manifest = grouped_split(records, seed=config.seed)
    # Preserve transitive run/seed links BEFORE discarding unlabelled records.
    # Otherwise an unlabelled bridge can cause connected labelled runs to leak.
    partitions = {
        name: sorted(
            [
                r
                for r in rows
                if r.get("chosen_action_id") is not None or r.get("outcome") is not None
            ],
            key=lambda r: (r["run_id"], r["decision_id"]),
        )
        for name, rows in partitions.items()
    }
    manifest["labelled_counts"] = {name: len(rows) for name, rows in partitions.items()}
    for name, rows in partitions.items():
        if not rows:
            raise ValueError(
                f"empty {name} split; collect more independent runs (do not split decisions)"
            )
    if not any(r.get("chosen_action_id") is not None for r in partitions["train"]):
        raise ValueError("training requires at least one imitation label")
    if not any(r.get("chosen_action_id") is not None for r in partitions["validation"]):
        raise ValueError("validation requires imitation labels for checkpoint selection")
    torch.set_num_threads(config.threads)
    torch.manual_seed(config.seed)
    rng = random.Random(config.seed)
    vocab = Vocabulary.build(partitions["train"])
    model_config = ModelConfig(
        len(vocab), config.d_model, config.n_heads, config.n_layers, dropout=config.dropout
    )
    model = MacroPolicyValue(model_config).to(config.device)
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=config.learning_rate, weight_decay=config.weight_decay
    )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    baselines = fit_baselines(partitions["train"])
    history, best_score, best_epoch = [], float("inf"), -1
    for epoch in range(1, config.epochs + 1):
        model.train()
        rows = list(partitions["train"])
        rng.shuffle(rows)
        for start in range(0, len(rows), config.batch_size):
            batch = collate_records(rows[start : start + config.batch_size], vocab, config.device)
            optimizer.zero_grad(set_to_none=True)
            losses = policy_value_loss(model(batch), batch, config.value_weight)
            if not bool(torch.isfinite(losses["loss"])):
                raise RuntimeError("non-finite training loss")
            losses["loss"].backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0, error_if_nonfinite=True)
            optimizer.step()
        # The test split is deliberately not evaluated here.
        train_metrics = evaluate(
            model, partitions["train"], vocab, device=config.device, baselines=baselines
        )
        validation = evaluate(
            model, partitions["validation"], vocab, device=config.device, baselines=baselines
        )
        history.append({"epoch": epoch, "train": train_metrics, "validation": validation})
        score = validation["policy_nll"]
        if score < best_score:
            best_score, best_epoch = score, epoch
            checkpoint = {
                "checkpoint_version": 1,
                "model_config": asdict(model_config),
                "vocabulary": vocab.to_dict(),
                "model_state": {
                    key: value.detach().cpu().clone() for key, value in model.state_dict().items()
                },
                "train_config": asdict(config),
                "best_epoch": epoch,
                "split_manifest": manifest,
                "baselines": baselines,
                "training_audit": audit_records(partitions["train"]),
            }
            torch.save(checkpoint, output_dir / "best.pt")
    best_model, _, _ = load_checkpoint(output_dir / "best.pt", device=config.device)
    report = {
        "status": "offline_baseline",
        "training": asdict(config),
        "model": asdict(model_config),
        "parameter_count": model.parameter_count,
        "best_epoch": best_epoch,
        "selection_metric": "validation policy cross-entropy",
        "split": manifest,
        "dataset": audit_records(records),
        "history": history,
        "test": evaluate(
            best_model, partitions["test"], vocab, device=config.device, baselines=baselines
        ),
        "limitations": [
            "This does not measure game-playing strength or causal card value.",
            "Decisions within a run are correlated; small run counts do not support strong conclusions.",
            "State quality and missing features are explicit; partial records are not complete game states.",
            "Loss is decision-weighted; longer runs supply more examples.",
        ],
    }
    (output_dir / "report.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    (output_dir / "split.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return report


def load_checkpoint(
    path: str | Path, *, device: str = "cpu"
) -> tuple[MacroPolicyValue, Vocabulary, dict]:
    # Restrict deserialization to tensors and primitive values. Do not use unrestricted pickle.
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    if checkpoint.get("checkpoint_version") != 1:
        raise ValueError("unsupported checkpoint version")
    vocab = Vocabulary.from_dict(checkpoint["vocabulary"])
    config = ModelConfig(**checkpoint["model_config"])
    if config.vocab_size != len(vocab):
        raise ValueError("checkpoint vocabulary/model size mismatch")
    model = MacroPolicyValue(config).to(device)
    model.load_state_dict(checkpoint["model_state"], strict=True)
    model.eval()
    return model, vocab, checkpoint


@torch.inference_mode()
def predict(checkpoint_path: str | Path, record: dict, *, device: str = "cpu") -> dict:
    validate_record(record)
    model, vocab, checkpoint = load_checkpoint(checkpoint_path, device=device)
    outputs = model(collate_records([record], vocab, device))
    probabilities = outputs["policy_logits"][0].softmax(-1).cpu().tolist()
    ranked = sorted(
        (
            {"action_id": c["action_id"], "entity_id": c.get("entity_id"), "probability": p}
            for c, p in zip(record["candidates"], probabilities, strict=True)
        ),
        key=lambda row: row["probability"],
        reverse=True,
    )
    value_trained = (
        checkpoint["training_audit"]["value_labels"] > 0
        and checkpoint["train_config"]["value_weight"] > 0
    )
    return {
        "ranked_actions": ranked,
        "outcome_probability": float(outputs["value_logits"].sigmoid()[0])
        if value_trained
        else None,
        "value_head_trained": value_trained,
        "state_quality": record["observation"]["state_quality"],
        "interpretation": "imitation scores and observational outcome prediction, not proven action quality",
    }
