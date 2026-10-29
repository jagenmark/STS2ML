"""A synthetic learning check, explicitly unrelated to actual STS2 strategy."""

from __future__ import annotations

import random


def make_demo_records(runs: int = 96, seed: int = 17) -> list[dict]:
    """Create a learnable toy rule with permuted offers and independent groups.

    A deck containing DEMO_RED prefers DEMO_RED; DEMO_BLUE prefers DEMO_BLUE.
    These are invented identifiers and labels, not human or simulator data.
    """
    if runs < 3:
        raise ValueError("at least three runs are required")
    rng, rows = random.Random(seed), []
    for run in range(runs):
        color = "RED" if run % 2 else "BLUE"
        for decision in range(3):
            candidates = [
                {
                    "action_id": "red",
                    "kind": "pick_card",
                    "entity_id": "DEMO_RED",
                    "upgrades": 0,
                    "price": None,
                },
                {
                    "action_id": "blue",
                    "kind": "pick_card",
                    "entity_id": "DEMO_BLUE",
                    "upgrades": 0,
                    "price": None,
                },
                {
                    "action_id": "skip",
                    "kind": "skip",
                    "entity_id": None,
                    "upgrades": None,
                    "price": None,
                },
            ]
            rng.shuffle(candidates)
            rows.append(
                {
                    "schema_version": 1,
                    "run_id": f"synthetic-{run}",
                    "decision_id": str(decision),
                    "source": "synthetic_demo",
                    "game_version": "synthetic-not-game-data",
                    "split_group": f"synthetic-seed-{run}",
                    "observation": {
                        "character": "DEMO",
                        "ascension": 10,
                        "decision_type": "card_reward",
                        "act": 1,
                        "floor": decision + 1,
                        "hp": 50 if color == "RED" else 20,
                        "max_hp": 80,
                        "gold": rng.randrange(100),
                        "deck": [{"id": f"DEMO_{color}", "upgrades": 0}] * (decision + 1),
                        "relics": [],
                        "potions": [],
                        "state_quality": "synthetic",
                    },
                    "candidates": candidates,
                    "chosen_action_id": color.lower(),
                    "outcome": float(color == "RED"),
                    "metadata": {"purpose": "plumbing and learnability check only"},
                }
            )
    return rows
