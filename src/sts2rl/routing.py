"""Fit room returns from A10 play and plan over the visible map graph."""
from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
import json
from pathlib import Path

from .native import legal_actions
from .run_policy import IDENTITY

# Each entry is net HP, net gold, non-HP reward, and probability of death.
# Sparse rooms fall back to neutral expectations until the model sees them.
NEUTRAL = (0., 0., 0., 0.)


def _buckets(icon, act, row, hp_fraction, gold):
    early = int(row <= 4)
    low = int(hp_fraction < .65)
    rich = int(gold >= 110)
    return (icon, f"{icon}/{act}/{early}", f"{icon}/{act}/{early}/{low}/{rich}")


class RoomModel:
    def __init__(self, cells):
        self.cells = cells

    @classmethod
    def fit(cls, episodes):
        totals = defaultdict(lambda: [0.] * 5)
        for episode in episodes:
            if episode["status"] != "complete":
                continue
            if episode.get("ascension") != 10:
                raise ValueError("Room model requires A10 episodes")
            for room in episode["rooms"]:
                before, after = room["before"], room["after"]
                keys = _buckets(room["icon"], room["act"], room["row"],
                                before["hp"] / before["max_hp"], before["gold"])
                def delta(name):
                    return after[name] - before[name]
                reward = (2.5 * delta("cards") + 7 * delta("relics") + 3 * delta("potions")
                          + 2.5 * delta("upgrades") + .65 * delta("max_hp"))
                for key in keys:
                    cell = totals[key]
                    for i, val in enumerate((1, delta("hp"), delta("gold"), reward, room["died"])):
                        cell[i] += val
        if not totals:
            raise ValueError("No complete room transitions in training data")
        return cls(dict(totals))

    def save(self, path):
        path = Path(path)
        with path.open("x", encoding="utf-8") as f:
            json.dump({"version": 1, "runtime_identity": IDENTITY, "cells": self.cells}, f, indent=2)

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("version") == 2 and data.get("runtime_identity") == IDENTITY:
            from .survival_route import SurvivalRouter
            return SurvivalRouter(data)
        if data.get("version") != 1 or data.get("runtime_identity") != IDENTITY:
            raise ValueError("Incompatible room model")
        return cls(data["cells"])

    def estimate(self, icon, act, row, hp_fraction, gold):
        mean = NEUTRAL
        for i, key in enumerate(_buckets(icon, act, row, hp_fraction, gold)):
            cell = self.cells.get(key)
            if cell:
                prior = 1 if i == 0 else 12
                mean = tuple((value + prior * old) / (cell[0] + prior)
                             for value, old in zip(cell[1:], mean, strict=True))
        return mean

    def choose(self, state, rows):
        if state.get("runtime_identity") != IDENTITY or state.get("decision") != "map_select":
            raise ValueError("Room planning requires a Silent A10 map")
        nodes = {(n["row"], n["col"]): n for row in rows for n in row}
        player = state["player"]
        max_hp = player["max_hp"]
        act = state["context"]["act"]

        @lru_cache(maxsize=None)
        def value(row, col, hp, gold, depth):
            node = nodes.get((row, col))
            if not node or depth <= 0:
                return 0
            hp_delta, gold_delta, gain, death = self.estimate(node["type"], act, row, hp / max_hp, gold)
            hp_after = max(1, min(max_hp, hp + hp_delta))
            gold_after = max(0, gold + gold_delta)
            # Gold spent in a shop buys the observed reward. Account for gold
            # gained in other rooms and discount stockpiling as the purse grows.
            gold_value = max(0, gold_delta) * (.055 if gold < 150 else .02)
            immediate = (hp_after - hp) * (1.4 if hp < .5 * max_hp else 1.) + gain + gold_value - 20 * death
            future = max((value(c["row"], c["col"], round(hp_after), round(gold_after), depth - 1)
                          for c in node.get("children") or [] if c["row"] > row), default=0)
            return immediate + .88 * future

        return max(legal_actions(state), key=lambda a: value(a.args["row"], a.args["col"],
                                                             player["hp"], player["gold"], 7))
