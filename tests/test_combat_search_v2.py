"""Public projection, ordered transitions, and planner fixtures."""
from copy import deepcopy
from dataclasses import replace

import pytest

from sts2rl.combat_search_v2.state import Card, Move, Unsupported, project, root_move
from sts2rl.combat_search_v2.transitions import admission, advance, legal
from sts2rl.native import legal_actions


def card(name, cost=1, *, kind="Skill", target="Self", upgrade=0, keywords=(), **fields):
    return {"id": f"CARD.{name}", "type": kind, "cost": cost, "target_type": target,
            "upgrades": upgrade, "keywords": list(keywords), **fields}


def potion(name, target="Self", **stats):
    return {"id": f"POTION.{name}", "target_type": target, "vars": stats, "can_use": True}


def powers(**values):
    return [{"id": f"POWER.{k}_POWER", "amount": n} for k, n in values.items()]


def enemy(name="SHRINKER_BEETLE", *, hp=38, hit=10, hits=1, power=(), block=0):
    return {"id": f"MONSTER.{name}", "hp": hp, "max_hp": max(hp, 38), "block": block,
            "powers": power, "intents": [{"type": "Attack", "damage": hit, "hits": hits}]}


def view(*hand, hp=25, block=0, energy=3, enemies=None, potions=(), power=(), draw=(),
         discard=(), relics=()):
    return {
        "decision": "combat_play", "in_combat": True, "observation_version": 2,
        "context": {"act": 1, "room_type": "Monster"}, "round": 2, "pile_order": "unordered",
        "energy": energy, "max_energy": 3, "player_powers": power,
        "hand": [{"index": i, "can_play": ("Unplayable" not in c["keywords"] and c["cost"] <= energy), **c}
                 for i, c in enumerate(hand)],
        "enemies": [{"index": i, **e} for i, e in enumerate(enemies if enemies is not None else [enemy()])],
        "player": {"hp": hp, "max_hp": 70, "block": block, "relics": relics,
                   "potions": [{"index": i, **p} for i, p in enumerate(potions)]},
        "draw_pile": list(draw), "discard_pile": list(discard), "exhaust_pile": [], "play_pile": [],
    }


DEFEND = card("DEFEND_SILENT")
DEFEND_PLUS = card("DEFEND_SILENT", upgrade=1)
STRIKE = card("STRIKE_SILENT", kind="Attack", target="AnyEnemy")
SURVIVOR = card("SURVIVOR")
BURST = card("BURST")
BURN = card("BURN", 0, kind="Status", target="None", keywords=("Unplayable",))
DAZED = card("DAZED", 0, kind="Status", target="None", keywords=("Unplayable", "Ethereal"))
ADRENALINE = card("ADRENALINE", 0, keywords=("Exhaust",))
ENERGY = potion("ENERGY_POTION", Energy=2)


def play(state, name, target=-1):
    slot = next(c.slot for c in state.hand if c.variant.name == name)
    move = Move("play_card", slot, target)
    assert move in legal(state)
    return advance(state, move)


class ForbiddenRead:
    def __getattribute__(self, name):
        raise AssertionError(f"read private state via {name}")


class AllowlistGuard(dict):
    def __getitem__(self, key):
        if str(key).startswith("private"):
            raise AssertionError(f"read private field {key}")
        value = super().__getitem__(key)
        if isinstance(value, ForbiddenRead):
            raise AssertionError(f"read forbidden field {key}")
        return value

    def get(self, key, default=None):
        return self[key] if key in self else default

    def items(self):
        raise AssertionError("enumerated an observation object")

    def __iter__(self):
        raise AssertionError("enumerated an observation object")


def test_projection_poison_pill_and_unordered_duplicate_variants():
    public = view(DEFEND, draw=(STRIKE, {**STRIKE, "upgrades": 1}, DEFEND))
    changed = deepcopy(public)
    changed["draw_pile"].reverse()
    expected = project(public)
    changed["draw_pile"][1] = AllowlistGuard({**changed["draw_pile"][1], "private_copy": ForbiddenRead()})
    changed["player"] = AllowlistGuard({**changed["player"], "private_rng": ForbiddenRead()})
    guarded = AllowlistGuard({**changed, **dict.fromkeys(
        ("private_rng", "seed", "index", "session", "history", "serialized", "draw_order"), ForbiddenRead()
    )})
    assert project(guarded) == expected
    assert legal(project(guarded).state) == legal(expected.state)


def test_projection_physical_mapping_and_unqualified_legality():
    public = view(STRIKE, DEFEND, enemies=[enemy(), enemy()])
    public["hand"][0]["index"] = 5
    public["enemies"][1]["index"] = 8
    projected = project(public)
    assert tuple(root_move(projected, a.kind, a.args) for a in legal_actions(public)) == legal(projected.state)
    public["hand"][0]["can_play"] = False
    assert admission(project(public)) == "legality/STRIKE_SILENT"
    public["hand"][1]["enchantment_state"] = {"id": "ENCHANTMENT.TEST"}
    public["hand"][0]["can_play"] = True
    assert admission(project(public)) == "card/DEFEND_SILENT"
    public["hand"][1]["index"] = 5
    with pytest.raises(Unsupported, match="duplicate physical"):
        project(public)


def test_energy_unlocks_after_potion_and_adrenaline():
    projected = project(view(DEFEND_PLUS, potions=(ENERGY,), energy=0, hp=4))
    assert not admission(projected)
    s = projected.state
    assert legal(s) == (Move("use_potion", 0), Move("end_turn"))
    s = advance(s, legal(s)[0])
    assert s.energy == 2 and s.spent == 1 and not s.potions
    assert play(s, "DEFEND_SILENT").block == 8

    s = project(view(ADRENALINE, DEFEND, energy=0)).state
    s = play(s, "ADRENALINE")
    assert s.energy == 1 and s.exhaust[0].name == "ADRENALINE"
    assert play(s, "DEFEND_SILENT").block == 5
    s = project(view(ADRENALINE, DEFEND, energy=0, draw=(STRIKE, DEFEND))).state
    s = play(s, "ADRENALINE")
    assert s.energy == 1 and s.boundary.reason == "draw" and s.boundary.count == 2
    assert not legal(s)


def test_burst_stacked_replay_cost_hooks_and_exhaust():
    s = project(view(BURST, DEFEND_PLUS, energy=2, hp=3)).state
    s = play(s, "BURST")
    s = play(s, "DEFEND_SILENT")
    assert s.block == 16 and s.energy == 0 and not s.powers
    assert [v.name for v in s.discard] == ["BURST", "DEFEND_SILENT"]

    s = project(view(DEFEND_PLUS, energy=1, power=powers(BURST=1, DUPLICATION=1, AFTERIMAGE=1),
                     enemies=[enemy(power=powers(VITAL_SPARK=3))])).state
    s = play(s, "DEFEND_SILENT")
    assert s.block == 27 and s.energy == 0
    assert dict(s.powers) == {"AFTERIMAGE": 1, "TAINTED": 9}
    assert s.enemies[0].attack_delta == 9

    s = project(view(ADRENALINE, power=powers(BURST=1))).state
    s = play(s, "ADRENALINE")
    assert s.energy == 5 and len(s.exhaust) == 1


def test_survivor_prompt_and_sly():
    s = project(view(SURVIVOR, DEFEND, BURN, energy=2, hp=3)).state
    s = play(s, "SURVIVOR")
    assert s.energy == 1 and s.block == 8 and s.prompt.operation == "SURVIVOR"
    assert legal(s) == (Move("select_cards", selection=(1,)), Move("select_cards", selection=(2,)))
    s = advance(s, legal(s)[1])
    assert not s.prompt and [c.slot for c in s.hand] == [1]
    assert play(s, "DEFEND_SILENT").block == 13

    tactician = card("TACTICIAN", 3, keywords=("Sly",))
    s = project(view(SURVIVOR, tactician, DEFEND, energy=1)).state
    s = advance(play(s, "SURVIVOR"), Move("select_cards", selection=(1,)))
    assert s.energy == 1 and not s.prompt
    assert [v.name for v in s.discard] == ["SURVIVOR", "TACTICIAN"]
    assert [c.slot for c in s.hand] == [2]

    sly_damage = Card(1, replace(project(view(STRIKE)).state.hand[0].variant, keywords=("Sly",)))
    s = project(view(SURVIVOR, STRIKE, energy=1, enemies=[enemy(), enemy()])).state
    s = replace(s, hand=(s.hand[0], sly_damage))
    s = advance(play(s, "SURVIVOR"), Move("select_cards", selection=(1,)))
    assert s.boundary.reason == "sly target"


@pytest.mark.parametrize("name,cost", [("ACROBATICS", 1), ("PREPARED", 0)])
def test_draw_before_discard(name, cost):
    s = play(project(view(card(name, cost), DEFEND, draw=(STRIKE,))).state, name)
    assert s.boundary.reason == "draw" and not s.prompt
    assert [event.kind for event in s.queue][:2] == ["prompt", "after_play"]
    s = play(project(view(card(name, cost), DEFEND)).state, name)
    assert s.prompt.operation == name


def test_gamble_triggers_sly_before_draw():
    s = project(view(card("CALCULATED_GAMBLE", 0, keywords=("Exhaust",)),
                     card("TACTICIAN", 3, keywords=("Sly",)), DEFEND, energy=0)).state
    s = play(s, "CALCULATED_GAMBLE")
    assert not s.hand and s.energy == 1 and s.boundary.reason == "draw"
    assert s.boundary.count == 2 and s.boundary.shuffle


def test_x_cost_at_resolution_and_artifact_order():
    malaise = card("MALAISE", 0, target="AnyEnemy", upgrade=1, costs_x=True, keywords=("Exhaust",))
    s = project(view(STRIKE, malaise, enemies=[enemy(power=powers(ARTIFACT=1, STRENGTH=2))],
                     potions=(ENERGY,))).state
    for initial, expected in [(s, 4), (play(s, "STRIKE_SILENT", 0), 3),
                               (advance(s, Move("use_potion", 0)), 6)]:
        successor = play(initial, "MALAISE", 0)
        assert successor.energy == 0
        assert dict(successor.enemies[0].powers) == {"STRENGTH": 2, "WEAK": expected}


def test_blade_dance_hand_cap_and_shiv_exhaust():
    dance = card("BLADE_DANCE", keywords=("Exhaust",))
    s = project(view(dance, *([STRIKE] * 9))).state
    capped = play(s, "BLADE_DANCE")
    assert len(capped.hand) == 10 and sum(c.variant.name == "SHIV" for c in capped.hand) == 1
    s = play(play(s, "STRIKE_SILENT", 0), "STRIKE_SILENT", 0)
    s = play(s, "BLADE_DANCE")
    assert len(s.hand) == 10 and sum(c.variant.name == "SHIV" for c in s.hand) == 3
    s = play(s, "SHIV", 0)
    assert sorted(v.name for v in s.exhaust) == ["BLADE_DANCE", "SHIV"]
    assert len({c.slot for c in s.hand}) == len(s.hand)

def end(state):
    return advance(state, Move("end_turn"))


def test_end_turn_audit_sequences():
    s = project(view(DEFEND_PLUS, hp=4, energy=0, potions=(ENERGY,))).state
    assert end(s).outcome == "dead"
    assert end(play(advance(s, Move("use_potion", 0)), "DEFEND_SILENT")).hp == 2
    s = project(view(BURST, DEFEND_PLUS, hp=3, energy=2, enemies=[enemy(hit=16)])).state
    assert end(play(s, "DEFEND_SILENT")).hp == 0
    assert end(play(play(s, "BURST"), "DEFEND_SILENT")).hp == 3
    s = project(view(SURVIVOR, DEFEND, BURN, hp=3, energy=2, enemies=[enemy(hit=15)])).state
    s = play(s, "SURVIVOR")
    assert end(play(advance(s, Move("select_cards", selection=(2,))), "DEFEND_SILENT")).hp == 1
    assert end(advance(s, Move("select_cards", selection=(1,)))).hp == 0


def test_retain_ethereal_blur_and_start_boundaries():
    plans = card("WELL_LAID_PLANS", 2, kind="Power")
    blur = card("BLUR")
    s = project(view(plans, blur, DAZED, BURN, *([DEFEND] * 6), draw=(STRIKE,) * 5,
                     enemies=[enemy(hit=0)])).state
    s = end(play(play(s, "WELL_LAID_PLANS"), "BLUR"))
    assert s.outcome == "completed" and s.block == 3
    assert len(s.hand) == 7 and s.boundary.count == 3
    assert s.exhaust[0].name == "DAZED"
    assert dict(s.powers) == {"WELL_LAID_PLANS": 1}
    for name in ("NIGHTMARE", "TOOLS_OF_THE_TRADE"):
        assert end(project(view(power=powers(**{name: 1}))).state).boundary.reason == f"start/{name}"
        assert play(project(view(card(name))).state, name).boundary.reason == name.lower()


def test_constrict_hand_effects_and_immediate_clear():
    wither = card("WITHER", 0, kind="Status", target="None", keywords=("Unplayable",))
    source = enemy("SLITHERING_STRANGLER", hp=5, hit=0, power=powers(POISON=6))
    s = project(view(STRIKE, BURN, wither, hp=3, enemies=[source], power=powers(CONSTRICT=3))).state
    assert end(s).outcome == "dead"
    assert end(play(s, "STRIKE_SILENT", 0)).outcome == "victory"
    cloak = {"id": "RELIC.CLOAK_CLASP", "vars": {"Block": 1}}
    s = project(view(BURN, wither, DEFEND, DEFEND, hp=7, block=3, enemies=[source],
                     power=powers(CONSTRICT=3), relics=(cloak,))).state
    assert end(s).hp == 6
    s = play(s, "DEFEND_SILENT")
    assert end(s).hp == 7


def test_buffer_and_intangible_resolve_per_hit_in_source_order():
    for damage, remaining in [((1, 20), 5), ((20, 1), 24)]:
        s = project(view(hp=25, power=powers(BUFFER=1), enemies=[enemy(hit=n) for n in damage])).state
        assert end(s).hp == remaining
        if damage[0] == 1:
            assert end(replace(s, block=1)).hp == 25
    s = project(view(BURN, hp=25, power=powers(BUFFER=1), enemies=[enemy(hit=10, hits=2)])).state
    assert end(s).hp == 5
    s = project(view(hp=25, power=powers(BUFFER=1, INTANGIBLE=1), enemies=[enemy(hit=20, hits=3)])).state
    assert end(s).hp == 23


def test_sandpit_escape_and_true_clear():
    escape = card("FRANTIC_ESCAPE", kind="Status")
    boss = enemy("THE_INSATIABLE", hp=38, hit=0, power=powers(SANDPIT=1))
    s = project(view(escape, hp=5, enemies=[boss])).state
    assert end(s).outcome == "dead"
    escaped = play(s, "FRANTIC_ESCAPE")
    assert escaped.discard[0].cost == 2
    assert dict(escaped.enemies[0].powers)["SANDPIT"] == 2
    assert end(escaped).outcome == "completed"

    boss = enemy("THE_INSATIABLE", hp=38, hit=8, power=powers(SANDPIT=1))
    s = project(view(escape, DEFEND, hp=5, energy=2, enemies=[boss])).state
    assert end(play(s, "FRANTIC_ESCAPE")).outcome == "dead"
    assert end(play(s, "DEFEND_SILENT")).outcome == "dead"
    saved = end(play(play(s, "FRANTIC_ESCAPE"), "DEFEND_SILENT"))
    assert saved.hp == 2 and dict(saved.enemies[0].powers)["SANDPIT"] == 1
    following = replace(saved, outcome="", boundary=None)
    assert end(following).outcome == "dead"

    for hp, expected in [(6, "victory"), (7, "dead")]:
        boss = enemy("THE_INSATIABLE", hp=hp, hit=0, power=powers(SANDPIT=1))
        s = project(view(STRIKE, enemies=[boss])).state
        assert end(play(s, "STRIKE_SILENT", 0)).outcome == expected


@pytest.mark.parametrize("name,reason", [
    ("CEREMONIAL_BEAST", "plow"),
    ("VANTOM", "vantom slippery"), ("KIN_FOLLOWER", "kin leader"),
    ("WATERFALL_GIANT", "waterfall"), ("MECHA_KNIGHT", "reattach"),
    ("ROCK_BOWLBUG", "stun source"), ("ENTOMANCER", "dazed"),
    ("KNOWLEDGE_DEMON", "sloth"), ("KAISER_CRAB", "facing"), ("AXEBOT", "stock"),
])
def test_unsupported_encounter_regressions(name, reason):
    s = project(view(STRIKE, enemies=[enemy(name, hp=6, power=powers(POISON=7))])).state
    assert reason in end(s).boundary.reason
    assert reason in play(s, "STRIKE_SILENT", 0).boundary.reason
