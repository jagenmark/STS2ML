from dataclasses import replace

import pytest

from sts2rl.combat_search_v2.planner import Config, search
from sts2rl.combat_search_v2.state import project
from sts2rl.combat_search_v2.transitions import legal
from sts2rl.combat_search_v2.value import _power_value, _progress, interim
from sts2rl.deck_policy import deck_context
from sts2rl.strategy import _first_power_scaling
from test_combat_search_v2 import DEFEND, STRIKE, card, enemy, powers, view


@pytest.mark.parametrize("hp,enemy_hp,second", [(2, 120, DEFEND), (25, 6, STRIKE)])
def test_scaling_yields_to_fatal_block_and_lethal(hp, enemy_hp, second):
    projected = project(view(card("NOXIOUS_FUMES", kind="Power"), second, hp=hp, energy=1,
                             enemies=[enemy(hp=enemy_hp, hit=6)]))
    moves = legal(projected.state)
    result = search(projected, moves, moves[-1], Config(power_leaf_v62=True))
    assert not result.fallback and result.choice == moves[1]


def test_scaling_uses_unordered_live_cards_and_diminishing_poison():
    public = view(DEFEND, draw=[STRIKE, card("BLADE_DANCE")], power=powers(ACCURACY=4, ACCELERANT=2),
                  enemies=[enemy(hp=100, power=powers(POISON=4))])
    board = project(public).state
    public["draw_pile"].reverse()
    assert _power_value(board) == _power_value(project(public).state)
    assert _progress(board, True)[0] == pytest.approx(0.8 * (4 + 3 + 2))
    assert _power_value(board) > _power_value(replace(board, draw=(), exhaust=board.draw))
    assert interim(board, 7)[0] == interim(board, 7, power_leaf_v62=True)[0]
    assert interim(board, 7)[1] < interim(board, 7, power_leaf_v62=True)[1]
    assert _power_value(replace(board, enemies=(replace(board.enemies[0], hp=6),))) == 0


def test_first_free_power_split_uses_shop_term():
    deck = [card("DEADLY_POISON", stats={"poisonpower": 5}), card("BLADE_DANCE", stats={"shivs": 3})]
    ctx = {"act": 2}
    for name, stats in (("ACCELERANT", {"accelerant": 1}), ("INFINITE_BLADES", {"shivs": 1})):
        offered = card(name, kind="Power", stats=stats)
        both = _first_power_scaling(offered, ctx, deck_context(deck), deck, "scaling_powers_4")
        narrow = _first_power_scaling(offered, ctx, deck_context(deck), deck, "accelerant_only")
        assert both > 0 and narrow == (both if name == "ACCELERANT" else 0)
        owned = [*deck, offered]
        assert _first_power_scaling(offered, ctx, deck_context(owned), owned, "scaling_powers_4") == 0
