"""Batch 2 differentials on the immutable v0.111.0 host."""
from dataclasses import replace

import pytest

from sts2rl.combat_search_v2.integration import CombatSearchV2, _difference, _native_legal, _normalized_legal
from sts2rl.combat_search_v2.planner import Config
from sts2rl.combat_search_v2.silent_cards import BATCH2
from sts2rl.combat_search_v2.state import power, project, root_move
from sts2rl.combat_search_v2.transitions import admission, advance, card_supported, legal
from sts2rl.native import NativeSession, legal_actions
from test_combat_search_v2_native import HOST, ROOT, Oracle
from test_combat_search_v6_native import load_relics
from test_silent_cards_v66_native import action

pytestmark = pytest.mark.skipif(not HOST, reason="requires pinned v0.111.0 host")


@pytest.fixture
def oracle(tmp_path):
    with NativeSession(ROOT, tmp_path / "engine", host_path=HOST) as game:
        yield Oracle(game)


def start(o, name, deck, *, upgraded=False, encounter="WATERFALL_GIANT_BOSS", potions=()):
    o.game.reset("CSV12FIX_" + name + ("0" if name == "EXPERTISE" else ""))
    o.command(cmd="set_player", hp=400, max_hp=400, deck=deck, potions=potions)
    if upgraded:
        rest = o.command(cmd="enter_room", type="rest")
        prompt = o.command(**next(a for a in legal_actions(rest) if a.args["option_index"] == 1).command())
        if prompt["decision"] == "card_select":
            slot = next(c["index"] for c in prompt["cards"] if c["id"] == "CARD." + name)
            o.command(cmd="action", action="select_cards", args={"indices": str(slot)})
    o.public = o.command(cmd="enter_room", type="monster", encounter=encounter)


def check(o, kind, name=None, *, prior=None, late=False, boundary=None, selected=None):
    p = project(o.public, silent_cards_v67=True, late_prompts=late)
    state = replace(p.state, late=late)
    assert admission(replace(p, state=state)) is None
    assert _native_legal(p, legal_actions(o.public)) == legal(state)
    a = action(o, kind, name) if selected is None else next(a for a in legal_actions(o.public) if
        a.kind == "select_cards" and o.public["cards"][int(a.args["indices"])]["id"] == "CARD." + selected)
    move = root_move(p, a.kind, a.args)
    if prior and move.kind == "select_cards":
        move = replace(move, selection=tuple(prior.prompt.candidates[state.prompt.candidates.index(i)]
                                             for i in move.selection))
    predicted = advance(prior or state, move)
    o.public = o.command(**a.command())
    if boundary:
        assert predicted.boundary.reason == boundary and replace(predicted, boundary=None) == (prior or state)
        return predicted
    assert not predicted.boundary or predicted.outcome == "completed", predicted.boundary
    actual = project(o.public, silent_cards_v67=True, late_prompts=late)
    assert not (diff := _difference(predicted, actual.state)), (diff, predicted, actual.state)
    if not predicted.outcome:
        assert _normalized_legal(predicted) == _normalized_legal(actual.state)
    return predicted


@pytest.mark.parametrize("name", sorted(BATCH2 | {"NIGHTMARE"}))
@pytest.mark.parametrize("upgraded", (False, True))
def test_base_and_upgrade(oracle, name, upgraded):
    start(oracle, name, [name], upgraded=upgraded)
    card = project(oracle.public).state.hand[0].variant
    assert card.upgrade == upgraded
    if name != "NIGHTMARE":
        assert not card_supported(card, silent_cards_v66=True)
    assert card_supported(card, silent_cards_v67=True)
    check(oracle, "play_card", name)
    check(oracle, "end_turn")


@pytest.mark.parametrize("upgraded", (False, True))
def test_expertise_retain(oracle, upgraded):
    start(oracle, "EXPERTISE", ["DEFLECT"] * 10 + ["EXPERTISE"], upgraded=upgraded)
    before = len(oracle.public["hand"])
    state = check(oracle, "play_card", "EXPERTISE")
    drawn = state.hand[before - 1:]
    assert len(drawn) == 2 + upgraded and all(c.variant.flags == ("retain_this_turn",) for c in drawn)
    check(oracle, "end_turn")
    assert all(not c.get("retain_this_turn") for c in oracle.public["hand"])


def test_expertise_hidden_draw_precedes_spend(oracle):
    start(oracle, "EXPERTISE", ["EXPERTISE", "SLICE", "DEFLECT"] * 7)
    check(oracle, "play_card", "EXPERTISE", boundary="expertise draw")


def test_master_planner_persistent_sly(oracle):
    start(oracle, "MASTER_PLANNER", ["MASTER_PLANNER", "DEFLECT", "SURVIVOR"])
    check(oracle, "play_card", "MASTER_PLANNER")
    state = check(oracle, "play_card", "DEFLECT")
    assert "Sly" in state.discard[0].keywords
    check(oracle, "end_turn")
    assert "Sly" in next(c["keywords"] for c in oracle.public["hand"] if c["id"] == "CARD.DEFLECT")
    state = check(oracle, "play_card", "SURVIVOR")
    assert state.block == 12 and all("Sly" in v.keywords for v in state.discard)


@pytest.mark.parametrize("upgraded", (False, True))
def test_untouchable_sly(oracle, upgraded):
    start(oracle, "UNTOUCHABLE", ["SURVIVOR", "UNTOUCHABLE"], upgraded=upgraded)
    state = check(oracle, "play_card", "SURVIVOR")
    assert state.block == 14 + 3 * upgraded and state.energy == 2


@pytest.mark.parametrize("upgraded", (False, True))
def test_mirage_modifiers(oracle, upgraded):
    start(oracle, "MIRAGE", ["MIRAGE", "AFTERIMAGE", "BLUR", "DEADLY_POISON", "FOOTWORK"],
          upgraded=upgraded, encounter="AXEBOTS_NORMAL")
    for _ in range(8):
        if power(project(oracle.public).state.powers, "FRAIL"):
            break
        oracle.public = oracle.command(**action(oracle, "end_turn").command())
    assert power(project(oracle.public).state.powers, "FRAIL")
    check(oracle, "play_card", "AFTERIMAGE", late=True)
    check(oracle, "play_card", "FOOTWORK", late=True)
    check(oracle, "play_card", "BLUR", late=True)
    check(oracle, "end_turn", late=True)
    check(oracle, "play_card", "DEADLY_POISON", late=True)
    before = project(oracle.public).state
    state = check(oracle, "play_card", "MIRAGE", late=True)
    raw = sum(power(e.powers, "POISON") for e in before.enemies) + power(before.powers, "DEXTERITY")
    assert state.block == before.block + (raw * 3 // 4 if power(before.powers, "FRAIL") else raw) + 1
    assert any(v.name == "MIRAGE" for v in (state.discard if upgraded else state.exhaust))


def test_suppress_artifact(oracle):
    start(oracle, "SUPPRESS", ["SUPPRESS"], encounter="PUNCH_CONSTRUCT_NORMAL")
    assert power(project(oracle.public).state.enemies[0].powers, "ARTIFACT") == 1
    state = check(oracle, "play_card", "SUPPRESS")
    assert not power(state.enemies[0].powers, "ARTIFACT") and not power(state.enemies[0].powers, "WEAK")


def test_suppress_combined_modifiers(oracle):
    start(oracle, "SUPPRESS", ["SUPPRESS", "AFTERIMAGE", "ENVENOM"], encounter="AXEBOTS_NORMAL",
          potions=["STRENGTH_POTION", "VULNERABLE_POTION"])
    for _ in range(6):
        if power(project(oracle.public).state.powers, "WEAK"):
            break
        oracle.public = oracle.command(**action(oracle, "end_turn").command())
    assert power(project(oracle.public).state.powers, "WEAK")
    for _ in range(2):
        check(oracle, "use_potion", late=True)
    check(oracle, "play_card", "AFTERIMAGE", late=True)
    check(oracle, "play_card", "ENVENOM", late=True)
    before = project(oracle.public).state
    state = check(oracle, "play_card", "SUPPRESS", late=True)
    assert state.block == before.block + 1
    assert power(state.enemies[0].powers, "POISON") and power(state.enemies[0].powers, "WEAK") == 3


def test_wraith_turns(oracle):
    start(oracle, "WRAITH_FORM", ["WRAITH_FORM"], encounter="SHRINKER_BEETLE_WEAK")
    before = check(oracle, "play_card", "WRAITH_FORM")
    losses = []
    for i in (1, 2, 3):
        state = check(oracle, "end_turn")
        losses.append(before.hp - state.hp)
        assert power(state.powers, "DEXTERITY") == -i
        assert power(state.powers, "INTANGIBLE") == max(0, 2 - i)
        before = state
    assert 1 in losses[:2]


@pytest.mark.parametrize("upgraded", (False, True))
@pytest.mark.parametrize("options", (1, 2))
def test_nightmare_witnessed_copy_at_reveal(oracle, upgraded, options):
    start(oracle, "NIGHTMARE", ["NIGHTMARE", "DEFLECT"] + ["SLICE"] * (options - 1), upgraded=upgraded)
    mode = CombatSearchV2(Config(silent_cards_v67=True), record=True)
    for kind in (["play_card", "select_cards", "end_turn"] if options == 2 else ["play_card", "end_turn"]):
        a = action(oracle, kind, "NIGHTMARE" if kind == "play_card" else None)
        if kind == "select_cards":
            a = next(a for a in legal_actions(oracle.public) if
                     oracle.public["cards"][int(a.args["indices"])]["id"] == "CARD.DEFLECT")
        mode.choose(oracle.public, a, legal_actions)
        oracle.public = oracle.command(**a.command())
        mode.observe(a, oracle.public, legal_actions)
        assert mode.records[-1].get("oracle", [None, None])[1] == "match", mode.records[-1]
    assert [c["id"] for c in oracle.public["hand"]].count("CARD.DEFLECT") == 4


def test_pocketwatch_reset_and_refresh_around_mittens(oracle, tmp_path):
    load_relics(oracle, tmp_path, {"POCKETWATCH", "TOASTY_MITTENS"}, ["DEFLECT"] * 18, "SLIMED_BERSERKER_NORMAL")
    oracle.public = oracle.command(**action(oracle, "select_cards").command())
    for _ in range(4):
        check(oracle, "play_card", late=True)

    def watch(state):
        return next(r for r in state.relics if r.name == "POCKETWATCH")
    assert watch(project(oracle.public).state).status == "Normal"
    state = check(oracle, "end_turn", late=True)
    assert state.boundary.count == 5 and (watch(state).counter, watch(state).status) == (0, "Normal")
    state = check(oracle, "select_cards", late=True)
    assert (watch(state).counter, watch(state).status) == (0, "Active")
