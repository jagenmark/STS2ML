"""Small stochastic fixtures test the search contract, not STS2 gameplay."""

from copy import deepcopy

import pytest

from sts2rl.search import Transition, evaluate_root_actions


class HiddenCoin:
    """Safe 0.6 reward versus guessing a hidden fair coin for reward 0 or 1."""

    def sample_root(self, observation, rng):
        assert observation == {"stage": "root"}
        return {"stage": "root", "hidden": rng.randrange(2)}

    def clone(self, state):
        return deepcopy(state)

    def public_observation(self, state):
        return {"stage": state["stage"]}

    def legal_actions(self, state):
        return ("safe", "guess") if state["stage"] == "root" else ("zero", "one")

    def step(self, state, action_id, rng):
        if action_id == "safe":
            return Transition(state, 0.6, True)
        if action_id == "guess":
            state["stage"] = "guess"
            return Transition(state, 0.0, False)
        return Transition(state, float(int(action_id == "one") == state["hidden"]), True)


def visible_policy(observation, legal, rng):
    assert observation == {"stage": "guess"}
    assert "hidden" not in observation
    assert legal == ("zero", "one")
    return "zero"


def test_average_before_selection_and_no_latent_state_given_to_policy():
    result = evaluate_root_actions(
        HiddenCoin(), {"stage": "root"}, ["safe", "guess"], visible_policy,
        samples=1000, seed=17, horizon=2,
    )
    by_id = {item.action_id: item for item in result.estimates}
    assert result.best_action_id == "safe"
    assert by_id["safe"].mean_return == pytest.approx(0.6)
    assert 0.45 < by_id["guess"].mean_return < 0.55
    assert by_id["guess"].standard_error > 0
    assert all(item.truncated_rollouts == 0 for item in result.estimates)


def test_seed_reproducibility_and_candidate_order_independence():
    kwargs = dict(samples=50, seed=21, horizon=2)
    first = evaluate_root_actions(
        HiddenCoin(), {"stage": "root"}, ["safe", "guess"], visible_policy, **kwargs
    )
    repeated = evaluate_root_actions(
        HiddenCoin(), {"stage": "root"}, ["safe", "guess"], visible_policy, **kwargs
    )
    reversed_result = evaluate_root_actions(
        HiddenCoin(), {"stage": "root"}, ["guess", "safe"], visible_policy, **kwargs
    )
    assert first == repeated
    assert first.estimates == tuple(reversed(reversed_result.estimates))


def test_horizon_is_reported_as_truncation_and_has_no_fake_terminal_reward():
    result = evaluate_root_actions(
        HiddenCoin(), {"stage": "root"}, ["guess"], visible_policy,
        samples=10, horizon=1,
    )
    assert result.estimates[0].truncated_rollouts == 10
    assert result.estimates[0].mean_return == 0.0


def test_illegal_continuation_is_rejected():
    with pytest.raises(ValueError, match="illegal"):
        evaluate_root_actions(
            HiddenCoin(), {"stage": "root"}, ["guess"],
            lambda obs, legal, rng: "impossible", samples=1,
        )


def test_illegal_root_and_duplicate_candidates_are_rejected():
    with pytest.raises(ValueError, match="root world"):
        evaluate_root_actions(
            HiddenCoin(), {"stage": "root"}, ["unknown"], visible_policy, samples=1
        )
    with pytest.raises(ValueError, match="unique"):
        evaluate_root_actions(
            HiddenCoin(), {"stage": "root"}, ["safe", "safe"], visible_policy
        )


def test_discount_applies_to_later_reward():
    full = evaluate_root_actions(
        HiddenCoin(), {"stage": "root"}, ["guess"], visible_policy,
        samples=100, seed=42, discount=1,
    )
    half = evaluate_root_actions(
        HiddenCoin(), {"stage": "root"}, ["guess"], visible_policy,
        samples=100, seed=42, discount=0.5,
    )
    assert half.estimates[0].mean_return == pytest.approx(full.estimates[0].mean_return / 2)


def test_one_sample_does_not_claim_zero_uncertainty():
    result = evaluate_root_actions(
        HiddenCoin(), {"stage": "root"}, ["safe"], visible_policy, samples=1,
    )
    assert result.estimates[0].standard_error is None


@pytest.mark.parametrize("kwargs", [
    {"samples": 0}, {"samples": True}, {"horizon": 0}, {"discount": float("nan")},
    {"discount": 1.1}, {"seed": True},
])
def test_invalid_budgets_are_rejected(kwargs):
    with pytest.raises(ValueError):
        evaluate_root_actions(HiddenCoin(), {"stage": "root"}, ["safe"], visible_policy, **kwargs)


def test_nonfinite_rewards_are_rejected():
    class BadReward(HiddenCoin):
        def step(self, state, action_id, rng):
            return Transition(state, float("nan"), True)

    with pytest.raises(ValueError, match="finite"):
        evaluate_root_actions(BadReward(), {"stage": "root"}, ["safe"], visible_policy)
