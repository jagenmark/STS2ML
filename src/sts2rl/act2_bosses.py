"""Act 2 boss tactics based on public intents, targeted plays and the Sandpit timer."""
from .native import selected_cards
from .run_policy import _cost, _power
from .teacher import incoming


class BossTactics:
    def __init__(self, plan, opening):
        self.plan = plan
        # Surrounded starts facing the enemy on the right. A card or potion with
        # an explicit target turns Silent towards it before the effect resolves.
        self.facing = next((e["index"] for e in opening["enemies"]
                            if _power(e.get("powers"), "BACK_ATTACK_RIGHT")), None)

    def adjust_targets(self, state, actions, scores):
        enemies = [e for e in state["enemies"] if e["hp"] > 0]
        if len(enemies) != 2 or not _power(state.get("player_powers"), "SURROUNDED"):
            return
        facing = next((e for e in enemies if e["index"] == self.facing), None)
        if facing is None:
            return
        behind = next(e for e in enemies if e is not facing)
        block = state["player"]["block"] + max(0, _power(state.get("player_powers"), "PLATING"))
        front, back = incoming(facing), incoming(behind)
        before = max(0, front + back - block)
        after = max(0, 1.5 * front + back / 1.5 - block)
        danger = 1 + min(1, before / max(1, state["player"]["hp"]))
        guard = 0 if _power(state.get("player_powers"), "INTANGIBLE") else self.plan.get("facing", 0)
        for i, action in enumerate(actions):
            target = action.args.get("target_index")
            if target is None:
                continue
            if target == behind["index"]:
                scores[i] += guard * danger * (before - after)
            if self.plan.get("focus") == next(e["id"] for e in enemies if e["index"] == target):
                scores[i] += self.plan.get("focus_bonus", 0)

    def observe(self, action):
        if "target_index" in action.args:
            self.facing = action.args["target_index"]

    def curse_choice(self, state):
        choice = self.plan.get("curse")
        if choice is None or state.get("decision") != "card_select" or state.get("min_select") != 1:
            return None
        cards = {c["id"].removeprefix("CARD."): c for c in state["cards"]}
        if "DISINTEGRATION" not in cards or len(cards) != 2:
            return None
        other = next(k for k in cards if k != "DISINTEGRATION")
        if other not in ("MIND_ROT", "SLOTH", "WASTE_AWAY"):
            return None
        selected = cards[other if other in choice else "DISINTEGRATION"]
        return selected_cards(state, [selected["index"]])

    def escape_threshold(self, state, default):
        rule = self.plan.get("escape")
        if not rule:
            return default
        enemy = next((e for e in state["enemies"] if e["id"] == "MONSTER.THE_INSATIABLE"), None)
        costs = [_cost(c) for c in state["hand"] if c["id"] == "CARD.FRANTIC_ESCAPE" and c["can_play"]]
        if enemy is None or not costs:
            return default
        cost = min(costs)
        if cost == 0:
            return 4
        countdown = _power(enemy.get("powers"), "SANDPIT")
        observations = state.get("public_combat_history") or []
        earlier = [e["hp"] for turn in observations if turn["round"] < state["round"]
                   for e in turn["enemies"] if e["id"] == enemy["id"]]
        # Estimate damage per remaining turn from actual progress in this fight.
        pace = (earlier[0] - enemy["hp"]) / len(earlier) if earlier else 18
        poison = max(0, _power(enemy.get("powers"), "POISON"))
        if countdown > 1 and enemy["hp"] <= poison + (countdown - 1) * max(12, pace):
            return 0
        uncovered = max(0, incoming(enemy) - state["player"]["block"])
        if countdown > 1 and uncovered >= state["player"]["hp"]:
            return 0
        if rule == "cheap":
            return 3 if cost == 1 else 1
        if rule == "bank":
            # Pay an increasing energy cost on quiet turns while there is still time.
            return 4 if uncovered <= 5 else (2 if cost == 1 else 1)
        raise ValueError(f"Unknown Sandpit plan {rule}")
