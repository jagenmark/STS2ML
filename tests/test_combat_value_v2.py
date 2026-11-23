"""Combat value bundle integrity and safety-rank integration."""
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from sts2rl.combat_search_v2.artifact import CombatValueModel
from sts2rl.combat_search_v2.state import State
from sts2rl.combat_search_v2.value import DEAD, SURVIVED, UNRESOLVED, VICTORY, leaf_value
from sts2rl.run_bundle import freeze_bundle, load_bundle

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "docs/combat-search-v2/models/combat_value_v2.npz"


def test_value_checkpoint_is_hash_bound_and_numpy_callable(tmp_path):
    manifest = {"args": {"roles": ["candidate"], "combat_search_v2": True, "combat_value_v2": MODEL,
                         "weights": ROOT / "releases/silent-a10-v2-tactics/challenger/weights.json"}}
    bundle = freeze_bundle(manifest, tmp_path / "bundle")
    _, settings = load_bundle(bundle)
    model = CombatValueModel.load(settings["combat_value_v2"])
    state = State(21, 70, 8, 3, 3, 3, 1, "Monster", (), (), (), outcome="completed", floor=4)
    prediction = model.leaf(state)
    assert all(0 < x < 1 for x in prediction)
    assert np.array_equal(model.mean, CombatValueModel.load(MODEL).mean)
    with settings["combat_value_v2"].open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError, match="checksum mismatch"):
        load_bundle(bundle)


def test_learned_value_preserves_terminal_rank_and_charges_potions_once():
    class Model:
        calls = []

        def leaf(self, state):
            self.calls.append(state)
            return 0.8, 0.5

    model = Model()
    state = State(21, 70, 0, 3, 3, 3, 1, "Monster", (), (), (), outcome="completed", spent=1)
    assert leaf_value(state, 7, model) == (SURVIVED, 21.0)
    assert leaf_value(state, 7, model, 10) == (SURVIVED, 29.0)
    assert leaf_value(replace(state, outcome="victory"), 7, model) == (VICTORY, 14.0)
    assert leaf_value(replace(state, outcome="dead", hp=0), 7, model)[0] == DEAD
    assert leaf_value(replace(state, outcome=""), 7, model)[0] == UNRESOLVED
    assert model.calls == [state, state]
