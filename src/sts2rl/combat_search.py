"""Spend a bounded number of sampled fight simulations on late Act 1 decisions."""
from __future__ import annotations

from copy import deepcopy
import random

from .native import ACT1_SAMPLER, NativeError, NativeSession, digest, legal_actions
from .run_policy import RunPolicy
from .teacher import combat_result, equivalent_groups, heuristic, heuristic_score
from .turn_planning import choose_turn


class CombatSearch:
    def __init__(
        self,
        root,
        host,
        folder,
        index,
        policy,
        *,
        encounter=None,
        deployed_continuation=False,
        ascension=10,
        turn_search=False,
    ):
        self.root, self.host, self.folder = root, host, folder
        self.index, self.policy = index, policy
        self.encounter = encounter
        self.deployed_continuation = bool(deployed_continuation)
        self.ascension = int(ascension)
        self.turn_search = bool(turn_search)
        self.worker = None
        self.attempts = self.branches = self.changes = 0
        self.errors = []
        self.turns = set()

    def close(self):
        if self.worker is not None:
            self.worker.close()

    def _rollout(self, action, world, *, encounter_clone=None):
        worker = self.worker
        continuation = RunPolicy(self.policy.weights, macro_seed=world, deck_effects=self.policy.deck_effects)
        potions, escaped = 0, False
        for _ in range(256):
            smoke_attempted = False
            if action.kind == "use_potion":
                potions += 1
                slot = action.args["potion_index"]
                item = next(p for p in worker.state["player"]["potions"] if p["index"] == slot)
                smoke_attempted = "SMOKE_BOMB" in item["id"]
                if not self.deployed_continuation:
                    escaped |= smoke_attempted
            s = worker.step(action)
            result = combat_result(s, profile=ACT1_SAMPLER)
            if result is not None:
                if self.deployed_continuation:
                    escaped = smoke_attempted and bool(result.get("won"))
                return max(0., result["return"] - 3 * potions - 100 * escaped)
            if encounter_clone is not None and encounter_clone.applies(s):
                action = encounter_clone.choose(s, continuation)
            elif self.deployed_continuation and self.turn_search and s.get("decision") == "combat_play":
                action = choose_turn(s, continuation)
            else:
                action = continuation(s)
        raise NativeError("Fight search exceeded its rollout horizon")

    def choose(self, game, primary, step):
        state = game.state
        ctx = state["context"]
        if (self.attempts >= 8 or ctx["act"] != 1 or state["decision"] != "combat_play"
                or not state.get("act1_search_support", {}).get("supported")):
            return primary
        # Preserve budget for the Act 1 boss. Earlier queries are restricted
        # to elites or late fights with meaningful danger.
        boss = ctx["room_type"] == "Boss"
        if not boss and (self.attempts >= 2 or ctx["floor"] < 7 or
                         (ctx["room_type"] != "Elite" and state["player"]["hp"] > 25)):
            return primary
        turn = (ctx["floor"], state["round"])
        if turn in self.turns:
            return primary

        actions = legal_actions(state)
        groups = equivalent_groups(state, actions)
        which = {a.id: i for i, g in enumerate(groups) for a in g}
        encounter_applies = (
            self.deployed_continuation
            and self.encounter is not None
            and self.encounter.applies(state)
        )
        state_key = (ctx["act"], ctx["floor"], ctx["room_type"])
        scorer = (
            self.encounter.actor
            if (encounter_applies and self.encounter.actor is not None and self.encounter.key == state_key)
            else self.policy
        )
        scored = {a.id: score for a, score in zip(actions, scorer.combat_scores(state, actions), strict=True)}
        second = max((a for a in actions if which[a.id] != which[primary.id]),
                     key=lambda a: scored[a.id], default=None)
        if second is None:
            return primary
        candidates = [primary, second]
        teacher_choice = heuristic(state)
        if which[teacher_choice.id] not in {which[a.id] for a in candidates}:
            candidates.append(teacher_choice)
        if len(candidates) == 2 and second.kind == "end_turn" and heuristic_score(state, primary) > 0:
            return primary
        self.attempts += 1
        self.turns.add(turn)
        # The sampling stream is independent of the game's seed and its hidden
        # RNG. All candidate effects see the same pair of resampled worlds.
        rng = random.Random(f"silent-combat-search-v1/{self.index}/{step}")
        worlds = [rng.getrandbits(64) for _ in range(2)]
        values = [0.] * len(candidates)
        fork = game.fork()
        try:
            if self.worker is None or self.worker.closed:
                self.worker = NativeSession(
                    self.root,
                    self.folder / f"worker-{self.attempts:02d}",
                    ascension=self.ascension,
                    host_path=self.host,
                    timeout=12,
                    act_list=game.act_list,
                )
            for world in worlds:
                for j, action in enumerate(candidates):
                    self.worker.restore(fork)
                    self.worker.sample(world, profile=ACT1_SAMPLER)
                    self.branches += 1
                    enc_clone = deepcopy(self.encounter) if encounter_applies else None
                    if enc_clone is not None and enc_clone.boss_tactics is not None:
                        enc_clone.boss_tactics.observe(action)
                    if enc_clone is not None:
                        values[j] += self._rollout(action, world, encounter_clone=enc_clone)
                    else:
                        values[j] += self._rollout(action, world)
            # A tie keeps the deployed policy, including its physical card copy.
            idx = max(range(len(values)), key=values.__getitem__)
            self.changes += int(idx != 0)
            return candidates[idx]
        except (NativeError, TimeoutError, ValueError) as exc:
            self.errors.append({"step": step, "state": digest(state), "message": str(exc)})
            self.close()
            return primary
