"""Train, calibrate, parity-check, and export the Schema 4 combat value MLP on ROCm/CPU."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from sts2rl.combat_search_v2.artifact import CombatValueModel, export_model
from sts2rl.combat_search_v2.features import SCHEMA4_NAMES, SCHEMA5_NAMES


def build_mlp(in_dim: int, widths: tuple[int, ...], dropout: float = 0.10) -> nn.Sequential:
    layers: list[nn.Module] = []
    prev = in_dim
    for w in widths:
        layers.append(nn.Linear(prev, w))
        layers.append(nn.ReLU())
        if dropout > 0:
            layers.append(nn.Dropout(dropout))
        prev = w
    layers.append(nn.Linear(prev, 2))
    return nn.Sequential(*layers)


def extract_linear_layers(net: nn.Sequential) -> list[tuple[np.ndarray, np.ndarray]]:
    out = []
    for mod in net:
        if isinstance(mod, nn.Linear):
            w = mod.weight.detach().cpu().numpy().T.astype(np.float32)
            b = mod.bias.detach().cpu().numpy().astype(np.float32)
            out.append((w, b))
    return out


def fit_temperature(logits: np.ndarray, targets: np.ndarray) -> tuple[float, float]:
    lt = torch.from_numpy(logits.astype(np.float32))
    yt = torch.from_numpy(targets.astype(np.float32))
    a = torch.tensor(1.0, requires_grad=True)
    b = torch.tensor(0.0, requires_grad=True)
    opt = torch.optim.LBFGS([a, b], lr=0.5, max_iter=60, line_search_fn="strong_wolfe")

    def closure():
        opt.zero_grad()
        loss = F.binary_cross_entropy_with_logits(lt * torch.clamp(a, min=0.05) + b, yt)
        loss.backward()
        return loss

    opt.step(closure)
    return float(max(0.05, a.item())), float(b.item())


def train_one(
    x_tr: np.ndarray,
    yw_tr: np.ndarray,
    yh_tr: np.ndarray,
    sw_tr: np.ndarray,
    x_va: np.ndarray,
    yw_va: np.ndarray,
    yh_va: np.ndarray,
    widths: tuple[int, ...],
    device: torch.device,
    epochs: int = 35,
    batch_size: int = 2048,
    dropout: float = 0.10,
    weight_decay: float = 1.5e-3,
    seed: int = 42,
):
    torch.manual_seed(seed)
    net = build_mlp(x_tr.shape[1], widths, dropout=dropout).to(device)
    opt = torch.optim.AdamW(net.parameters(), lr=2e-3, weight_decay=weight_decay)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(1, epochs))

    xt = torch.from_numpy(x_tr).to(device)
    ywt = torch.from_numpy(yw_tr).to(device)
    yht = torch.from_numpy(yh_tr).to(device)
    swt = torch.from_numpy(sw_tr).to(device)
    xv = torch.from_numpy(x_va).to(device)
    ywv = torch.from_numpy(yw_va).to(device)
    yhv = torch.from_numpy(yh_va).to(device)

    n = xt.shape[0]
    best_val = 1e9
    best_state = None
    best_ep = 0

    for ep in range(1, epochs + 1):
        net.train()
        perm = torch.randperm(n, device=device)
        for i in range(0, n, batch_size):
            idx = perm[i : i + batch_size]
            out = net(xt[idx])
            bw = swt[idx]
            bw = bw / bw.mean().clamp(min=1e-6)
            win_loss = (F.binary_cross_entropy_with_logits(out[:, 0], ywt[idx], reduction="none") * bw).mean()
            win_mask = ywt[idx] > 0.5
            if win_mask.any():
                hp_pred = torch.sigmoid(out[win_mask, 1])
                hp_w = bw[win_mask]
                hp_w = hp_w / hp_w.mean().clamp(min=1e-6)
                hp_loss = (F.smooth_l1_loss(hp_pred, yht[idx][win_mask], beta=0.05, reduction="none") * hp_w).mean()
            else:
                hp_loss = out.sum() * 0.0
            loss = win_loss + 2.5 * hp_loss
            opt.zero_grad()
            loss.backward()
            opt.step()
        sched.step()

        net.eval()
        with torch.no_grad():
            vo = net(xv)
            vw = F.binary_cross_entropy_with_logits(vo[:, 0], ywv).item()
            wm = ywv > 0.5
            vh = (
                F.smooth_l1_loss(torch.sigmoid(vo[wm, 1]), yhv[wm], beta=0.05).item()
                if wm.any()
                else 0.0
            )
            v_tot = vw + 2.5 * vh
            if v_tot < best_val:
                best_val = v_tot
                best_ep = ep
                best_state = {k: v.detach().cpu().clone() for k, v in net.state_dict().items()}

    if best_state is not None:
        net.load_state_dict(best_state)
    net.eval()
    with torch.no_grad():
        val_logits = net(xv).cpu().numpy()
    cal = fit_temperature(val_logits[:, 0], yw_va)
    return net, cal, best_val, best_ep


def evaluate_np(model: CombatValueModel, x: np.ndarray, yw: np.ndarray, yh: np.ndarray) -> dict:
    preds = model.predict(x)
    pw = np.clip(preds[:, 0], 1e-6, 1.0 - 1e-6)
    ph = preds[:, 1]
    bce = float(-np.mean(yw * np.log(pw) + (1.0 - yw) * np.log(1.0 - pw)))
    brier = float(np.mean((pw - yw) ** 2))
    acc = float(np.mean((pw >= 0.5) == (yw >= 0.5)))
    wm = yw > 0.5
    hp_mae = float(np.mean(np.abs(ph[wm] - yh[wm]))) if wm.any() else 0.0
    return {
        "n": int(len(yw)),
        "win_rate": round(float(np.mean(yw)), 4),
        "bce": round(bce, 4),
        "brier": round(brier, 4),
        "win_acc": round(acc, 4),
        "hp_mae": round(hp_mae, 4),
    }


def evaluate_slices(model: CombatValueModel, x: np.ndarray, yw: np.ndarray, yh: np.ndarray, names: tuple[str, ...]) -> dict:
    out = {"all": evaluate_np(model, x, yw, yh)}
    ia1, ia2, ia3, ib = [names.index(k) for k in ("act.1", "act.2", "act.3", "room.Boss")]
    slices = {
        "act1": x[:, ia1] > 0.5,
        "act2": x[:, ia2] > 0.5,
        "act3": x[:, ia3] > 0.5,
        "boss": x[:, ib] > 0.5,
        "a2_boss": (x[:, ia2] > 0.5) & (x[:, ib] > 0.5),
        "a3_boss": (x[:, ia3] > 0.5) & (x[:, ib] > 0.5),
    }
    if "s5.kaiser_crusher_hp" in names:
        ic = names.index("s5.kaiser_crusher_hp")
        ir = names.index("s5.kaiser_rocket_hp")
        slices["kaiser"] = (x[:, ic] > 0) | (x[:, ir] > 0)
        slices["kaiser_2arm"] = (x[:, ic] > 0) & (x[:, ir] > 0)
    for key, mask in slices.items():
        if mask.any():
            out[key] = evaluate_np(model, x[mask], yw[mask], yh[mask])
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--schema", type=int, choices=(4, 5), default=4)
    parser.add_argument("--epochs", type=int, default=35)
    parser.add_argument("--late-weight", type=float, default=2.0)
    parser.add_argument("--kaiser-weight", type=float, default=1.0)
    parser.add_argument("--act3-weight", type=float, default=1.0)
    args = parser.parse_args()

    names = SCHEMA4_NAMES if args.schema == 4 else SCHEMA5_NAMES
    t0 = time.time()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    dev_name = torch.cuda.get_device_name(0) if device.type == "cuda" else "CPU"
    print(f"Training Schema {args.schema} ({len(names)} features) on {dev_name} ({device})")

    xs, yws, yhs, rids = [], [], [], []
    uid_offset = 0
    for dp in args.data:
        with np.load(dp) as d:
            xs.append(d["X"].astype(np.float32))
            yws.append(d["y_win"].astype(np.float32))
            yhs.append(d["y_hp"].astype(np.float32))
            rid = d["run_id"].astype(np.int64) + uid_offset
            rids.append(rid)
            uid_offset = int(rid.max()) + 1 if len(rid) else uid_offset
    x_all = np.concatenate(xs, axis=0)
    yw_all = np.concatenate(yws, axis=0)
    yh_all = np.concatenate(yhs, axis=0)
    run_ids = np.concatenate(rids, axis=0)

    assert x_all.shape[1] == len(names), (x_all.shape, len(names))
    # Upweight Act 2/3 & Boss fights so late-game decisions aren't drowned out by Act 1 hallways
    idx_act2 = names.index("act.2")
    idx_act3 = names.index("act.3")
    idx_boss = names.index("room.Boss")
    sw_all = (
        1.0
        + (args.late_weight - 1.0) * ((x_all[:, idx_act2] > 0.5) | (x_all[:, idx_act3] > 0.5)).astype(np.float32)
        + (args.late_weight - 1.0) * (x_all[:, idx_boss] > 0.5).astype(np.float32)
    ).astype(np.float32)
    if args.kaiser_weight > 1.0 and "s5.kaiser_crusher_hp" in names:
        ic = names.index("s5.kaiser_crusher_hp")
        ir = names.index("s5.kaiser_rocket_hp")
        k_mask = ((x_all[:, ic] > 0) | (x_all[:, ir] > 0)).astype(np.float32)
        sw_all = sw_all * (1.0 + (args.kaiser_weight - 1.0) * k_mask)
    if args.act3_weight > 1.0:
        a3_mask = (x_all[:, idx_act3] > 0.5).astype(np.float32)
        sw_all = sw_all * (1.0 + (args.act3_weight - 1.0) * a3_mask)

    # Strict run-disjoint split (80/10/10)
    buckets = (run_ids * 2654435761) % 100
    m_tr = buckets < 80
    m_va = (buckets >= 80) & (buckets < 90)
    m_te = buckets >= 90
    if not m_va.any() or not m_te.any():
        n = len(run_ids)
        m_tr = np.arange(n) < max(1, int(0.7 * n))
        m_va = (np.arange(n) >= max(1, int(0.7 * n))) & (np.arange(n) < max(2, int(0.85 * n)))
        m_te = np.arange(n) >= max(2, int(0.85 * n))

    mean = x_all[m_tr].mean(axis=0).astype(np.float32)
    std = x_all[m_tr].std(axis=0).astype(np.float32)
    std_floor = np.float32(0.05 if args.schema == 5 else 1e-3)
    scale = (1.0 / np.maximum(std, std_floor)).astype(np.float32)

    def norm(x):
        return (x - mean) * scale

    x_tr, x_va, x_te = norm(x_all[m_tr]), norm(x_all[m_va]), norm(x_all[m_te])
    yw_tr, yw_va, yw_te = yw_all[m_tr], yw_all[m_va], yw_all[m_te]
    yh_tr, yh_va, yh_te = yh_all[m_tr], yh_all[m_va], yh_all[m_te]
    sw_tr = sw_all[m_tr]
    print(f"Samples: total={len(x_all):,} | train={len(x_tr):,} | val={len(x_va):,} | test={len(x_te):,}")

    if args.schema == 5:
        candidates = [(128, 64), (128, 64, 32), (256, 128, 64)]
        dropout, wd = 0.15, 2.5e-3
    else:
        candidates = [(64, 32), (128, 64), (128, 64, 32)]
        dropout, wd = 0.10, 1.5e-3

    results = []
    best = None
    for widths in candidates:
        net, cal, v_loss, best_ep = train_one(
            x_tr, yw_tr, yh_tr, sw_tr, x_va, yw_va, yh_va, widths, device,
            epochs=args.epochs, dropout=dropout, weight_decay=wd,
        )
        layers = extract_linear_layers(net)
        tmp_model = CombatValueModel(mean, scale, tuple(layers), np.asarray(cal, dtype=np.float32), schema=args.schema)
        va_m = evaluate_np(tmp_model, x_all[m_va], yw_va, yh_va)
        te_m = evaluate_np(tmp_model, x_all[m_te], yw_te, yh_te)
        rec = {
            "widths": list(widths),
            "best_epoch": best_ep,
            "val_loss": round(v_loss, 4),
            "calibration": [round(cal[0], 4), round(cal[1], 4)],
            "val": va_m,
            "test": te_m,
        }
        results.append(rec)
        print(f"  widths={widths}: ep={best_ep} val={va_m} | test={te_m}")
        if best is None or v_loss < best[0]:
            best = (v_loss, widths, layers, cal, net, rec)

    _, widths, layers, cal, best_net, best_rec = best
    out = args.output.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    export_model(out, mean, scale, layers, cal, widths, schema=args.schema)

    # Verify exact PyTorch vs NumPy parity on test slice
    loaded = CombatValueModel.load(out)
    sample_x = x_all[m_te][: min(128, len(x_te))]
    np_out = loaded.predict(sample_x)
    best_net.eval()
    with torch.no_grad():
        raw_t = best_net(torch.from_numpy(norm(sample_x)).to(device)).cpu().numpy()
    raw_t[:, 0] = raw_t[:, 0] * cal[0] + cal[1]
    t_out = 1.0 / (1.0 + np.exp(-np.clip(raw_t, -30.0, 30.0)))
    max_diff = float(np.max(np.abs(np_out - t_out)))
    if max_diff > 1e-4:
        raise RuntimeError(f"Schema {args.schema} NumPy parity check failed: max_diff={max_diff:.6g}")

    test_slices = evaluate_slices(loaded, x_all[m_te], yw_te, yh_te, names)
    print(f"  Test slices: {test_slices}")

    sha = hashlib.sha256(out.read_bytes()).hexdigest()
    elapsed = round(time.time() - t0, 1)
    print(f"Exported {out} ({out.stat().st_size:,} bytes, sha256={sha[:16]}..., parity={max_diff:.2e}, {elapsed}s)")

    if args.report:
        report = {
            "schema": args.schema,
            "device": dev_name,
            "elapsed_s": elapsed,
            "features": len(names),
            "samples": {"total": int(len(x_all)), "train": int(len(x_tr)), "val": int(len(x_va)), "test": int(len(x_te))},
            "candidates": results,
            "selected": best_rec,
            "test_slices": test_slices,
            "parity_max_diff": max_diff,
            "sha256": sha,
            "path": str(out),
        }
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
