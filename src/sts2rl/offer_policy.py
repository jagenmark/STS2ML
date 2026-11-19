"""Fit a regularized ranker to paired native continuations of public offers."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .native import legal_actions
from .run_policy import IDENTITY, _card_id, _cost


def offer_type(state):
    if state.get("in_combat") or state.get("context", {}).get("act") != 1:
        return None
    if state["decision"] == "event_choice" and state.get("event_name") == "Neow":
        return "neow"
    if state["decision"] == "card_reward" and state["context"]["floor"] <= 12:
        return "card"
    return None


def offer_features(state, action, policy):
    if offer_type(state) == "neow":
        option = next(o for o in state["options"] if o["index"] == action.args["option_index"])
        return 0., {"neow:" + option["text_key"]: 1.}
    deck = state["player"]["deck"]
    if action.kind == "skip_card_reward":
        return 0., {"skip": 1., "skip:deck": (len(deck) - 12) / 5}
    card = next(c for c in state["cards"] if c["index"] == action.args["card_index"])
    card_id = _card_id(card)
    copies = sum(_card_id(c) == card_id for c in deck)
    value = policy.card_value(card, deck=deck)
    prior = .2 * (value - 1.5 * copies - policy.weights.draft_threshold - .35 * max(0, len(deck) - 12))
    stats = card.get("stats") or {}
    features = {"card:" + card_id: 1., "type:" + card["type"]: 1., "value": value / 10,
                "copies": copies, "cost": _cost(card) / 2,
                "block": stats.get("block", 0) / 7, "poison": stats.get("poisonpower", 0) / 5}
    return prior, features


class OfferModel:
    def __init__(self, weights):
        self.weights = weights

    def predict(self, prior, features):
        return prior + sum(val * self.weights.get(key, 0.) for key, val in features.items())

    def choose(self, state, policy):
        if state.get("runtime_identity") != IDENTITY or not offer_type(state):
            raise ValueError("Offer ranker received an out-of-scope decision")
        return max(legal_actions(state), key=lambda a: self.predict(*offer_features(state, a, policy)))

    @classmethod
    def fit(cls, roots, ridge=5.):
        # Center within each offer: every candidate shares the game seed, public
        # root and continuation policy. Easy seeds cannot inflate every option.
        vocab = sorted({key for root in roots for arm in root["arms"] for key in arm["features"]})
        index = {key: i for i, key in enumerate(vocab)}
        gram = np.eye(len(vocab)) * ridge
        rhs = np.zeros(len(vocab))
        for root in roots:
            arms = root["arms"]
            x = np.zeros((len(arms), len(vocab)))
            for i, arm in enumerate(arms):
                for key, val in arm["features"].items():
                    x[i, index[key]] = val
            y = np.array([a["return"] - a["prior"] for a in arms])
            x -= x.mean(axis=0)
            y -= y.mean()
            gram += x.T @ x
            rhs += x.T @ y
        return cls(dict(zip(vocab, np.linalg.solve(gram, rhs).tolist(), strict=True)))

    def save(self, path):
        with Path(path).open("x", encoding="utf-8") as stream:
            json.dump({"version": 1, "runtime_identity": IDENTITY, "weights": self.weights}, stream, indent=2)

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("version") != 1 or data.get("runtime_identity") != IDENTITY:
            raise ValueError("Incompatible offer ranker")
        return cls(data["weights"])
