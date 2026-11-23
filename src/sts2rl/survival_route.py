"""Plan to the visible boss with room mortality and a fitted boss-opening value."""

from collections import defaultdict
from copy import deepcopy
from functools import lru_cache
import json
import math
from pathlib import Path

import numpy as np

from .deck_policy import deck_context
from .native import legal_actions
from .run_policy import IDENTITY, INFERENCE_IDENTITY


def _sigmoid(x):
    return 1.0 / (1.0 + math.exp(-max(-20.0, min(20.0, float(x)))))


def _logsumexp(values):
    top = max(values)
    return top + math.log(sum(math.exp(v - top) for v in values))


def deck_readiness(deck):
    """Compact public deck densities for routing mortality and boss-clear estimates."""
    if not deck:
        return {"attack_density": 0.0, "block_density": 0.0, "scaling_density": 0.0}
    counts, _ = deck_context(deck)
    n = max(1, counts["n"])
    scaling = (
        counts["power"]
        + 0.25 * counts["poison"]
        + 0.20 * counts["shiv"]
        + 0.50 * (counts["dexterity"] + counts["afterimage"] + counts["accel"])
    )
    return {
        "attack_density": min(1.0, counts["attack"] / n),
        "block_density": min(1.0, counts["block"] / n),
        "scaling_density": min(1.0, scaling / max(4.0, n * 0.5)),
    }


def _keys(icon, act, row, hp, gold):
    return (
        icon,
        f"{icon}/{act}",
        f"{icon}/{act}/{row <= 4}",
        f"{icon}/{act}/{row <= 4}/{min(2, int(3 * hp))}/{gold >= 100}",
    )


def _strength(before):
    return [
        1.0,
        before["hp"] / before["max_hp"],
        before["relics"] / 4,
        before["upgrades"] / 3,
        before["potions"] / 2,
        (before["cards"] - 12) / 8,
        before["max_hp"] / 70,
    ]


class SurvivalRouter:
    def __init__(self, data):
        self.cells = data["cells"]
        self.boss = data["boss_coefficients"]
        self.risk = data.get("risk", 2.5)
        self.reward = data.get("reward", 1.0)
        self.health = data.get("health", 1.0)
        self.discount = data.get("discount", 0.975)
        self.elite = data.get("elite", 0.0)
        self.data = data
        self.act1_context = data.get("act1_context", {})
        self.act3_context = data.get("act3_context", {})
        self.survival_weighted = bool(data.get("survival_weighted", False))
        self.readiness_weights = data.get("readiness_weights") or {}
        if data.get("version") == 3 and not self.act1_context:
            raise ValueError("Missing Act 1 route context")

    @classmethod
    def from_data(cls, data):
        return cls(deepcopy(data))

    @classmethod
    def fit(cls, episodes, *, damped_boss_fit=False):
        cells = defaultdict(lambda: np.zeros(9))
        bosses = defaultdict(list)
        for episode in episodes:
            if episode.get("status") != "complete":
                continue
            for room in episode["rooms"]:
                a, b = room["before"], room["after"]
                act = room["act"]
                if room["icon"] == "Boss":
                    bosses[act].append((_strength(a), float(not room["died"])))
                    continue
                obs = np.array(
                    [
                        1.0,
                        room["died"],
                        *[
                            b[k] - a[k] if not room["died"] else 0.0
                            for k in (
                                "hp",
                                "gold",
                                "relics",
                                "upgrades",
                                "potions",
                                "cards",
                                "max_hp",
                            )
                        ],
                    ]
                )
                for key in _keys(room["icon"], act, room["row"], a["hp"] / a["max_hp"], a["gold"]):
                    cells[key] += obs
        if not cells or not bosses:
            raise ValueError("No complete room and boss outcomes")
        fit = {}
        # Dimensionless, modest initial effects keep sparse later acts from extrapolating wildly.
        prior = np.array([-2.8, 2.0, 0.4, 0.45, 0.3, 0.2, 0.15])
        for act in (1, 2, 3):
            values = bosses[act]
            beta = prior.copy() if act == 1 else np.array(fit[str(act - 1)])
            if values:
                x = np.array([a for a, _ in values])
                y = np.array([b for _, b in values])
                reference = beta.copy()
                penalty = np.array([2.0, 5.0, 7.0, 6.0, 7.0, 8.0, 10.0])

                def objective(candidate):
                    logits = x @ candidate
                    return (
                        np.sum(np.logaddexp(0, logits) - y * logits)
                        + 0.5 * np.sum(penalty * (candidate - reference) ** 2)
                    )

                for _ in range(18):
                    p = 1 / (1 + np.exp(-np.clip(x @ beta, -20.0, 20.0)))
                    gradient = x.T @ (y - p) - penalty * (beta - reference)
                    step = np.linalg.solve((x.T * (p * (1 - p))) @ x + np.diag(penalty), gradient)
                    if damped_boss_fit:
                        # Later acts may have a very different base clear rate.
                        # Backtrack a Newton step when the transferred prior overshoots.
                        previous_loss = objective(beta)
                        while objective(beta + step) > previous_loss:
                            step *= 0.5
                    beta += step
                    if abs(step).max() < 1e-7:
                        break
            fit[str(act)] = beta.tolist()
        return cls(
            {
                "version": 2,
                "runtime_identity": IDENTITY,
                "boss_coefficients": fit,
                "cells": {k: v.tolist() for k, v in cells.items()},
                "boss_counts": {k: len(v) for k, v in bosses.items()},
            }
        )

    def save(self, path):
        with Path(path).open("x", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)

    def estimates(self, icon, act, row, hp, gold):
        mortality = 0.025 if icon in ("Elite", "Monster") else 0.0
        average = np.zeros(7)
        for i, key in enumerate(_keys(icon, act, row, hp, gold)):
            cell = self.cells.get(key)
            if cell:
                n, d, *sums = cell
                shrink = (2.0, 12.0, 16.0, 18.0)[i]
                mortality = (d + shrink * mortality) / (n + shrink)
                average = (np.asarray(sums) + shrink * average) / (n - d + shrink)
        return mortality, average

    def choose(self, state, rows, *, normal_count=None):
        if state["decision"] != "map_select" or state.get("runtime_identity") != INFERENCE_IDENTITY.get():
            raise ValueError("Expected a public Silent A10 map")
        options = legal_actions(state)
        if len(options) == 1:
            return options[0]
        nodes = {(node["row"], node["col"]): node for level in rows for node in level}
        player = state["player"]
        maximum = player["max_hp"]
        act = state["context"]["act"]
        act_weights = self.data.get("act3_weights", {}) if act == 3 else {}
        risk = act_weights.get("risk", self.risk)
        health = act_weights.get("health", self.health)
        elite = act_weights.get("elite", self.elite)
        contextual = self.act1_context if act == 1 else self.act3_context if act == 3 else {}
        weak_fights = 2 if act == 3 else 3
        biome = state["context"].get("act_name")
        boss_id = (state["context"].get("boss") or {}).get("id")
        coefficients = contextual.get("boss_coefficients", {}).get(boss_id, self.boss[str(act)])
        _, hp_beta, relic, upgrade, potion, card, max_hp = coefficients
        hp_beta = min(5.0, max(1.4, hp_beta)) * health
        gain = (
            np.array(
                [
                    max(0.13, relic / 4),
                    max(0.17, upgrade / 3),
                    max(0.08, potion / 2),
                    max(0.035, min(0.18, card / 8)),
                    max(0.004, max_hp / 70),
                ]
            )
            * self.reward
        )

        @lru_cache(None)
        def estimate(icon, row, hp_bucket, gold_bucket, prior_fights):
            death, recovery = self.estimates(icon, act, row, hp_bucket / maximum, gold_bucket)
            cells = contextual.get("rooms", {})
            keys = [f"{biome}/{icon}"]
            if icon in ("Monster", "Unknown") and prior_fights is not None:
                keys.append(f"{biome}/{icon}/{'weak' if prior_fights < weak_fights else 'regular'}")
            for key in keys:
                cell = cells.get(key)
                if cell:
                    n, died, *sums = cell
                    # Keep the existing HP/gold-conditioned result as the prior.
                    blend = contextual["blend"] * n / (n + 40)
                    death += blend * (died / n - death)
                    if n > died:
                        recovery = recovery + blend * (np.asarray(sums) / (n - died) - recovery)
            return death, recovery

        if self.survival_weighted:
            return self._choose_survival_weighted(state, rows, options, nodes, normal_count)

        @lru_cache(None)
        def value(row, col, hp, gold, prior_fights):
            node = nodes.get((row, col))
            if not node or node["type"] == "Boss":
                return hp_beta * hp / maximum
            icon = node["type"]
            death, recovery = estimate(icon, row, hp, gold, prior_fights)
            dh, dg, *improvements = recovery
            if icon == "RestSite":
                # A fire near maximum HP cannot deliver the mean heal from injured visitors.
                dh = min(dh, maximum - hp)
            if icon == "Shop" and gold < 42:
                improvements = [0.0] * 5
                dg = 0.0
            balance = int(max(0, min(400, round((gold + dg) / 20) * 20)))
            new_hp = max(0.0, min(maximum, hp + dh))
            # A survivor-only room mean can still imply death for this particular low-HP arrival.
            if hp + dh < maximum * 0.12 and icon in ("Elite", "Monster", "Unknown"):
                death = max(death, min(0.92, 0.24 + (0.12 - (hp + dh) / maximum) * 1.8))
            new_hp = max(1, min(maximum, round(new_hp / 3) * 3))
            scaled_gold = max(0.0, dg) * (0.0017 if gold < 135 else 0.0005)
            benefit = (
                float(gain @ improvements) + scaled_gold + (elite if icon == "Elite" else 0.0)
            )
            children = [c for c in node.get("children") or [] if c["row"] > row]
            def best_child(count):
                return max((value(c["row"], c["col"], new_hp, balance, count) for c in children),
                           default=hp_beta * new_hp / maximum)

            if contextual and prior_fights is not None and prior_fights < weak_fights and icon == "Unknown":
                probability = contextual["unknown_fight_probability"].get(biome, 0.0)
                end = (1 - probability) * best_child(prior_fights) + probability * best_child(prior_fights + 1)
            else:
                count = prior_fights
                if contextual and count is not None and icon == "Monster":
                    count = min(weak_fights, count + 1)
                end = best_child(count)
            return benefit + risk * math.log(max(0.025, 1 - death)) + self.discount * end

        return max(
            options, key=lambda a: value(a.args["row"], a.args["col"], player["hp"], player["gold"],
                                         normal_count if contextual else None)
        )

    def _choose_survival_weighted(self, state, rows, options, nodes, normal_count):
        """Maximize boss-clear probability directly via exact probability Bellman recursion.

        P(dead) = 0; P(boss entry) = sigmoid(boss_logit(state));
        Q(room) = q_room * E[P(next decision) | survived], with expected survivor reward tie-break.
        """
        player = state["player"]
        maximum = max(1, player["max_hp"])
        act = state["context"]["act"]
        act_weights = self.data.get("act3_weights", {}) if act == 3 else {}
        elite_bias = act_weights.get("elite", self.elite)
        contextual = self.act1_context if act == 1 else self.act3_context if act == 3 else {}
        weak_fights = 2 if act == 3 else 3
        biome = state["context"].get("act_name")
        boss_id = (state["context"].get("boss") or {}).get("id")
        coefficients = contextual.get("boss_coefficients", {}).get(boss_id, self.boss[str(act)])
        b0, hp_b, relic_b, upgrade_b, potion_b, card_b, max_hp_b = coefficients
        deck = player.get("deck") or ()
        readiness = deck_readiness(deck)
        base_relics = len(player.get("relics") or ())
        base_upgrades = sum(
            c.get("upgrades", int(c.get("upgraded", False))) for c in deck
        )
        base_nonbasic = sum(
            c.get("rarity") != "Basic" and c.get("type") not in ("Status", "Curse", "Quest")
            for c in deck
        )
        start_potions = min(4, len(player.get("potions") or ()))
        max_potions = int(player.get("max_potions", max(2, start_potions)))
        start_pots_q = start_potions * 4
        max_pots_q = max_potions * 4
        rw = self.readiness_weights
        # Default modest log-odds readiness adjustment centered at typical Silent densities.
        readiness_logit = (
            rw.get("attack", -0.45) * (readiness["attack_density"] - 0.35)
            + rw.get("block", -0.55) * (readiness["block_density"] - 0.35)
            + rw.get("scaling", -0.40) * (readiness["scaling_density"] - 0.25)
        )
        potion_mortality_slope = rw.get("potion", -0.22)
        gain_weights = (
            np.array(
                [
                    max(0.13, relic_b / 4),
                    max(0.17, upgrade_b / 3),
                    max(0.08, potion_b / 2),
                    max(0.035, min(0.18, card_b / 8)),
                    max(0.004, max_hp_b / 70),
                ]
            )
            * self.reward
        )

        @lru_cache(None)
        def estimate(icon, row, hp_bucket, gold_bucket, pots_q, prior_fights):
            death, recovery = self.estimates(icon, act, row, hp_bucket / maximum, gold_bucket)
            cells = contextual.get("rooms", {})
            keys = [f"{biome}/{icon}"]
            if icon in ("Monster", "Unknown") and prior_fights is not None:
                keys.append(f"{biome}/{icon}/{'weak' if prior_fights < weak_fights else 'regular'}")
            for key in keys:
                cell = cells.get(key)
                if cell:
                    n, died, *sums = cell
                    blend = contextual["blend"] * n / (n + 40)
                    death += blend * (died / n - death)
                    if n > died:
                        recovery = recovery + blend * (np.asarray(sums) / (n - died) - recovery)
            if icon in ("Monster", "Elite", "Unknown") and 0.0 < death < 1.0:
                clipped = max(1e-4, min(1.0 - 1e-4, float(death)))
                base_logit = math.log(clipped / (1.0 - clipped))
                pot_adj = potion_mortality_slope * ((pots_q / 4.0) - 1.0)
                death = _sigmoid(base_logit + readiness_logit + pot_adj)
            return death, recovery

        def boss_clear_prob(hp, pots_q, bonus_q):
            logit = (
                b0
                + hp_b * (hp / maximum)
                + relic_b * (base_relics / 4.0)
                + upgrade_b * (base_upgrades / 3.0)
                + potion_b * ((pots_q / 4.0) / 2.0)
                + card_b * ((base_nonbasic - 12.0) / 8.0)
                + max_hp_b * (maximum / 70.0)
                + (bonus_q / 10.0)
                - 0.35 * readiness_logit
            )
            return max(1e-6, _sigmoid(logit))

        def _guarded_death(icon, hp_val, raw_death, dh_val):
            d = float(raw_death)
            if hp_val + dh_val < maximum * 0.12 and icon in ("Elite", "Monster", "Unknown"):
                d = max(d, min(0.92, 0.24 + (0.12 - (hp_val + dh_val) / maximum) * 1.8))
            return max(0.0, min(1.0, d))

        @lru_cache(None)
        def plan(row, col, hp, gold, pots_q, bonus_q, prior_fights):
            """Return (log_clear_prob, expected_survivor_reward) from entering (row, col)."""
            node = nodes.get((row, col))
            if not node or node["type"] == "Boss":
                return math.log(boss_clear_prob(hp, pots_q, bonus_q)), 0.0
            icon = node["type"]
            raw_death, recovery = estimate(icon, row, hp, gold, pots_q, prior_fights)
            dh, dg, *improvements = recovery
            if icon == "RestSite":
                dh = min(dh, maximum - hp)
            if icon == "Shop" and gold < 42:
                improvements = [0.0] * 5
                dg = 0.0
            death = _guarded_death(icon, hp, raw_death, dh)
            if death >= 1.0:
                return -math.inf, 0.0
            survive = max(1e-9, 1.0 - death)
            new_hp = max(1, min(maximum, round(max(0.0, min(maximum, hp + dh)) / 5) * 5))
            balance = int(max(0, min(400, round((gold + dg) / 40) * 40)))
            dpot = improvements[2]
            next_pots_q = max(0, min(max_pots_q, pots_q + int(round(dpot * 4))))
            # Propagate exact fitted boss-logit gains from room rewards so explicit and implicit bosses agree.
            step_boss_logit = (
                relic_b * (improvements[0] / 4.0)
                + upgrade_b * (improvements[1] / 3.0)
                + card_b * (improvements[3] / 8.0)
                + max_hp_b * (improvements[4] / 70.0)
            )
            next_bonus_q = max(-20, min(60, bonus_q + int(round(step_boss_logit * 10))))
            non_pot_impr = [improvements[0], improvements[1], 0.0, improvements[3], improvements[4]]
            step_reward = float(gain_weights @ non_pot_impr) + (elite_bias if icon == "Elite" else 0.0)
            children = [c for c in node.get("children") or [] if c["row"] > row]

            def best_child(count):
                if not children:
                    return math.log(boss_clear_prob(new_hp, next_pots_q, next_bonus_q)), 0.0
                child_scores = [
                    plan(c["row"], c["col"], new_hp, balance, next_pots_q, next_bonus_q, count)
                    for c in children
                ]
                return max(child_scores)

            if contextual and prior_fights is not None and prior_fights < weak_fights and icon == "Unknown":
                p_fight = max(0.0, min(1.0, float(contextual["unknown_fight_probability"].get(biome, 0.0))))
                log_p0, r0 = best_child(prior_fights)
                log_p1, r1 = best_child(prior_fights + 1)
                if 0.0 < p_fight < 1.0:
                    raw_dm, m_rec = estimate("Monster", row, hp, gold, pots_q, prior_fights)
                    d_m = _guarded_death("Monster", hp, raw_dm, m_rec[0])
                    lo = max(0.0, (death - (1.0 - p_fight)) / p_fight)
                    hi = min(1.0, death / p_fight)
                    d_fight = min(hi, max(lo, d_m))
                    d_nonfight = max(0.0, min(1.0, (death - p_fight * d_fight) / (1.0 - p_fight)))
                    w0 = (1.0 - p_fight) * max(0.0, 1.0 - d_nonfight)
                    w1 = p_fight * max(0.0, 1.0 - d_fight)
                else:
                    w0 = (1.0 - p_fight) * survive
                    w1 = p_fight * survive
                terms = []
                if w0 > 0.0 and math.isfinite(log_p0):
                    terms.append(math.log(w0) + log_p0)
                if w1 > 0.0 and math.isfinite(log_p1):
                    terms.append(math.log(w1) + log_p1)
                total_log_p = _logsumexp(terms) if terms else -math.inf
                total_reward = w0 * (step_reward + r0) + w1 * (step_reward + r1)
                return total_log_p, total_reward

            count = prior_fights
            if contextual and count is not None and icon == "Monster":
                count = min(weak_fights, count + 1)
            child_log_p, child_reward = best_child(count)

            # Exact probability multiplication: log(q_room * P_next) = log(q_room) + log(P_next).
            # Reward is strictly conditional on survival: q_room * (step_reward + child_reward).
            total_log_p = (math.log(survive) + child_log_p) if math.isfinite(child_log_p) else -math.inf
            total_reward = survive * (step_reward + child_reward)
            return total_log_p, total_reward

        start_hp = max(1, min(maximum, round(player["hp"] / 5) * 5))
        start_gold = int(max(0, min(400, round(player["gold"] / 40) * 40)))
        return max(
            options,
            key=lambda a: plan(
                a.args["row"],
                a.args["col"],
                start_hp,
                start_gold,
                start_pots_q,
                0,
                normal_count if contextual else None,
            ),
        )
