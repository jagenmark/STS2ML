"""Rank a small public action set by learned differences in native fight returns."""

from __future__ import annotations

from .encounter import EncounterPolicy
from .native import legal_actions
from .run_policy import IDENTITY, RunPolicy, RunWeights, _power
from .tactical_student import action_examples, make_network, pack
from .teacher import incoming
from .turn_planning import choose_turn


def shortlist(state, prior, encounter):
    groups, choices = action_examples(state, prior)
    if len(groups) < 2:
        return [g[0] for g in groups], choices
    actions = [g[0] for g in groups]
    advanced = encounter.combat_scores(state, actions)
    simple = prior.combat_scores(state, actions)
    planner_action = choose_turn(state, prior)
    planned = next(
        i for i, group in enumerate(groups) if any(a.id == planner_action.id for a in group)
    )
    descending = sorted(range(len(advanced)), key=advanced.__getitem__, reverse=True)
    old = sorted(range(len(simple)), key=simple.__getitem__, reverse=True)
    if len(actions) <= 5:
        use = list(range(len(actions)))
    else:
        use = list(dict.fromkeys([descending[0], planned, old[0], descending[1]]))
        # Preserve a meaningful guard, attack or potion alternative even in a hand of many similar attacks.
        for test in (
            lambda a, x: a.kind == "use_potion",
            lambda a, x: x[27] > 0,
            lambda a, x: x[24] > 0,
        ):
            high = next((i for i in descending if test(actions[i], choices[i]["x"])), None)
            if high is not None and len(use) < 5 and high not in use:
                use.append(high)
        use.extend(i for i in descending if i not in use and len(use) < 5)
        use.sort()
    if not use:
        raise ValueError("No public actions in the return adviser")
    best = max(advanced)
    enemies = [e for e in state["enemies"] if e["hp"] > 0]
    total_hp = sum(e["hp"] for e in enemies)
    results = []
    for i in use:
        a = actions[i]
        target = next((e for e in enemies if e["index"] == a.args.get("target_index")), None)
        e = target or max(enemies, key=lambda enemy: enemy["hp"], default={})
        e_powers = e.get("powers", [])
        numeric = [
            advanced[i] / 22,
            (advanced[i] - best) / 15,
            float(planned == i),
            float(descending[0] == i),
            float(old[0] == i),
            state["player"]["hp"] / 70,
            total_hp / 200,
            _power(e_powers, "SLIPPERY") / 5,
            bool(_power(e_powers, "MINION")),
            _power(e_powers, "ARTIFACT") / 2,
            _power(e_powers, "WEAK") / 3,
            _power(e_powers, "VULNERABLE") / 3,
            _power(state.get("player_powers"), "DEXTERITY") / 5,
            _power(state.get("player_powers"), "STRENGTH") / 5,
            _power(state.get("player_powers"), "INTANGIBLE") / 2,
            state["draw_pile_count"] / 15,
            state["discard_pile_count"] / 15,
            (incoming(e) if e else 0) / 25,
        ]
        numeric += [
            float(e.get("id") == "MONSTER." + name)
            for name in (
                "VANTOM",
                "CEREMONIAL_BEAST",
                "KIN_PRIEST",
                "KIN_FOLLOWER",
                "CRUSHER",
                "ROCKET",
                "KNOWLEDGE_DEMON",
                "THE_INSATIABLE",
            )
        ]
        results.append(
            {
                "token": choices[i]["token"],
                "x": choices[i]["x"] + [round(min(8.0, max(-8.0, float(v))), 5) for v in numeric],
            }
        )
    return [actions[i] for i in use], results


class ReturnPolicy:
    def __init__(self, path):
        import torch

        data = torch.load(path, map_location="cpu", weights_only=True)
        if data["version"] != 1 or data["runtime_identity"] != IDENTITY:
            raise ValueError("Incompatible native return model")
        self.vocab = data["vocab"]
        weights = RunWeights(**data["weights"])
        self.prior = RunPolicy(weights)
        self.encounter = EncounterPolicy(weights)
        self.model = make_network(data["width"], data["inputs"], len(self.vocab) + 1)
        self.model.load_state_dict(data["state_dict"])
        self.model.eval()
        self.margin = data["margin"]
        self.rooms = frozenset(data.get("rooms", ()))

    def choose(self, state, primary):
        import torch

        if self.rooms and state["context"]["room_type"] not in self.rooms:
            return primary
        if len(legal_actions(state)) < 3:
            return primary
        actions, choices = shortlist(state, self.prior, self.encounter)
        index = next((i for i, a in enumerate(actions) if a.id == primary.id), None)
        if index is None:
            return primary
        with torch.inference_mode():
            values = self.model(*pack([{"choices": choices}], self.vocab))[0]
        best = int(values.argmax())
        if best != index and float(values[best] - values[index]) >= self.margin:
            return actions[best]
        return primary
