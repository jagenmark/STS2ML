import runpy
from pathlib import Path

import pytest

from sts2rl.encounter import EncounterPolicy
from sts2rl.enemy_forecast import WATERFALL_GIANT, attack_hits, waterfall_after_card, waterfall_forecast
from sts2rl.native import legal_actions
from sts2rl.run_policy import RunPolicy, RunWeights
from sts2rl.tactical_student import action_examples
from sts2rl.teacher import ARTIFACT_CONTINUATION, heuristic, heuristic_score, incoming
from sts2rl.turn_planning import choose_turn
from test_teacher_status import hand


def giant(hp=80, steam=38, poison=0, *, intents=("Attack", "Buff"), max_hp=250, block=0):
    return {"index": 0, "id": WATERFALL_GIANT, "hp": hp, "max_hp": max_hp, "block": block,
            "intents": [{"type": kind, **({"damage": 11} if kind == "Attack" else {})} for kind in intents],
            "powers": [{"id": f"POWER.{key}_POWER", "amount": amount}
                       for key, amount in (("STEAM_ERUPTION", steam), ("POISON", poison)) if amount]}


@pytest.mark.parametrize(("hp", "poison", "steam"), [(7, 13, 38), (9, 20, 53)])
def test_same_steam_has_different_outcomes_when_poison_is_lethal(hp, poison, steam):
    surviving = waterfall_forecast(giant(steam=steam), 8)
    assert (surviving.normal_damage, surviving.eruption_damage, surviving.certain_damage) == (0, steam, None)
    lethal = waterfall_forecast(giant(hp, steam, poison, block=50), 8)
    assert lethal.eruption_forced and lethal.certain_damage == steam
    assert not waterfall_forecast(giant(hp, steam, hp - 1), 8).eruption_forced


def test_direct_damage_accelerant_and_an_unarmed_opening():
    enemy = giant(8, poison=4)
    assert not waterfall_forecast(enemy, 8, accelerant=1).eruption_forced  # 4 then 3
    assert waterfall_forecast(enemy, 8, accelerant=1, hp_loss=1).certain_damage == 38
    assert waterfall_forecast(enemy, 8, hp_loss=4).eruption_forced
    cold = giant(8, 0, intents=("Buff",))
    assert waterfall_forecast(cold, 1).certain_damage == 16
    assert waterfall_forecast(cold, 1, added_poison=8).certain_damage is None
    assert waterfall_forecast({**enemy, "id": "MONSTER.OTHER"}, 8) is None


def test_windup_is_distinct_from_ordinary_stun_and_final_preview():
    stun = giant(intents=("Stun",))
    assert not waterfall_forecast(stun, 4).eruption_forced
    windup = waterfall_forecast({**stun, "max_hp": 999_999_999}, 8)
    assert windup.final_phase and windup.certain_damage == 38
    final = giant(999_999_999, 0, max_hp=999_999_999)
    final["intents"] = [{"type": "DeathBlow", "damage": 28}]  # 38 base with Weak
    forecast = waterfall_forecast(final, 9)
    assert forecast.final_phase and forecast.certain_damage is None
    assert (attack_hits(final), incoming(final)) == (1, 28)
    assert attack_hits({"intents": [{"type": "DeathBlow", "damage": 0}]}) == 1
    assert attack_hits({"intents": [{"type": "Attack", "hits": 3}, {"type": "Buff"}]}) == 3
    assert attack_hits({"intents": None}) == 0
    assert waterfall_forecast(giant(steam=41, intents=("Heal", "Buff")), 9).normal_damage == 28
    assert waterfall_forecast(giant(steam=40), 3).normal_damage is None
    assert waterfall_forecast(giant(steam=38, intents=("Heal", "Buff")), 8).normal_damage is None


def test_projection_uses_target_damage_block_and_artifact():
    enemy = giant(hp=5, block=2)
    strike = {"id": "CARD.STRIKE_SILENT", "stats": {"damage": 20},
              "damage_by_target": [{"target_index": 0, "damage": 6}]}
    assert not waterfall_after_card(enemy, 8, strike).eruption_forced
    assert waterfall_after_card({**enemy, "hp": 4}, 8, strike).eruption_forced
    assert not waterfall_after_card(enemy, 8, {**strike, "damage_by_target": []}).eruption_forced
    poison = {"id": "CARD.DEADLY_POISON", "stats": {"poisonpower": 5}, "target_type": "AnyEnemy"}
    assert waterfall_after_card(enemy, 8, poison).eruption_forced
    enemy["powers"].append({"id": "POWER.ARTIFACT_POWER", "amount": 1})
    assert not waterfall_after_card(enemy, 8, poison).eruption_forced


def test_teacher_knows_the_armed_giant_survives_a_knockout_and_preserves_v4():
    obs = hand(("CARD.STRIKE_SILENT", "AnyEnemy", {"damage": 6}),
               ("CARD.DEADLY_POISON", "AnyEnemy", {"poisonpower": 5}))
    obs["enemies"] = [giant(hp=6)]
    obs["hand"][0].update(type="Attack", damage_by_target=[{"target_index": 0, "damage": 6}])
    strike, poison, _ = legal_actions(obs)
    assert heuristic_score(obs, strike) == 6 + 11
    assert heuristic_score(obs, strike, version=ARTIFACT_CONTINUATION) == 6 + 11 + 10
    obs["enemies"] = [giant(hp=6, poison=6)]
    assert [heuristic_score(obs, a) for a in (strike, poison)] == [0, 0]


def test_student_can_discriminate_a_knockout_card_and_ignores_an_obsolete_static_rule():
    study = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/act1-pattern-students.py"))
    obs = hand(("CARD.STRIKE_SILENT", "AnyEnemy", {"damage": 6}),
               ("CARD.DEFEND_SILENT", "Self", {"block": 5}))
    obs["hand"][0].update(type="Attack", damage_by_target=[{"target_index": 0, "damage": 6}])
    obs["enemies"] = [giant(hp=6)]
    obs["round"] = 8
    rule = study["permitted_prediction"]
    obsolete = {(WATERFALL_GIANT, "Attack+Buff", 0, 0)}
    assert rule(obs["enemies"][0], obs, {}, obsolete) is None
    _, rows = study["inputs"](obs, RunPolicy(RunWeights()), {})
    features = {r["token"]: r["x"][-9:] for r in rows}
    assert features["STRIKE_SILENT"][1:6] == [38/30, 1/5, 1.0, 38/30, 1/5]
    assert features["DEFEND_SILENT"][:6] == [0] * 6
    assert features["end_turn"][-3:] == [1.0, 0.0, 38/30]
    obs["enemies"] = [giant(hp=6, poison=6)]
    assert rule(obs["enemies"][0], obs, {}, set())[2:] == (1, 38)
    _, current = action_examples(obs, RunPolicy(RunWeights()))
    _, legacy = action_examples(obs, RunPolicy(RunWeights(), legacy_features=True))
    assert current[0]["x"][4] == 0 and legacy[0]["x"][4] == 11/20


@pytest.mark.parametrize("actor", [RunPolicy, EncounterPolicy])
def test_policy_saves_a_one_turn_intangible_potion_for_the_actual_deathblow(actor):
    obs = hand(("CARD.STRIKE_SILENT", "AnyEnemy", {"damage": 6}),
               ("CARD.DEFEND_SILENT", "Self", {"block": 5}))
    obs.update(round=8, energy=1)
    obs["context"]["room_type"] = "Boss"
    obs["hand"][0]["type"] = "Attack"
    obs["player"].update(hp=5, block=0, potions=[
        {"id": "POTION.GHOST_IN_A_JAR", "index": 0, "target_type": "Self", "can_use": True,
         "vars": {"IntangiblePower": 1}}])
    obs["enemies"] = [giant(hp=7, poison=13)]
    policy = actor(RunWeights())
    assert policy(obs).kind != "use_potion"
    assert choose_turn(obs, policy).kind != "use_potion"
    assert heuristic(obs).kind != "use_potion"
    obs["enemies"] = [giant(999_999_999, 0, max_hp=999_999_999)]
    obs["enemies"][0]["intents"] = [{"type": "DeathBlow", "damage": 38}]
    for pick in (policy(obs), choose_turn(obs, policy), heuristic(obs)):
        assert pick.kind == "use_potion"
    strike, defend, potion, _ = policy.combat_scores(obs, legal_actions(obs))
    assert potion > defend > strike


def test_deck_effects_count_wraith_form_once_and_use_the_current_deathblow():
    obs = hand(("CARD.WRAITH_FORM", "Self", {"intangiblepower": 2, "wraithformpower": 1}),
               ("CARD.DARK_SHACKLES", "AnyEnemy", {"strengthloss": 9}))
    obs["hand"][0].update(type="Power", cost=3)
    obs["context"]["room_type"] = "Boss"
    obs["player"].update(hp=24, block=0)
    plain = RunPolicy(RunWeights())
    augmented = RunPolicy(RunWeights(), deck_effects=True)
    for enemy in (giant(hp=7, poison=13), giant(999_999_999, max_hp=999_999_999, intents=("Stun",)),
                  giant(999_999_999, steam=0, max_hp=999_999_999, intents=("DeathBlow",))):
        windup = enemy["intents"][0]["type"] != "DeathBlow"
        if not windup:
            enemy["intents"][0]["damage"] = 38
        enemy["intends_attack"] = enemy["intents"][0]["type"] != "Stun"
        obs["enemies"] = [enemy]
        actions = legal_actions(obs)
        wraith, shackles, _ = augmented.combat_scores(obs, actions)
        reference = plain.combat_scores(obs, actions)
        assert wraith == pytest.approx(reference[0])
        assert shackles == pytest.approx(0 if windup else reference[1])
        if not windup:
            assert shackles > 0
