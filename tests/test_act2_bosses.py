from copy import deepcopy

from sts2rl.act2_bosses import BossTactics
from sts2rl.native import legal_actions
from test_teacher_status import hand


def test_position_uses_current_native_preview_and_changes_on_targeted_potions():
    state = hand(("CARD.STRIKE_SILENT", "AnyEnemy", {"damage": 6}))
    left = state["enemies"][0]
    left.update(index=0, id="MONSTER.CRUSHER", intents=[{"damage": 21}],
                powers=[{"id": "POWER.BACK_ATTACK_LEFT_POWER", "amount": 1}])
    right = deepcopy(left)
    right.update(index=1, id="MONSTER.ROCKET", intents=[{"damage": 4}],
                 powers=[{"id": "POWER.BACK_ATTACK_RIGHT_POWER", "amount": 1}])
    state["enemies"] = [left, right]
    state["player"]["block"] = 0
    state["player"]["potions"] = [{"index": 0, "target_type": "AnyEnemy", "can_use": True}]
    state["player_powers"] = [{"id": "POWER.SURROUNDED_POWER", "amount": 1}]
    tactic = BossTactics({"facing": 2}, state)
    actions = legal_actions(state)
    scores = [0.] * len(actions)
    tactic.adjust_targets(state, actions, scores)
    assert scores[0] > scores[1] == 0
    assert scores[0] == scores[2]
    tactic.observe(actions[2])
    assert tactic.facing == 0
    left["intents"], right["intents"] = [{"damage": 14}], [{"damage": 6}]
    scores = [0.] * len(actions)
    tactic.adjust_targets(state, actions, scores)
    assert scores[1] < scores[0] == 0
    state["player"]["block"] = 25
    scores = [0.] * len(actions)
    tactic.adjust_targets(state, actions, scores)
    assert all(s == 0 for s in scores)


def test_expensive_escape_can_wait_when_player_would_die_to_this_hit():
    state = hand(("CARD.FRANTIC_ESCAPE", "Self", {}))
    state["round"] = 3
    state["enemies"][0].update(id="MONSTER.THE_INSATIABLE", hp=200,
                               powers=[{"id":"POWER.SANDPIT_POWER","amount":2}])
    state["player"].update(hp=5, block=0)
    state["hand"][0].update(cost=2, card_cost=2)
    tactics = BossTactics({"escape":"bank"}, state)
    assert tactics.escape_threshold(state,4) == 0
    state["enemies"][0]["powers"][0]["amount"] = 1
    assert tactics.escape_threshold(state,4) == 1


def test_mandatory_curse_selection_depends_on_offered_cards_not_their_order():
    tactics = BossTactics({"curse":["SLOTH"]},{"enemies":[]})
    state = {"decision":"card_select","min_select":1,"max_select":1,
             "cards":[{"id":"CARD.SLOTH","index":3},{"id":"CARD.DISINTEGRATION","index":7}]}
    assert tactics.curse_choice(state).args == {"indices":"3"}
    state["cards"].reverse()
    assert tactics.curse_choice(state).args == {"indices":"3"}
    state["cards"][1]["id"]="CARD.MIND_ROT"
    assert tactics.curse_choice(state).args == {"indices":"7"}
    state["cards"][1]["id"]="CARD.STRIKE_SILENT"
    assert tactics.curse_choice(state) is None
