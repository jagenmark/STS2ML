"""Pinned-host differential fixtures. Set CSV2DEV_HOST to run on the oracle."""
from collections import Counter
from pathlib import Path
import json
import os

import pytest

from sts2rl.combat_search_v2.end_turn import attack_amount
from sts2rl.combat_search_v2.state import project, root_move
from sts2rl.combat_search_v2.transitions import advance, legal
from sts2rl.native import NativeSession, legal_actions

HOST = os.environ.get("CSV2DEV_HOST")
pytestmark = pytest.mark.skipif(not HOST, reason="set CSV2DEV_HOST to the pinned v0.111.0 host")
ROOT = Path(__file__).resolve().parents[1]


class Oracle:
    def __init__(self, game):
        self.game = game

    def command(self, **command):
        # The two scenario controls are deliberately outside the policy loop.
        self.game.process.stdin.write(json.dumps(command) + "\n")
        self.game.process.stdin.flush()
        result = self.game._read()
        assert result.get("type") != "error", result
        return result

    def start(self, label, deck, potions=(), encounter="SHRINKER_BEETLE_WEAK", hp=56, seed=None):
        self.game.reset(seed or f"CSV2DEV_ORACLE_{label}")
        self.command(cmd="set_player", hp=hp, deck=deck, potions=potions)
        self.public = self.command(cmd="enter_room", type="monster", encounter=encounter)
        self.simulated = project(self.public).state
        self.check_legal(self.simulated)

    def refresh(self):
        self.simulated = project(self.public).state
        self.check_legal(self.simulated)

    def with_cloak(self, deck, encounter, potions=(), hp=70):
        self.game.reset("CSV2DEV_FIND_CLOAK_135")
        self.command(cmd="set_player", gold=999, hp=hp, deck=deck, potions=potions)
        shop = self.command(cmd="enter_room", type="shop")
        relic = next(r for r in shop["relics"] if r.get("name") == "Cloak Clasp")
        self.command(cmd="action", action="buy_relic", args={"relic_index": relic["index"]})
        self.public = self.command(cmd="enter_room", type="monster", encounter=encounter)
        self.refresh()

    def moves(self, state):
        living = [e.slot for e in state.enemies if e.hp > 0]
        hand = [c.slot for c in state.hand]
        potions = [p.slot for p in state.potions]
        candidates = state.prompt.candidates if state.prompt else ()
        result = []
        for move in legal(state):
            target = living.index(move.target) if move.target >= 0 else -1
            slot = move.slot
            if move.kind == "play_card":
                slot = hand.index(move.slot)
            elif move.kind == "use_potion":
                slot = potions.index(move.slot)
            selection = tuple(candidates.index(i) for i in move.selection)
            result.append((move.kind, slot, target, selection))
        return result

    def check_legal(self, state):
        if state.prompt and self.public["decision"] == "card_select":
            native = [("select_cards", -1, -1, tuple(map(int, a.args["indices"].split(",")))
                       if a.kind == "select_cards" else ()) for a in legal_actions(self.public)]
        else:
            projected = project(self.public)
            native = [(m.kind, m.slot, m.target, m.selection) for m in
                      (root_move(projected, a.kind, a.args) for a in legal_actions(self.public))]
        assert self.moves(state) == native

    def step(self, kind, name=None, target=None):
        state = self.simulated
        choices = legal_actions(self.public)

        def matches(action):
            if action.kind != kind or (target is not None and action.args.get("target_index") != target):
                return False
            if name is None:
                return True
            if kind == "play_card":
                return self.public["hand"][action.args["card_index"]]["id"] == f"CARD.{name}"
            if kind == "use_potion":
                return any(p["index"] == action.args["potion_index"] and p["id"] == f"POTION.{name}"
                           for p in self.public["player"]["potions"])
            return self.public["cards"][int(action.args["indices"])]["id"] == f"CARD.{name}"

        action = next(a for a in choices if matches(a))
        move = next(move for move, signature in zip(legal(state), self.moves(state))
                    if signature == (
                        "select_cards" if kind == "skip_select" else kind,
                        action.args.get("card_index", action.args.get("potion_index", -1)),
                        action.args.get("target_index", -1),
                        tuple(map(int, action.args["indices"].split(","))) if kind == "select_cards" else (),
                    ))
        self.simulated = advance(state, move)
        self.public = self.command(**action.command())
        self.check_observation()
        return self.simulated

    def check_observation(self):
        state = self.simulated
        public = self.public
        if state.outcome == "dead":
            assert public["decision"] == "game_over" and public["player"]["hp"] == 0
            return
        if state.outcome == "victory":
            assert not public["in_combat"]
            return
        view = public.get("combat_state", public)
        assert (state.hp, state.block) == (view["player"]["hp"], view["player"]["block"])
        assert state.energy == view["energy"]
        actual_enemies = view["enemies"]
        living = [e for e in state.enemies if e.hp > 0]
        assert [(e.name, e.hp, e.block) for e in living] == [
            (e["id"].split(".")[1], e["hp"], e["block"]) for e in actual_enemies
        ]

        def native_powers(rows):
            return dict((p["id"].split(".")[1].removesuffix("_POWER"), p["amount"]) for p in rows or ())

        assert dict(state.powers) == native_powers(view["player_powers"])
        for e, row in zip(living, actual_enemies):
            assert dict(e.powers) == native_powers(row["powers"])
        if state.boundary:
            if state.outcome == "completed":
                assert view["round"] == state.round
            return
        assert view["round"] == state.round
        assert public["decision"] == ("card_select" if state.prompt else "combat_play")
        if state.prompt:
            assert (state.prompt.minimum, state.prompt.maximum) == (public["min_select"], public["max_select"])
        assert [(c.variant.name, c.variant.cost) for c in state.hand] == [
            (c["id"].split(".")[1], c["cost"]) for c in view["hand"]
        ]
        for zone in ("draw", "discard", "exhaust", "play"):
            assert Counter((v.name, v.cost) for v in getattr(state, zone)) == Counter(
                (c["id"].split(".")[1], c["cost"]) for c in view[f"{zone}_pile"]
            )
        for predicted, actual in zip(living, actual_enemies):
            assert [attack_amount(state, predicted, intent) for intent in predicted.intents
                    if intent.damage is not None] == [
                        intent["damage"] for intent in actual["intents"] if "damage" in intent
                    ]
        self.check_legal(state)


@pytest.fixture
def oracle(tmp_path):
    with NativeSession(ROOT, tmp_path / "engine", host_path=HOST) as game:
        yield Oracle(game)


def test_native_energy_and_x_replay(oracle):
    oracle.start("ENERGY", ["STRIKE_SILENT", "DEFEND_SILENT", "DEFEND_SILENT", "MALAISE"],
                 ["ENERGY_POTION", "DUPLICATOR"])
    for _ in range(3):
        oracle.step("play_card", "STRIKE_SILENT" if _ == 0 else "DEFEND_SILENT")
    oracle.step("use_potion", "ENERGY_POTION")
    oracle.step("use_potion", "DUPLICATOR")
    oracle.step("play_card", "MALAISE")


def test_native_burst_duplication_survivor_and_afterimage(oracle):
    oracle.start("BURST", ["AFTERIMAGE", "BURST", "SURVIVOR", "DEFEND_SILENT",
                           "DEFEND_SILENT", "TACTICIAN", "BURN"], ["DUPLICATOR"])
    oracle.step("play_card", "AFTERIMAGE")
    oracle.step("play_card", "BURST")
    oracle.step("use_potion", "DUPLICATOR")
    oracle.step("play_card", "SURVIVOR")
    oracle.step("select_cards", "BURN")
    oracle.step("select_cards", "DEFEND_SILENT")
    oracle.step("select_cards", "DEFEND_SILENT")


def test_native_retained_status_ethereal_and_blur(oracle):
    oracle.start("RETAIN", ["WELL_LAID_PLANS", "DAZED", "BURN", "WITHER",
                            "BLUR", "DEFEND_SILENT", "DEFEND_SILENT"])
    oracle.step("play_card", "WELL_LAID_PLANS")
    oracle.step("play_card", "BLUR")
    successor = oracle.step("end_turn")
    assert successor.outcome == "completed"
    assert successor.exhaust[0].name == "DAZED"
    assert set(c.variant.name for c in successor.hand) == {"DEFEND_SILENT", "BURN", "WITHER"}


def test_native_shiv_overflow(oracle):
    oracle.start("SHIV", ["BLADE_DANCE", *(["STRIKE_SILENT"] * 11)], ["SWIFT_POTION"])
    action = next(a for a in legal_actions(oracle.public) if a.kind == "use_potion")
    oracle.public = oracle.command(**action.command())
    if not any(c["id"] == "CARD.BLADE_DANCE" for c in oracle.public["hand"]):
        pytest.fail("Fixture did not draw Blade Dance")
    oracle.refresh()
    oracle.step("play_card", "BLADE_DANCE")
    oracle.step("play_card", "SHIV")


def test_native_sandpit_countdown(oracle):
    oracle.start("SANDPIT", ["DEFEND_SILENT"] * 3, encounter="THE_INSATIABLE_BOSS", hp=70)
    oracle.step("end_turn")
    oracle.refresh()
    oracle.step("end_turn")
    oracle.refresh()
    oracle.step("play_card", "FRANTIC_ESCAPE")
    oracle.step("play_card", "DEFEND_SILENT")
    oracle.step("end_turn")


def test_native_cloak_before_hand_damage(oracle):
    oracle.with_cloak(["BURN", "WITHER", "DAZED", "DEFEND_SILENT", "DEFEND_SILENT",
                       "DEFEND_SILENT", "DEFEND_SILENT"], "SHRINKER_BEETLE_WEAK")
    successor = oracle.step("end_turn")
    assert successor.hp == 70


def test_native_constrict_cloak_and_status_damage(oracle):
    oracle.with_cloak(["BURN", "WITHER", "DEFEND_SILENT", "DEFEND_SILENT", "DEFEND_SILENT"],
                      "SLITHERING_STRANGLER_NORMAL", ["BLOCK_POTION"])
    a = next(a for a in legal_actions(oracle.public) if a.kind == "end_turn")
    oracle.public = oracle.command(**a.command())
    oracle.refresh()
    oracle.step("use_potion", "BLOCK_POTION")
    oracle.step("end_turn")

def test_native_vital_spark_and_replayed_skill(oracle):
    oracle.start("VITAL_SPARK", ["BURST", "DEFEND_SILENT", "AFTERIMAGE", "DEFEND_SILENT"],
                 ["DUPLICATOR"], encounter="INFESTED_PRISMS_ELITE", hp=70)
    oracle.step("play_card", "AFTERIMAGE")
    oracle.step("play_card", "BURST")
    oracle.step("use_potion", "DUPLICATOR")
    successor = oracle.step("play_card", "DEFEND_SILENT")
    assert successor.enemies[0].attack_delta == 12
    oracle.step("end_turn")


def test_native_sly_trigger_and_adrenaline(oracle):
    oracle.start("SLY", ["SURVIVOR", "TACTICIAN", "ADRENALINE", "DEFEND_SILENT"])
    oracle.step("play_card", "ADRENALINE")
    oracle.step("play_card", "SURVIVOR")
    oracle.step("select_cards", "TACTICIAN")


def test_native_buffer_order_and_block(oracle):
    oracle.start("ORDER", ["BUFFER", "BURN", "DEFEND_SILENT", "DEFEND_SILENT"],
                 ["BLOCK_POTION"], encounter="SLITHERING_STRANGLER_NORMAL", hp=70)
    a = next(a for a in legal_actions(oracle.public) if a.kind == "end_turn")
    oracle.public = oracle.command(**a.command())
    oracle.refresh()
    oracle.step("play_card", "BUFFER")
    oracle.step("play_card", "DEFEND_SILENT")
    oracle.step("end_turn")


def test_native_wriggler_slots_and_status_generation(oracle):
    oracle.start("WRIGGLERS", ["DEFEND_SILENT"] * 20,
                 encounter="DENSE_VEGETATION_EVENT_ENCOUNTER", hp=70)
    state = oracle.step("end_turn")
    assert state.hp == 56
    assert sum(v.name == "INFECTION" for v in state.discard) == 2
    oracle.refresh()
    oracle.step("end_turn")


def test_native_replay_planners_energy_save(oracle):
    from sts2rl.combat_search_v2.planner import search
    from sts2rl.combat_search_v2.state import END_TURN

    oracle.start("PLANNER_REPLAY", ["STRIKE_SILENT"] * 3 + ["DEFEND_SILENT"],
                 ["ENERGY_POTION"], hp=4)
    oracle.step("end_turn")
    oracle.refresh()
    for _ in range(3):
        oracle.step("play_card", "STRIKE_SILENT")
    projected = project(oracle.public)
    result = search(projected, legal(projected.state), END_TURN)
    line = result.line
    assert [m.kind for m in line.path] == ["use_potion", "play_card", "end_turn"]
    for move in line.path:
        oracle.step(move.kind)
    assert oracle.simulated.hp == line.state.hp == 1


def test_native_constrict_precedes_lethal_poison(oracle):
    oracle.start("CONSTRICT_POISON", ["DEADLY_POISON"] * 5, ["POISON_POTION"] * 2,
                 encounter="SLITHERING_STRANGLER_NORMAL", hp=3,
                 seed="CSV2DEV_PROFILE_SLITHERING_STRANGLER_NORMAL")
    for _ in range(2):
        oracle.step("use_potion", "POISON_POTION", target=1)
    for _ in range(3):
        oracle.step("play_card", "DEADLY_POISON", target=1)
    oracle.step("end_turn")
    oracle.refresh()
    for _ in range(3):
        oracle.step("play_card", "DEADLY_POISON", target=1)
    enemy = oracle.simulated.enemies[1]
    assert dict(enemy.powers)["POISON"] >= enemy.hp
    assert oracle.step("end_turn").outcome == "dead"


def test_native_x_with_artifact(oracle):
    oracle.start("ARTIFACT", ["NEUTRALIZE", "MALAISE", "DEFEND_SILENT"],
                 encounter="TUNNELER_NORMAL", hp=70)
    oracle.step("play_card", "NEUTRALIZE", target=0)
    successor = oracle.step("play_card", "MALAISE", target=0)
    assert dict(successor.enemies[0].powers) == {"WEAK": 3}


@pytest.mark.parametrize("formation", ["NIBBITS_NORMAL", "FUZZY_WURM_CRAWLER_WEAK", "SLIMES_WEAK"])
def test_native_hallway_turns(oracle, formation):
    oracle.start(formation, ["DEFEND_SILENT"] * 16, encounter=formation, hp=70)
    for _ in range(3):
        oracle.step("play_card", "DEFEND_SILENT")
        oracle.step("end_turn")
        oracle.refresh()


@pytest.mark.parametrize("label", ["STATUS_ORDER_0", "STATUS_ORDER_1", "STATUS_ORDER_2"])
def test_native_buffer_with_multiple_hand_statuses(oracle, label):
    oracle.start(label, ["BUFFER", "BURN", "WITHER", "DEFEND_SILENT"], hp=70)
    oracle.step("play_card", "BUFFER")
    oracle.step("end_turn")


def test_native_sandpit_countdown_is_lethal_independently_of_hits(oracle):
    oracle.start("SANDPIT_DEATH", ["DEFEND_SILENT"] * 16,
                 encounter="THE_INSATIABLE_BOSS", hp=70)
    for _ in range(4):
        for _ in range(2):
            oracle.step("play_card", "DEFEND_SILENT")
        oracle.step("end_turn")
        oracle.refresh()
    state = oracle.simulated
    assert dict(state.enemies[0].powers)["SANDPIT"] == 1
    assert state.hp > sum(i.damage * i.hits for i in state.enemies[0].intents if i.damage is not None)
    assert oracle.step("end_turn").outcome == "dead"


@pytest.mark.parametrize("first,second", [
    ("STRENGTH_POTION", "VULNERABLE_POTION"),
    ("DEXTERITY_POTION", "WEAK_POTION"),
    ("GHOST_IN_A_JAR", "BLOCK_POTION"),
    ("FIRE_POTION", "EXPLOSIVE_AMPOULE"),
])
def test_native_deterministic_potion_pairs(oracle, first, second):
    oracle.start(first, ["DEFEND_SILENT"] * 5 + ["STRIKE_SILENT"] * 5,
                 [first, second], encounter="NIBBITS_WEAK", hp=70)
    oracle.step("use_potion", first)
    if oracle.public["in_combat"]:
        oracle.step("use_potion", second)
    if oracle.public["in_combat"]:
        oracle.step("end_turn")


def test_native_escape_replay_cost(oracle):
    oracle.start("ESCAPE_REPLAY", ["DEFEND_SILENT"] * 3, ["DUPLICATOR"],
                 encounter="THE_INSATIABLE_BOSS", hp=70)
    oracle.step("end_turn")
    oracle.refresh()
    oracle.step("use_potion", "DUPLICATOR")
    successor = oracle.step("play_card", "FRANTIC_ESCAPE")
    assert dict(successor.enemies[0].powers)["SANDPIT"] == 6


@pytest.fixture
def recorded_oracle(tmp_path):
    from sts2rl.combat_search_v2.recording import observer_environment, observer_path

    path = os.environ.get("CSV2DEV_OBSERVER")
    if not path:
        pytest.skip("set CSV2DEV_OBSERVER to the Phase 2 startup hook")
    receipt_path = tmp_path / "observer.jsonl"
    with observer_environment(observer_path(ROOT, path), receipt_path):
        with NativeSession(ROOT, tmp_path / "engine", host_path=HOST) as game:
            yield Oracle(game), receipt_path


def _draw_receipt(path):
    return [row["draw"] for line in path.read_text().splitlines()
            if (row := json.loads(line)).get("draw")][-1]


def test_native_recorded_features_and_hidden_draw_permutation(tmp_path):
    from sts2rl.combat_search_v2.end_turn import resolve
    from sts2rl.combat_search_v2.features import extract_leaf_features, extract_post_eot_features
    from sts2rl.combat_search_v2.recording import observer_environment, observer_path

    import numpy as np

    path = os.environ.get("CSV2DEV_OBSERVER")
    if not path:
        pytest.skip("set CSV2DEV_OBSERVER to the Phase 2 startup hook")
    results = []
    hands = []
    for reverse in (False, True):
        receipt_path = tmp_path / f"observer-{reverse}.jsonl"
        with observer_environment(observer_path(ROOT, path), receipt_path):
            with NativeSession(ROOT, tmp_path / f"engine-{reverse}", host_path=HOST) as game:
                oracle = Oracle(game)
                oracle.start("PERMUTATION", ["STRIKE_SILENT"] * 9 + ["DEFEND_SILENT"] * 9)
                before = oracle.public
                order = sorted([c["id"].split(".")[-1] for c in before["draw_pile"]], reverse=reverse)
                oracle.command(cmd="set_draw_order", cards=order)
                oracle.step("end_turn")
                after = oracle.public
                hands.append([c["id"] for c in after["hand"]])
                x = extract_post_eot_features(before, after, witness=_draw_receipt(receipt_path))
                np.testing.assert_allclose(x, extract_leaf_features(resolve(project(before).state)),
                                           rtol=0, atol=1e-5)
                np.testing.assert_array_equal(x, extract_post_eot_features(before, after))
                after["energy"] = -123456
                after["player"]["potions"] = [{"private_rng": object()}]
                after["enemies"][0]["intents"] = object()
                np.testing.assert_array_equal(x, extract_post_eot_features(
                    before, after, witness=_draw_receipt(receipt_path)))
                results.append(x)
    assert hands[0] != hands[1]
    np.testing.assert_array_equal(*results)


def test_native_draw_created_card_is_censored(recorded_oracle):
    from sts2rl.combat_search_v2.features import extract_post_eot_features
    from sts2rl.combat_search_v2.state import Unsupported

    oracle, receipt_path = recorded_oracle
    oracle.start("DRAW_SIZE", ["STRIKE_SILENT"] * 9 + ["DEFEND_SILENT"] * 9)
    before = oracle.public
    after = oracle.command(cmd="action", action="end_turn")
    # Inject the same public multiset change as a draw-created card.
    after["hand"].append({**after["hand"][0], "id": "CARD.ENDLESS_AGONY"})
    with pytest.raises(Unsupported, match="live deck size"):
        extract_post_eot_features(before, after, witness=_draw_receipt(receipt_path))


def test_native_act1_boss_labels_before_act_heal(recorded_oracle):
    from sts2rl.combat_search_v2.recording import terminal_label

    oracle, receipt_path = recorded_oracle
    oracle.game.reset("CSV2DEV_ORACLE_BOSS_EXIT")
    oracle.command(cmd="set_player", hp=48, deck=["BACKSTAB"] * 40,
                   potions=["EXPLOSIVE_AMPOULE"] * 3)
    state = oracle.command(cmd="enter_room", type="monster", encounter="CEREMONIAL_BEAST_BOSS")
    assert state["context"]["room_type"] == "Boss"
    for _ in range(100):
        before = state
        actions = legal_actions(state)
        action = next((a for a in actions if a.kind == "use_potion"), actions[0])
        state = oracle.command(**action.command())
        if not state["in_combat"]:
            break
    assert not state["in_combat"]
    witness = json.loads(receipt_path.read_text().splitlines()[-1])["exit"]
    label = terminal_label(before, action, state, witness)
    assert label["outcome"] == "victory"
    assert label["exit_hp"] == before["player"]["hp"]
    for _ in range(10):
        if state["context"]["act"] == 2:
            break
        action = legal_actions(state)[-1]
        state = oracle.command(**action.command())
    assert state["context"]["act"] == 2
    assert state["player"]["hp"] > label["exit_hp"]


def test_pinned_host_smoke_bomb_model_is_absent(oracle):
    oracle.game.reset("CSV2DEV_ORACLE_SMOKE_BOMB")
    with pytest.raises(AssertionError, match=r"Model id=POTION.SMOKE_BOMB not found"):
        oracle.command(cmd="set_player", potions=["SMOKE_BOMB"])
