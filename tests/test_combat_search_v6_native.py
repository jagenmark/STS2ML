"""Pinned v0.111.0 late-room differential fixtures."""
from dataclasses import replace
from copy import deepcopy
import json

import pytest

from sts2rl.combat_search_v2.encounters import encounter_reason
from sts2rl.combat_search_v2.integration import _difference, _native_legal, _normalized_legal
from sts2rl.combat_search_v2.state import project, root_move
from sts2rl.combat_search_v2.transitions import advance, legal
from sts2rl.native import NativeSession, legal_actions
from test_combat_search_v2_native import HOST, ROOT, Oracle

pytestmark = pytest.mark.skipif(not HOST, reason="requires pinned native host")


@pytest.fixture
def oracle(tmp_path):
    with NativeSession(ROOT, tmp_path / "oracle", host_path=HOST) as game:
        yield Oracle(game)


def check(game, action, *, facing=-1, plays=0, aeon=0, bound=False, stop=None):
    projection = project(game.public, late_prompts=True)
    state = replace(projection.state, right_hand_return=True, late=True, facing=facing, preview_facing=facing, sloth_plays=plays, bound_used=bound, aeon_plays=aeon)
    assert not encounter_reason(state)
    assert _native_legal(projection, legal_actions(game.public)) == legal(state)
    shuffled = deepcopy(game.public)
    shuffled.get("combat_state", shuffled)["draw_pile"].reverse()
    assert project(shuffled, late_prompts=True) == projection
    move = root_move(projection, action.kind, action.args)
    predicted = advance(state, move)
    game.public = game.command(**action.command())
    if stop:
        assert predicted.boundary and stop in predicted.boundary.reason and not predicted.outcome
    elif predicted.outcome in ("victory", "dead"):
        assert not game.public.get("in_combat") or game.public["decision"] == "game_over"
    else:
        assert not predicted.boundary or predicted.outcome == "completed", predicted.boundary
        actual = project(game.public, late_prompts=True)
        assert not _difference(predicted, actual.state)
        if not predicted.outcome:
            actual_state = replace(actual.state, late=True, facing=predicted.facing, preview_facing=predicted.facing,
                                   sloth_plays=predicted.sloth_plays, bound_used=predicted.bound_used)
            assert _normalized_legal(predicted) == _normalized_legal(actual_state)
            assert _native_legal(actual, legal_actions(game.public)) == legal(actual_state)
    return predicted


def action(game, kind, target=None):
    return next(a for a in legal_actions(game.public) if a.kind == kind and (
        target is None or a.args.get("target_index") == target))


@pytest.mark.parametrize("name,turns", [
    ("SCROLLS_OF_BITING_NORMAL", 4), ("TURRET_OPERATOR_WEAK", 4), ("SLIMED_BERSERKER_NORMAL", 4),
    ("TEST_SUBJECT_BOSS", 4), ("AXEBOTS_NORMAL", 3), ("OWL_MAGISTRATE_NORMAL", 4),
    ("THE_LOST_AND_FORGOTTEN_NORMAL", 4), ("GLOBE_HEAD_NORMAL", 4), ("FROG_KNIGHT_NORMAL", 4),
    ("MECHA_KNIGHT_ELITE", 3), ("QUEEN_BOSS", 4), ("AEONGLASS_BOSS", 4), ("CONSTRUCT_MENAGERIE_NORMAL", 3),
    ("DEVOTED_SCULPTOR_WEAK", 3), ("THE_INSATIABLE_BOSS", 3),
])
def test_late_native_moves(oracle, name, turns):
    oracle.start("LATE", ["DEFEND_SILENT"] * 50, encounter=name, hp=800, seed="CSV4FIX_" + name)
    if name == "SCROLLS_OF_BITING_NORMAL":
        oracle.game.reset("CSV4FIX_PAPER_CUTS")
        oracle.command(cmd="set_player", hp=700, max_hp=800, deck=["DEFEND_SILENT"] * 50)
        oracle.public = oracle.command(cmd="enter_room", type="monster", encounter=name)
    for i in range(turns):
        check(oracle, action(oracle, "play_card"), aeon=i)
        stop = "enemy intent" if (name == "MECHA_KNIGHT_ELITE" and i == 1) else None
        check(oracle, action(oracle, "end_turn"), stop=stop, aeon=i + 1, bound=name == "QUEEN_BOSS" and i > 0)


def test_kaiser_targeted_turns(oracle):
    oracle.start("KAISER", ["STRIKE_SILENT"] * 30, ["WEAK_POTION"], encounter="KAISER_CRAB_BOSS",
                 hp=800, seed="CSV4FIX_KAISER_CRAB_BOSS")
    facing = 1
    for i in range(5):
        target = i % 2
        check(oracle, action(oracle, "play_card", target), facing=facing)
        facing = target
        if i == 1:
            check(oracle, action(oracle, "use_potion", 0), facing=facing)
            facing = 0
        check(oracle, action(oracle, "end_turn"), facing=facing)


@pytest.mark.parametrize("option", [0, 1])
def test_demon_curse_and_sloth(oracle, option):
    oracle.start("DEMON", ["SLICE"] * 40, encounter="KNOWLEDGE_DEMON_BOSS", hp=800,
                 seed="CSV4FIX_KNOWLEDGE_DEMON_BOSS")
    for i in range(10):
        for n in range(3):
            check(oracle, action(oracle, "play_card"), plays=n)
        if i in (0, 4, 8):
            check(oracle, action(oracle, "end_turn"), plays=3)
            check(oracle, legal_actions(oracle.public)[option], plays=3)
        else:
            check(oracle, action(oracle, "end_turn"), plays=3)


@pytest.mark.parametrize("name", ["ASSASSINATE", "THE_HUNT", "ULTIMATE_STRIKE", "DRAMATIC_ENTRANCE",
                                  "DANSE_MACABRE", "RELAX", "PREP_TIME", "SIDESTEP", "PHANTOM_BLADES",
                                  "ACCURACY", "BOUNCING_FLASK", "ECHOING_SLASH", "SHRUG_IT_OFF"])
@pytest.mark.parametrize("upgrade", [False, True])
def test_late_card_effects(oracle, name, upgrade):
    oracle.game.reset("CSV4FIX_CARD_" + name)
    oracle.command(cmd="set_player", deck=[name], hp=70)
    if upgrade:
        rest = oracle.command(cmd="enter_room", type="rest")
        oracle.command(**next(a for a in legal_actions(rest) if a.args["option_index"] == 1).command())
    oracle.public = oracle.command(cmd="enter_room", type="monster", encounter="THE_INSATIABLE_BOSS")
    assert bool(oracle.public["hand"][0]["upgrades"]) == upgrade
    check(oracle, action(oracle, "play_card"))
    check(oracle, action(oracle, "end_turn"))


def load_relics(oracle, path, relics, deck, encounter, *, hp=400, edit=None):
    with NativeSession(ROOT, path / "writer", host_path=HOST) as fixture:
        fixture.reset("CSV4FIX_LATE_RELICS")
        fixture._request({"cmd": "set_player", "deck": deck, "relics": sorted(relics), "hp": hp, "max_hp": 400})
        fixture._request({"cmd": "write_continue_save", "path": str(path / "fixture.save")})
    if edit:
        save = json.loads((path / "fixture.save").read_bytes())
        edit(save["players"][0])
        (path / "fixture.save").write_text(json.dumps(save))
    oracle.command(cmd="load_save", path=str(path / "fixture.save"))
    oracle.public = oracle.command(cmd="enter_room", type="monster", encounter=encounter)


def test_late_passives_and_turn_hooks(oracle, tmp_path):
    from sts2rl.combat_search_v2.late_encounters import PASSIVE_RELICS
    from sts2rl.combat_search_v2.transitions import admission_reasons

    relics = PASSIVE_RELICS | {"MR_STRUGGLES", "MERCURY_HOURGLASS", "IRON_CLUB", "STONE_CALENDAR",
                               "SHURIKEN", "KUNAI", "STURDY_CLAMP", "FIDDLE", "HELICAL_DART"}
    load_relics(oracle, tmp_path, relics, ["SLICE"] * 40, "SLIMED_BERSERKER_NORMAL")
    if oracle.public["decision"] == "card_select":
        oracle.public = oracle.command(**legal_actions(oracle.public)[0].command())
    projection = project(oracle.public)
    assert {r.name for r in projection.state.relics} == relics
    assert not list(admission_reasons(replace(projection, state=replace(projection.state, late=True))))
    for _ in range(2):
        for _ in range(4):
            check(oracle, action(oracle, "play_card"))
        check(oracle, action(oracle, "end_turn"))


def test_late_forgotten_soul_and_tough_bandages(oracle, tmp_path):
    load_relics(oracle, tmp_path, {"FORGOTTEN_SOUL", "TOUGH_BANDAGES"},
                ["SURVIVOR", "DEFEND_SILENT", "ASCENDERS_BANE", "ASSASSINATE"], "THE_INSATIABLE_BOSS")
    check(oracle, next(a for a in legal_actions(oracle.public) if a.kind == "play_card" and
                       oracle.public["hand"][a.args["card_index"]]["id"] == "CARD.ASSASSINATE"))
    state = project(oracle.public)
    survivor = next(a for a in legal_actions(oracle.public) if a.kind == "play_card" and
                    oracle.public["hand"][a.args["card_index"]]["id"] == "CARD.SURVIVOR")
    predicted = advance(replace(state.state, late=True), root_move(state, survivor.kind, survivor.args))
    oracle.public = oracle.command(**survivor.command())
    assert not _difference(predicted, project(oracle.public).state)
    select = next(a for a in legal_actions(oracle.public) if a.kind == "select_cards" and
                  oracle.public["cards"][int(a.args["indices"])]["id"] == "CARD.DEFEND_SILENT")
    prediction = advance(predicted, next(m for m in legal(predicted) if
                         m.selection == (next(c.slot for c in predicted.hand if c.variant.name == "DEFEND_SILENT"),)))
    oracle.public = oracle.command(**select.command())
    assert not _difference(prediction, project(oracle.public).state)
    check(oracle, action(oracle, "end_turn"))


def test_right_hand_returns_from_discard(oracle):
    oracle.start("HAND", ["RIGHT_HAND_HAND", "SURVIVOR", "DASH"], encounter="SLIMED_BERSERKER_NORMAL",
                 seed="CSV4FIX_RIGHT_HAND")
    survivor = next(a for a in legal_actions(oracle.public) if a.kind == "play_card" and
                    oracle.public["hand"][a.args["card_index"]]["id"] == "CARD.SURVIVOR")
    oracle.public = oracle.command(**survivor.command())
    select = next(a for a in legal_actions(oracle.public) if a.kind == "select_cards" and
                  oracle.public["cards"][int(a.args["indices"])]["id"] == "CARD.RIGHT_HAND_HAND")
    oracle.public = oracle.command(**select.command())
    check(oracle, action(oracle, "play_card"))
    assert oracle.public["hand"][-1]["id"] == "CARD.RIGHT_HAND_HAND"


def test_turret_rampart_after_start_damage(oracle, tmp_path):
    load_relics(oracle, tmp_path, {"MR_STRUGGLES", "MERCURY_HOURGLASS", "STRIKE_DUMMY"},
                ["ULTIMATE_STRIKE"] * 20, "TURRET_OPERATOR_WEAK")
    check(oracle, action(oracle, "play_card", 0))
    check(oracle, action(oracle, "end_turn"))


def test_start_and_damage_relics(oracle, tmp_path):
    load_relics(oracle, tmp_path, {"TOY_BOX", "TUNGSTEN_ROD", "BREAD", "ICE_CREAM"},
                ["DEFEND_SILENT"] * 20, "SLIMED_BERSERKER_NORMAL")
    for _ in range(3):
        check(oracle, action(oracle, "play_card"))
        check(oracle, action(oracle, "end_turn"))


def test_mittens_post_draw_choice(oracle, tmp_path):
    load_relics(oracle, tmp_path, {"TOASTY_MITTENS"}, ["DEFEND_SILENT"] * 24, "SLIMED_BERSERKER_NORMAL")
    oracle.public = oracle.command(**legal_actions(oracle.public)[0].command())
    for _ in range(2):
        check(oracle, action(oracle, "end_turn"))
        check(oracle, action(oracle, "select_cards"))


def test_knowledge_demise_tick(oracle):
    oracle.start("DEMISE", ["DEFLECT"] * 20, ["POWDERED_DEMISE"], encounter="KNOWLEDGE_DEMON_BOSS")
    oracle.public = oracle.command(**action(oracle, "end_turn").command())
    oracle.public = oracle.command(**legal_actions(oracle.public)[0].command())
    oracle.public = oracle.command(**action(oracle, "use_potion").command())
    check(oracle, action(oracle, "end_turn"))


@pytest.mark.parametrize("card,potion", [("ENVENOM", None), ("INFINITE_BLADES", "FLEX_POTION")])
def test_late_silent_powers(oracle, card, potion):
    oracle.start("POWERS", [card, "STRIKE_SILENT", "DEFEND_SILENT"], [potion] if potion else [],
                 encounter="SLIMED_BERSERKER_NORMAL")
    oracle.public = oracle.command(**next(a for a in legal_actions(oracle.public) if a.kind == "play_card" and
                                  oracle.public["hand"][a.args["card_index"]]["id"] == "CARD." + card).command())
    if potion:
        oracle.public = oracle.command(**action(oracle, "use_potion").command())
    check(oracle, action(oracle, "play_card", 0))
    check(oracle, action(oracle, "end_turn"))


def test_subject_phase_boundary_and_painful_stabs(oracle):
    oracle.start("SUBJECT", ["GRAND_FINALE"] * 7, encounter="TEST_SUBJECT_BOSS", hp=450)
    check(oracle, action(oracle, "play_card"))
    check(oracle, action(oracle, "play_card"), stop="death phase")
    assert not oracle.public["enemies"]
    oracle.public = oracle.command(**action(oracle, "end_turn").command())
    assert any(p["id"] == "POWER.PAINFUL_STABS_POWER" for p in oracle.public["enemies"][0]["powers"])
    check(oracle, action(oracle, "end_turn"))


def test_crab_arm_rage_then_knockout(oracle):
    oracle.start("CRAB", ["GRAND_FINALE"] * 7, ["FIRE_POTION"] * 2, encounter="KAISER_CRAB_BOSS")
    for _ in range(2):
        check(oracle, action(oracle, "use_potion", 1), facing=1)
    for _ in range(3):
        check(oracle, action(oracle, "play_card"), facing=1)
    assert len(oracle.public["enemies"]) == 1
    for _ in range(3):
        check(oracle, action(oracle, "play_card"), facing=0)


def test_knight_hex_and_fabricator_summons(oracle):
    for name in ("KNIGHTS_ELITE", "FABRICATOR_NORMAL"):
        oracle.start("LATE", ["DEFEND_SILENT"] * 40, encounter=name, hp=450, seed="CSV4FIX_" + name)
        for _ in range(2):
            check(oracle, action(oracle, "end_turn"), stop="enemy intent")
        for _ in range(2):
            check(oracle, action(oracle, "play_card"))
            check(oracle, action(oracle, "end_turn"))


def test_hidden_daggers_native_continuation(oracle):
    oracle.start("DAGGERS", ["HIDDEN_DAGGERS", "STRIKE_SILENT", "DEFLECT", "DEFLECT"],
                 encounter="THE_INSATIABLE_BOSS", seed="CSV4FIX_HIDDEN_DAGGERS")
    projected = project(oracle.public)
    daggers = next(a for a in legal_actions(oracle.public) if a.kind == "play_card" and
                   oracle.public["hand"][a.args["card_index"]]["id"] == "CARD.HIDDEN_DAGGERS")
    predicted = advance(replace(projected.state, late=True), root_move(projected, daggers.kind, daggers.args))
    oracle.public = oracle.command(**daggers.command())
    actual = project(oracle.public, late_prompts=True)
    assert not _difference(predicted, actual.state)
    selected = legal_actions(oracle.public)[0]
    predicted = advance(predicted, legal(predicted)[0])
    oracle.public = oracle.command(**selected.command())
    assert not _difference(predicted, project(oracle.public).state)
    assert sum(c["id"] == "CARD.SHIV" for c in oracle.public["hand"]) == 2


@pytest.mark.parametrize("encounter,first_turns", [("KAISER_CRAB_BOSS", 0), ("THE_INSATIABLE_BOSS", 0),
                                                   ("KNOWLEDGE_DEMON_BOSS", 1)])
def test_boss_hidden_draw_permutation(oracle, encounter, first_turns):
    from sts2rl.combat_search_v2.features import extract_leaf_features
    from sts2rl.combat_search_v2.state import END_TURN

    features, hands = [], []
    for reverse in (False, True):
        oracle.start("SWAP", ["DEFEND_SILENT"] * 16 + ["STRIKE_SILENT"] * 16,
                     encounter=encounter, seed="CSV4FIX_SWAP_" + encounter)
        for _ in range(first_turns):
            oracle.public = oracle.command(**action(oracle, "end_turn").command())
            oracle.public = oracle.command(**legal_actions(oracle.public)[0].command())
        projection = project(oracle.public, late_prompts=True)
        order = sorted((c["id"].split(".")[-1] for c in oracle.public["draw_pile"]), reverse=reverse)
        oracle.command(cmd="set_draw_order", cards=order)
        predicted = advance(replace(projection.state, late=True, facing=1, preview_facing=1), END_TURN)
        assert predicted.outcome == "completed"
        features.append(extract_leaf_features(predicted).tobytes())
        oracle.public = oracle.command(**action(oracle, "end_turn").command())
        hands.append(tuple(c["id"] for c in oracle.public["hand"]))
    assert features[0] == features[1] and hands[0] != hands[1]

def named_card(game, name, target=None):
    return next(a for a in legal_actions(game.public) if a.kind == "play_card"
                and game.public["hand"][a.args["card_index"]]["id"] == "CARD." + name
                and (target is None or a.args.get("target_index") == target))


def test_crab_poison_rage_order(oracle):
    deck = ["GRAND_FINALE"] * 3 + ["STRIKE_SILENT"] * 3 + ["DEADLY_POISON"]
    oracle.start("CRAB_POISON", deck, ["FIRE_POTION", "POISON_POTION"], encounter="KAISER_CRAB_BOSS")
    facing = 1
    for _ in range(3):
        check(oracle, named_card(oracle, "GRAND_FINALE"), facing=facing)
    for _ in range(2):
        check(oracle, action(oracle, "use_potion", 0), facing=facing)
        facing = 0
    for name in ("STRIKE_SILENT", "STRIKE_SILENT", "DEADLY_POISON"):
        check(oracle, named_card(oracle, name, 0), facing=facing)
    check(oracle, action(oracle, "end_turn"), facing=facing)
    assert [(e["id"], e["block"]) for e in oracle.public["enemies"]] == [("MONSTER.ROCKET", 99)]


def test_knowledge_relic_order(oracle, tmp_path):
    load_relics(oracle, tmp_path, {"RIPPLE_BASIN", "KUSARIGAMA", "SHURIKEN"}, ["SLICE"] * 20, "KNOWLEDGE_DEMON_BOSS")
    check(oracle, named_card(oracle, "SLICE"))
    check(oracle, action(oracle, "end_turn"), plays=1)
    check(oracle, legal_actions(oracle.public)[1])


def test_meat_on_the_bone_crosses_half(oracle, tmp_path):
    load_relics(oracle, tmp_path, {"MEAT_ON_THE_BONE"}, ["DEFLECT"] * 10, "SLIMED_BERSERKER_NORMAL", hp=204)
    for _ in range(12):
        check(oracle, action(oracle, "end_turn"))
        if oracle.public["player"]["hp"] <= 200:
            break
    assert oracle.public["player"]["relics"][0]["status"] == "Active"


def test_late_enchantments(oracle, tmp_path):
    def modify(player):
        for card, ench, amount in zip(player["deck"], ("NIMBLE", "TEZCATARAS_EMBER", "PERFECT_FIT"), (2, 1, 1)):
            card["enchantment"] = {"id": "ENCHANTMENT." + ench, "amount": amount}
    load_relics(oracle, tmp_path, {"MYSTIC_LIGHTER"}, ["DEFEND_SILENT", "STRIKE_SILENT", "SLICE"],
                "THE_INSATIABLE_BOSS", edit=modify)
    for name in ("DEFEND_SILENT", "STRIKE_SILENT", "SLICE"):
        check(oracle, named_card(oracle, name))
    check(oracle, action(oracle, "end_turn"))


@pytest.mark.parametrize("name", ["PINPOINT", "ENLIGHTENMENT"])
def test_late_costs(oracle, name):
    if name == "PINPOINT":
        deck, plays = ["PINPOINT"] + ["DEFLECT"] * 3, ["DEFLECT"] * 3 + ["PINPOINT"]
    else:
        deck, plays = ["ENLIGHTENMENT", "DASH"], ["ENLIGHTENMENT", "DASH"]
    oracle.start(name, deck, encounter="THE_INSATIABLE_BOSS")
    for card in plays:
        check(oracle, named_card(oracle, card))


@pytest.mark.parametrize("name", ["HAND_TRICK", "SEEKER_STRIKE"])
def test_late_choice_boundary(oracle, name):
    oracle.start(name, [name] + ["SLICE"] * 10, encounter="THE_INSATIABLE_BOSS")
    while not any(c["id"] == "CARD." + name for c in oracle.public["hand"]):
        oracle.public = oracle.command(**action(oracle, "end_turn").command())
    check(oracle, named_card(oracle, name), stop="card selection")


def test_late_decay_pyramid(oracle, tmp_path):
    load_relics(oracle, tmp_path, {"RUNIC_PYRAMID"}, ["DECAY", "DEFEND_SILENT"], "THE_INSATIABLE_BOSS")
    check(oracle, action(oracle, "end_turn"))
    assert any(c["id"] == "CARD.DECAY" for c in oracle.public["hand"])

def test_stable_serum_ticks_before_curse(oracle):
    oracle.start("SERUM", ["DEFLECT"] * 18, ["STABLE_SERUM"], encounter="KNOWLEDGE_DEMON_BOSS")
    check(oracle, action(oracle, "use_potion"))
    assert dict(project(oracle.public).state.powers)["RETAIN_HAND"] == 2
    check(oracle, action(oracle, "end_turn"))
    check(oracle, legal_actions(oracle.public)[1])
    check(oracle, action(oracle, "end_turn"))


def test_expensive_block_and_single_shield_target(oracle, tmp_path):
    load_relics(oracle, tmp_path, {"INTIMIDATING_HELMET", "PARRYING_SHIELD"}, ["DASH", "DEFEND_SILENT"], "THE_INSATIABLE_BOSS")
    check(oracle, named_card(oracle, "DASH"))
    check(oracle, named_card(oracle, "DEFEND_SILENT"))
    check(oracle, action(oracle, "end_turn"))


def test_phantom_existing_shiv(oracle):
    oracle.start("BLADES", ["SHIV", "PHANTOM_BLADES"], encounter="THE_INSATIABLE_BOSS")
    check(oracle, named_card(oracle, "PHANTOM_BLADES"), stop="existing shiv")
    assert "Retain" in next(c for c in oracle.public["hand"] if c["id"] == "CARD.SHIV")["keywords"]

def test_disabled_wax_relic(oracle, tmp_path):
    def ready_to_melt(player):
        for relic in player["relics"]:
            if relic["id"] == "RELIC.TOY_BOX":
                relic["props"]["ints"][0]["value"] = 2
            else:
                relic["props"] = {"bools": [{"name": "IsWax", "value": True}]}
    load_relics(oracle, tmp_path, {"TOY_BOX", "CAPTAINS_WHEEL"}, ["GRAND_FINALE"] * 4,
                "SHRINKER_BEETLE_WEAK", edit=ready_to_melt)
    while oracle.public.get("in_combat"):
        oracle.public = oracle.command(**action(oracle, "play_card").command())
    for _ in range(8):
        if oracle.public["decision"] == "map_select":
            break
        oracle.public = oracle.command(**legal_actions(oracle.public)[-1].command())
    oracle.public = oracle.command(cmd="enter_room", type="monster", encounter="KAISER_CRAB_BOSS")
    current = replace(project(oracle.public).state, late=True, facing=1, preview_facing=1)
    assert next(r for r in current.relics if r.name == "CAPTAINS_WHEEL").status == "Disabled"
    assert encounter_reason(current) == "disabled wax relic"


@pytest.mark.parametrize("name,reason", [("THE_INSATIABLE_BOSS", "confused escape"), ("SLIMED_BERSERKER_NORMAL", None)])
def test_snecko_current_costs(oracle, tmp_path, name, reason):
    load_relics(oracle, tmp_path, {"SNECKO_EYE"}, ["STRIKE_SILENT"] * 22, name)
    assert dict(project(oracle.public).state.powers)["CONFUSED"]
    check(oracle, action(oracle, "play_card"))
    check(oracle, action(oracle, "end_turn"), stop=reason)


def test_serum_projection_outside_late_rooms(oracle):
    from sts2rl.combat_search_v2.integration import CombatSearchV2
    from sts2rl.combat_search_v2.planner import Config
    from sts2rl.native import runtime_identity

    oracle.start("EARLY_SERUM", ["DEFEND_SILENT"] * 12, ["STABLE_SERUM"], seed="CSV4FIX_EARLY_SERUM")
    public = {**oracle.public, "runtime_identity": runtime_identity(10)}
    mode = CombatSearchV2(Config(v6_late_coverage=True), record=True)
    chosen = mode.choose(public, action(oracle, "play_card"), legal_actions)
    after = oracle.command(**chosen.command())
    mode.observe(chosen, after, legal_actions)
    assert mode.records[-1]["oracle"][1] == "match"


@pytest.mark.parametrize("name", ["STRIKE_SILENT", "DEFEND_SILENT", "SLICE", "DEFLECT", "DASH", "DEADLY_POISON"])
def test_razor_tooth_after_source_card(oracle, tmp_path, name):
    load_relics(oracle, tmp_path, {"RAZOR_TOOTH"}, [name], "THE_INSATIABLE_BOSS")
    check(oracle, named_card(oracle, name))
    assert oracle.public["discard_pile"][0]["upgrades"] == 1
    check(oracle, action(oracle, "end_turn"))


def test_razor_tooth_unknown_upgrade_boundary(oracle, tmp_path):
    load_relics(oracle, tmp_path, {"RAZOR_TOOTH"}, ["ACROBATICS"], "THE_INSATIABLE_BOSS")
    check(oracle, named_card(oracle, "ACROBATICS"), stop="razor tooth upgrade")


def test_mittens_deferred_plating(oracle, tmp_path):
    def add_potion(player):
        player["potions"] = [{"id": "POTION.HEART_OF_IRON", "slot_index": 0}]
    load_relics(oracle, tmp_path, {"TOASTY_MITTENS"}, ["DEFEND_SILENT"] * 24, "KAISER_CRAB_BOSS", edit=add_potion)
    oracle.public = oracle.command(**legal_actions(oracle.public)[0].command())
    check(oracle, action(oracle, "use_potion"), facing=1)
    check(oracle, action(oracle, "end_turn"), facing=1)
    check(oracle, action(oracle, "select_cards"), facing=1)


def test_belt_buckle_last_potion(oracle, tmp_path):
    def add_potion(player):
        player["potions"] = [{"id": "POTION.BLOCK_POTION", "slot_index": 0}]
    load_relics(oracle, tmp_path, {"BELT_BUCKLE"}, ["DEFLECT"] * 10, "THE_INSATIABLE_BOSS", edit=add_potion)
    check(oracle, action(oracle, "use_potion"), stop="belt buckle")


def test_subject_enrage_after_survivor_choice(oracle):
    oracle.start("SUBJECT_DISCARD", ["SURVIVOR", "DEFLECT", "DEFEND_SILENT"], encounter="TEST_SUBJECT_BOSS")
    predicted = check(oracle, named_card(oracle, "SURVIVOR"))
    assert predicted.prompt and "STRENGTH" not in dict(predicted.enemies[0].powers)
    selected = legal_actions(oracle.public)[0]
    after = advance(predicted, legal(predicted)[0])
    oracle.public = oracle.command(**selected.command())
    assert not _difference(after, project(oracle.public).state)
    assert dict(after.enemies[0].powers)["STRENGTH"] == dict(after.enemies[0].powers)["ENRAGE"]


def test_aeonglass_sixth_play_boundary(oracle):
    oracle.start("WITHER", ["SLICE"] * 16, encounter="AEONGLASS_BOSS")
    for count in range(5):
        check(oracle, named_card(oracle, "SLICE"), aeon=count)
    check(oracle, named_card(oracle, "SLICE"), aeon=5, stop="creates wither")
    assert any(c["id"] == "CARD.WITHER" for c in oracle.public["hand"])
