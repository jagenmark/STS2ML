"""Physical CSV5 fixtures for mechanics newly enabled in natural Act 2 rooms."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from sts2rl.act2_bosses import BossTactics
from sts2rl.combat_search_v2.artifact import CombatValueModel
from sts2rl.combat_search_v2.features import extract_leaf_features
from sts2rl.combat_search_v2.integration import CombatSearchV2, _difference, _native_legal
from sts2rl.combat_search_v2.planner import Config, search
from sts2rl.combat_search_v2.state import END_TURN, power, project, root_move
from sts2rl.combat_search_v2.transitions import admission, advance, legal
from sts2rl.combat_search_v2.value import leaf_value
from sts2rl.native import NativeSession, legal_actions
from test_combat_search_v2_native import HOST, ROOT, Oracle
from test_combat_search_v6_native import action, load_relics, named_card

pytestmark = pytest.mark.skipif(not HOST, reason="requires pinned v0.111.0 host")


@pytest.fixture
def oracle(tmp_path):
    with NativeSession(ROOT, tmp_path / "oracle", host_path=HOST) as game:
        yield Oracle(game)


def room_view(raw, room):
    # enter_room instantiates the native encounter on the current map. Set its
    # routing context for the controller; every combat field comes from the host.
    public = deepcopy(raw)
    public.get("combat_state", public)["context"].update(act=2, room_type=room)
    return public


def projected(raw, room="Monster", **witness):
    public = room_view(raw, room)
    p = project(public, late_prompts=True)
    public.get("combat_state", public)["draw_pile"].reverse()
    assert p == project(public, late_prompts=True)
    return replace(p, state=replace(p.state, late=True, v61_rules=True, **witness))


def check(game, act, room="Monster", stop=None, **witness):
    p = projected(game.public, room, **witness)
    assert not admission(p)
    assert legal(p.state) == _native_legal(p, legal_actions(game.public))
    expected = advance(p.state, root_move(p, act.kind, act.args))
    game.public = game.command(**act.command())
    if stop:
        assert expected.boundary and expected.boundary.reason == stop and not expected.outcome
    elif expected.outcome == "victory":
        assert not game.public.get("in_combat")
    else:
        assert expected.outcome == "completed" or not expected.boundary
        assert not _difference(expected, projected(game.public, room).state)
    return expected


def test_tender_card_decrements_and_refund(oracle):
    oracle.start("TENDER", ["DEFLECT", "SLICE"] * 9, hp=400, encounter="HUNTER_KILLER_NORMAL", seed="CSV5FIX_TENDER")
    check(oracle, action(oracle, "end_turn"))
    for i in range(3):
        s = check(oracle, action(oracle, "play_card"), tender_plays=i)
        assert power(s.powers, "DEXTERITY") == power(s.powers, "STRENGTH") == -(i + 1)
    check(oracle, action(oracle, "end_turn"), tender_plays=3)
    assert "unwitnessed tender" in admission(projected(oracle.public))


def test_slumber_plating_block_and_wake(oracle):
    oracle.start("SLUMBER", ["GRAND_FINALE"] * 7, hp=400, encounter="SLUMBERING_BEETLE_NORMAL", seed="CSV5FIX_SLUMBER")
    check(oracle, action(oracle, "play_card"))
    assert power(projected(oracle.public).state.enemies[-1].powers, "SLUMBER") == 2
    for _ in range(2):
        check(oracle, action(oracle, "end_turn"))
    assert not power(projected(oracle.public).state.enemies[-1].powers, "SLUMBER")


def test_fresh_segment_knockout_and_due_revival(oracle):
    oracle.start("SEGMENT", ["PREDATOR"] * 8, ["FIRE_POTION"] * 2, hp=400,
                 encounter="DECIMILLIPEDE_ELITE", seed="CSV5FIX_SEGMENT")
    check(oracle, named_card(oracle, "PREDATOR", 0), "Elite")
    while len(oracle.public["enemies"]) == 3:
        check(oracle, action(oracle, "use_potion", 0), "Elite")
    check(oracle, action(oracle, "end_turn"), "Elite")
    check(oracle, action(oracle, "end_turn"), "Elite", stop="segment due to reattach")
    assert len(oracle.public["enemies"]) == 3


def test_beating_remnant_caps_multihit_and_dolly_is_passive(oracle, tmp_path):
    load_relics(oracle, tmp_path, {"BEATING_REMNANT", "DOLLYS_MIRROR"}, ["STRIKE_SILENT"] * 16, "HUNTER_KILLER_NORMAL")
    losses = []
    for _ in range(4):
        hp = oracle.public["player"]["hp"]
        check(oracle, action(oracle, "end_turn"), tender_plays=0, remnant_floor=hp - 20)
        losses.append(hp - oracle.public["player"]["hp"])
    assert 20 in losses and max(losses) == 20


def test_burning_sticks_skill_exhaust(oracle, tmp_path):
    load_relics(oracle, tmp_path, {"BURNING_STICKS"}, ["DEFEND_SILENT", "BLADE_DANCE"], "HUNTER_KILLER_NORMAL")
    check(oracle, named_card(oracle, "DEFEND_SILENT"))
    check(oracle, named_card(oracle, "BLADE_DANCE"), stop="burning sticks generated skill")
    assert next(r for r in oracle.public["player"]["relics"] if r["id"] == "RELIC.BURNING_STICKS")["status"] == "Normal"


def test_spent_wax_counter_boundary(oracle, tmp_path):
    def spent(player):
        for relic in player["relics"]:
            if relic["id"] == "RELIC.TOY_BOX":
                relic["props"]["ints"][0]["value"] = 2
            else:
                relic["props"] = {"bools": [{"name": "IsWax", "value": True}]}
    load_relics(oracle, tmp_path, {"TOY_BOX", "PENDULUM"}, ["GRAND_FINALE"] * 4, "SHRINKER_BEETLE_WEAK", edit=spent)
    while oracle.public.get("in_combat"):
        oracle.public = oracle.command(**action(oracle, "play_card").command())
    for _ in range(8):
        if oracle.public["decision"] == "map_select":
            break
        oracle.public = oracle.command(**legal_actions(oracle.public)[-1].command())
    oracle.public = oracle.command(cmd="enter_room", type="monster", encounter="HUNTER_KILLER_NORMAL")
    assert admission(projected(oracle.public)) == "spent toy box wax relic"
    before = next(r["counter"] for r in oracle.public["player"]["relics"] if r["id"] == "RELIC.PENDULUM")
    after = oracle.command(**action(oracle, "end_turn").command())
    assert next(r["counter"] for r in after["player"]["relics"] if r["id"] == "RELIC.PENDULUM") == before


def test_nimble_relax_native_block(oracle, tmp_path):
    def enchant(player):
        player["deck"][0]["enchantment"] = {"id": "ENCHANTMENT.NIMBLE", "amount": 2}
    load_relics(oracle, tmp_path, set(), ["RELAX"], "KAISER_CRAB_BOSS", edit=enchant)
    s = check(oracle, named_card(oracle, "RELAX"), "Boss", facing=1, preview_facing=1)
    assert s.block == 18


def test_retained_enlightenment_cost_resets_before_curse(oracle):
    oracle.start("RETAIN", ["SNAKEBITE", "ENLIGHTENMENT"], encounter="KNOWLEDGE_DEMON_BOSS", seed="CSV5FIX_RETAIN")
    check(oracle, named_card(oracle, "ENLIGHTENMENT"), "Boss")
    assert oracle.public["hand"][0]["cost"] == 1
    check(oracle, action(oracle, "end_turn"), "Boss", stop="retained enlightenment cost at curse offer")
    assert oracle.public["decision"] == "card_select"
    assert oracle.public["combat_state"]["hand"][0]["cost"] == 2


def test_the_hunt_fatal_with_living_allies(oracle):
    oracle.start("HUNT", ["THE_HUNT"] * 16, hp=400, encounter="EXOSKELETONS_NORMAL", seed="CSV5FIX_HUNT")
    while not power(projected(oracle.public).state.powers, "THE_HUNT"):
        plays = [a for a in legal_actions(oracle.public) if a.kind == "play_card" and a.args["target_index"] == 0]
        check(oracle, plays[0] if plays else action(oracle, "end_turn"))
    assert len(oracle.public["enemies"]) >= 2
    check(oracle, action(oracle, "end_turn"))


@pytest.mark.parametrize("clarity", [False, True])
def test_mittens_suspends_later_start_triggers(oracle, tmp_path, clarity):
    load_relics(oracle, tmp_path, {"TOASTY_MITTENS"} if clarity else {"TOASTY_MITTENS", "HAPPY_FLOWER"},
                ["DEFEND_SILENT"] * 18, "HUNTER_KILLER_NORMAL",
                edit=(lambda p: p.update(potions=[{"id": "POTION.CLARITY", "slot_index": 0}])) if clarity else None)
    if oracle.public["decision"] == "card_select":
        oracle.public = oracle.command(**legal_actions(oracle.public)[0].command())
    if clarity:
        oracle.public = oracle.command(**action(oracle, "use_potion").command())
    check(oracle, action(oracle, "end_turn"), stop="toasty mittens delayed start triggers")
    assert oracle.public["decision"] == "card_select"


def test_crab_rage_cost_tracks_native_survivor(oracle):
    from sts2rl.combat_search_v2.value import interim

    oracle.start("RAGE", ["GRAND_FINALE"] * 7, ["FIRE_POTION"] * 2, hp=400,
                 encounter="KAISER_CRAB_BOSS", seed="CSV5FIX_RAGE")
    for _ in range(2):
        check(oracle, action(oracle, "use_potion", 1), "Boss", facing=1, preview_facing=1)
    while len(oracle.public["enemies"]) == 2:
        s = check(oracle, action(oracle, "play_card"), "Boss", facing=1, preview_facing=1)
    remaining, = [e for e in s.enemies if e.hp]
    assert remaining.block == 99 and power(remaining.powers, "STRENGTH") == 6
    assert interim(s, 7, boss_safe=True) < interim(s, 7)


@pytest.mark.parametrize("encounter,room", [("HUNTER_KILLER_NORMAL", "Monster"), ("SLUMBERING_BEETLE_NORMAL", "Monster"),
                                          ("DECIMILLIPEDE_ELITE", "Elite")])
def test_hallway_hidden_draw_swap(oracle, encounter, room):
    leaves, hands = [], []
    for reverse in (False, True):
        oracle.start("SWAP", ["DEFEND_SILENT"] * 16 + ["STRIKE_SILENT"] * 16, hp=400, encounter=encounter,
                     seed="CSV5FIX_SWAP_" + encounter)
        cards = sorted((c["id"].split(".")[-1] for c in oracle.public["draw_pile"]), reverse=reverse)
        oracle.command(cmd="set_draw_order", cards=cards)
        expected = check(oracle, action(oracle, "end_turn"), room)
        leaves.append(extract_leaf_features(expected).tobytes())
        hands.append(tuple(c["id"] for c in oracle.public["hand"]))
    assert leaves[0] == leaves[1] and hands[0] != hands[1]


def test_curse_prompts_use_champion_and_card_roots_resume(oracle):
    oracle.start("CURSE", ["SLICE"] * 40, hp=700, encounter="KNOWLEDGE_DEMON_BOSS", seed="CSV5FIX_CURSE")
    tactics = BossTactics({"curse": ["MIND_ROT", "SLOTH", "WASTE_AWAY"]}, oracle.public)
    mode = CombatSearchV2(Config(v61_boss_safe=True), record=True)
    offered = []
    for _ in range(10):
        public = room_view(oracle.public, "Boss")
        champion = legal_actions(public)[-1]
        mode.choose(public, champion, legal_actions, curse_preferences=tactics.plan["curse"])
        assert mode.records[-1]["attempts"] > 0
        oracle.public = oracle.command(**champion.command())
        mode.observe(champion, room_view(oracle.public, "Boss"), legal_actions)
        if oracle.public["decision"] == "card_select":
            public = room_view(oracle.public, "Boss")
            champion = tactics.curse_choice(public)
            selection = mode.choose(public, champion, legal_actions, curse_preferences=tactics.plan["curse"])
            assert selection is champion and mode.last_fallback == "champion knowledge curse"
            offered.append(public["cards"][int(selection.args["indices"])]["id"])
            oracle.public = oracle.command(**selection.command())
            mode.observe(selection, room_view(oracle.public, "Boss"), legal_actions)
    assert offered == ["CARD.MIND_ROT", "CARD.SLOTH", "CARD.WASTE_AWAY"]
    assert not any(r.get("oracle", [None, None])[1] == "mismatch" for r in mode.records)


@pytest.mark.parametrize("preferred", [(), ("MIND_ROT",)])
def test_only_champion_curse_reaches_the_hypothetical_leaf(oracle, preferred):
    oracle.start("CURSE_LEAF", ["DEFLECT"] * 12, encounter="KNOWLEDGE_DEMON_BOSS", seed="CSV5FIX_CURSE_LEAF")
    p = projected(oracle.public, "Boss")
    evaluated = set()
    class Model:
        def leaf(self, state):
            evaluated.add(tuple(name for name, _ in state.powers if name in ("MIND_ROT", "DISINTEGRATION")))
            return 1., float(not power(state.powers, preferred[0] if preferred else "DISINTEGRATION"))
    result = search(p, legal(p.state), END_TURN, Config(v61_boss_safe=True), model=Model(), curse_preferences=preferred)
    assert not result.fallback
    assert evaluated == {preferred or ("DISINTEGRATION",)}


@pytest.mark.parametrize("name", ["KAISER_CRAB_BOSS", "KNOWLEDGE_DEMON_BOSS", "THE_INSATIABLE_BOSS"])
def test_boss_values_invariant_to_realized_native_hand(oracle, name):
    model = CombatValueModel.load(ROOT / "releases/silent-a10-v2-tactics/challenger/combat_value_v2.npz")
    values, hands = [], []
    for reverse in (False, True):
        oracle.start("BOSS_SWAP", ["DEFEND_SILENT"] * 16 + ["STRIKE_SILENT"] * 16, hp=400,
                     encounter=name, seed="CSV5FIX_BOSS_SWAP_" + name)
        if name == "KNOWLEDGE_DEMON_BOSS":
            oracle.public = oracle.command(**action(oracle, "end_turn").command())
            oracle.public = oracle.command(**legal_actions(oracle.public)[1].command())
        order = sorted((c["id"].split(".")[-1] for c in oracle.public["draw_pile"]), reverse=reverse)
        oracle.command(cmd="set_draw_order", cards=order)
        s = check(oracle, action(oracle, "end_turn"), "Boss", facing=1, preview_facing=1)
        values.append([leaf_value(s, 7, m, boss_safe=True) for m in (None, model)])
        hands.append(tuple(c["id"] for c in oracle.public["hand"]))
    assert hands[0] != hands[1] and values[0] == values[1]


@pytest.mark.parametrize("learned", [False, True])
def test_deadline_action_on_native_timer(oracle, learned):
    oracle.start("DEADLINE", ["FRANTIC_ESCAPE"] * 8 + ["STRIKE_SILENT"] * 2, hp=400, encounter="THE_INSATIABLE_BOSS",
                 seed="CSV5FIX_DEADLINE")
    for _ in range(8):
        if power(projected(oracle.public, "Boss").state.enemies[0].powers, "SANDPIT") == 2:
            break
        oracle.public = oracle.command(**action(oracle, "end_turn").command())
    public = room_view(oracle.public, "Boss")
    model = CombatValueModel.load(Path(ROOT) / "releases/silent-a10-v2-tactics/challenger/combat_value_v2.npz") if learned else None
    mode = CombatSearchV2(Config(v61_boss_safe=True), model=model)
    chosen = mode.choose(public, legal_actions(public)[-1], legal_actions)
    assert chosen.kind == "play_card" and public["hand"][chosen.args["card_index"]]["id"] == "CARD.FRANTIC_ESCAPE"
    expected = check(oracle, chosen, "Boss")
    assert power(expected.enemies[0].powers, "SANDPIT") == 3
    assert power(advance(expected, END_TURN).enemies[0].powers, "SANDPIT") == 2
