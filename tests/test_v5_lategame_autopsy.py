import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from shutil import copytree

import pytest

from sts2rl.deployed_controller import DeployedController
from sts2rl.native import NativeSession, runtime_identity
from sts2rl.strategy import strategy_arms


BUNDLE = Path(__file__).resolve().parents[1] / "releases/silent-a10-v2-tactics/challenger"


def controller(flag, macro_seed=0):
    if flag is None:
        return DeployedController.from_bundle(BUNDLE / "policy.json", macro_seed=macro_seed)
    with TemporaryDirectory() as folder:
        copytree(BUNDLE, folder, dirs_exist_ok=True)
        path = Path(folder) / "policy.json"
        path.write_text(json.dumps({**json.loads(path.read_bytes()), "v6_lategame_fixes": flag}))
        return DeployedController.from_bundle(path, macro_seed=macro_seed)


def camp(hp=70, charges=0, enabled=True, act=2):
    return dict(
        decision="rest_site",
        runtime_identity=runtime_identity(10),
        context={"act": act, "floor": 10},
        in_combat=False,
        player=dict(
            hp=hp,
            max_hp=70,
            deck=[],
            gold=0,
            potions=[],
            relics=[{"id": "RELIC.PUMPKIN_CANDLE", "counter": charges}],
        ),
        options=[
            dict(index=i, option_id=x, is_enabled=x != "KINDLE" or enabled)
            for i, x in enumerate(("HEAL", "SMITH", "KINDLE"))
        ],
    )


@pytest.mark.parametrize("flag,expected", [(None, 1), (False, 1), (True, 2)])
def test_expired_candle_opt_in(flag, expected):
    actor = controller(flag)
    state = camp()
    action = actor.choose(state, None)
    assert action.args == {"option_index": expected}
    assert actor.deck_model.to_upgrade == (expected == 1)
    actor.observe(state, action, state)
    assert (actor.policy.selection == "upgrade") == (expected == 1)


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"hp": 25}, 0),
        ({"charges": 1}, 1),
        ({"enabled": False}, 1),
        ({"act": 1}, 1),
    ],
)
def test_candle_preserves_heal_and_requires_spent_legal_candle(kwargs, expected):
    assert controller(True).choose(camp(**kwargs), None).args == {"option_index": expected}


def test_enemy_strength_direction_and_frozen_ancient_behavior():
    state = camp()
    state.update(
        decision="event_choice",
        event_name="Darv",
        context={"act": 2, "floor": 1},
        options=[
            dict(
                index=0,
                text_key="DARV.pages.INITIAL.options.PHILOSOPHERS_STONE",
                description="Gain energy at the start of each turn. ALL enemies start combat with Strength.",
                vars={"StrengthPower": 1},
            ),
            dict(
                index=1,
                text_key="TEZCATARA.pages.INITIAL.options.TOASTY_MITTENS",
                description="At the start of your turn gain Strength.",
                vars={"StrengthPower": 1},
            ),
        ],
    )
    default, disabled, enabled = [
        strategy_arms(state, controller(flag).policy) for flag in (None, False, True)
    ]
    assert default == disabled
    assert default[0][2]["ancient/strength"] == 1 and enabled[0][2]["ancient/strength"] == -1
    assert enabled[0][1] == pytest.approx(default[0][1] - 4)
    assert enabled[1] == default[1]


@pytest.mark.skipif(not os.environ.get("CSV2DEV_HOST"), reason="requires the native A10 host")
def test_explicit_false_matches_every_decision_of_the_default_bundle(tmp_path):
    deployed, disabled = (controller(flag, macro_seed=7203) for flag in (None, False))
    root = BUNDLE.parents[2]
    with NativeSession(root, tmp_path / "episode", host_path=os.environ["CSV2DEV_HOST"]) as game:
        state = game.reset("V5DIAG_0100")
        for _ in range(3000):
            if state["decision"] == "game_over":
                return
            action = deployed.choose(state, game)
            assert disabled.choose(state, game) == action
            after = game.step(action)
            for actor in (deployed, disabled):
                actor.observe(state, action, after)
            state = after
    pytest.fail("Native diagnostic episode did not terminate")
