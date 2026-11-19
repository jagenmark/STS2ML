"""Plan to the visible boss with room mortality and a fitted boss-opening value."""

from collections import defaultdict
from functools import lru_cache
import json
import math
from pathlib import Path

import numpy as np

from .native import legal_actions
from .run_policy import IDENTITY


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
        if data.get("version") == 3 and not self.act1_context:
            raise ValueError("Missing Act 1 route context")

    @classmethod
    def fit(cls, episodes):
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
                for _ in range(18):
                    p = 1 / (1 + np.exp(-np.clip(x @ beta, -20.0, 20.0)))
                    gradient = x.T @ (y - p) - penalty * (beta - reference)
                    step = np.linalg.solve((x.T * (p * (1 - p))) @ x + np.diag(penalty), gradient)
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
        if state["decision"] != "map_select" or state.get("runtime_identity") != IDENTITY:
            raise ValueError("Expected a public Silent A10 map")
        options = legal_actions(state)
        if len(options) == 1:
            return options[0]
        nodes = {(node["row"], node["col"]): node for level in rows for node in level}
        player = state["player"]
        maximum = player["max_hp"]
        act = state["context"]["act"]
        contextual = self.act1_context if act == 1 else {}
        biome = state["context"].get("act_name")
        boss_id = (state["context"].get("boss") or {}).get("id")
        coefficients = contextual.get("boss_coefficients", {}).get(boss_id, self.boss[str(act)])
        _, hp_beta, relic, upgrade, potion, card, max_hp = coefficients
        hp_beta = min(5.0, max(1.4, hp_beta)) * self.health
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
                keys.append(f"{biome}/{icon}/{'weak' if prior_fights < 3 else 'regular'}")
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
                float(gain @ improvements) + scaled_gold + (self.elite if icon == "Elite" else 0.0)
            )
            children = [c for c in node.get("children") or [] if c["row"] > row]
            def best_child(count):
                return max((value(c["row"], c["col"], new_hp, balance, count) for c in children),
                           default=hp_beta * new_hp / maximum)

            if contextual and prior_fights is not None and prior_fights < 3 and icon == "Unknown":
                probability = contextual["unknown_fight_probability"].get(biome, 0.0)
                end = (1 - probability) * best_child(prior_fights) + probability * best_child(prior_fights + 1)
            else:
                count = prior_fights
                if contextual and count is not None and icon == "Monster":
                    count = min(3, count + 1)
                end = best_child(count)
            return benefit + self.risk * math.log(max(0.025, 1 - death)) + self.discount * end

        return max(
            options, key=lambda a: value(a.args["row"], a.args["col"], player["hp"], player["gold"],
                                         normal_count if contextual else None)
        )
