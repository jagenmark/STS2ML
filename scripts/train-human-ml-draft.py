"""Train and export the frozen v0.111.0 human Silent A10 Contextual Residual MLP draft artifact."""

from __future__ import annotations

import argparse
from collections import Counter
import glob
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import time

os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from sts2rl.human_ml_draft import (
    DEFAULT_MODEL_PATH,
    FEAT_DIM,
    SCHEMA_VERSION,
    Z_DIM,
    HumanMLDraftModel,
    extract_card_features,
    extract_context_vec,
)
from sts2rl.unified_draft import ENERGY_RELICS


def _entity(value) -> str | None:
    return value.rsplit(".", 1)[-1].upper() if isinstance(value, str) and value else None


def _int(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _num(value) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if math.isfinite(value) else None
    return None


def _parse_deck(cards) -> dict[int, dict] | None:
    if not isinstance(cards, list):
        return None
    out = {}
    for card in cards:
        if not isinstance(card, dict):
            return None
        inst = _int(card.get("c"))
        ent = _entity(card.get("id"))
        if inst is None or ent is None:
            return None
        up = _int(card.get("up"))
        out[inst] = {"id": ent, "upgrades": max(0, up or 0)}
    return out


def _load_events(path: Path) -> list[dict]:
    raw = path.read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return [json.loads(line) for line in raw.decode("utf-8-sig").splitlines() if line.strip()]


def load_listings(raw_dir: Path) -> dict[str, dict]:
    by_hash: dict[str, dict] = {}
    for fp in sorted(glob.glob(str(raw_dir / "listings" / "pass-*-page-*.json"))):
        data = json.loads(Path(fp).read_text(encoding="utf-8"))
        for row in data.get("runs", []):
            rh = row.get("run_hash")
            if rh:
                by_hash[rh] = row
    return by_hash


def extract_decisions(raw_dir: Path) -> tuple[list[dict], dict]:
    t0 = time.time()
    listings = load_listings(raw_dir)
    raw_files = sorted(raw_dir.glob("*.jsonl.gz"))
    clean_runs = []
    excluded = Counter()
    player_runs = Counter()
    player_wins = Counter()

    for fp in raw_files:
        run_hash = fp.name.removesuffix(".jsonl.gz")
        meta = listings.get(run_hash, {})
        try:
            events = _load_events(fp)
        except Exception:
            excluded["corrupt"] += 1
            continue
        if not events or events[0].get("t") != "header":
            excluded["missing_header"] += 1
            continue
        h = events[0]
        if h.get("build_id") != "v0.111.0":
            excluded["wrong_build"] += 1
            continue
        if _entity(h.get("character")) != "SILENT" or _int(h.get("ascension")) != 10:
            excluded["wrong_char_asc"] += 1
            continue
        if _int(h.get("player_count")) != 1 or h.get("game_mode") != "standard" or h.get("modifiers"):
            excluded["non_standard"] += 1
            continue
        mods = h.get("mods", [])
        if not isinstance(mods, list) or any(
            not isinstance(m, dict) or m.get("affects_gameplay") is not False for m in mods
        ):
            excluded["gameplay_mod"] += 1
            continue
        if h.get("full_console") is True or any(ev.get("t") == "console" for ev in events):
            excluded["console"] += 1
            continue

        win = None
        for ev in reversed(events):
            if ev.get("t") == "end":
                tr = ev.get("terminal_reason")
                if tr == "victory":
                    win = 1
                elif tr in ("death", "abandoned"):
                    win = 0
                break
        if win is None and "win" in meta:
            win = int(bool(meta["win"]))
        win = 0 if win is None else win

        player_id = meta.get("player_token") or meta.get("username") or f"anon:{run_hash}"
        player_runs[player_id] += 1
        player_wins[player_id] += win
        clean_runs.append((run_hash, events, meta, player_id, win))

    strong_players = {
        pid for pid, n in player_runs.items() if n >= 5 and (player_wins[pid] / n) >= 0.40
    }

    decisions = []
    for run_hash, events, _meta, player_id, win in clean_runs:
        h = events[0]
        deck = _parse_deck(h.get("starting_deck"))
        if not deck:
            continue
        relics = [_entity(r) for r in (h.get("starting_relics") or []) if _entity(r)]
        hp = _num(h.get("starting_max_hp"))
        max_hp = _num(h.get("starting_max_hp"))
        seed = h.get("seed")
        seed_group = f"seed:{str(seed).upper()}" if seed else f"run:{run_hash}"

        pending: dict[str, dict] = {}
        seen_resolved: set[str] = set()
        deck_known = True

        for ev in events[1:]:
            t = ev.get("t")
            did = str(ev["decision_id"]) if "decision_id" in ev else None
            if t == "deck":
                snap = _parse_deck(ev.get("cards"))
                if snap is not None:
                    deck = snap
                    deck_known = True
            elif t == "remap":
                mapping = {}
                for item in ev.get("cards") or []:
                    if isinstance(item, dict):
                        f_id, t_id = _int(item.get("from")), _int(item.get("to"))
                        if f_id is not None and t_id is not None:
                            mapping[f_id] = t_id
                if mapping:
                    deck = {mapping.get(k, k): v for k, v in deck.items()}
            elif t == "resume":
                if _num(ev.get("hp")) is not None:
                    hp = _num(ev.get("hp"))
                if isinstance(ev.get("relics"), list):
                    parsed_r = [
                        _entity(r.get("id") if isinstance(r, dict) else r) for r in ev["relics"]
                    ]
                    parsed_r = [r for r in parsed_r if r]
                    if parsed_r:
                        relics = parsed_r
            elif t == "decision" and ev.get("decision_type") == "card_reward":
                if did is None or did in seen_resolved or not deck_known:
                    continue
                if ev.get("can_reroll") is True or ev.get("offer_generation", 0) != 0:
                    continue
                options = ev.get("options")
                if not isinstance(options, list) or not options:
                    continue
                cands = []
                idx_map = {}
                malformed = False
                for opt in options:
                    if not isinstance(opt, dict):
                        malformed = True
                        break
                    if opt.get("presented") is not True or opt.get("selectable") is not True:
                        continue
                    oi = _int(opt.get("option_index"))
                    ent = _entity(opt.get("option_id"))
                    if oi is None or oi < 0 or oi in idx_map or not ent or opt.get("option_kind") != "card":
                        malformed = True
                        break
                    cand = {"kind": "card", "id": ent, "upgrades": max(0, _int(opt.get("up")) or 0)}
                    idx_map[oi] = (len(cands), opt.get("instance_id"), ent)
                    cands.append(cand)
                if malformed or not cands:
                    continue
                decline = bool(ev.get("decline_available", True))
                if decline:
                    cands.append({"kind": "skip", "id": "SKIP", "upgrades": 0})
                act = min(3, max(1, _int(ev.get("act")) or 1))
                g_floor = max(1, _int(ev.get("floor")) or 1)
                act_floor = min(17, max(1, g_floor - 17 * (act - 1)))
                pending[did] = {
                    "idx_map": idx_map,
                    "decline": decline,
                    "record": {
                        "seed_group": seed_group,
                        "win": win,
                        "is_strong": player_id in strong_players,
                        "act": act,
                        "act_floor": act_floor,
                        "hp": hp,
                        "max_hp": max_hp,
                        "deck": [dict(c) for c in deck.values()],
                        "relics": list(relics),
                        "candidates": cands,
                        "chosen_idx": None,
                    },
                }
            elif t == "outcome" and did in pending:
                entry = pending[did]
                oc = ev.get("outcome")
                if oc == "skip" and entry["decline"]:
                    entry["record"]["chosen_idx"] = len(entry["record"]["candidates"]) - 1
                    decisions.append(entry["record"])
                    seen_resolved.add(did)
                    del pending[did]
                elif oc in ("chosen", "select"):
                    oi = _int(ev.get("option_index"))
                    if oi in entry["idx_map"]:
                        entry["record"]["chosen_idx"] = entry["idx_map"][oi][0]
                        decisions.append(entry["record"])
                        seen_resolved.add(did)
                        del pending[did]
            elif t == "acquire":
                ent = _entity(ev.get("id"))
                inst = _int(ev.get("c"))
                selected_up = None
                if did in pending:
                    entry = pending[did]
                    oi = _int(ev.get("option_index"))
                    chosen_ci = None
                    if oi in entry["idx_map"] and entry["idx_map"][oi][2] == ent:
                        chosen_ci = entry["idx_map"][oi][0]
                    else:
                        matches = [
                            v[0]
                            for v in entry["idx_map"].values()
                            if v[1] == inst and inst is not None and v[2] == ent
                        ]
                        if len(matches) == 1:
                            chosen_ci = matches[0]
                    if chosen_ci is not None:
                        entry["record"]["chosen_idx"] = chosen_ci
                        selected_up = entry["record"]["candidates"][chosen_ci]["upgrades"]
                        decisions.append(entry["record"])
                        seen_resolved.add(did)
                        del pending[did]
                if ent is not None and inst is not None:
                    up = selected_up if selected_up is not None else max(0, _int(ev.get("up")) or 0)
                    deck[inst] = {"id": ent, "upgrades": up}
            elif t == "remove":
                inst = _int(ev.get("c"))
                if inst in deck:
                    del deck[inst]
            elif t == "upgrade":
                inst = _int(ev.get("c"))
                if inst in deck:
                    up = _int(ev.get("up"))
                    deck[inst]["upgrades"] = up if up is not None else deck[inst]["upgrades"] + 1
            elif t == "downgrade":
                inst = _int(ev.get("c"))
                if inst in deck:
                    up = _int(ev.get("up"))
                    deck[inst]["upgrades"] = max(0, up if up is not None else deck[inst]["upgrades"] - 1)
            elif t == "transform":
                old, new = _int(ev.get("from_c")), _int(ev.get("to_c"))
                ent = _entity(ev.get("to_id"))
                if old in deck:
                    del deck[old]
                if new is not None and ent is not None:
                    deck[new] = {"id": ent, "upgrades": max(0, _int(ev.get("up")) or 0)}
            elif t == "hp" and ev.get("dst", "player") in ("player", "SILENT"):
                if ev.get("mine") is not False and _num(ev.get("hp")) is not None:
                    hp = _num(ev.get("hp"))
            elif t == "max_hp" and ev.get("dst", "player") in ("player", "SILENT"):
                if _num(ev.get("max_hp")) is not None:
                    max_hp = _num(ev.get("max_hp"))
                if _num(ev.get("hp")) is not None:
                    hp = _num(ev.get("hp"))
            elif t == "relic":
                ent = _entity(ev.get("id"))
                if ent:
                    relics.append(ent)
            elif t == "relic_lost":
                ent = _entity(ev.get("id"))
                if ent and ent in relics:
                    relics.remove(ent)

    info = {
        "clean_runs": len(clean_runs),
        "wins": sum(r[4] for r in clean_runs),
        "strong_players": len(strong_players),
        "decisions": len(decisions),
        "strong_decisions": sum(d["is_strong"] for d in decisions),
        "elapsed_s": round(time.time() - t0, 1),
    }
    return decisions, info


def assign_split(seed_group: str) -> str:
    h = int(hashlib.sha256(seed_group.encode()).hexdigest()[:8], 16) % 100
    return "train" if h < 75 else "val" if h < 85 else "test"


def featurize(decisions: list[dict], vocab: list[str]) -> list[dict]:
    card_to_idx = {cid: i for i, cid in enumerate(vocab)}
    rows = []
    for d in decisions:
        rset = set(d["relics"])
        max_energy = 3 + sum(1 for r in ENERGY_RELICS if r in rset)
        z, ctx = extract_context_vec(
            d["deck"],
            act=d["act"],
            act_floor=d["act_floor"],
            max_energy=max_energy,
            stone_dex=1.0 if "ODDLY_SMOOTH_STONE" in rset else 0.0,
            paper_krane=1.0 if "PAPER_KRANE" in rset else 0.0,
            hp=d["hp"],
            max_hp=d["max_hp"],
        )
        c_ids, c_is_skip, c_up, c_dup, c_feats = [], [], [], [], []
        for cand in d["candidates"]:
            if cand["kind"] == "skip":
                c_ids.append(0)
                c_is_skip.append(1.0)
                c_up.append(0.0)
                c_dup.append(0.0)
                c_feats.append(np.zeros(FEAT_DIM, dtype=np.float32))
            else:
                c, feats, up, dup = extract_card_features(cand, z, ctx)
                c_ids.append(card_to_idx.get(c["id"], 0))
                c_is_skip.append(0.0)
                c_up.append(up)
                c_dup.append(dup)
                c_feats.append(feats)
        rows.append(
            {
                "split": assign_split(d["seed_group"]),
                "z": z,
                "c_ids": np.array(c_ids, dtype=np.int64),
                "c_is_skip": np.array(c_is_skip, dtype=np.float32),
                "c_up": np.array(c_up, dtype=np.float32),
                "c_dup": np.array(c_dup, dtype=np.float32),
                "c_feats": np.stack(c_feats, axis=0),
                "chosen": int(d["chosen_idx"]),
                "act": int(d["act"]),
                "win": int(d["win"]),
                "is_strong": bool(d["is_strong"]),
                "has_skip": bool(c_is_skip[-1] > 0.5),
            }
        )
    return rows


def collate(items: list[dict]) -> dict[str, torch.Tensor]:
    n = len(items)
    k_max = max(len(x["c_ids"]) for x in items)
    z = np.zeros((n, Z_DIM), dtype=np.float32)
    c_ids = np.zeros((n, k_max), dtype=np.int64)
    c_is_skip = np.zeros((n, k_max), dtype=np.float32)
    c_up = np.zeros((n, k_max), dtype=np.float32)
    c_dup = np.zeros((n, k_max), dtype=np.float32)
    c_feats = np.zeros((n, k_max, FEAT_DIM), dtype=np.float32)
    mask = np.zeros((n, k_max), dtype=np.bool_)
    chosen = np.zeros(n, dtype=np.int64)
    act_idx = np.zeros(n, dtype=np.int64)
    win = np.zeros(n, dtype=np.float32)
    strong = np.zeros(n, dtype=np.float32)
    has_skip = np.zeros(n, dtype=np.bool_)

    for i, x in enumerate(items):
        k = len(x["c_ids"])
        z[i] = x["z"]
        c_ids[i, :k] = x["c_ids"]
        c_is_skip[i, :k] = x["c_is_skip"]
        c_up[i, :k] = x["c_up"]
        c_dup[i, :k] = x["c_dup"]
        c_feats[i, :k] = x["c_feats"]
        mask[i, :k] = True
        chosen[i] = x["chosen"]
        act_idx[i] = x["act"] - 1
        win[i] = x["win"]
        strong[i] = 1.0 if x["is_strong"] else 0.0
        has_skip[i] = x["has_skip"]

    return {
        "z": torch.from_numpy(z),
        "c_ids": torch.from_numpy(c_ids),
        "c_is_skip": torch.from_numpy(c_is_skip),
        "c_up": torch.from_numpy(c_up),
        "c_dup": torch.from_numpy(c_dup),
        "c_feats": torch.from_numpy(c_feats),
        "mask": torch.from_numpy(mask),
        "chosen": torch.from_numpy(chosen),
        "act_idx": torch.from_numpy(act_idx),
        "win": torch.from_numpy(win),
        "strong": torch.from_numpy(strong),
        "has_skip": torch.from_numpy(has_skip),
    }


class ContextualResidualMLP(nn.Module):
    def __init__(self, vocab_size: int, emb_dim: int = 16, hid: int = 48, skip_hid: int = 24):
        super().__init__()
        self.card_bias = nn.Embedding(vocab_size, 1)
        self.card_act = nn.Embedding(vocab_size, 3)
        self.card_up = nn.Embedding(vocab_size, 1)
        self.card_dup = nn.Embedding(vocab_size, 1)
        self.feat_w = nn.Linear(FEAT_DIM, 1, bias=False)
        self.skip_w = nn.Linear(Z_DIM, 1, bias=True)
        for m in (self.card_bias, self.card_act, self.card_up, self.card_dup):
            nn.init.zeros_(m.weight)
        nn.init.zeros_(self.feat_w.weight)
        nn.init.zeros_(self.skip_w.weight)
        nn.init.zeros_(self.skip_w.bias)

        self.card_emb = nn.Embedding(vocab_size, emb_dim)
        nn.init.normal_(self.card_emb.weight, std=0.05)
        self.c_fc1 = nn.Linear(emb_dim + FEAT_DIM + Z_DIM, hid)
        self.c_drop = nn.Dropout(0.20)
        self.c_fc2 = nn.Linear(hid, 1)
        nn.init.zeros_(self.c_fc2.weight)
        nn.init.zeros_(self.c_fc2.bias)

        self.s_fc1 = nn.Linear(Z_DIM, skip_hid)
        self.s_drop = nn.Dropout(0.15)
        self.s_fc2 = nn.Linear(skip_hid, 1)
        nn.init.zeros_(self.s_fc2.weight)
        nn.init.zeros_(self.s_fc2.bias)

    def forward(self, b: dict[str, torch.Tensor]) -> torch.Tensor:
        act_exp = b["act_idx"].unsqueeze(1).expand_as(b["c_ids"])
        cb = self.card_bias(b["c_ids"]).squeeze(-1)
        ca = self.card_act(b["c_ids"]).gather(-1, act_exp.unsqueeze(-1)).squeeze(-1)
        cu = self.card_up(b["c_ids"]).squeeze(-1) * b["c_up"]
        cd = self.card_dup(b["c_ids"]).squeeze(-1) * b["c_dup"]
        cf = self.feat_w(b["c_feats"]).squeeze(-1)
        base_card = cb + ca + cu + cd + cf
        base_skip = self.skip_w(b["z"]).expand_as(base_card)

        k = b["c_ids"].shape[1]
        z_exp = b["z"].unsqueeze(1).expand(-1, k, -1)
        inp = torch.cat([self.card_emb(b["c_ids"]), b["c_feats"], z_exp], dim=-1)
        res_card = self.c_fc2(self.c_drop(F.silu(self.c_fc1(inp)))).squeeze(-1)
        res_skip = self.s_fc2(self.s_drop(F.silu(self.s_fc1(b["z"])))).expand_as(res_card)

        logits = torch.where(b["c_is_skip"] > 0.5, base_skip + res_skip, base_card + res_card)
        return logits.masked_fill(~b["mask"], -1e9)

    def backbone_reg(self) -> torch.Tensor:
        return (
            2e-4
            * (
                self.card_bias.weight.pow(2).sum()
                + self.feat_w.weight.pow(2).sum()
                + self.skip_w.weight.pow(2).sum()
            )
            + 6e-4 * self.card_act.weight.pow(2).sum()
            + 1.5e-3 * (self.card_up.weight.pow(2).sum() + self.card_dup.weight.pow(2).sum())
        )

    def export_arrays(self, vocab: list[str]) -> dict[str, np.ndarray]:
        self.eval()
        with torch.no_grad():
            return {
                "schema_version": np.array(SCHEMA_VERSION, dtype=np.int32),
                "vocab": np.array(vocab, dtype="<U64"),
                "card_bias": self.card_bias.weight.squeeze(-1).cpu().numpy().astype(np.float32),
                "card_act": self.card_act.weight.cpu().numpy().astype(np.float32),
                "card_up": self.card_up.weight.squeeze(-1).cpu().numpy().astype(np.float32),
                "card_dup": self.card_dup.weight.squeeze(-1).cpu().numpy().astype(np.float32),
                "feat_w": self.feat_w.weight.squeeze(0).cpu().numpy().astype(np.float32),
                "skip_w": self.skip_w.weight.squeeze(0).cpu().numpy().astype(np.float32),
                "skip_b": self.skip_w.bias.cpu().numpy().astype(np.float32),
                "card_emb": self.card_emb.weight.cpu().numpy().astype(np.float32),
                "c_w1": self.c_fc1.weight.cpu().numpy().astype(np.float32),
                "c_b1": self.c_fc1.bias.cpu().numpy().astype(np.float32),
                "c_w2": self.c_fc2.weight.squeeze(0).cpu().numpy().astype(np.float32),
                "c_b2": self.c_fc2.bias.cpu().numpy().astype(np.float32),
                "s_w1": self.s_fc1.weight.cpu().numpy().astype(np.float32),
                "s_b1": self.s_fc1.bias.cpu().numpy().astype(np.float32),
                "s_w2": self.s_fc2.weight.squeeze(0).cpu().numpy().astype(np.float32),
                "s_b2": self.s_fc2.bias.cpu().numpy().astype(np.float32),
            }


def fit_model(
    train_b: dict[str, torch.Tensor],
    val_b: dict[str, torch.Tensor] | None,
    vocab_size: int,
    *,
    w_strong: float = 2.0,
    w_win: float = 1.0,
    epochs: int = 80,
    seed: int = 42,
) -> tuple[ContextualResidualMLP, int, float]:
    torch.manual_seed(seed)
    model = ContextualResidualMLP(vocab_size)
    opt = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=1.5e-2)
    weights = 1.0 + w_strong * train_b["strong"] + w_win * train_b["win"]
    weights = weights / weights.mean()
    n = train_b["chosen"].shape[0]
    bs = 512

    best_val = 1e9
    best_ep = epochs
    best_state = None
    for ep in range(1, epochs + 1):
        model.train()
        perm = torch.randperm(n)
        for i in range(0, n, bs):
            idx = perm[i : i + bs]
            sub = {k: v[idx] for k, v in train_b.items()}
            sw = weights[idx]
            opt.zero_grad()
            ce = F.cross_entropy(model(sub), sub["chosen"], reduction="none")
            loss = (ce * sw).mean() + model.backbone_reg()
            loss.backward()
            opt.step()
        if val_b is not None:
            model.eval()
            with torch.no_grad():
                vm = (val_b["strong"] > 0.5) | (val_b["win"] > 0.5)
                v_nll = F.cross_entropy(model(val_b)[vm], val_b["chosen"][vm]).item()
                if v_nll < best_val:
                    best_val = v_nll
                    best_ep = ep
                    best_state = {k: v.clone() for k, v in model.state_dict().items()}
    if best_state is not None:
        model.load_state_dict(best_state)
    return model, best_ep, best_val


@torch.no_grad()
def evaluate(model: ContextualResidualMLP, b: dict[str, torch.Tensor], mask=None) -> dict:
    model.eval()
    logits = model(b)
    chosen = b["chosen"]
    c_is_skip = b["c_is_skip"]
    act_idx = b["act_idx"]
    has_skip = b["has_skip"]
    if mask is not None:
        logits, chosen, c_is_skip, act_idx, has_skip = (
            logits[mask],
            chosen[mask],
            c_is_skip[mask],
            act_idx[mask],
            has_skip[mask],
        )
    nll = F.cross_entropy(logits, chosen).item()
    preds = logits.argmax(dim=-1)
    top1 = (preds == chosen).float().mean().item()
    probs = F.softmax(logits, dim=-1)
    skip_pos = c_is_skip > 0.5
    actual_skip = skip_pos.gather(1, chosen.unsqueeze(1)).squeeze(1)
    pred_skip = skip_pos.gather(1, preds.unsqueeze(1)).squeeze(1)
    pred_skip_p = (probs * c_is_skip).sum(dim=-1)
    hs = has_skip
    skip_acc = (pred_skip[hs] == actual_skip[hs]).float().mean().item()
    by_act = {}
    for a in (0, 1, 2):
        m = hs & (act_idx == a)
        if m.sum().item() > 0:
            by_act[a + 1] = {
                "actual": round(actual_skip[m].float().mean().item(), 4),
                "pred_prob": round(pred_skip_p[m].mean().item(), 4),
                "pred_hard": round(pred_skip[m].float().mean().item(), 4),
            }
    return {
        "n": int(chosen.shape[0]),
        "nll": round(nll, 4),
        "top1": round(top1, 4),
        "skip_acc": round(skip_acc, 4),
        "skip_by_act": by_act,
    }


def verify_numpy_parity(
    torch_model: ContextualResidualMLP, vocab: list[str], sample_batch: dict[str, torch.Tensor]
) -> float:
    np_model = HumanMLDraftModel(torch_model.export_arrays(vocab))
    torch_model.eval()
    with torch.no_grad():
        t_logits = torch_model(sample_batch).numpy()
    max_diff = 0.0
    n = min(64, t_logits.shape[0])
    for i in range(n):
        z = sample_batch["z"][i].numpy()
        act = int(sample_batch["act_idx"][i].item()) + 1
        k = int(sample_batch["mask"][i].sum().item())
        for j in range(k):
            if sample_batch["c_is_skip"][i, j].item() > 0.5:
                val = np_model.skip_logit(z)
            else:
                cid = vocab[int(sample_batch["c_ids"][i, j].item())]
                val = np_model.card_logit(
                    cid,
                    sample_batch["c_feats"][i, j].numpy(),
                    float(sample_batch["c_up"][i, j].item()),
                    float(sample_batch["c_dup"][i, j].item()),
                    z,
                    act,
                )
            max_diff = max(max_diff, abs(val - float(t_logits[i, j])))
    if max_diff > 1e-4:
        raise RuntimeError(f"NumPy parity check failed: max_diff={max_diff:.6g}")
    return max_diff


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--replays-dir",
        type=Path,
        default=Path("data/replays/silent-a10/raw"),
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--threads", type=int, default=2)
    args = parser.parse_args()
    torch.set_num_threads(args.threads)

    decisions, corpus_info = extract_decisions(args.replays_dir)
    print(f"Corpus: {corpus_info}")

    # 1. Seed-disjoint validation & held-out test check
    train_counts = Counter()
    for d in decisions:
        if assign_split(d["seed_group"]) == "train":
            for c in d["candidates"]:
                if c["kind"] == "card":
                    train_counts[c["id"]] += 1
    eval_vocab = ["<UNK>"] + sorted(k for k, v in train_counts.items() if v >= 3)
    eval_rows = featurize(decisions, eval_vocab)
    train_b = collate([r for r in eval_rows if r["split"] == "train"])
    val_b = collate([r for r in eval_rows if r["split"] == "val"])
    test_b = collate([r for r in eval_rows if r["split"] == "test"])

    eval_model, best_ep, best_val = fit_model(train_b, val_b, len(eval_vocab), epochs=80, seed=42)
    heldout = {
        "best_epoch": best_ep,
        "val_sw_nll": round(best_val, 4),
        "test_all": evaluate(eval_model, test_b),
        "test_strong": evaluate(eval_model, test_b, test_b["strong"] > 0.5),
        "test_win": evaluate(eval_model, test_b, test_b["win"] > 0.5),
    }
    print("Held-out disjoint test:", json.dumps(heldout))

    # 2. Refit production artifact on 100% of clean v0.111.0 decisions for exact val-selected epoch budget
    all_counts = Counter()
    for d in decisions:
        for c in d["candidates"]:
            if c["kind"] == "card":
                all_counts[c["id"]] += 1
    full_vocab = ["<UNK>"] + sorted(k for k, v in all_counts.items() if v >= 3)
    full_rows = featurize(decisions, full_vocab)
    full_b = collate(full_rows)
    prod_model, _, _ = fit_model(full_b, None, len(full_vocab), epochs=best_ep, seed=42)
    max_diff = verify_numpy_parity(prod_model, full_vocab, test_b if full_vocab == eval_vocab else full_b)
    print(f"NumPy parity max_abs_diff={max_diff:.2e} | vocab={len(full_vocab)}")

    out = args.output.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, **prod_model.export_arrays(full_vocab))
    sha = hashlib.sha256(out.read_bytes()).hexdigest()
    print(f"Wrote {out} ({out.stat().st_size:,} bytes, sha256={sha})")

    if args.report:
        report = {
            "corpus": corpus_info,
            "heldout": heldout,
            "production": {
                "vocab_size": len(full_vocab),
                "epochs": best_ep,
                "numpy_parity_max_diff": max_diff,
                "path": str(out),
                "sha256": sha,
            },
        }
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
