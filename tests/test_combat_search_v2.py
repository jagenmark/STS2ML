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
    changed["draw_pile"][1]["stats"] = AllowlistGuard({"private_preview": ForbiddenRead()})
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
    s = play(s, "SURVIVOR")
    assert s.boundary.reason == "sly target"


@pytest.mark.parametrize("name,cost", [("ACROBATICS", 1), ("PREPARED", 0)])
def test_draw_before_discard(name, cost):
    s = play(project(view(card(name, cost), DEFEND, draw=(STRIKE,))).state, name)
    assert s.boundary.reason == "draw" and not s.prompt
    assert [event.kind for event in s.queue][:2] == ["prompt", "after_play"]
    s = play(project(view(card(name, cost), DEFEND, STRIKE)).state, name)
    assert s.prompt.operation == name
    forced = play(project(view(card(name, cost), DEFEND)).state, name)
    assert forced.prompt is None and not forced.hand
    assert "DEFEND_SILENT" in {card.name for card in forced.discard}


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


def test_repeated_aoe_removes_shrink_between_waves():
    spray = card("DAGGER_SPRAY", kind="Attack", target="AllEnemies")
    s = project(view(spray, power=powers(SHRINK=-1),
                     enemies=[enemy(hp=2), enemy("FUZZY_WURM_CRAWLER", hp=20)])).state
    successor = play(s, "DAGGER_SPRAY")
    assert [e.hp for e in successor.enemies] == [0, 14]
    assert not successor.powers

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
    s = project(view(hp=25, power=powers(BUFFER=1, INTANGIBLE=1), enemies=[enemy(hit=1, hits=3)])).state
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


def test_sandpit_cheap_retained_escape_on_following_observation():
    escape = card("FRANTIC_ESCAPE", kind="Status")
    first = project(view(escape, hp=5, energy=2, power=powers(WELL_LAID_PLANS=1),
                         enemies=[enemy("THE_INSATIABLE", hit=0, power=powers(SANDPIT=2))])).state
    banked = end(first)
    assert banked.outcome == "completed" and banked.hand[0].variant.cost == 1
    assert dict(banked.enemies[0].powers)["SANDPIT"] == 1

    # Supply the new public hand and intent explicitly after the turn boundary.
    # A cheap retained copy can fit alongside Defend on the critical turn.
    next_boss = enemy("THE_INSATIABLE", hit=8, power=powers(SANDPIT=1))
    cheap = project(view(escape, DEFEND, hp=banked.hp, energy=2, enemies=[next_boss])).state
    assert end(play(play(cheap, "FRANTIC_ESCAPE"), "DEFEND_SILENT")).hp == 2
    dear = project(view({**escape, "cost": 2}, DEFEND, hp=banked.hp, energy=2,
                        enemies=[next_boss])).state
    assert all(end(advance(dear, move)).outcome == "dead" for move in legal(dear) if move.kind == "play_card")


def test_prompt_mapping_uses_candidate_order_and_rejects_a_stale_index():
    source = view(SURVIVOR, DEFEND, BURN)
    nested = view(DEFEND, BURN, block=8, energy=2)
    nested["play_pile"] = [source["hand"][0]]
    prompt = {
        "decision": "card_select", "in_combat": True, "combat_state": nested,
        "selection_source": {"kind": "play_card", "id": "CARD.SURVIVOR"},
        "cards": [{"index": 10, "id": "CARD.DEFEND_SILENT"}, {"index": 11, "id": "CARD.BURN"}],
        "min_select": 1, "max_select": 1,
    }
    projected = project(prompt)
    assert root_move(projected, "select_cards", {"indices": "11"}) == Move("select_cards", selection=(1,))
    with pytest.raises(ValueError):
        root_move(projected, "select_cards", {"indices": "1"})
    with pytest.raises(Unsupported, match="selection operation"):
        project({**prompt, "selection_source": {"kind": "end_turn"}})


def test_skewer_binds_energy_after_target_changes():
    skewer = card("SKEWER", 0, kind="Attack", target="AnyEnemy", costs_x=True)
    s = project(view(STRIKE, skewer, enemies=[enemy(hp=6), enemy(hp=31)])).state
    assert play(s, "SKEWER", 1).enemies[1].hp == 7
    s = play(s, "STRIKE_SILENT", 0)
    assert tuple(m.target for m in legal(s) if m.kind == "play_card") == (1,)
    assert play(s, "SKEWER", 1).enemies[1].hp == 15


def test_shiv_replay_overflow_and_unqualified_inky_copy():
    dance = card("BLADE_DANCE", keywords=("Exhaust",))
    s = project(view(dance, *([DEFEND] * 7), power=powers(BURST=1))).state
    successor = play(s, "BLADE_DANCE")
    assert sum(c.variant.name == "SHIV" for c in successor.hand) == 3
    assert sum(v.name == "SHIV" for v in successor.discard) == 3
    inky = card("SHIV", 0, kind="Attack", target="AnyEnemy", keywords=("Exhaust",),
                enchantment_state={"id": "ENCHANTMENT.INKY", "amount": 1})
    assert admission(project(view(inky))) == "card/SHIV"


@pytest.mark.parametrize("name,reason", [
    ("MECHA_KNIGHT", "reattach"), ("ROCK_BOWLBUG", "stun source"),
    ("KNOWLEDGE_DEMON", "sloth"), ("KAISER_CRAB", "facing"), ("AXEBOT", "stock"),
])
def test_unsupported_encounter_regressions(name, reason):
    s = project(view(STRIKE, enemies=[enemy(name, hp=6, power=powers(POISON=7))])).state
    assert reason in end(s).boundary.reason
    assert reason in play(s, "STRIKE_SILENT", 0).boundary.reason

def search_fixture(public, champion, config=None):
    from sts2rl.combat_search_v2.planner import Config, search

    projected = project(public)
    return search(projected, legal(projected.state), champion, config or Config())


def test_beam_repairs_all_three_audit_failures():
    s = view(DEFEND_PLUS, hp=4, energy=0, potions=(ENERGY,))
    result = search_fixture(s, Move("end_turn"))
    assert result.choice == Move("use_potion", 0)
    assert result.line.state.hp == 2 and result.line.state.outcome == "completed"
    assert result.no_potion.state.outcome == "dead"
    assert result.with_potion.state.outcome == "completed"

    s = view(BURST, DEFEND_PLUS, hp=3, energy=2, enemies=[enemy(hit=16)])
    result = search_fixture(s, Move("play_card", 1))
    assert result.choice == Move("play_card", 0)
    assert result.line.state.hp == 3

    s = view(SURVIVOR, DEFEND, BURN, hp=3, energy=2, enemies=[enemy(hit=15)])
    assert search_fixture(s, Move("play_card", 1)).choice == Move("play_card", 1)
    result = search_fixture(s, Move("end_turn"))
    assert result.line.path[:2] == (Move("play_card", 0), Move("select_cards", selection=(2,)))
    assert result.line.state.hp == 1


def test_beam_reserve_and_tie():
    s = view(DEFEND, DEFEND, energy=1, hp=25, potions=(ENERGY,), enemies=[enemy(hit=4)])
    champion = Move("play_card", 1)
    result = search_fixture(s, champion)
    assert result.choice == champion
    assert not result.line.state.spent and result.with_potion is not None
    assert result.no_potion.score > result.with_potion.score


def test_search_swap_includes_scores_work_and_root_choice():
    s = view(BURST, DEFEND_PLUS, ADRENALINE, hp=4, energy=2, potions=(ENERGY,),
             draw=(DEFEND, STRIKE, {**STRIKE, "upgrades": 1}), enemies=[enemy(hit=16)])
    changes = deepcopy(s)
    changes["draw_pile"].reverse()
    changes.update({"seed": "unrelated", "index": 100, "private_rng": ForbiddenRead(),
                    "private_draw_order": ForbiddenRead(), "private_replay": ForbiddenRead()})
    baseline = search_fixture(s, Move("end_turn"))
    assert baseline == search_fixture(AllowlistGuard(changes), Move("end_turn"))
    assert baseline.attempts > 0 and baseline.root_count == baseline.covered_roots
    assert baseline.root_scores and baseline.choice == Move("play_card", 0)


def test_unknown_saving_draw_keeps_champion_and_work_caps_are_fixed():
    from sts2rl.combat_search_v2.planner import Config

    s = view(ADRENALINE, DEFEND, draw=(STRIKE, DEFEND), hp=4, energy=0)
    result = search_fixture(s, Move("play_card", 0))
    assert result.choice == Move("play_card", 0) and result.fallback
    assert dict(result.boundary_counts)["draw"] == 1
    s = view(*([STRIKE, DEFEND] * 5), hp=25, energy=3, potions=(ENERGY,),
             enemies=[enemy(hit=8) for _ in range(3)])
    result = search_fixture(s, Move("end_turn"), Config(children=48))
    assert result.child_cap and result.attempts == 48
    assert result.root_count == result.covered_roots
    assert result.reached_depth <= 10
    assert result == search_fixture(s, Move("end_turn"), Config(children=48))


def test_opt_in_bridge_emits_original_stamp_and_shadow_keeps_champion():
    from sts2rl.combat_search_v2.integration import CombatSearchV2
    from sts2rl.run_policy import IDENTITY

    public = {**view(DEFEND_PLUS, hp=4, energy=0, potions=(ENERGY,)), "runtime_identity": IDENTITY}
    actions = legal_actions(public)
    guarded = AllowlistGuard({**public, "private_serialized": ForbiddenRead()})
    assert CombatSearchV2().choose(guarded, actions[-1], lambda _: actions) is actions[0]
    assert CombatSearchV2(shadow=True).choose(guarded, actions[-1], lambda _: actions) is actions[-1]


def test_optional_bundle_settings_and_config_hash(tmp_path):
    import json
    from pathlib import Path
    from sts2rl.combat_search_v2.integration import CombatSearchV2
    from sts2rl.run_bundle import freeze_bundle, load_bundle

    root = Path(__file__).resolve().parents[1]
    frozen = root / "releases/silent-a10-mecha-knight/challenger/policy.json"
    _, old = load_bundle(frozen)
    assert not any(k.startswith("combat_search_v2") for k in old)

    config = tmp_path / "config.json"
    config.write_text(json.dumps({"version": 1, "width": 6}), encoding="utf8")
    path = freeze_bundle({"args": {"roles": ["candidate"], "weights": old["weights"],
                                   "combat_search_v2_shadow": True,
                                   "combat_search_v2_config": config}}, tmp_path / "bundle")
    _, settings = load_bundle(path)
    mode = CombatSearchV2.from_options(settings)
    assert mode.shadow and mode.config.width == 6
    settings["combat_search_v2_config"].write_text("{}", encoding="utf8")
    with pytest.raises(ValueError, match="checksum mismatch"):
        load_bundle(path)


def test_clone_keeps_combat_v2_state_and_prepare_is_idempotent():
    from sts2rl.combat_search_v2.integration import CombatSearchV2
    from sts2rl.deployed_controller import DeployedController
    from sts2rl.encounter import EncounterModel
    from sts2rl.run_policy import IDENTITY, RunPolicy, RunWeights

    public = view(DEFEND)
    public["context"]["floor"] = 3
    encounter = EncounterModel.from_data({"version": 1, "runtime_identity": IDENTITY, "default": "balanced"})
    mode = CombatSearchV2(record=True)
    controller = DeployedController(RunPolicy(RunWeights()), encounter=encounter, combat_v2=mode)
    encounter.prepare(public, controller.policy)
    mode.records.append({"history": ["root"]})
    mode._decision = (project(public), (Move("end_turn"),))
    clone = controller.clone()

    assert clone.combat_v2 is not mode
    assert clone.combat_v2._decision == mode._decision
    clone.combat_v2.records[0]["history"].append("child")
    assert mode.records == [{"history": ["root"]}]
    actor = clone.encounter.actor
    assert actor is not encounter.actor
    clone.encounter.prepare(public, clone.policy)
    assert clone.encounter.actor is actor


def test_phase2_bounds_and_seed_lock():
    from collections import Counter

    from sts2rl.combat_search_v2.planner import Config
    from sts2rl.combat_search_v2.seed_registry import load_confirmation_registry, load_registry

    assert (Config().width, Config().depth, Config().children) == (8, 10, 256)
    assert Config(width=32, children=1024).width == 32
    with pytest.raises(ValueError):
        Config(width=33)
    with pytest.raises(ValueError):
        Config(children=1025)
    rows = load_registry()
    assert len({r.seed for r in rows}) == len(rows) == 2048
    assert Counter((r.mode, r.split) for r in rows) == {
        (mode, split): count for mode in ("default", "seeded")
        for split, count in (("train", 716), ("dev", 154), ("test", 154))
    }
    test = load_confirmation_registry()
    assert len({r.seed for r in (*rows, *test)}) == 2356
    assert Counter((r.mode, r.split) for r in test) == {("default", "test"): 154, ("seeded", "test"): 154}


def test_smoke_bomb_transition_labels_only_when_combat_ends():
    from types import SimpleNamespace

    from sts2rl.combat_search_v2.recording import terminal_label

    action = SimpleNamespace(kind="use_potion", args={"potion_index": 0})
    before = view(DEFEND, potions=(potion("SMOKE_BOMB"),))
    witness = {"hp": 31, "max_hp": 70, "escaped": True}
    assert terminal_label(before, action, before, witness) is None
    after = {"in_combat": False, "decision": "map_select", "player": {"hp": 35}}
    assert terminal_label(before, action, after, witness) == {
        "outcome": "escape", "exit_hp": 31, "exit_max_hp": 70
    }
