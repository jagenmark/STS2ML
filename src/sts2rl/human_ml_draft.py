"""Contextual Residual MLP card-drafting policy trained on clean v0.111.0 human Silent A10 replays.

Pure NumPy inference (<0.2 ms per decision) with strict v6.5 safety guardrails
(`prohibited` traps and Curse/Status/Quest exclusion). All features derive from
public decision state using the pinned v0.111.0 card catalog.
"""

from __future__ import annotations

from functools import lru_cache
import hashlib
import math
from pathlib import Path
from typing import Any

import numpy as np

from .draft_v65 import prohibited, role_context, roles, same_turn_draw, wave_hand
from .unified_draft import effects, normalize, public_context

SCHEMA_VERSION = 1
Z_DIM = 32
PROPS_DIM = 36
INTER_DIM = 44
FEAT_DIM = PROPS_DIM + INTER_DIM

DEFAULT_MODEL_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "combat-search-v2" / "models" / "human_ml_draft_v1.npz"
)

SHIV_PAYOFFS = frozenset(
    "ACCURACY PHANTOM_BLADES KNIFE_TRAP FINISHER FAN_OF_KNIVES STRANGLE ENVENOM AFTERIMAGE".split()
)
POISON_PAYOFFS = frozenset("ACCELERANT BUBBLE_BUBBLE OUTBREAK MIRAGE CATALYST".split())
DISCARD_PAYOFFS = frozenset("TACTICIAN REFLEX SNEAKY_STRIKE EVISCERATE CALCULATED_GAMBLE".split())
DRAW_PAYOFFS = frozenset("CORROSIVE_WAVE SPEEDSTER MURDER".split())
DEX_PAYOFFS = frozenset("DODGE_AND_ROLL BLUR BACKFLIP DEFLECT ESCAPE_PLAN LEG_SWEEP AFTERIMAGE".split())


def extract_context_vec(
    deck: list[dict[str, Any]],
    *,
    act: int,
    act_floor: int,
    max_energy: int,
    stone_dex: float = 0.0,
    paper_krane: float = 0.0,
    hp: float | None = None,
    max_hp: float | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Build the 32-dim public run/deck context vector shared between training and runtime."""
    n, copies = role_context(deck, max_energy)
    length = max(1, n["n"])
    dex = n["dexterity"] + stone_dex
    wave_hit, wave_exp = wave_hand(n)
    hp_known = 1.0 if (hp is not None and max_hp is not None and max_hp > 0) else 0.0
    hp_frac = min(1.0, max(0.0, float(hp) / float(max_hp))) if hp_known else 0.8

    act_clamped = min(3, max(1, int(act)))
    af_clamped = min(17, max(1, int(act_floor)))
    global_floor = 17 * (act_clamped - 1) + af_clamped

    act1 = 1.0 if act_clamped == 1 else 0.0
    act2 = 1.0 if act_clamped == 2 else 0.0
    act3 = 1.0 if act_clamped == 3 else 0.0
    early_a1 = 1.0 if (act_clamped == 1 and af_clamped <= 8) else 0.0
    floor_norm = min(1.2, global_floor / 50.0)
    act_floor_norm = (af_clamped - 1) / 16.0
    dsize = (length - 12.0) / 20.0

    z = np.array(
        [
            act1,
            act2,
            act3,
            early_a1,
            floor_norm,
            act_floor_norm,
            dsize,
            dsize * dsize,
            float(max_energy) - 3.0,
            float(stone_dex),
            float(paper_krane),
            min(3.0, n["front"] / 5.0),
            min(3.0, n["area"] / 2.0),
            min(3.0, n["scaling"] / 3.0),
            min(3.0, n["guard"] / 3.0),
            n["block"] / length,
            n["Attack"] / length,
            n["Skill"] / length,
            n["cost_two_plus"] / length,
            min(2.0, n["filtering"] / length),
            wave_hit,
            min(3.0, n["discard"] / 5.0),
            min(3.0, n["sly"] / 3.0),
            min(3.0, n["shiv"] / 6.0),
            min(3.0, n["poison"] / 12.0),
            min(3.0, dex / 3.0),
            min(3.0, n["weak"] / 3.0),
            min(3.0, n["vulnerable"] / 2.0),
            min(3.0, n["exhaust"] / 8.0),
            min(3.0, n["accuracy"] / 6.0),
            hp_frac,
            hp_known,
        ],
        dtype=np.float32,
    )
    ctx = {
        "act": act_clamped,
        "act_floor": af_clamped,
        "global_floor": global_floor,
        "max_energy": max_energy,
        "stone_dex": float(stone_dex),
        "paper_krane": float(paper_krane),
        "length": length,
        "n": n,
        "copies": copies,
        "dex": dex,
        "wave_hit": wave_hit,
        "wave_exp": wave_exp,
    }
    return z, ctx


def context_from_state(state: dict[str, Any], deck: list[dict[str, Any]] | None = None):
    """Extract aligned context vector from a live native STS2 state dict."""
    pub = public_context(state, v65=True)
    player = state["player"]
    cards = player["deck"] if deck is None else deck
    return extract_context_vec(
        cards,
        act=int(pub.get("act", 1)),
        act_floor=int(pub.get("floor", 1)),
        max_energy=int(pub.get("max_energy", 3)),
        stone_dex=float(pub.get("stone_dex", 0)),
        paper_krane=1.0 if pub.get("paper_krane") else 0.0,
        hp=player.get("hp"),
        max_hp=player.get("max_hp"),
    )


def extract_card_features(
    card: dict[str, Any], z: np.ndarray, ctx: dict[str, Any]
) -> tuple[dict[str, Any], np.ndarray, float, float]:
    """Return (normalized_card, 80-dim feature vector, is_upgraded, is_duplicate)."""
    c = normalize(card)
    name, s, keys = c["id"], c["stats"], c["keywords"]
    e = effects(c)
    r = roles(c, e)
    copies_in_deck = ctx["copies"][name]
    cost = max(0, int(c["cost"]) if c["cost"] is not None else 1)
    dmg = max(s.get("damage", 0), s.get("calculateddamage", 0))
    if name in ("DAGGER_SPRAY", "TWIN_STRIKE"):
        dmg *= 2

    up = 1.0 if c["upgraded"] else 0.0
    is_atk = 1.0 if c["type"] == "Attack" else 0.0
    is_skl = 1.0 if c["type"] == "Skill" else 0.0
    is_pwr = 1.0 if c["type"] == "Power" else 0.0
    cost_0 = 1.0 if (cost == 0 and not c["costs_x"]) else 0.0
    cost_1 = 1.0 if (cost == 1 and not c["costs_x"]) else 0.0
    cost_2p = 1.0 if (cost >= 2 and not c["costs_x"]) else 0.0
    costs_x = 1.0 if c["costs_x"] else 0.0
    st_draw = same_turn_draw(c, e)
    is_sly = 1.0 if "Sly" in keys else 0.0
    is_ret = 1.0 if "Retain" in keys else 0.0
    is_exh = 1.0 if "Exhaust" in keys else 0.0
    is_inn = 1.0 if "Innate" in keys else 0.0

    is_shiv_pay = 1.0 if name in SHIV_PAYOFFS else 0.0
    is_pois_pay = 1.0 if name in POISON_PAYOFFS else 0.0
    is_disc_pay = 1.0 if (name in DISCARD_PAYOFFS or is_sly > 0) else 0.0
    is_draw_pay = 1.0 if name in DRAW_PAYOFFS else 0.0
    is_dex_pay = 1.0 if (name in DEX_PAYOFFS or e.block > 0) else 0.0

    dmg_n = min(3.0, dmg / 12.0)
    blk_n = min(3.0, e.block / 10.0)
    drw_n = min(3.0, e.draw / 2.0)
    st_drw_n = min(3.0, st_draw / 2.0)
    dsc_n = min(3.0, e.discard / 2.0)
    shv_n = min(3.0, e.shivs / 3.0)
    poi_n = min(3.0, (e.poison + 3.0 * s.get("poisonperturn", 0)) / 8.0)
    eng_n = min(2.0, e.energy / 2.0)
    wk_n = min(2.0, s.get("weakpower", 0) / 2.0)
    vl_n = min(2.0, (s.get("vulnerablepower", 0) + (2.0 if name == "EXPOSE" else 0.0)) / 2.0)
    dx_n = min(2.0, s.get("dexteritypower", 0) / 2.0)
    sl_n = min(2.0, s.get("strengthloss", 0) / 6.0)
    cp_gt0 = 1.0 if copies_in_deck > 0 else 0.0
    cp_ge2 = 1.0 if copies_in_deck >= 2 else 0.0
    cp_log = math.log1p(copies_in_deck)

    (
        act1, act2, act3, early_a1, _floor_n, _af, dsize, _dsize2,
        eng_m3, _sdex, pkrane,
        front_n, area_n, scal_n, guard_n,
        blk_dens, atk_dens, skl_dens, c2_dens,
        drw_dens, wave_hit, disc_n, sly_n,
        shiv_ctx, pois_ctx, dex_ctx, wk_ctx, _vl_ctx, exh_ctx, acc_ctx,
        hp_frac, _hpk,
    ) = z.tolist()

    feats = np.array(
        [
            # 36 card properties
            up,
            cp_log,
            cp_gt0,
            cp_ge2,
            is_atk,
            is_skl,
            is_pwr,
            cost_0,
            cost_1,
            cost_2p,
            costs_x,
            dmg_n,
            blk_n,
            drw_n,
            st_drw_n,
            dsc_n,
            shv_n,
            poi_n,
            eng_n,
            wk_n,
            vl_n,
            dx_n,
            sl_n,
            float(r["front"]),
            float(r["area"]),
            float(r["scaling"]),
            float(r["guard"]),
            is_sly,
            is_ret,
            is_exh,
            is_inn,
            is_shiv_pay,
            is_pois_pay,
            is_disc_pay,
            is_draw_pay,
            is_dex_pay,
            # 44 contextual interactions
            r["front"] * front_n,
            r["front"] * act1,
            r["front"] * early_a1,
            dmg_n * front_n,
            dmg_n * early_a1,
            dmg_n * act3,
            r["area"] * area_n,
            r["area"] * act1,
            r["area"] * act2,
            r["scaling"] * scal_n,
            r["scaling"] * early_a1,
            r["scaling"] * act3,
            r["guard"] * guard_n,
            r["guard"] * act1,
            blk_n * blk_dens,
            blk_n * dex_ctx,
            blk_n * (1.0 - hp_frac),
            is_dex_pay * dex_ctx,
            drw_n * drw_dens,
            drw_n * dsize,
            st_drw_n * wave_hit,
            dsc_n * sly_n,
            is_disc_pay * disc_n,
            is_shiv_pay * shiv_ctx,
            shv_n * acc_ctx,
            shv_n * shiv_ctx,
            is_pois_pay * pois_ctx,
            poi_n * pois_ctx,
            is_draw_pay * drw_dens,
            is_draw_pay * wave_hit,
            wk_n * wk_ctx,
            wk_n * pkrane,
            vl_n * atk_dens,
            cost_2p * eng_m3,
            cost_2p * c2_dens,
            cost_0 * drw_dens,
            cp_gt0 * is_pwr,
            cp_gt0 * is_skl,
            cp_gt0 * is_atk,
            is_exh * exh_ctx,
            (1.0 if name == "PACTS_END" else 0.0) * exh_ctx,
            (1.0 if name == "CORROSIVE_WAVE" else 0.0) * wave_hit,
            (1.0 if name == "FINISHER" else 0.0) * (atk_dens + shiv_ctx),
            (1.0 if name == "FLECHETTES" else 0.0) * skl_dens,
        ],
        dtype=np.float32,
    )
    return c, feats, up, cp_gt0


def is_rejected(normalized_card: dict[str, Any], ctx: dict[str, Any]) -> bool:
    """Hard safety filter matching v6.5 prohibited traps plus Curse/Status/Quest exclusion."""
    if normalized_card["type"] in ("Curse", "Status", "Quest"):
        return True
    return prohibited(normalized_card, ctx["max_energy"], ctx["n"]["generators"])


def _silu(x: np.ndarray) -> np.ndarray:
    return x / (1.0 + np.exp(np.clip(-x, -60.0, 60.0)))


class HumanMLDraftModel:
    """Pure NumPy Contextual Residual MLP scorer for card rewards, bundles, and shops."""

    def __init__(self, arrays: dict[str, np.ndarray]):
        version = int(np.asarray(arrays["schema_version"]).item())
        if version != SCHEMA_VERSION:
            raise ValueError(f"Unsupported human_ml_draft schema_version={version!r}")
        vocab = [str(x) for x in arrays["vocab"].tolist()]
        if not vocab or vocab[0] != "<UNK>":
            raise ValueError("Invalid vocabulary in human_ml_draft artifact")
        self.vocab = vocab
        self.card_to_idx = {cid: i for i, cid in enumerate(vocab)}
        self.card_bias = np.asarray(arrays["card_bias"], dtype=np.float32).reshape(-1)
        self.card_act = np.asarray(arrays["card_act"], dtype=np.float32)
        self.card_up = np.asarray(arrays["card_up"], dtype=np.float32).reshape(-1)
        self.card_dup = np.asarray(arrays["card_dup"], dtype=np.float32).reshape(-1)
        self.feat_w = np.asarray(arrays["feat_w"], dtype=np.float32).reshape(-1)
        self.skip_w = np.asarray(arrays["skip_w"], dtype=np.float32).reshape(-1)
        self.skip_b = float(np.asarray(arrays["skip_b"], dtype=np.float32).reshape(-1)[0])

        self.card_emb = np.asarray(arrays["card_emb"], dtype=np.float32)
        self.c_w1 = np.asarray(arrays["c_w1"], dtype=np.float32)
        self.c_b1 = np.asarray(arrays["c_b1"], dtype=np.float32).reshape(-1)
        self.c_w2 = np.asarray(arrays["c_w2"], dtype=np.float32).reshape(-1)
        self.c_b2 = float(np.asarray(arrays["c_b2"], dtype=np.float32).reshape(-1)[0])

        self.s_w1 = np.asarray(arrays["s_w1"], dtype=np.float32)
        self.s_b1 = np.asarray(arrays["s_b1"], dtype=np.float32).reshape(-1)
        self.s_w2 = np.asarray(arrays["s_w2"], dtype=np.float32).reshape(-1)
        self.s_b2 = float(np.asarray(arrays["s_b2"], dtype=np.float32).reshape(-1)[0])

        v = len(vocab)
        if (
            self.card_bias.shape != (v,)
            or self.card_act.shape != (v, 3)
            or self.feat_w.shape != (FEAT_DIM,)
            or self.skip_w.shape != (Z_DIM,)
            or self.card_emb.shape[0] != v
        ):
            raise ValueError("Shape mismatch in human_ml_draft artifact")

    @classmethod
    def load(cls, path: str | Path | None = None) -> HumanMLDraftModel:
        resolved = Path(DEFAULT_MODEL_PATH if path is None else path).resolve()
        digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
        return _load_cached(str(resolved), digest)

    def skip_logit(self, z: np.ndarray) -> float:
        base = float(np.dot(self.skip_w, z) + self.skip_b)
        h = _silu(self.s_w1 @ z + self.s_b1)
        res = float(np.dot(self.s_w2, h) + self.s_b2)
        return base + res

    def card_logit(
        self, cid: str, feats: np.ndarray, up: float, dup: float, z: np.ndarray, act: int
    ) -> float:
        idx = self.card_to_idx.get(cid, 0)
        act_idx = min(2, max(0, int(act) - 1))
        base = (
            float(self.card_bias[idx])
            + float(self.card_act[idx, act_idx])
            + float(self.card_up[idx]) * up
            + float(self.card_dup[idx]) * dup
            + float(np.dot(self.feat_w, feats))
        )
        inp = np.concatenate([self.card_emb[idx], feats, z], axis=0)
        h = _silu(self.c_w1 @ inp + self.c_b1)
        res = float(np.dot(self.c_w2, h) + self.c_b2)
        return base + res

    def score_card(
        self,
        card: dict[str, Any],
        z: np.ndarray,
        ctx: dict[str, Any],
        *,
        skip_logit: float | None = None,
        skip_bias: float = 0.0,
        act_skip_bias: tuple[float, float, float] = (0.0, 0.0, 0.0),
        a1_offense_boost: float = 0.0,
        a1_offense_cap: float = 4.0,
    ) -> float:
        """Return logit(card) - logit(SKIP) - bias, or -1_000_000.0 if safety-rejected."""
        c, feats, up, dup = extract_card_features(card, z, ctx)
        if is_rejected(c, ctx):
            return -1_000_000.0
        sl = self.skip_logit(z) if skip_logit is None else skip_logit
        act_idx = min(2, max(0, int(ctx["act"]) - 1))
        offset = float(skip_bias) + float(act_skip_bias[act_idx])
        margin = self.card_logit(c["id"], feats, up, dup, z, ctx["act"]) - (sl + offset)
        if a1_offense_boost != 0.0 and act_idx == 0:
            s = c["stats"]
            e = effects(c)
            dmg = max(s.get("damage", 0), s.get("calculateddamage", 0))
            if c["id"] in ("DAGGER_SPRAY", "TWIN_STRIKE"):
                dmg *= 2
            offense_str = min(
                1.5,
                (dmg / 10.0)
                + 0.55 * e.shivs
                + 0.14 * (e.poison + 2.0 * s.get("poisonperturn", 0)),
            )
            if offense_str > 0.0:
                n = ctx["n"]
                have = n["front"] + 0.25 * n["poison"] + 0.35 * n["shiv"]
                need = max(0.0, 1.0 - have / max(0.5, float(a1_offense_cap)))
                margin += float(a1_offense_boost) * need * offense_str
        return margin


@lru_cache(maxsize=16)
def _load_cached(resolved_path: str, _digest: str) -> HumanMLDraftModel:
    with np.load(resolved_path, allow_pickle=False) as data:
        arrays = {k: data[k] for k in data.files}
    return HumanMLDraftModel(arrays)
