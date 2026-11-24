"""Observe the pinned host only after forecasting from the completed public leaf."""
from dataclasses import replace
import os
from pathlib import Path

import pytest

from sts2rl.combat_search_v2.next_intent import next_intent
from sts2rl.combat_search_v2.state import END_TURN, project
from sts2rl.combat_search_v2.transitions import advance
from sts2rl.native import NativeSession, legal_actions
from test_combat_search_v2_native import Oracle, ROOT

ENCOUNTERS = (
    "WATERFALL_GIANT_BOSS", "CEREMONIAL_BEAST_BOSS", "LAGAVULIN_MATRIARCH_BOSS",
    "THE_INSATIABLE_BOSS", "VANTOM_BOSS", "SOUL_FYSH_BOSS", "TUNNELER_WEAK",
    "SLUMBERING_BEETLE_NORMAL", "LOUSE_PROGENITOR_NORMAL", "SHRINKER_BEETLE_WEAK",
)
HOST = os.environ.get("CSV2DEV_HOST")
pytestmark = pytest.mark.skipif(not HOST, reason="requires pinned v0.111.0 host")


@pytest.mark.parametrize("encounter", ENCOUNTERS)
def test_pinned_next_intents(tmp_path, encounter):
    with NativeSession(ROOT, tmp_path / "game", host_path=Path(HOST)) as game:
        oracle = Oracle(game)
        insatiable = encounter == "THE_INSATIABLE_BOSS"
        deck = ["FRANTIC_ESCAPE" if insatiable else "DEFEND_SILENT"] * 12
        oracle.start("2TURN_INTENTS_" + encounter, deck, encounter=encounter, hp=900)
        public = oracle.public
        checked = 0
        repeated = 0
        for _ in range(12):
            if insatiable and public["round"] > 1:
                escape = next((a for a in legal_actions(public) if a.kind == "play_card" and
                               public["hand"][a.args["card_index"]]["id"] == "CARD.FRANTIC_ESCAPE"), None)
                if escape:
                    public = oracle.command(**escape.command())
            state = replace(project(public).state, late=True, v61_rules=True, act=2,
                            room="Boss" if encounter.endswith("_BOSS") else "Monster")
            leaf = advance(state, END_TURN)
            forecasts = {e.name: next_intent(leaf, e) for e in leaf.enemies}
            if insatiable and state.round > 2 and state.enemies[0].intents[0].hits == 2:
                assert forecasts["THE_INSATIABLE"] is None
                repeated += 1
            public = oracle.command(cmd="action", action="end_turn", args={})
            if public["decision"] != "combat_play":
                assert not any(forecasts.values())
                break
            for enemy in project(public).state.enemies:
                if (forecast := forecasts.get(enemy.name)) is not None:
                    assert forecast == enemy.intents, (state.round, enemy.name)
                    checked += 1
        assert checked >= 4
        if insatiable:
            assert repeated > 0

def test_private_rng_and_draw_permutation_do_not_change_physical_choice(tmp_path):
    from unittest.mock import patch
    from sts2rl.combat_search_v2 import two_turn
    from sts2rl.combat_search_v2.planner import Config, search
    from sts2rl.combat_search_v2.transitions import legal
    from sts2rl.native import ACT1_SAMPLER, digest

    transcript, reveals = [], []
    deal = two_turn.sample_hand
    config = Config(width=16, children=512, v61_boss_safe=True, v61_act2_hallways_act3=True,
                    power_leaf_v62=True, two_turn_pilot=True)
    for i in range(2):
        with NativeSession(ROOT, tmp_path / str(i), host_path=Path(HOST)) as game:
            oracle = Oracle(game)
            oracle.start("TWO_TURN_PERMUTE", ["STRIKE_SILENT"] * 9 + ["DEFEND_SILENT"] * 9)
            before = oracle.public
            game.state = before
            # The native sampler permutes the hidden pile and reseeds private RNGs,
            # then exports the public root again. Only that observation reaches search.
            observed = game.sample(591 + i, profile=ACT1_SAMPLER)
            assert digest(observed) == digest(before)
            projected = project(observed)
            roots = legal(projected.state)
            hands = []

            def record(*args):
                world = deal(*args)
                hands.append(tuple(c.variant for c in world.hand))
                return world

            with patch.object(two_turn, "sample_hand", record):
                result = search(projected, roots, roots[0], config, record_timing=True)
            assert result.pilot["active"] and len(hands) == 8
            transcript.append((digest(observed), hands, result.pilot["scores"],
                               result.pilot["candidates"], result.choice))
            # No next/native observation exists in the call graph above.
            after = oracle.command(cmd="action", action="end_turn")
            reveals.append([c["id"] for c in after["hand"]])
    assert transcript[0] == transcript[1]
    assert reveals[0] != reveals[1]


def test_synthesized_turn_start_and_researched_line_on_host(tmp_path):
    from sts2rl.combat_search_v2.integration import _board, _difference, _intents, _normalized_legal, _positions
    from sts2rl.combat_search_v2.planner import Config, _Search
    from sts2rl.combat_search_v2.state import root_move
    from sts2rl.combat_search_v2.transitions import legal
    from sts2rl.combat_search_v2.two_turn import prepare, public_key, sample_hand
    from sts2rl.native import legal_actions

    with NativeSession(ROOT, tmp_path / "game", host_path=Path(HOST)) as game:
        oracle = Oracle(game)
        game.reset("CSV2TURN_START_BLUR_ICE")
        deck = ["BLUR", "DEFEND_SILENT", "SNAKEBITE", "SLICE"] * 4
        oracle.command(cmd="set_player", hp=70, deck=deck, relics=["RING_OF_THE_SNAKE", "ICE_CREAM"],
                       potions=["BLOCK_POTION"])
        save = tmp_path / "ice.save"
        oracle.command(cmd="write_continue_save", path=str(save))
    with NativeSession(ROOT, tmp_path / "restored", host_path=Path(HOST)) as game:
        oracle = Oracle(game)
        oracle.command(cmd="load_save", path=str(save))
        before = oracle.command(cmd="enter_room", type="monster", encounter="SHRINKER_BEETLE_WEAK")
        state = replace(project(before).state, late=True, v61_rules=True, act=2, room="Monster")
        for kind in ("use_potion", "play_card"):
            act = next(a for a in legal_actions(before) if a.kind == kind and (kind == "use_potion" or
                       before["hand"][a.args["card_index"]]["id"] == "CARD.BLUR"))
            state = advance(state, root_move(project(before), act.kind, act.args))
            before = oracle.command(**act.command())
        leaf = advance(state, END_TURN)
        start, reason = prepare(leaf)
        assert not reason and start.spent == 1 and start.block > 0 and start.energy > start.max_energy
        assert start.hand and all(c.variant.name == "SNAKEBITE" for c in start.hand)
        world = sample_hand(start, public_key(state), 0)
        desired = [c.variant.name for c in world.hand[len(start.hand):]]
        remainder = [v.name for v in world.draw]
        oracle.command(cmd="set_draw_order", cards=desired + remainder)
        after = oracle.command(cmd="action", action="end_turn")
        observed = replace(project(after).state, late=True, v61_rules=True, act=2, room="Monster")
        assert _board(world) == _board(observed)
        assert _intents(world) == _intents(observed)
        assert _positions(world) == _positions(observed)
        assert _normalized_legal(world) == _normalized_legal(observed)

        config = Config(width=6, children=96, depth=8, power_leaf_v62=True)
        moves = legal(world)
        search = _Search(moves, len(moves) - 1, config, None, False, False, None)
        search.run(world)
        best = max((line for line in search.certified if line), key=search.key)
        for move in best.path:
            ordinal = legal(world).index(move)
            act = legal_actions(after)[ordinal]
            world = advance(world, move)
            after = oracle.command(**act.command())
            assert world.spent == 1
            if world.outcome == "victory":
                assert not after.get("in_combat")
            else:
                assert not _difference(world, project(after).state)
