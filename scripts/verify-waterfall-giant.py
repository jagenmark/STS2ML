"""Replay the two archived A10 DeathBlows and exercise the full boss cycle on the native host."""
import argparse
import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from sts2rl.combat_effects import power
from sts2rl.encounter import EncounterModel, EncounterPolicy
from sts2rl.enemy_forecast import WATERFALL_GIANT, attack_hits, waterfall_after_card, waterfall_forecast
from sts2rl.native import NativeSession, ReplayFork, digest, legal_actions
from sts2rl.run_bundle import load_bundle
from sts2rl.run_policy import RunPolicy, RunWeights
from sts2rl.teacher import heuristic, incoming


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "docs/evidence/silent-a10-waterfall-forecasts.json.gz"


def end_turn(game, state):
    return game.step(next(a for a in legal_actions(state) if a.kind == "end_turn"))


def public_forecast(state):
    enemy, = state["enemies"]
    assert enemy["id"] == WATERFALL_GIANT
    return waterfall_forecast(enemy, state["round"],
                              accelerant=power(state.get("player_powers"), "ACCELERANT"))


def check_deathblow(state, damage, round_number):
    enemy, = state["enemies"]
    assert state["round"] == round_number
    assert enemy["intents"] == [{"type": "DeathBlow", "damage": damage}]
    assert attack_hits(enemy) == 1 and incoming(enemy) == damage
    forecast = public_forecast(state)
    assert forecast.final_phase and forecast.certain_damage is None


def replay_fixture(game, row, survival):
    before, after = row["before"], row["after"]
    history = row["history"]
    fork = ReplayFork(row["specification"], tuple(history[:before["actions"]]), before["digest"])
    state = game.restore(fork)
    initial, = state["enemies"]
    stored = power(initial["powers"], "STEAM_ERUPTION")
    assert power(initial["powers"], "POISON") >= initial["hp"]
    assert public_forecast(state).certain_damage == stored
    saw_stun = False
    for command in history[before["actions"]:after["actions"]]:
        action = next(a for a in legal_actions(state) if a.command() == command)
        state = game.step(action)
        if state["enemies"][0]["intents"] == [{"type": "Stun"}]:
            saw_stun = True
            assert public_forecast(state).certain_damage == stored
    assert saw_stun and digest(state) == after["digest"]
    check_deathblow(state, stored, row["round"] + 1)
    # At the same public opening, end the turn without dealing any card damage.
    state = end_turn(game, game.restore(fork))
    check_deathblow(state, stored, row["round"] + 1)
    assert survival["seed"] == row["specification"]["seed"]
    state = game.restore(ReplayFork(row["specification"], tuple(history[:survival["opening_actions"]]),
                                    survival["opening_digest"]))
    assert state["round"] == survival["round"]
    peak = None
    for kind, args in survival["actions"]:
        action = next(a for a in legal_actions(state) if a.kind == kind and a.args == args)
        if state["decision"] == "combat_play" and state["enemies"][0]["intents"][0]["type"] == "DeathBlow":
            if peak is None:
                peak = incoming(state["enemies"][0])
        state = game.step(action)
    assert peak == survival["deathblow"]
    assert state["decision"] == "card_reward" and state["player"]["hp"] == survival["hp_after"]
    return {"seed": row["specification"]["seed"], "hp": initial["hp"],
            "poison": power(initial["powers"], "POISON"), "deathblow": stored,
            "alternative_from_round": survival["round"], "alternative_surviving_hp": state["player"]["hp"]}


def controlled_fight(game, seed, first_attack_round, *, ghost=False):
    game.reset(seed)
    game._request({"cmd": "set_player", "max_hp": 900, "hp": 900, "deck": ["STRIKE_SILENT"] * 10,
                   "potions": ["GHOST_IN_A_JAR"] if ghost else []})
    state = game._request({"cmd": "enter_room", "type": "monster", "encounter": "WATERFALL_GIANT_BOSS"})
    game.state = state
    ordinary = 0
    siphons = []
    policy = EncounterPolicy(RunWeights())
    for _ in range(90):
        before = public_forecast(state)
        enemy, = state["enemies"]
        turn = state["round"]
        if before.eruption_forced:
            assert before.final_phase and enemy["intents"] == [{"type": "Stun"}]
            stored = before.certain_damage
            if ghost:
                assert policy(state).kind != "use_potion" and heuristic(state).kind != "use_potion"
            state = end_turn(game, state)
            check_deathblow(state, stored, turn + 1)
            hp = state["player"]["hp"]
            if ghost:
                potion = policy(state)
                assert potion.kind == "use_potion" and heuristic(state) == potion
                state = game.step(potion)
                assert power(state.get("player_powers"), "INTANGIBLE") == 1
            state = end_turn(game, state)
            assert state.get("in_combat") is False and state["decision"] != "game_over"
            hp_lost = hp - state["player"]["hp"]
            assert hp_lost == (1 if ghost else stored)
            return {"seed": seed, "ordinary_transitions": ordinary, "siphon_at_steam": siphons,
                    "deathblow": stored, "ghost_in_a_jar": ghost, "hp_lost_to_deathblow": hp_lost,
                    "surviving_hp": state["player"]["hp"]}
        assert before.normal_damage is not None
        if turn >= first_attack_round:
            action = next((a for a in legal_actions(state) if a.kind == "play_card"), None)
            if action is not None:
                card = next(c for c in state["hand"] if c["index"] == action.args["card_index"])
                assert card["id"] == "CARD.STRIKE_SILENT"
                projected = waterfall_after_card(enemy, turn, card)
                state = game.step(action)
                assert projected.eruption_forced == public_forecast(state).final_phase
                continue
        state = end_turn(game, state)
        actual, = state["enemies"]
        assert state["round"] == turn + 1
        assert attack_hits(actual) == int(before.normal_damage > 0)
        assert incoming(actual) == before.normal_damage
        if before.normal_damage == 0:
            assert {i["type"] for i in actual["intents"]} == {"Heal", "Buff"}
            siphons.append(power(enemy.get("powers"), "STEAM_ERUPTION"))
        ordinary += 1
    raise AssertionError(f"Giant fight did not finish on seed {seed}")


def compare_openings(game, bundle):
    """Play the released challenger's boss combat path from each distinct saved opening."""
    role, settings = load_bundle(bundle)
    if role != "candidate" or "encounter_model" not in settings:
        raise ValueError("Expected the released challenger policy manifest with encounter weights")
    weights = RunWeights.load(settings["weights"])
    with gzip.open(FIXTURES.parent / "silent-a10-waterfall-openings.json.gz", "rt", encoding="utf-8") as stream:
        openings = json.load(stream)
    assert len({row["opening"] for row in openings}) == len(openings)
    gained = lost = won = exact = 0
    for row in openings:
        scorer = RunPolicy(weights, macro_seed=7103 + int(row["seed"][-4:]))
        model = EncounterModel.load(settings["encounter_model"])
        s = game.restore(ReplayFork(row["specification"], tuple(row["history"]), row["opening"]))
        assert s["round"] == 1 and s["enemies"][0]["id"] == WATERFALL_GIANT
        for _ in range(500):
            if s.get("in_combat") is False or s["decision"] == "game_over":
                break
            assert model.applies(s)
            s = game.step(model.choose(s, scorer))
        assert s["decision"] in ("card_reward", "map_select", "game_over")
        hp = s["player"]["hp"] if s["decision"] != "game_over" else 0
        won += hp > 0
        gained += hp > 0 and row["previous_hp"] == 0
        lost += hp == 0 and row["previous_hp"] > 0
        exact += hp == row["corrected_hp"]
    return {"openings": len(openings), "seeds": len({row["seed"] for row in openings}),
            "previous_wins": sum(row["previous_hp"] > 0 for row in openings), "wins": won,
            "new_wins": gained, "lost_wins": lost, "matched_recorded_ending_hp": exact}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", type=Path, help="Path to the training-enabled Sts2Headless.dll")
    parser.add_argument("--bundle", type=Path, help="Also replay the 30 boss openings with the released challenger policy.json")
    args = parser.parse_args()
    with gzip.open(FIXTURES, "rt", encoding="utf-8") as stream:
        fixtures = json.load(stream)
    survivals = {row["seed"]: row for row in json.loads(
        (FIXTURES.parent / "silent-a10-waterfall-survivals.json").read_text(encoding="utf-8"))}
    report = {}
    with TemporaryDirectory() as tmp:
        with NativeSession(ROOT, Path(tmp) / "archive", host_path=args.host, act_list="seeded") as game:
            archived = [replay_fixture(game, row, survivals[row["specification"]["seed"]]) for row in fixtures]
        controlled = []
        for run, first_attack in enumerate((8, 13, 16)):
            with NativeSession(ROOT, Path(tmp) / str(run), host_path=args.host, act_list="seeded") as game:
                controlled.append(controlled_fight(game, f"WATERFALLMECHANIC{run:04}", first_attack,
                                                   ghost=run == 2))
        if args.bundle:
            with NativeSession(ROOT, Path(tmp) / "openings", host_path=args.host, act_list="seeded") as game:
                report["comparison"] = compare_openings(game, args.bundle)
    assert {38, 53} <= {value for row in controlled for value in row["siphon_at_steam"]}
    print(json.dumps({"archived": archived, "controlled": controlled, **report}, indent=2))


if __name__ == "__main__":
    main()
