"""Root-sampled Monte Carlo evaluation contract, independent of STS2 mechanics.

The simulator owns latent states and chance sampling. A continuation policy sees
only public observations and legal actions, including when the current action
draws cards mid-turn. This is a small rollout evaluator, not an STS2 simulator or
an implementation of information-set MCTS.
"""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol

PublicObservation = Mapping[str, Any]
RolloutPolicy = Callable[[PublicObservation, Sequence[str], random.Random], str]


@dataclass(frozen=True)
class Transition:
    """One simulator transition; reward belongs to this transition, not the next one."""

    state: Any
    reward: float
    terminated: bool


class ChanceSimulator(Protocol):
    """A backend must honor the information boundary, not just these method types.

    ``sample_root`` samples a fresh latent world conditional only on public root
    information. ``public_observation`` must exclude hidden draw order, RNG state
    and future outcomes. ``legal_actions`` must not encode hidden information.
    ``step`` must use the sampled world and RNG for unresolved chance transitions.
    ``clone`` must isolate worlds so siblings cannot mutate each other.
    """

    def sample_root(self, observation: PublicObservation, rng: random.Random) -> Any: ...
    def clone(self, state: Any) -> Any: ...
    def public_observation(self, state: Any) -> PublicObservation: ...
    def legal_actions(self, state: Any) -> Sequence[str]: ...
    def step(self, state: Any, action_id: str, rng: random.Random) -> Transition: ...


@dataclass(frozen=True)
class ActionEstimate:
    action_id: str
    mean_return: float
    standard_error: float | None
    samples: int
    truncated_rollouts: int


@dataclass(frozen=True)
class RootEvaluation:
    """Per-action Monte Carlo estimates; uncertainty is sampling error, not calibration."""

    estimates: tuple[ActionEstimate, ...]
    seed: int
    horizon: int

    @property
    def best_action_id(self) -> str:
        # Python's max preserves candidate order on ties.
        return max(self.estimates, key=lambda item: item.mean_return).action_id


def _action_ids(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError("Legal actions must be a sequence of action IDs")
    actions = tuple(values)
    if any(not isinstance(action, str) or not action for action in actions):
        raise ValueError("Action IDs must be nonempty strings")
    if len(set(actions)) != len(actions):
        raise ValueError("Action IDs must be unique")
    return actions


def evaluate_root_actions(
    simulator: ChanceSimulator,
    public_observation: PublicObservation,
    candidates: Sequence[str],
    rollout_policy: RolloutPolicy,
    *,
    samples: int = 64,
    seed: int = 0,
    horizon: int = 100,
    discount: float = 1.0,
) -> RootEvaluation:
    """Evaluate root choices by averaging sampled returns under one public policy.

    Each sample shares one independently sampled hidden world across root actions
    (common random numbers). Root choices are compared *after* averaging across
    worlds. Continuations use ``rollout_policy`` rather than a planner that gets
    to inspect each world's latent information. Candidates may be a subset of
    legal root actions. At a nonterminal horizon cutoff no fabricated terminal
    reward is added; truncations are reported explicitly.

    This estimates action values under the supplied continuation policy, not
    optimal play. A simulator can violate visibility guarantees internally, so
    implementing this Protocol is not evidence that a game backend is fair.
    """
    if isinstance(samples, bool) or not isinstance(samples, int) or samples < 1:
        raise ValueError("samples must be a positive integer")
    if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon < 1:
        raise ValueError("horizon must be a positive integer")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    if isinstance(discount, bool) or not isinstance(discount, (int, float)):
        raise ValueError("discount must be numeric")
    if not math.isfinite(discount) or not 0 <= discount <= 1:
        raise ValueError("discount must be finite and between zero and one")
    if not isinstance(public_observation, Mapping):
        raise ValueError("public_observation must be a mapping")
    actions = _action_ids(candidates)
    if not actions:
        raise ValueError("At least one root candidate is required")
    rng = random.Random(seed)
    returns: dict[str, list[float]] = {action: [] for action in actions}
    cutoffs = dict.fromkeys(actions, 0)

    for _ in range(samples):
        world_seed = rng.getrandbits(128)
        transition_seed = rng.getrandbits(128)
        policy_seed = rng.getrandbits(128)
        world = simulator.sample_root(deepcopy(public_observation), random.Random(world_seed))
        root_legal = _action_ids(simulator.legal_actions(world))
        if any(action not in root_legal for action in actions):
            raise ValueError("A candidate is not legal in a sampled root world")
        for root_action in actions:
            state = simulator.clone(world)
            chance_rng = random.Random(transition_seed)
            policy_rng = random.Random(policy_seed)
            action = root_action
            total = 0.0
            weight = 1.0
            terminated = False
            for depth in range(horizon):
                transition = simulator.step(state, action, chance_rng)
                if (
                    isinstance(transition.reward, bool)
                    or not isinstance(transition.reward, (float, int))
                    or not math.isfinite(transition.reward)
                ):
                    raise ValueError("Simulator rewards must be finite numbers")
                if not isinstance(transition.terminated, bool):
                    raise ValueError("Simulator terminated must be a boolean")
                total += weight * transition.reward
                state = transition.state
                terminated = transition.terminated
                if terminated or depth + 1 == horizon:
                    break
                weight *= discount
                legal = _action_ids(simulator.legal_actions(state))
                if not legal:
                    raise ValueError("Nonterminal rollout state has no legal actions")
                visible = simulator.public_observation(state)
                if not isinstance(visible, Mapping):
                    raise ValueError("Simulator public observation must be a mapping")
                # A policy cannot mutate the simulator's public view in place.
                action = rollout_policy(deepcopy(visible), legal, policy_rng)
                if action not in legal:
                    raise ValueError("Rollout policy selected an illegal action")
            if not math.isfinite(total):
                raise ValueError("Accumulated return must be finite")
            returns[root_action].append(total)
            cutoffs[root_action] += int(not terminated)

    estimates = tuple(
        ActionEstimate(
            action_id=action,
            mean_return=statistics.fmean(returns[action]),
            standard_error=(
                statistics.stdev(returns[action]) / math.sqrt(samples) if samples > 1 else None
            ),
            samples=samples,
            truncated_rollouts=cutoffs[action],
        )
        for action in actions
    )
    return RootEvaluation(estimates=estimates, seed=seed, horizon=horizon)
