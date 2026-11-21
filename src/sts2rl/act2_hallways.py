"""Select a hallway or elite combat plan from the public opening of a fight."""

import math


def formation_key(state):
    return "+".join(
        sorted(e["id"].removeprefix("MONSTER.") for e in state["enemies"] if e["hp"] > 0)
    )


class HallwayPlans:
    def __init__(self, data, styles, *, act=2):
        self.act = act
        self.plans = data["plans"]
        self.by_formation = data.get("by_formation", {})
        self.by_room = data.get("by_room", {})
        self.linear = data.get("linear", {})
        self.margin = data.get("margin", 0.0)
        if any(
            name not in self.plans
            for name in [*self.by_formation.values(), *self.by_room.values(), *self.linear]
        ):
            raise ValueError(f"Unknown Act {act} hallway plan")
        for plan in self.plans.values():
            if plan.get("style", "engine") not in styles or plan.get("search", "greedy") not in (
                "greedy",
                "beam",
            ):
                raise ValueError(f"Invalid Act {act} style or search")
            for key, value in plan.get("style_weights", {}).items():
                if (
                    key not in ("guard", "horizon", "potion", "leader", "poison", "draw")
                    or not math.isfinite(value)
                    or value < 0
                ):
                    raise ValueError(f"Invalid Act {act} style weight")

    def select(self, state, features):
        ctx = state["context"]
        if ctx.get("act") != self.act or ctx.get("room_type") not in ("Monster", "Elite"):
            return {}
        key = formation_key(state)
        choice = self.by_formation.get(key, self.by_room.get(ctx["room_type"]))
        if self.linear:
            values = features(state)
            values["formation/" + key] = 1.0
            estimates = {
                name: sum(v * model.get(k, 0.0) for k, v in values.items())
                for name, model in self.linear.items()
            }
            best = max(estimates, key=estimates.get)
            if estimates[best] > max(0.0, estimates.get(choice, 0.0)) + self.margin:
                choice = best
        return self.plans.get(choice, {})
