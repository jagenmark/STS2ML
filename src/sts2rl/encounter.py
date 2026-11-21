"""Estimate the value of public Silent card and potion effects over a fight."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path

from .card_effects import deck_engines
from .act2_hallways import HallwayPlans, formation_key
from .act2_action_ranker import rerank
from .act2_bosses import BossTactics
from .mecha_knight import MechaTactics
from .act3_combat import adjust_for_next_turn, adjust_potion_timing
from .enemy_forecast import attack_hits, eruption_intangible_savings, solo_waterfall_forecast
from .native import legal_actions, selected_cards
from .combat_effects import debuff_order, landed_debuffs
from .run_policy import IDENTITY, RunPolicy, _cost, _damage, _draw_count, _hits, _power, _shiv_count
from .sandpit import escape_action
from .teacher import incoming


@dataclass(frozen=True)
class Style:
    guard: float = 1.15
    horizon: float = 1.0
    potion: float = 1.0
    leader: float = 0.7
    poison: float = 1.0
    draw: float = 1.0


# Candidate policies for counterfactual fights. Deployment can choose using only opening features.
STYLES = {
    "balanced": Style(),
    "guard": Style(1.9, 1.05, 0.8, 0.6, 1.1, 1.0),
    "pressure": Style(0.65, 0.85, 1.0, 0.45, 0.9, 0.85),
    "engine": Style(1.25, 1.55, 0.8, 0.7, 1.25, 1.2),
    "leader": Style(0.95, 1.05, 0.7, 0.12, 1.0, 1.0),
    "sustain": Style(2.6, 1.4, 1.2, 0.7, 1.3, 1.1),
    "tempo": Style(0.88, 1.25, 0.52, 0.38, 1.25, 1.3),
    "frugal": Style(1.42, 0.95, 1.7, 0.75, 0.9, 0.9),
    "isolate": Style(1.28, 1.45, 0.65, 1.8, 1.0, 1.0),
    "sweep": Style(1.75, 1.15, 0.6, 2.65, 1.15, 1.05),
}


def combat_features(state):
    enemies = [e for e in state["enemies"] if e["hp"] > 0]
    player = state["player"]
    deck = player["deck"]
    n = max(1, len(deck))
    stats = [(c.get("stats") or {}) for c in deck]
    ctx = state["context"]
    features = {
        "bias": 1.0,
        "room/" + ctx["room_type"]: 1.0,
        "act/" + str(ctx["act"]): 1.0,
        "hp": player["hp"] / 70,
        "hp-frac": player["hp"] / player["max_hp"],
        "deck-size": (n - 15) / 10,
        "potions": len(player["potions"]) / 2,
        "enemy-hp": sum(e["hp"] for e in enemies) / 250,
        "enemies": len(enemies) / 3,
        "attacks": sum(c.get("type") == "Attack" for c in deck) / n,
        "powers": sum(c.get("type") == "Power" for c in deck) / 3,
        "poison": sum(s.get("poisonpower", 0) + 3 * s.get("poisonperturn", 0) for s in stats) / 15,
        "block": sum(s.get("block", 0) for s in stats) / n / 4,
        "shivs": sum(_shiv_count(c) for c in deck) / 6,
        "upgrades": sum(c.get("upgrades", 0) for c in deck) / 4,
    }
    for enemy in enemies:
        features[enemy["id"]] = 1.0
    return features


def _count_hits(enemy):
    return sum(i.get("hits", 1) for i in enemy.get("intents") or [] if i.get("damage", 0) > 0)


def _sly(card):
    return card.get("sly_this_turn") or "Sly" in (card.get("keywords") or [])


class EncounterPolicy(RunPolicy):
    def __init__(
        self, weights, *, macro_seed=0, style="balanced", mechanics=False, persistent=False, legacy_features=False,
        tender=False, potion_effects=False, draw_potions=False, intent_forecast=None, potion_timing=0, mecha_plan=None
    ):
        super().__init__(weights, macro_seed=macro_seed, legacy_features=legacy_features)
        self.style = STYLES[style] if isinstance(style, str) else style
        self.mechanics = mechanics
        self.persistent = persistent
        self.tender = tender
        self.potion_effects = potion_effects
        self.draw_potions = draw_potions
        self.intent_forecast = intent_forecast
        self.potion_timing = potion_timing
        self.mecha_tactics = MechaTactics(mecha_plan) if mecha_plan else None

    def select_cards(self, state):
        source = state.get("selection_source") or {}
        name = source.get("id", "")
        beneficial = (
            name
            in {
                "CARD.SEEKER_STRIKE",
                "CARD.NIGHTMARE",
                "CARD.HEADBUTT",
                "CARD.HAND_TRICK",
                "CARD.DECISIONS_DECISIONS",
                "POTION.LIQUID_MEMORIES",
                "POTION.TOUCH_OF_INSANITY",
                "POTION.DROPLET_OF_PRECOGNITION",
            }
            or source.get("kind") == "end_turn"
        )
        if not state.get("in_combat") or self.selection == "upgrade":
            return super().select_cards(state)

        def value(card):
            base = self.card_value(card, deck=state["player"]["deck"])
            if beneficial:
                return base
            if _sly(card):
                return 20 + base
            if card.get("type") in ("Curse", "Status", "Quest"):
                return 12.0
            return -base

        ranked = sorted(state["cards"], key=value, reverse=True)
        n = min(state["max_select"], max(state["min_select"], sum(value(c) > 0 for c in ranked)))
        return selected_cards(state, [c["index"] for c in ranked[:n]])

    def combat_scores(self, state, actions):
        w = self.style
        player = state["player"]
        hp, maxhp = player["hp"], player["max_hp"]
        powers = state.get("player_powers") or []
        enemies = [e for e in state["enemies"] if e["hp"] > 0]
        giant = None if self.legacy_features else solo_waterfall_forecast(state, enemies)
        giant_defeated = giant and (giant.final_phase or giant.eruption_forced)
        hand = {c["index"]: c for c in state["hand"]}
        potions = {p["index"]: p for p in player["potions"]}
        energy = state["energy"]
        hard = state["context"]["room_type"] in ("Boss", "Elite")
        boss = state["context"]["room_type"] == "Boss"
        hp_pool = sum(e["hp"] for e in enemies if not _power(e.get("powers"), "MINION")) or sum(
            e["hp"] for e in enemies
        )
        horizon = min(8.0, max(1.0, hp_pool / (18 + 3 * (state["context"]["act"] - 1)))) * w.horizon
        if giant_defeated:
            horizon = 2.0 if giant.eruption_forced else 1.0
        attacks = [c for c in hand.values() if c["type"] == "Attack" and c.get("can_play")]
        skills = [c for c in hand.values() if c["type"] == "Skill" and c.get("can_play")]
        strength = _power(powers, "STRENGTH")
        plating = max(0, _power(powers, "PLATING"))
        intangible = _power(powers, "INTANGIBLE") > 0
        afterimage = max(0, _power(powers, "AFTERIMAGE"))
        shiv_damage = max(0, 4 + strength + _power(powers, "ACCURACY"))
        tender = self.tender and any(p["id"] == "POWER.TENDER_POWER" for p in powers)
        count_hits = attack_hits if giant else _count_hits
        total_hit = sum(count_hits(e) for e in enemies)
        inc = total_hit if intangible else sum(incoming(e) for e in enemies)
        if giant and intangible:
            inc = min(inc, incoming(enemies[0]))
        if giant and giant.eruption_forced:
            inc = 0
        need = max(0.0, inc - player["block"] - plating)
        block_value = w.guard * (1.12 + 0.55 * (1 - hp / maxhp) + min(1.8, need / max(1, hp)))
        if need >= hp:
            block_value += 1.4
        shiv_engine, poison_engine = deck_engines(player["deck"])
        max_attack = max(
            (max((_damage(c, e) for e in enemies), default=0) for c in attacks), default=0
        )
        discard_payoff = sorted(
            (max(2.0, self.card_value(c)) for c in hand.values() if _sly(c)), reverse=True
        )
        hit_envenom = _power(powers, "ENVENOM")
        poison_triggers = 1 + max(0, _power(powers, "ACCELERANT"))
        deck = player["deck"]
        attack_density = sum(c["type"] == "Attack" for c in deck) / max(1, len(deck))

        def score(action):
            if action.kind == "end_turn":
                return 0.0
            potion = action.kind == "use_potion"
            item = (
                potions[action.args["potion_index"]] if potion else hand[action.args["card_index"]]
            )
            name = item.get("id", "").split(".")[-1]
            stats = (
                {k.lower(): v for k, v in (item.get("vars") or {}).items()}
                if potion
                else item.get("stats") or {}
            )
            cost = 0 if potion else _cost(item)
            if item.get("costs_x"):
                cost = energy
            targets = (
                [e for e in enemies if e["index"] == action.args["target_index"]]
                if "target_index" in action.args
                else enemies
            )
            random_target = item.get("target_type") == "RandomEnemy" or (
                self.mechanics and name == "BOUNCING_FLASK"
            )
            is_attack = item.get("type") == "Attack"
            offense = mitigation = setup = 0.0
            block = stats.get("calculatedblock", stats.get("block", 0))
            # The native hand exposes the resolved block preview (including Dexterity and Frail).
            if name == "FORTIFIER":
                block = 2 * player["block"]
            block += 0 if potion else afterimage
            hits = _hits(item)
            if item.get("costs_x") and name in ("SKEWER", "VOLLEY", "STARDUST"):
                hits = energy
            for e in targets:
                powers_e = e.get("powers") or []
                minion = bool(_power(powers_e, "MINION"))
                leader_weight = w.leader if minion else 1.0
                if minion and w.leader > 1 and hp_pool < 35:
                    # The encounter ends when the leader dies, including when it has surviving followers.
                    leader_weight = 0.45
                artifact = _power(powers_e, "ARTIFACT") > 0
                existing = max(0, _power(powers_e, "POISON"))
                dmg = stats.get("damage", 0) if potion else _damage(item, e) if is_attack else 0
                if (
                    is_attack
                    and item.get("costs_x")
                    and "total_damage"
                    not in next(
                        (
                            p
                            for p in item.get("damage_by_target") or []
                            if p["target_index"] == e["index"]
                        ),
                        {},
                    )
                ):
                    dmg = stats.get("damage", 0) * hits
                slippery = _power(powers_e, "SLIPPERY")
                if slippery and dmg > 0:
                    consumed = min(slippery, max(1, hits))
                    dmg = max(0.0, dmg - consumed * (dmg / max(1, hits) - 1))
                    setup += min(5.0, horizon) * consumed
                if _power(powers_e, "INTANGIBLE") and dmg > 0:
                    dmg = min(dmg, max(1, hits))
                if self.mechanics and dmg > 0:
                    cap = _power(powers_e, "HARD_TO_KILL")
                    if cap:
                        dmg = min(dmg, cap * hits)
                    if is_attack:
                        recoil = hits * _power(powers_e, "THORNS")
                        if _power(powers_e, "REFLECT"):
                            recoil += min(dmg, e.get("block", 0))
                        setup -= block_value * max(0, recoil - max(0, player["block"] - inc))
                        if dmg < e["hp"] + e.get("block", 0):
                            setup -= min(4.5, horizon * 0.9) * min(
                                3, hits * _power(powers_e, "PERSONAL_HIVE")
                            )
                poison = stats.get("poisonpower", 0) + (
                    hit_envenom * hits if is_attack and dmg > e.get("block", 0) else 0
                )
                if self.mechanics and name == "BOUNCING_FLASK":
                    # Each bounce applies the full dose. Artifact can absorb individual applications.
                    poison *= max(0, hits - _power(powers_e, "ARTIFACT"))
                    artifact = False
                if name == "BUBBLE_BUBBLE" and not existing or artifact:
                    poison = 0
                if name == "OUTBREAK":
                    dmg += (existing + poison) * poison_triggers
                hp_e = e["hp"] + e.get("block", 0)
                if giant_defeated:
                    dmg = poison = 0
                threat = incoming(e) if not intangible else count_hits(e)
                if giant and intangible:
                    threat = min(threat, incoming(e))
                if giant and giant.eruption_forced:
                    threat = 0
                poison_end = min(e["hp"], (existing + poison) * poison_triggers)
                focus = (
                    1.0 + 0.27 * (1 - e["hp"] / max(1, e["max_hp"])) if len(enemies) > 1 else 1.0
                )
                offense += leader_weight * focus * min(hp_e, dmg)
                psn_turns = min(horizon, max(1.0, (e["hp"] - dmg) / (16 + existing)))
                psn_value = max(
                    0.0, min(poison * psn_turns, poison * (poison + 1) / 2 + existing * poison)
                )
                offense += (
                    leader_weight
                    * w.poison
                    * min(max(0.0, e["hp"] - existing), poison_triggers * psn_value)
                )
                if dmg > 0 or poison > 0:
                    if dmg >= hp_e or max(0.0, dmg - e.get("block", 0)) + poison_end >= e["hp"]:
                        mitigation += threat
                        if not (giant and giant.eruption_damage is not None):
                            offense += (
                                11 if minion else (
                                    25 if len(enemies) == 1
                                    or any(_power(o.get("powers"), "MINION") for o in enemies)
                                    else 15
                                )
                            )
                weak = stats.get("weakpower", 0)
                vuln = stats.get("vulnerablepower", 0)
                if name == "EXPOSE":
                    offense += min(17, e.get("block", 0)) * (energy > cost)
                    vuln = stats.get("power", 2)
                    artifact = False
                if name == "MALAISE":
                    weak = energy + int(item.get("upgrades", 0) > 0)
                    if not artifact:
                        setup += weak * min(8.0, horizon * 1.5)
                        mitigation += min(threat, weak * count_hits(e))
                if artifact and not self.legacy_features:
                    # Haze applies Poison before Weak. Binding applies Weak
                    # before Vulnerable. One Artifact stack stops one application.
                    landed = landed_debuffs(item, debuff_order(item, stats, e, energy=energy),
                                             _power(powers_e, "ARTIFACT"), targets=len(targets))
                    weak = landed.get("weak", 0)
                    vuln = landed.get("vulnerable", 0)
                if (not artifact or not self.legacy_features) and weak > 0:
                    current = _power(powers_e, "WEAK")
                    if not current:
                        mitigation += 0.25 * threat
                    setup += min(weak, max(0.0, horizon - current)) * min(3.7, hp_pool / 35)
                if (not artifact or not self.legacy_features) and vuln > 0:
                    current = _power(powers_e, "VULNERABLE")
                    setup += min(vuln, max(0.0, horizon - current)) * (4.0 if hard else 3.0)
                    if not current and (potion or energy > cost):
                        setup += min(4.0, 0.25 * max_attack)
                drop = stats.get("strengthloss", 0) or (
                    stats.get("strengthpower", 0) if name == "SHACKLING_POTION" else 0
                )
                if drop and not artifact:
                    mitigation += min(threat, drop * count_hits(e))
                if name == "BEETLE_JUICE" and not artifact:
                    setup += 0.3 * min(4.0, horizon) * max(8, threat)
                if name == "POWDERED_DEMISE":
                    setup += stats.get("demise", 0) * min(5, horizon)
            if random_target and len(targets) > 1:
                offense /= len(targets)
                mitigation /= len(targets)
            if self.mechanics:
                if block > 0 and any(
                    _power(e.get("powers"), "IMBALANCED") and incoming(e) > 0 for e in enemies
                ):
                    if 0 < need <= block:
                        setup += 8.0
                if name == "BURST":
                    usable = [
                        c
                        for c in skills
                        if c["index"] != item["index"] and _cost(c) <= energy - cost
                    ]
                    setup += min(
                        26.0,
                        sum(
                            sorted((self.card_value(c, deck=deck) for c in usable), reverse=True)[
                                : stats.get("skills", 1)
                            ]
                        ),
                    )
                elif item.get("type") == "Skill" and _power(powers, "BURST"):
                    offense *= 1.65
                    block *= 2
                if name == "PREDATOR":
                    setup += 4.0 * min(1, horizon - 1)
                if (
                    name == "WRAITH_FORM"
                    and horizon > stats.get("intangiblepower", 1) + 2
                    and inc < 7
                ):
                    setup -= 7
            shiv = _shiv_count(item)
            if name == "BLADE_OF_INK":
                shiv = stats.get("cards", 0)
            if name == "STORM_OF_STEEL":
                shiv = len(hand) - 1
            if name == "CUNNING_POTION":
                shiv = stats.get("cards", 0)
            shiv = (
                min(shiv, max(0, 10 - len(hand) + (not potion)))
                if name != "STORM_OF_STEEL"
                else shiv
            )
            if not giant_defeated:
                shiv_hit = shiv_damage + (2 if name == "CUNNING_POTION" else 0)
                if tender:
                    offense += sum(max(0, shiv_hit - n - int(not potion)) for n in range(int(shiv)))
                else:
                    offense += shiv * shiv_hit
            draw = _draw_count(item)
            if name in ("ESCAPE_PLAN", "FINESSE", "FLASH_OF_STEEL"):
                draw = 1
            if name == "CALCULATED_GAMBLE":
                draw = max(0, len(hand) - 1 - energy)
            if name in (
                "HIDDEN_DAGGERS",
                "PREPARED",
                "SURVIVOR",
                "DAGGER_THROW",
                "ACROBATICS",
                "CALCULATED_GAMBLE",
                "STORM_OF_STEEL",
            ):
                count = (
                    len(hand)
                    if name in ("CALCULATED_GAMBLE", "STORM_OF_STEEL")
                    else stats.get("cards", 1)
                    if name in ("PREPARED", "HIDDEN_DAGGERS")
                    else 1
                )
                setup += sum(discard_payoff[:count]) * 0.85
            if name in ("DODGE_AND_ROLL", "TORIC_TOUGHNESS", "SHIP_IN_A_BOTTLE"):
                setup += min(horizon - 1, stats.get("turns", 1)) * 0.8 * block
            if name == "BLUR":
                setup += 0.75 * min(10, max(0, player["block"] + block - inc))
            if name in ("ANTICIPATE", "SPEED_POTION"):
                setup += (
                    min(need, stats.get("dexteritypower", 0) * min(energy - cost, len(skills)))
                    * block_value
                )
            else:
                setup += stats.get("dexteritypower", 0) * min(7.0, horizon * 0.95)
            if name not in ("SHACKLING_POTION", "FLEX_POTION"):
                setup += stats.get("strengthpower", 0) * min(9.0, horizon * (1 + attack_density))
            elif name == "FLEX_POTION":
                setup += stats.get("strengthpower", 0) * min(len(attacks), max(1, energy))
            setup += (
                stats.get("poisonperturn", 0)
                * len(enemies)
                * min(14.0, horizon * (horizon + 1) / 3)
            )
            setup += stats.get("afterimagepower", 0) * min(16, horizon * 2.9)
            setup += stats.get("envenompower", 0) * min(18, horizon * 2.8)
            setup += stats.get("serpentformpower", 0) * min(18, horizon * 3.1)
            setup += stats.get("thornspower", 0) * min(9, horizon * max(1.0, total_hit / 2))
            setup += (
                stats.get("speedsterpower", 0) + stats.get("dansemacabrepower", 0) * 0.65
            ) * min(7.0, horizon)
            setup += (
                stats.get("accuracypower", 0) + stats.get("phantombladespower", 0) * 0.45
            ) * min(7.0, shiv_engine * horizon / 4)
            setup += stats.get("accelerant", 0) * min(
                32.0,
                (max(0, poison_engine) + sum(_power(e.get("powers"), "POISON") for e in enemies))
                * horizon
                * 0.48,
            )
            if name in ("INFINITE_BLADES", "TOOLS_OF_THE_TRADE", "WELL_LAID_PLANS", "TRACKING"):
                setup += min(
                    20.0,
                    horizon
                    * {
                        "INFINITE_BLADES": shiv_damage,
                        "TOOLS_OF_THE_TRADE": 3.5,
                        "WELL_LAID_PLANS": 2.2,
                        "TRACKING": 3.0,
                    }[name],
                )
            if name == "BULLET_TIME":
                setup += 5.4 * max(
                    0,
                    sum(
                        min(3, _cost(c))
                        for c in hand.values()
                        if c["index"] != item["index"] and c["type"] in ("Attack", "Skill", "Power")
                    )
                    - energy
                    + cost,
                )
            if name == "FISTICUFFS":
                block += stats.get("damage", 0)
            if name in ("GHOST_IN_A_JAR", "WRAITH_FORM"):
                turns = stats.get("intangiblepower", 1)
                if not intangible:
                    mitigation += max(0, inc - total_hit)
                if giant and giant.eruption_forced:
                    setup += block_value * eruption_intangible_savings(giant, _power(powers, "INTANGIBLE"), turns)
                elif not intangible:
                    setup += max(0, min(horizon, turns) - 1) * (11 if hard else 7)
            energy_gain = (
                stats.get("energy", 0) if name not in ("DANSE_MACABRE", "RIGHT_HAND_HAND") else 0
            )
            setup += energy_gain * min(7, max(0, (len(hand) - energy + cost - 1) * 2.5))
            if self.draw_potions and potion and name in (
                "SWIFT_POTION", "CURE_ALL", "CLARITY", "GLOWWATER_POTION", "BOTTLED_POTENTIAL", "SNECKO_OIL"
            ):
                # Native potions expose Cards in vars. Card draw uses the separate card stats field.
                redraw_hand = name in ("GLOWWATER_POTION", "BOTTLED_POTENTIAL")
                room = 10 if redraw_hand else max(0, 10 - len(hand))
                draw = min(room, stats.get("cards", 0))
                if redraw_hand:
                    setup -= 2.3 * min(energy, len(attacks) + len(skills))
                if name == "SNECKO_OIL":
                    setup -= 1.6 * sum(_cost(c) == 0 for c in (*attacks, *skills))
                if draw and need > 0:
                    # Estimate the chance of an affordable defensive draw from the public deck.
                    available_energy = energy + stats.get("energy", 0)
                    defenses = sum(_cost(c) <= available_energy and (
                        (c.get("stats") or {}).get("block", 0) > 0 or
                        (c.get("stats") or {}).get("weakpower", 0) > 0) for c in deck)
                    chance = 1 - (1 - defenses / max(1, len(deck))) ** draw
                    setup += chance * min(need, 9) * block_value
            else:
                draw = min(draw, max(0, 10 - len(hand) + (not potion)))
            if self.persistent and not potion:
                # Public buffs can give a setup card immediate damage or block.
                offense += _power(powers, "SERPENT_FORM") + draw * len(enemies) * _power(
                    powers, "SPEEDSTER"
                )
                offense += draw * len(enemies) * _power(powers, "CORROSIVE_WAVE") * min(4, horizon)
                if cost >= 2:
                    block += _power(powers, "DANSE_MACABRE")
                if _power(powers, "FAN_OF_KNIVES") or name == "FAN_OF_KNIVES":
                    offense += shiv * shiv_damage * (len(enemies) - 1)
                if item.get("type") == "Skill":
                    setup -= sum(_power(e.get("powers"), "ENRAGE") for e in enemies) * min(
                        3, max(0, horizon - 1)
                    )
                if name == "REAPER_FORM":
                    setup += min(36, hp_pool * 0.28) * min(1, horizon / 4)
                elif name == "MASTER_PLANNER":
                    setup += horizon * min(4, 0.8 + len(discard_payoff))
                elif name == "FAN_OF_KNIVES" and len(enemies) > 1:
                    setup += min(16, shiv_engine * horizon * 0.6)
                elif name == "CORROSIVE_WAVE":
                    draws_left = sum(
                        _draw_count(c)
                        for c in hand.values()
                        if c["index"] != item["index"] and _cost(c) <= energy - cost
                    )
                    setup += (
                        min(4, draws_left)
                        * stats.get("corrosivewave", 0)
                        * len(enemies)
                        * min(4, horizon)
                    )
            setup += draw * w.draw * (3.8 if energy > cost else 1.1)
            if potion:
                # Convert survival, hand creation and persistent potion effects to the same units as a hit.
                setup += stats.get("platingpower", 0) * min(4, horizon) + stats.get(
                    "ritualpower", 0
                ) * min(24, horizon * horizon * 0.55)
                setup += stats.get("regenpower", 0) * min(3, max(0, maxhp - hp) / 5, horizon)
                setup += (
                    stats.get("maxhp", 0) * 2.6
                    + min(maxhp - hp, maxhp * stats.get("healpercent", 0) / 100) * block_value
                )
                setup += (
                    stats.get("radiancepower", 0) * min(5.0, horizon)
                    + stats.get("claritypower", 0) * 1.8
                )
                if name in (
                    "ATTACK_POTION",
                    "SKILL_POTION",
                    "COLORLESS_POTION",
                    "POWER_POTION",
                    "OROBIC_ACID",
                    "DISTILLED_CHAOS",
                ):
                    setup += {
                        "ATTACK_POTION": 10.0,
                        "SKILL_POTION": 8.0,
                        "COLORLESS_POTION": 8.0,
                        "POWER_POTION": min(21.0, horizon * 4.0),
                        "OROBIC_ACID": 23.0,
                        "DISTILLED_CHAOS": 19.0,
                    }[name]
                if name in ("DUPLICATOR", "GIGANTIFICATION_POTION"):
                    setup += (
                        max_attack * (2 if name == "GIGANTIFICATION_POTION" else 0.95)
                        if attacks
                        else 0
                    )
                if name == "AMBERGRIS":
                    setup += 10 + min(need, 16)
                if name in (
                    "TOUCH_OF_INSANITY",
                    "LIQUID_MEMORIES",
                    "DROPLET_OF_PRECOGNITION",
                    "BLESSING_OF_THE_FORGE",
                ):
                    setup += {
                        "TOUCH_OF_INSANITY": max((_cost(c) for c in hand.values()), default=0)
                        * 5.0,
                        "LIQUID_MEMORIES": 11.0 if state.get("discard_pile_count") else 0.0,
                        "DROPLET_OF_PRECOGNITION": min(10.0, energy * 4),
                        "BLESSING_OF_THE_FORGE": min(12.0, len(hand) * 1.6),
                    }[name]
                if name == "ENTROPIC_BREW":
                    setup += 15 if len(potions) < 2 else 6
                if name == "STABLE_SERUM":
                    setup += min(8.0, len(hand))
                if name == "GAMBLERS_BREW":
                    setup += min(10.0, sum(not c["can_play"] for c in hand.values()) * 2.2)
            raw = (
                offense
                + block_value * min(need, mitigation + block)
                + setup
                - stats.get("hploss", 0) * block_value
            )
            if potion:
                if self.potion_effects:
                    if name == "LUCKY_TONIC" and not _power(powers, "BUFFER"):
                        # Buffer prevents one loss of HP, including just one hit of a multiattack.
                        # Keep a modest value for later turns when current block already suffices.
                        first_hit = max((incoming(e) / max(1, attack_hits(e)) for e in enemies), default=0)
                        raw += block_value * max(min(need, first_hit), min(5.0, horizon - 1))
                    elif name == "FOUL_POTION":
                        own_hit = stats.get("damage", 0)
                        if intangible:
                            own_hit = min(own_hit, 1)
                        loss = max(0, own_hit - player["block"])
                        if _power(powers, "BUFFER"):
                            loss = 0
                        raw -= loss * block_value + 100 * (loss >= hp)
                    elif name == "SOLDIERS_STEW":
                        strikes = [c for c in deck if "STRIKE" in c.get("id", "") and c.get("type") == "Attack"]
                        raw += min(24, len(strikes) * max(0, horizon - 1) * 1.25)
                    elif name == "POTION_OF_DOOM":
                        for e in targets:
                            if not _power(e.get("powers"), "ARTIFACT"):
                                doom = stats.get("doompower", 0)
                                effective = max(0, e["hp"] - _power(e.get("powers"), "DOOM"))
                                raw += min(doom, effective) * (1.0 if doom >= effective else 0.45)
                reserve = (7.0 if boss else 10.5 if hard else 14.0) * w.potion
                reserve /= 1 + 0.53 * (len(potions) >= 2) + min(2.0, need / max(1, hp))
                return raw - reserve
            # Free useful effects and card draw can expose additional options before consuming energy.
            if cost == 0 and raw > 0.15:
                raw += 5.0
            return (raw - 0.12 * cost) / max(1, cost) ** 0.74

        scores = [score(a) for a in actions]
        if self.intent_forecast:
            adjust_for_next_turn(self.intent_forecast, state, actions, scores)
        if self.potion_timing:
            adjust_potion_timing(self.potion_timing, state, actions, scores)
        if self.mecha_tactics:
            self.mecha_tactics.adjust(state, actions, scores)
        return scores


class EncounterModel:
    def __init__(self, data):
        if data.get("version") != 1 or data.get("runtime_identity") != IDENTITY:
            raise ValueError("Incompatible encounter policy")
        self.default = data["default"]
        self.by_room = data.get("by_room", {})
        self.by_act = data.get("by_act", {})
        self.by_act_room = data.get("by_act_room", {})
        self.rooms = frozenset(data.get("rooms", ()))
        self.models = data.get("models", {})
        self.model_rooms = frozenset(data.get("model_rooms", ("Boss",)))
        self.model_min_act = data.get("model_min_act", 1)
        self.overrides = data.get("overrides", {})
        self.beam = data.get("beam", False)
        self.prompt_aware = data.get("prompt_aware", False)
        self.mechanics_from_act = data.get("mechanics_from_act", 4)
        self.persistent_from_act = data.get("persistent_from_act", 4)
        self.sandpit_threshold = data.get("sandpit_threshold", 0)
        self.hallways = HallwayPlans(data["act2_hallways"], STYLES) if "act2_hallways" in data else None
        self.act3_hallways = HallwayPlans(data["act3_hallways"], STYLES, act=3) if "act3_hallways" in data else None
        self.act3_intents = data.get("act3_intents")
        self.act3_potion_timing = data.get("act3_potion_timing", 0)
        self.mecha_plan = data.get("mecha_knight")
        self.action_rankers = {2: data.get("act2_action_ranker"), 3: data.get("act3_action_ranker")}
        self.action_ranker = None
        self.boss_plans = data.get("act2_boss_plans", {})
        self.boss_tactics = None
        self.rerank_fight = False
        self.search_hand = self.beam
        if type(self.sandpit_threshold) is not int or not 0 <= self.sandpit_threshold <= 4:
            raise ValueError("Sandpit threshold must be an integer from zero to four")
        if any(
            s not in STYLES
            for s in [
                self.default,
                *self.by_room.values(),
                *self.by_act.values(),
                *self.by_act_room.values(),
                *self.models,
                *self.overrides.values(),
            ]
        ):
            raise ValueError("Unknown encounter style")
        self.key = self.actor = None

    @classmethod
    def load(cls, path):
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def applies(self, state):
        return not self.rooms or state["context"]["room_type"] in self.rooms

    def choose(self, state, base_policy):
        from .turn_planning import choose_turn

        if state["decision"] != "combat_play":
            if self.boss_tactics and (choice := self.boss_tactics.curse_choice(state)) is not None:
                return choice
            if self.prompt_aware and state["decision"] in ("card_select", "card_reward"):
                from .selections import combat_selection

                return combat_selection(state, self.actor or base_policy)
            return (self.actor or base_policy)(state)
        ctx = state["context"]
        key = (ctx["act"], ctx["floor"], ctx["room_type"])
        if key != self.key or self.actor is None:
            style = self.by_act.get(
                str(ctx["act"]), self.by_room.get(ctx["room_type"], self.default)
            )
            style = self.by_act_room.get(f"{ctx['act']}/{ctx['room_type']}", style)
            if (
                self.models
                and ctx["room_type"] in self.model_rooms
                and ctx["act"] >= self.model_min_act
            ):
                x = combat_features(state)
                style = max(
                    self.models,
                    key=lambda s: sum(v * self.models[s].get(k, 0.0) for k, v in x.items()),
                )
            if ctx["room_type"] == "Boss":
                encounter = (ctx.get("boss") or {}).get("id", "")
                style = self.overrides.get(encounter, style)
            hallways = self.act3_hallways if ctx["act"] == 3 else self.hallways
            plan = hallways.select(state, combat_features) if hallways else {}
            boss_plan = self.boss_plans.get((ctx.get("boss") or {}).get("id")) if (
                ctx["act"] == 2 and ctx["room_type"] == "Boss") else None
            self.boss_tactics = BossTactics(boss_plan, state) if boss_plan else None
            if boss_plan:
                plan = boss_plan
            self.action_ranker = self.action_rankers.get(ctx["act"])
            scope = (self.action_ranker or {}).get("formations", [])
            self.rerank_fight = bool(self.action_ranker and ctx["room_type"] in ("Monster", "Elite")
                                     and (not scope or formation_key(state) in scope))
            if plan:
                style = replace(STYLES[plan.get("style", style)], **plan.get("style_weights", {}))
            self.search_hand = plan.get("search", "beam" if self.beam else "greedy") == "beam"
            self.actor = EncounterPolicy(
                base_policy.weights,
                style=style,
                mechanics=plan.get("mechanics", ctx["act"] >= self.mechanics_from_act),
                persistent=plan.get("persistent", ctx["act"] >= self.persistent_from_act),
                tender=plan.get("tender", False),
                potion_effects=plan.get("potion_effects", False),
                draw_potions=plan.get("draw_potions", False),
                mecha_plan=self.mecha_plan if ctx["act"] == 3 and ctx["room_type"] == "Elite" and formation_key(state) == "MECHA_KNIGHT" else None,
                intent_forecast=self.act3_intents if ctx["act"] == 3 and ctx["room_type"] in ("Monster", "Elite") else None,
                potion_timing=self.act3_potion_timing if ctx["act"] == 3 and ctx["room_type"] in ("Monster", "Elite") else 0,
            )
            self.key = key
        actions = legal_actions(state)
        if self.boss_tactics and self.boss_tactics.plan.get("facing"):
            scores = self.actor.combat_scores(state, actions)
            self.boss_tactics.adjust_targets(state, actions, scores)
            action = actions[max(range(len(actions)), key=scores.__getitem__)]
        else:
            search_hand = self.search_hand
            if self.actor.mecha_tactics:
                stage = self.actor.mecha_tactics.observe(state)
                if stage and stage in self.mecha_plan.get("search", {}):
                    search_hand = self.mecha_plan["search"][stage] == "beam"
            action = choose_turn(state, self.actor) if search_hand else self.actor.combat(state, actions)
        if self.rerank_fight and state["round"] <= self.action_ranker.get("max_round", float("inf")):
            action = rerank(self.action_ranker, state, actions, action, self.actor)
        if self.actor.mecha_tactics:
            action = self.actor.mecha_tactics.rank(state, actions, action, self.actor)
        if self.sandpit_threshold and ctx["room_type"] == "Boss":
            threshold = self.boss_tactics.escape_threshold(state, self.sandpit_threshold) if self.boss_tactics else self.sandpit_threshold
            action = escape_action(state, actions, action, threshold)
        if self.boss_tactics:
            self.boss_tactics.observe(action)
        return action
