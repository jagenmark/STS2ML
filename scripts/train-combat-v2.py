"""Fit and select a fight-weighted public combat value model."""
import argparse
from collections import Counter
from dataclasses import dataclass
import gzip
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np

from sts2rl.combat_search_v2.artifact import CombatValueModel, export_model, sigmoid
from sts2rl.combat_search_v2.features import FEATURE_NAMES, VERSION
from sts2rl.combat_search_v2.seed_registry import (
    load_confirmation_registry, load_phase3_registry, load_registry, registry_sha256,
)

ARCHITECTURES = {"linear": (), "mlp32": (32, 16), "mlp64": (64, 32), "residual": ()}
RANDOM_SEED = 20261123


@dataclass
class Data:
    x: np.ndarray
    win: np.ndarray
    exit_hp: np.ndarray
    exit_fraction: np.ndarray
    weight: np.ndarray
    act: np.ndarray
    groups: np.ndarray
    summary: dict

    def with_potions(self, potions):
        return np.column_stack((self.x, np.asarray(potions, dtype=np.float32)))


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_data(data, lobbies, *, potion_diagnostic=False):
    features, labels, weights, acts, groups, potions = [], [], [], [], [], []
    outcomes, censors, support = Counter(), Counter(), Counter()
    exit_values = []
    for group, lobby in enumerate(lobbies):
        attempts = sorted((data / lobby.split / lobby.seed).glob("attempt-*"))
        matched = []
        for attempt in attempts:
            if not (attempt / "result.json").exists():
                continue
            row = json.loads((attempt / "result.json").read_bytes())
            if (row["seed"], row["index"], row["act_list"]) != (lobby.seed, lobby.index, lobby.mode):
                raise ValueError(f"Wrong lobby identity: {attempt}")
            if row["status"] == "complete":
                matched.append(attempt)
        if len(matched) != 1:
            raise ValueError(f"Expected exactly one complete episode for {lobby.seed}")
        with gzip.open(matched[0] / "combat-v2-recording.json.gz", "rt", encoding="utf-8") as stream:
            record = json.load(stream)
        if record["schema"] != VERSION or tuple(record["feature_names"]) != FEATURE_NAMES:
            raise ValueError(f"Incompatible feature schema for {lobby.seed}")
        fights = {f["id"]: f for f in record["fights"]}
        outcomes.update(f["outcome"] for f in fights.values())
        usable = [t for t in record["turns"] if "x" in t and fights[t["fight"]]["outcome"] in
                  ("victory", "dead", "escape")]
        censors.update(t["censor"] for t in record["turns"] if "censor" in t)
        counts = Counter(t["fight"] for t in usable)
        support.update(fights[fight]["act"] for fight in counts)
        for turn in usable:
            fight = fights[turn["fight"]]
            win = fight["outcome"] == "victory"
            features.append(turn["x"])
            labels.append(win)
            weights.append(1 / counts[turn["fight"]])
            exit_hp = fight["exit_hp"] if win else 0
            exit_values.append((exit_hp, exit_hp / fight["exit_max_hp"]))
            acts.append(fight["act"])
            groups.append(group)
            if potion_diagnostic:
                potions.append(turn["potion_count"])
    exit_hp, exit_fraction = np.asarray(exit_values, dtype=np.float32).T
    x = np.asarray(features, dtype=np.float32)
    if x.shape != (len(labels), len(FEATURE_NAMES)) or not np.isfinite(x).all():
        raise ValueError("Invalid training feature array")
    dataset = Data(x, np.asarray(labels, dtype=np.float32), exit_hp, exit_fraction,
                   np.asarray(weights, dtype=np.float32), np.asarray(acts), np.asarray(groups),
                   {"lobbies": len(lobbies), "leaves": len(x), "fit_fights_by_act": dict(support),
                    "all_fight_outcomes": dict(outcomes), "censored_turns": dict(censors)})
    return dataset, potions


def split_dev(rows):
    calibration, selection = [], []
    for mode in ("default", "seeded"):
        dev = [row for row in rows if row.split == "dev" and row.mode == mode]
        dev.sort(key=lambda row: hashlib.sha256(f"phase2-calibration/{row.seed}".encode()).digest())
        calibration.extend(dev[:len(dev) // 2])
        selection.extend(dev[len(dev) // 2:])
    return calibration, selection


def fit_model(dataset, widths, *, features=None, residual=False):
    import torch
    from torch import nn
    from torch.nn import functional as loss

    device = torch.device("cuda:0")
    torch.manual_seed(RANDOM_SEED)
    rng = np.random.default_rng(RANDOM_SEED)
    x = dataset.x if features is None else features
    mean = np.average(x, weights=dataset.weight, axis=0).astype(np.float32)
    variance = np.average((x - mean) ** 2, weights=dataset.weight, axis=0)
    scale = np.float32(1) / np.maximum(np.sqrt(variance), np.float32(0.1))
    standardized = (x - mean) * scale
    prior = np.zeros((mean.size, 2), dtype=np.float32)
    fixed = []
    if residual:
        # Fit contextual corrections around a monotone public HP/block/damage
        # heuristic. Folding the affine prior into the export keeps inference
        # identical to an ordinary two-head linear model.
        for i, name in enumerate(FEATURE_NAMES):
            if name in ("player.hp", "player.block", "living_hp", "living_count",
                        "effective_poison_progress", "damage_dealt_fraction", "living_log_hp",
                        "player.hp_fraction") or (
                            name.startswith("enemy.") and name.split(".")[1].isdigit()
                            and name.split(".")[-1] in ("hp", "hp_fraction", "log_hp")):
                fixed.append(i)
        for name, coefficient in {"player.hp": .07, "player.block": .025, "living_hp": -.012,
                                  "living_count": -.15, "enemy.0.hp": -.004,
                                  "damage_dealt_fraction": .35, "effective_poison_progress": .28}.items():
            i = FEATURE_NAMES.index(name)
            prior[i] = np.asarray([coefficient, coefficient * .65]) / scale[i]
    offset = torch.tensor(standardized @ prior, device=device)
    standardized[:, fixed] = 0
    x = torch.tensor(standardized, device=device)
    y = torch.tensor(dataset.win, device=device)
    hp = torch.tensor(dataset.exit_fraction, device=device)
    weight = torch.tensor(dataset.weight / dataset.weight.mean(), device=device)
    dims = (mean.size, *widths, 2)
    linears = [nn.Linear(left, right) for left, right in zip(dims, dims[1:])]
    sequence = [layer for linear in linears[:-1] for layer in (linear, nn.ReLU())]
    model = nn.Sequential(*sequence, linears[-1]).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.004 if widths else 0.012,
                                  weight_decay=0.03 if widths else 0.12, foreach=False)
    epochs = 36 if widths else 44
    schedule = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, epochs, eta_min=0.0003)
    for _ in range(epochs):
        order = rng.permutation(len(x))
        for start in range(0, len(x), 1024):
            i = torch.as_tensor(order[start:start + 1024], device=device)
            z = model(x[i]) + offset[i]
            win_loss = loss.binary_cross_entropy_with_logits(z[:, 0], y[i], reduction="none")
            hp_loss = loss.huber_loss(z[:, 1].sigmoid(), hp[i], reduction="none", delta=0.1)
            objective = (weight[i] * (win_loss + 4 * y[i] * hp_loss)).mean()
            optimizer.zero_grad(set_to_none=True)
            objective.backward()
            optimizer.step()
        schedule.step()
    torch.cuda.synchronize(device)
    layers = tuple((layer.weight.detach().cpu().numpy().T.copy(), layer.bias.detach().cpu().numpy().copy())
                   for layer in linears)
    if residual:
        layers[0][0][fixed] = prior[fixed]
    return mean, scale, layers


def logits(features, params):
    mean, scale, layers = params
    values = (features - mean) * scale
    for i, (weights, bias) in enumerate(layers):
        values = values @ weights + bias
        if i < len(layers) - 1:
            values = np.maximum(values, np.float32(0))
    return values


def fit_platt(logit, data):
    """Two-parameter, positive-slope weighted logistic recalibration."""
    x = np.column_stack((logit.astype(np.float64), np.ones(len(logit))))
    y = data.win
    weight = data.weight.astype(np.float64)
    weight /= weight.sum()
    calibrator = np.array([1., 0.])
    ridge = 1e-5
    for _ in range(35):
        p = 1 / (1 + np.exp(-np.clip(x @ calibrator, -40, 40)))
        gradient = x.T @ (weight * (p - y)) + ridge * (calibrator - [1, 0])
        hessian = x.T @ (x * (weight * p * (1 - p))[:, None]) + ridge * np.eye(2)
        change = np.linalg.solve(hessian, gradient)
        calibrator -= change
        calibrator[0] = np.clip(calibrator[0], 0.02, 10)
        if np.max(np.abs(change)) < 1e-8:
            break
    return calibrator.astype(np.float32)


def calibrated(raw, calibration):
    result = raw.copy()
    result[:, 0] = result[:, 0] * calibration[0] + calibration[1]
    return sigmoid(result)


def metrics(data, result, mask=None):
    if mask is None:
        mask = np.ones(len(result), dtype=bool)
    if not mask.any():
        return {"leaves": 0}
    prob, fraction = result[mask].T
    prob = np.clip(prob.astype(np.float64), 1e-7, 1 - 1e-7)
    weight = data.weight[mask]
    y = data.win[mask]
    won = y > 0
    return {
        "leaves": int(mask.sum()), "weighted_fights": float(weight.sum()),
        "lobbies": int(len(set(data.groups[mask]))),
        "mean_prediction": float(np.average(prob, weights=weight)),
        "observed_win_rate": float(np.average(y, weights=weight)),
        "brier": float(np.average((prob - y) ** 2, weights=weight)),
        "log_loss": float(np.average(-y * np.log(prob) - (1 - y) * np.log1p(-prob), weights=weight)),
        "win_hp_fraction_mae": float(np.average(np.abs(fraction[won] - data.exit_fraction[mask][won]),
                                               weights=weight[won])) if won.any() else None,
        "win_hp_mae": float(np.average(np.abs(fraction[won] * data.x[mask, 1][won] - data.exit_hp[mask][won]),
                                      weights=weight[won])) if won.any() else None,
        "expected_hp_mae": float(np.average(np.abs(prob * fraction * data.x[mask, 1] - data.exit_hp[mask]),
                                            weights=weight)),
    }


def detailed_metrics(data, prediction):
    hp = data.x[:, 2]
    group_buckets = {}
    for act in (1, 2, 3):
        mask = data.act == act
        group_buckets[str(act)] = {"all": metrics(data, prediction, mask)}
        for lo, hi in ((0, .25), (.25, .5), (.5, .75), (.75, 1.01)):
            group_buckets[str(act)][f"{lo:g}–{min(hi, 1):g}"] = metrics(
                data, prediction, mask & (hp >= lo) & (hp < hi))
    bins = []
    probability = prediction[:, 0]
    rng = np.random.default_rng(RANDOM_SEED)
    for low in range(0, 100, 10):
        mask = (probability >= low / 100) & (probability < (low + 10.01) / 100)
        if low < 90:
            mask &= probability < (low + 10) / 100
        bucket = metrics(data, prediction, mask)
        if mask.any():
            _, index = np.unique(data.groups[mask], return_inverse=True)
            weights = np.bincount(index, weights=data.weight[mask])
            wins = np.bincount(index, weights=data.weight[mask] * data.win[mask])
            draws = rng.integers(len(weights), size=(1000, len(weights)))
            observed = wins[draws].sum(axis=1) / weights[draws].sum(axis=1)
            bucket["observed_win_rate_seed_ci"] = np.quantile(observed, [.025, .975]).tolist()
        bins.append({"min": low / 100, "max": (low + 10) / 100, **bucket})
    return {"overall": metrics(data, prediction), "act_and_hp_fraction": group_buckets, "reliability": bins}


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def fit(args, rows):
    import torch

    if not torch.version.hip or not torch.cuda.is_available() or "9070 XT" not in torch.cuda.get_device_name(0):
        raise SystemExit("Training requires the RX 9070 XT ROCm runtime on cuda:0")
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    args.output.mkdir(parents=True, exist_ok=False)
    train, train_potions = load_data(args.data, [row for row in rows if row.split == "train"], potion_diagnostic=True)
    calibration_rows, selection_rows = split_dev(rows)
    calibration, calibration_potions = load_data(args.data, calibration_rows, potion_diagnostic=True)
    dev, dev_potions = load_data(args.data, selection_rows, potion_diagnostic=True)
    report = {"device": torch.cuda.get_device_name(0), "torch": torch.__version__, "rocm": torch.version.hip,
              "registry_sha256": registry_sha256(rows), "train": train.summary,
              "calibration": calibration.summary, "selection": dev.summary, "candidates": {}}
    for name, widths in ARCHITECTURES.items():
        print(f"{name} on {report['device']}", flush=True)
        params = fit_model(train, widths, residual=name == "residual")
        platt = fit_platt(logits(calibration.x, params)[:, 0], calibration)
        raw = logits(dev.x, params)
        artifact = args.output / f"{name}.npz"
        export_model(artifact, *params, platt, widths)
        numpy_model = CombatValueModel.load(artifact)
        prediction = numpy_model.predict(dev.x)
        np.testing.assert_allclose(prediction, calibrated(raw, platt), rtol=0, atol=1e-6)
        report["candidates"][name] = {"widths": widths, "sha256": fingerprint(artifact),
                                      "calibration": platt.tolist(), "raw": metrics(dev, sigmoid(raw)),
                                      "calibrated": detailed_metrics(dev, prediction)}
        save(args.output / "dev-metrics.json", report)
    best = min(report["candidates"], key=lambda name: report["candidates"][name]["calibrated"]["overall"]["brier"])
    potion_params = fit_model(train, ARCHITECTURES[best], features=train.with_potions(train_potions),
                             residual=best == "residual")
    potion_platt = fit_platt(logits(calibration.with_potions(calibration_potions), potion_params)[:, 0], calibration)
    potion_metrics = metrics(dev, calibrated(logits(dev.with_potions(dev_potions), potion_params), potion_platt))
    report["offline_potion_count"] = {"model": best, "metrics": potion_metrics,
                                      "brier_delta": potion_metrics["brier"] - report["candidates"][best]
                                      ["calibrated"]["overall"]["brier"]}
    save(args.output / "dev-metrics.json", report)


def finalize(args, rows):
    report = json.loads((args.output / "dev-metrics.json").read_bytes())
    times = json.loads((args.output / "cpu-latency.json").read_bytes())
    eligible = [name for name, receipt in times.items() if receipt["p95_ms"] < .1
                and (not args.phase3 or min(receipt["damage_sensitivity"].values()) > 1e-4)
                and receipt["artifact_sha256"] == report["candidates"][name]["sha256"]]
    if not eligible:
        raise SystemExit("No candidate satisfies the CPU p95 latency gate")
    winner = min(eligible, key=lambda name: report["candidates"][name]["calibrated"]["overall"]["brier"])
    model_path = args.output / "combat_value_v2.npz"
    source = args.output / f"{winner}.npz"
    sha = fingerprint(source)
    if sha != report["candidates"][winner]["sha256"]:
        raise ValueError("Selected artifact checksum mismatch")
    freeze = {"model": winner, "artifact_sha256": sha, "registry_sha256": registry_sha256(rows),
              "selection_brier": report["candidates"][winner]["calibrated"]["overall"]["brier"],
              "cpu_latency": times[winner]}
    with (args.output / "selection-freeze.json").open("x", encoding="utf-8") as stream:
        json.dump(freeze, stream, indent=2)
    shutil.copyfile(source, model_path)
    if args.stage == "select":
        print(json.dumps(freeze), flush=True)
        return
    model = CombatValueModel.load(model_path)
    sealed, _ = load_data(args.data, [row for row in rows if row.split == "test"])
    result = {**freeze, "support": sealed.summary, "test": detailed_metrics(sealed, model.predict(sealed.x))}
    save(args.output / "sealed-test.json", result)
    print(json.dumps({**freeze, **result["test"]["overall"]}), flush=True)


def confirm(args, rows):
    freeze = json.loads((args.output / "selection-freeze.json").read_bytes())
    path = args.output / "combat_value_v2.npz"
    registry = load_phase3_registry() if args.phase3 else load_registry()
    if (freeze["registry_sha256"] != registry_sha256(registry)
            or freeze["artifact_sha256"] != fingerprint(path)):
        raise ValueError("Correction selection or model checksum mismatch")
    model = CombatValueModel.load(path)
    receipt = {**freeze, "confirmation_registry_sha256": registry_sha256(rows)}
    with (args.output / "confirmation-open.json").open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2)
    sealed, _ = load_data(args.data, rows)
    report = {**receipt, "support": sealed.summary,
              "test": detailed_metrics(sealed, model.predict(sealed.x))}
    save(args.output / "sealed-test.json", report)
    print(json.dumps({**receipt, **report["test"]["overall"]}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("fit", "select", "finalize", "confirm"))
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--phase3", action="store_true")
    args = parser.parse_args()
    confirmation = args.stage == "confirm"
    rows = load_phase3_registry() if args.phase3 else load_confirmation_registry() if confirmation else load_registry()
    collection = json.loads((args.data / "collection.json").read_bytes())
    census = json.loads((args.data / "coverage-census.json").read_bytes())
    fit_only = collection.get("fit_only", False)
    if args.phase3:
        phase = "test" if confirmation else "fit"
        if args.stage == "finalize" or collection.get("phase3") != phase or collection["champion_sha256"] != (
                "8636337a6082264bffffe9a79b50528bdf30ed9096b74ff33fd20a8e844fa51b"):
            parser.error("Phase 3 selection and one-pass sealed evaluation require separate v4 collections")
        expected = sum(row.split in (("test",) if confirmation else ("train", "dev")) for row in rows)
    else:
        expected = sum(row.split != "test" for row in rows) if fit_only else len(rows)
    if collection["registry_sha256"] != registry_sha256(rows) or census["runs"] != expected:
        parser.error("Complete locked collection required")
    if args.stage == "finalize" and fit_only:
        parser.error("Sealed test is absent from this collection")
    if not args.phase3 and bool(collection.get("confirmation_only")) != confirmation:
        parser.error("Confirm requires the separate locked test collection")
    if args.phase3 and confirmation:
        rows = [row for row in rows if row.split == "test"]
    {"fit": fit, "select": finalize, "finalize": finalize, "confirm": confirm}[args.stage](args, rows)


if __name__ == "__main__":
    main()
