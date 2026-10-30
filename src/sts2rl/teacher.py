"""Native Monte Carlo teacher for starter and experimental whole-Act-1 data.

Every candidate uses the same independently sampled hidden worlds. Continuations
use a public heuristic; these estimates are not optimal action values or MCTS.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import math
import random
import statistics
import time

from .native import ACT1_SAMPLER, Action, NativeError, NativeSession, ReplayFork, SAMPLER, digest, legal_actions


def incoming(enemy: dict) -> float:
    return sum(i.get("total_damage", i.get("damage", 0) * i.get("hits", 1))
               for i in enemy.get("intents") or [])


def heuristic_score(state: dict, action: Action) -> float:
    if action.kind == "end_turn":
        return 0.0
    if action.kind in ("select_cards", "skip_select"):
        # Qualified curriculum only asks Survivor's discard. Prefer unplayable
        # curses/statuses, then surplus block, then unaffordable cards.
        if action.kind == "skip_select":
            return 0.0
        combat = state.get("combat_state", {})
        need = max(0, sum(incoming(e) for e in combat.get("enemies", []))
                   - state["player"]["block"])
        score = 0.0
        for index in map(int, action.args["indices"].split(",")):
            card = next(c for c in state["cards"] if c["index"] == index)
            if card["type"] in ("Curse", "Status"):
                score += 20
            elif card.get("cost", 0) > combat.get("energy", 0):
                score += 5
            else:
                stats = card.get("stats") or {}
                score -= stats.get("damage", 0) + min(need, stats.get("block", 0))
        powers = combat.get("player_powers") or []
        source = state.get("selection_source", {})
        if source.get("kind") == "end_turn" and any("WELL_LAID_PLANS" in p["id"] for p in powers):
            score = -score  # Retain useful cards rather than discarding them.
        return score
    if action.kind == "play_card":
        card = next(c for c in state["hand"] if c["index"] == action.args["card_index"])
        stats = card.get("stats") or {}
        need = max(0, sum(incoming(e) for e in state["enemies"]) - state["player"]["block"])
        score = min(need, stats.get("block", 0)) * 1.2
        target = next((e for e in state["enemies"] if e["index"] == action.args.get("target_index")), None)
        if target:
            preview = next((p for p in card.get("damage_by_target", [])
                            if p["target_index"] == target["index"]), {})
            damage = preview.get("total_damage", preview.get("damage", stats.get("damage", 0)))
            score += min(damage, target["hp"] + target.get("block", 0))
            if damage >= target["hp"] + target.get("block", 0):
                score += 10 + incoming(target)
            if stats.get("weak", 0):
                score += incoming(target) * 0.25
            score += stats.get("poison", 0) * 2
        elif card.get("type") == "Attack":
            # Public multi-target previews when available; otherwise base damage.
            score += sum(min((card.get("stats") or {}).get("damage", 0), e["hp"] + e.get("block", 0))
                         for e in state["enemies"])
        if card.get("type") == "Power":
            score += 8  # Generic rollout heuristic; the teacher still compares outcomes.
        score += stats.get("energy", 0) * 5
        score += stats.get("cards", 0) * 2
        return score - 0.1 * card.get("cost", 0)
    if action.kind == "use_potion":
        potion = next(p for p in state["player"]["potions"] if p["index"] == action.args["potion_index"])
        v = {k.lower(): x for k, x in (potion.get("vars") or {}).items()}
        need = max(0, sum(incoming(e) for e in state["enemies"]) - state["player"]["block"])
        return min(need, v.get("block", 0)) + v.get("damage", 0) * .5 + v.get("energy", 0) * 4 - 3
    if action.kind == "select_card_reward":
        c = next(c for c in state["cards"] if c["index"] == action.args["card_index"])
        v = c.get("stats") or {}
        return v.get("damage", 0) + v.get("block", 0) + v.get("poison", 0) * 2 - c.get("cost", 0)
    return 0


def heuristic(state: dict) -> Action:
    return max(legal_actions(state), key=lambda a: heuristic_score(state, a))


def equivalent_groups(state: dict, actions: list[Action]) -> list[list[Action]]:
    """Share estimates only for audited stateless starter card identities.

    Other cards may carry per-copy history not yet covered by public export.
    Equal public fields alone do not prove those cards are interchangeable.
    """
    groups = defaultdict(list)
    for action in actions:
        if action.kind == "play_card":
            card = next(c for c in state["hand"] if c["index"] == action.args["card_index"])
            public_card = {k: v for k, v in card.items() if k != "index"}
            if card["id"] in ("CARD.STRIKE_SILENT", "CARD.DEFEND_SILENT", "CARD.NEUTRALIZE", "CARD.SURVIVOR"):
                key = digest([action.kind, public_card, action.args.get("target_index")])
            else:
                key = action.id
        else:
            key = action.id
        groups[key].append(action)
    return list(groups.values())


def combat_result(state: dict, *, profile: str = SAMPLER) -> dict | None:
    if state.get("decision") == "game_over":
        if state.get("victory") and profile == SAMPLER:
            raise NativeError("Unexpected whole-run victory in combat curriculum")
        if not state.get("victory"):
            return {"won": False, "hp": 0, "return": 0.0}
    if state.get("in_combat") is False:
        hp = state["player"]["hp"]
        if hp <= 0 or (profile == SAMPLER and state.get("decision") not in ("card_reward", "map_select")):
            raise NativeError("Unverified combat terminal state")
        value = hp if profile == SAMPLER else 100 * hp / state["player"]["max_hp"]
        return {"won": True, "hp": hp, "return": 100.0 + value}
    return None


def rollout(worker: NativeSession, first: Action, *, horizon: int = 256, profile: str = SAMPLER) -> dict:
    potions, escaped = 0, False
    def act(action):
        nonlocal potions, escaped
        if action.kind == "use_potion":
            potions += 1
            p = next(p for p in worker.state["player"]["potions"] if p["index"] == action.args["potion_index"])
            escaped |= "SMOKE_BOMB" in p["id"]
        worker.step(action)
    act(first)
    for step in range(1, horizon + 1):
        result = combat_result(worker.state, profile=profile)
        if result is not None:
            if profile == ACT1_SAMPLER:
                result["return"] = max(0, result["return"] - 3 * potions - (100 if escaped else 0))
                result["won"] &= not escaped
            return {**result, "steps": step}
        if step < horizon:
            act(heuristic(worker.state))
    raise NativeError("Rollout truncated; this root must not become a teacher label")


def teach_root(worker: NativeSession, fork: ReplayFork, state: dict, *, samples: int = 8,
               seed: int = 0, horizon: int = 256, profile: str = SAMPLER) -> dict:
    if samples < 2:
        raise ValueError("At least two chance samples required")
    if state.get("decision") not in ("combat_play", "card_select", "card_reward", "bundle_select") or digest(state) != fork.expected_digest:
        raise ValueError("Teacher requires a matching combat decision fork")
    actions = legal_actions(state)
    groups = equivalent_groups(state, actions)
    worlds = [random.Random(seed + i * 1000003).getrandbits(64) for i in range(samples)]
    estimates, started = {}, time.perf_counter()
    branches = 0
    for group in groups:
        values, wins, steps = [], [], []
        for world in worlds:
            worker.restore(fork)
            if profile == SAMPLER:
                worker.sample(world)
            else:
                worker.sample(world, profile=profile)
            first = next(a for a in legal_actions(worker.state) if a.id == group[0].id)
            result = rollout(worker, first, horizon=horizon, profile=profile)
            values.append(result["return"])
            wins.append(result["won"])
            steps.append(result["steps"])
            branches += 1
        for action in group:
            estimates[action.id] = {"mean_return": statistics.fmean(values),
                "standard_error": statistics.stdev(values) / math.sqrt(samples),
                "samples": samples, "win_fraction": statistics.fmean(wins),
                "mean_steps": statistics.fmean(steps)}
    best = max(actions, key=lambda a: (estimates[a.id]["mean_return"], heuristic_score(state, a)))
    return {"schema_version": 1, "sampler": profile,
        "observation": deepcopy(state),
        "actions": [{"id": a.id, "kind": a.kind, "args": a.args} for a in actions],
        "estimates": estimates, "chosen_action_id": best.id,
        "continuation": "public-combat-heuristic-v2", "horizon": horizon,
        "branches": branches, "seconds": time.perf_counter() - started}
