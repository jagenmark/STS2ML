"""Estimate the value of public Silent card and potion effects over a fight."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
import json
from math import comb
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
    cost_exponent = 0.74

    def __init__(
        self, weights, *, macro_seed=0, style="balanced", mechanics=False, persistent=False, legacy_features=False,
        tender=False, potion_effects=False, draw_potions=False, intent_forecast=None, potion_timing=0, mecha_plan=None,
        scorer_fixes=False, act2_mechanics=False, enemy_mechanics=False, card_potion_mechanics=False,
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
        self.scorer_fixes = scorer_fixes
        self.act2_mechanics = act2_mechanics
        self.enemy_mechanics = enemy_mechanics
        self.card_potion_mechanics = card_potion_mechanics

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

        def _effective_attack_dmg(card, enemy):
            raw_d = _damage(card, enemy)
            if raw_d <= 0:
                return 0.0
            ep = enemy.get("powers") or []
            h = max(1, _hits(card))
            if self.enemy_mechanics or self.card_potion_mechanics:
                slip = _power(ep, "SLIPPERY")
                if slip > 0:
                    consumed = min(slip, h)
                    raw_d = max(0.0, raw_d - consumed * (raw_d / h - 1.0))
                if _power(ep, "INTANGIBLE") > 0:
                    raw_d = min(raw_d, float(h))
            return float(raw_d)

        max_attack = max(
            (
                max(
                    (
                        _effective_attack_dmg(c, e)
                        if (self.enemy_mechanics or self.card_potion_mechanics)
                        else _damage(c, e)
                        for e in enemies
                    ),
                    default=0,
                )
                for c in attacks
            ),
            default=0,
        )
        any_slow = self.enemy_mechanics and any(_power(e.get("powers"), "SLOW") > 0 for e in enemies)
        max_slippery = (
            max((_power(e.get("powers"), "SLIPPERY") for e in enemies), default=0)
            if self.enemy_mechanics
            else 0
        )
        all_damage_capped = bool(
            enemies
            and all(
                _power(e.get("powers"), "INTANGIBLE") > 0 or _power(e.get("powers"), "SLIPPERY") >= 5
                for e in enemies
            )
        )
        gigantified = self.card_potion_mechanics and _power(powers, "GIGANTIFICATION") > 0
        duplicating = self.card_potion_mechanics and any(
            "DUPLICAT" in p.get("id", "") for p in powers
        )
        hard_or_lethal = hard or need >= hp
        playable_cards = [c for c in hand.values() if c.get("can_play")]

        def _budget_playable_block(budget_energy, exclude_idx=-1):
            avail = []
            free_blk = 0.0
            for c in playable_cards:
                if c["index"] == exclude_idx:
                    continue
                st_c = c.get("stats") or {}
                blk_c = st_c.get("calculatedblock", st_c.get("block", 0))
                if blk_c <= 0:
                    continue
                c_cost = _cost(c)
                if c_cost == 0:
                    free_blk += blk_c
                elif c_cost <= budget_energy:
                    avail.append((blk_c / c_cost, c_cost, blk_c))
            avail.sort(reverse=True)
            rem_e = budget_energy
            total_blk = free_blk
            for _, c_cost, blk_c in avail:
                if c_cost <= rem_e:
                    total_blk += blk_c
                    rem_e -= c_cost
            return total_blk

        def _playable_attack_hits(budget_energy):
            total_hits = 0
            costed = []
            hand_room = max(0, 10 - len(hand))
            for c in playable_cards:
                c_cost = energy if c.get("costs_x") else _cost(c)
                cname = c.get("id", "").split(".")[-1]
                if c.get("type") == "Attack":
                    h_c = energy if (c.get("costs_x") and cname in ("SKEWER", "VOLLEY", "STARDUST")) else _hits(c)
                    if c_cost == 0:
                        total_hits += h_c
                    elif c_cost <= budget_energy and h_c > 0:
                        costed.append((h_c / c_cost, c_cost, h_c))
                else:
                    sh_c = _shiv_count(c)
                    if sh_c > 0 and c_cost <= budget_energy:
                        eff_sh = min(sh_c, hand_room + 1)
                        if eff_sh > 0:
                            if c_cost == 0:
                                total_hits += eff_sh
                            else:
                                costed.append((eff_sh / c_cost, c_cost, eff_sh))
            costed.sort(reverse=True)
            rem_e = budget_energy
            for _, c_cost, h_c in costed:
                if c_cost <= rem_e:
                    total_hits += h_c
                    rem_e -= c_cost
            return total_hits

        def _playable_followup_cards(budget_energy, exclude_idx):
            count = 0
            costed = []
            hand_room = max(0, 10 - len(hand) + 1)
            for c in playable_cards:
                if c["index"] == exclude_idx:
                    continue
                c_cost = _cost(c)
                if c_cost == 0:
                    count += 1
                    count += min(_shiv_count(c), hand_room)
                elif c_cost <= budget_energy:
                    bonus = 1 + min(_shiv_count(c), hand_room)
                    costed.append((bonus / c_cost, c_cost, bonus))
            costed.sort(reverse=True)
            rem_e = budget_energy
            for _, c_cost, bonus in costed:
                if c_cost <= rem_e:
                    count += bonus
                    rem_e -= c_cost
            return min(6, count)

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
                illusion_minion = self.act2_mechanics and minion and bool(_power(powers_e, "ILLUSION"))
                leader_weight = 0.08 if illusion_minion else (w.leader if minion else 1.0)
                if minion and not illusion_minion and w.leader > 1 and hp_pool < 35:
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
                flask_kill_prob = None
                if self.scorer_fixes:
                    envenom_poison = 0
                    rem_art = _power(powers_e, "ARTIFACT")
                    if is_attack and hit_envenom > 0 and dmg > 0 and hits > 0:
                        rem_block = e.get("block", 0)
                        per_hit = dmg / hits
                        for _ in range(int(hits)):
                            if per_hit > rem_block:
                                rem_block = 0
                                if rem_art > 0:
                                    rem_art -= 1
                                else:
                                    envenom_poison += hit_envenom
                            else:
                                rem_block -= per_hit
                    if name == "BOUNCING_FLASK":
                        flask_item = (
                            item
                            if item.get("target_type") == "RandomEnemy"
                            else {**item, "target_type": "RandomEnemy"}
                        )
                        apps = debuff_order(flask_item, stats, e, energy=energy)
                        landed_flask = landed_debuffs(
                            flask_item, apps, rem_art, targets=len(targets)
                        )
                        poison = landed_flask.get("poison", 0)
                        # Compute exact bounce-count kill probability rather than thresholding mean poison.
                        n_bounces = len(apps)
                        dose = apps[0][1] if apps else 0
                        p_hit = 1.0 / max(1, len(targets))
                        e_buf_f = max(0, _power(powers_e, "BUFFER"))
                        e_int_f = _power(powers_e, "INTANGIBLE") > 0
                        kill_prob = 0.0
                        for k in range(n_bounces + 1):
                            landed_k = max(0, k - rem_art) * dose
                            if self.enemy_mechanics:
                                from .turn_planning import _poison_tick_loss

                                tick_dmg = _poison_tick_loss(
                                    existing + landed_k,
                                    poison_triggers - 1,
                                    e_int_f,
                                    slippery=slippery,
                                    buffer=e_buf_f,
                                )
                            else:
                                tick_dmg = (existing + landed_k) * poison_triggers
                            if tick_dmg >= e["hp"]:
                                kill_prob += comb(n_bounces, k) * (p_hit**k) * ((1.0 - p_hit) ** (n_bounces - k))
                        flask_kill_prob = kill_prob
                        if random_target and len(targets) > 1:
                            # Outer random_target block divides offense and mitigation by len(targets).
                            poison *= len(targets)
                            flask_kill_prob *= len(targets)
                        artifact = False
                    else:
                        base_poison = stats.get("poisonpower", 0)
                        if name == "BUBBLE_BUBBLE" and not existing:
                            base_poison = 0
                        elif base_poison > 0 and rem_art > 0:
                            rem_art -= 1
                            base_poison = 0
                        artifact = rem_art > 0
                        poison = base_poison + envenom_poison
                else:
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
                if self.card_potion_mechanics and name == "KNIFE_TRAP":
                    k_shivs = stats.get("calculatedshivs", 0)
                    if k_shivs > 0:
                        k_dmg = k_shivs * shiv_damage
                        if slippery:
                            k_cons = min(slippery, k_shivs)
                            k_dmg = max(0.0, k_dmg - k_cons * (shiv_damage - 1.0))
                            setup += min(5.0, horizon) * k_cons
                        if _power(powers_e, "INTANGIBLE"):
                            k_dmg = min(k_dmg, float(k_shivs))
                        dmg += k_dmg
                hp_e = e["hp"] + e.get("block", 0)
                if giant_defeated:
                    dmg = poison = 0
                threat = incoming(e) if not intangible else count_hits(e)
                if giant and intangible:
                    threat = min(threat, incoming(e))
                if giant and giant.eruption_forced:
                    threat = 0
                if self.enemy_mechanics and (slippery > 0 or _power(powers_e, "BUFFER") > 0):
                    from .turn_planning import _poison_tick_loss, _resolve_attack_hits

                    raw_hit_dmg = (
                        stats.get("damage", 0)
                        if potion
                        else (_damage(item, e) if is_attack else 0)
                    )
                    if self.card_potion_mechanics and name == "KNIFE_TRAP":
                        raw_hit_dmg += stats.get("calculatedshivs", 0) * shiv_damage
                    eff_hits = (
                        stats.get("calculatedshivs", 0)
                        if (self.card_potion_mechanics and name == "KNIFE_TRAP")
                        else max(1, hits)
                    )
                    _, _, rem_ebuf, rem_eslip, _ = _resolve_attack_hits(
                        float(raw_hit_dmg),
                        max(1, int(eff_hits)),
                        float(e.get("block", 0)),
                        max(0, _power(powers_e, "BUFFER")),
                        slippery,
                        max(0, _power(powers_e, "HARD_TO_KILL")),
                        _power(powers_e, "INTANGIBLE") > 0,
                        triggers_curl_up=False,
                        slippery_after_block=True,
                    )
                    poison_end = min(
                        e["hp"],
                        _poison_tick_loss(
                            int(round(existing + poison)),
                            poison_triggers - 1,
                            _power(powers_e, "INTANGIBLE") > 0,
                            slippery=rem_eslip,
                            buffer=rem_ebuf,
                        ),
                    )
                else:
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
                if self.enemy_mechanics:
                    plow = _power(powers_e, "PLOW")
                    if plow > 0 and (dmg > 0 or poison > 0):
                        from .turn_planning import _poison_tick_loss, _resolve_attack_hits

                        raw_hit_dmg = (
                            stats.get("damage", 0)
                            if potion
                            else (_damage(item, e) if is_attack else 0)
                        )
                        if self.card_potion_mechanics and name == "KNIFE_TRAP":
                            raw_hit_dmg += stats.get("calculatedshivs", 0) * shiv_damage
                        eff_hits = (
                            stats.get("calculatedshivs", 0)
                            if (self.card_potion_mechanics and name == "KNIFE_TRAP")
                            else max(1, hits)
                        )
                        eff_hp_dmg, _, ebuf_after, eslip_after, _ = _resolve_attack_hits(
                            float(raw_hit_dmg),
                            max(1, int(eff_hits)),
                            float(e.get("block", 0)),
                            max(0, _power(powers_e, "BUFFER")),
                            slippery,
                            max(0, _power(powers_e, "HARD_TO_KILL")),
                            _power(powers_e, "INTANGIBLE") > 0,
                            triggers_curl_up=False,
                            slippery_after_block=True,
                        )
                        plow_poison = _poison_tick_loss(
                            int(round(existing + poison)),
                            poison_triggers - 1,
                            _power(powers_e, "INTANGIBLE") > 0,
                            slippery=eslip_after,
                            buffer=ebuf_after,
                        )
                        total_plow_dmg = eff_hp_dmg + plow_poison
                        if total_plow_dmg > 0 and e["hp"] - total_plow_dmg <= plow:
                            mitigation += threat
                            setup += 14.0 + 3.0 * max(0, _power(powers_e, "STRENGTH"))
                        elif 0 < e["hp"] - plow <= 45 and eff_hp_dmg > 0:
                            offense += 0.35 * min(float(e["hp"] - plow), eff_hp_dmg)
                if self.card_potion_mechanics and not potion:
                    strangle = stats.get("stranglepower", 0)
                    if strangle > 0 and not artifact and not giant_defeated:
                        followups = _playable_followup_cards(max(0, energy - cost), item["index"])
                        if followups > 0:
                            per_card = 1.0 if (_power(powers_e, "INTANGIBLE") or slippery >= followups) else float(strangle)
                            offense += leader_weight * min(float(e["hp"]), per_card * followups)
                    debilitate = stats.get("debilitatepower", 0)
                    if debilitate > 0 and not artifact:
                        has_status = _power(powers_e, "WEAK") > 0 or _power(powers_e, "VULNERABLE") > 0
                        setup += (5.0 if has_status else 2.5) * min(float(debilitate), horizon)
                    esl = stats.get("enemystrengthloss", 0)
                    if esl > 0 and not artifact:
                        mitigation += min(threat, esl * count_hits(e))
                        setup += esl * min(4.0, horizon) - stats.get("playerstrengthloss", 0) * 2.5 * attack_density
                if flask_kill_prob is not None:
                    if flask_kill_prob > 0:
                        mitigation += threat * flask_kill_prob
                        if not (giant and giant.eruption_damage is not None) and not illusion_minion:
                            kill_bonus = (
                                11 if minion else (
                                    25 if len(enemies) == 1
                                    or any(_power(o.get("powers"), "MINION") for o in enemies)
                                    else 15
                                )
                            )
                            offense += kill_bonus * flask_kill_prob
                elif dmg > 0 or poison > 0:
                    if dmg >= hp_e or max(0.0, dmg - e.get("block", 0)) + poison_end >= e["hp"]:
                        mitigation += threat
                        if (
                            self.act2_mechanics
                            and not minion
                            and all(
                                o["index"] == e["index"] or _power(o.get("powers"), "MINION")
                                for o in enemies
                            )
                        ):
                            # Killing the sole remaining non-minion leader ends combat and cancels minion attacks.
                            mitigation += sum(
                                (incoming(o) if not intangible else count_hits(o))
                                for o in enemies
                                if o["index"] != e["index"]
                            )
                        if not (giant and giant.eruption_damage is not None) and not illusion_minion:
                            offense += (
                                11 if minion else (
                                    25 if len(enemies) == 1
                                    or any(_power(o.get("powers"), "MINION") for o in enemies)
                                    else 15
                                )
                            )
                if (
                    self.act2_mechanics
                    and is_attack
                    and not potion
                    and _power(powers_e, "CURL_UP") > 0
                    and dmg > e.get("block", 0)
                    and dmg < hp_e
                    and max_attack > dmg * 1.25
                ):
                    setup -= 0.45 * min(_power(powers_e, "CURL_UP"), max_attack - dmg)
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
                    vuln_scale = 0.15 if (self.enemy_mechanics and slippery >= 3) else 1.0
                    setup += vuln_scale * min(vuln, max(0.0, horizon - current)) * (4.0 if hard else 3.0)
                    if not current and (potion or energy > cost):
                        setup += vuln_scale * min(4.0, 0.25 * max_attack)
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
            if self.scorer_fixes and name == "HIDDEN_DAGGERS":
                actual_discards = min(max(0, len(hand) - 1), stats.get("cards", 1))
                shiv = min(shiv, max(0, 10 - max(0, len(hand) - 1 - actual_discards)))
            else:
                shiv = (
                    min(shiv, max(0, 10 - len(hand) + (not potion)))
                    if name != "STORM_OF_STEEL"
                    else shiv
                )
            if not giant_defeated:
                shiv_hit = shiv_damage + (2 if name == "CUNNING_POTION" else 0)
                if self.enemy_mechanics and max_slippery > 0 and shiv > 0:
                    stripped = min(int(shiv), max_slippery)
                    offense += stripped * 1.0 + max(0, int(shiv) - stripped) * shiv_hit
                    setup += stripped * min(5.0, horizon)
                elif tender:
                    offense += sum(max(0, shiv_hit - n - int(not potion)) for n in range(int(shiv)))
                else:
                    offense += shiv * shiv_hit
            draw = _draw_count(item)
            if name in ("ESCAPE_PLAN", "FINESSE", "FLASH_OF_STEEL"):
                draw = 1
            if name == "CALCULATED_GAMBLE":
                draw = max(0, len(hand) - 1) if self.scorer_fixes else max(0, len(hand) - 1 - energy)
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
                payoffs = (
                    sorted(
                        (
                            max(2.0, self.card_value(c))
                            for idx, c in hand.items()
                            if idx != item["index"] and _sly(c)
                        ),
                        reverse=True,
                    )
                    if self.scorer_fixes
                    else discard_payoff
                )
                setup += sum(payoffs[:count]) * 0.85
            if name in ("DODGE_AND_ROLL", "TORIC_TOUGHNESS", "SHIP_IN_A_BOTTLE"):
                setup += min(horizon - 1, stats.get("turns", 1)) * 0.8 * block
            if name == "BLUR":
                setup += 0.75 * min(10, max(0, player["block"] + block - inc))
            if name in ("ANTICIPATE", "SPEED_POTION"):
                if self.card_potion_mechanics and name == "SPEED_POTION" and hard_or_lethal:
                    free_blk_cards = 0
                    costed_blk_costs = []
                    for c in playable_cards:
                        st_c = c.get("stats") or {}
                        if st_c.get("block", 0) > 0 or st_c.get("calculatedblock", 0) > 0:
                            cc = _cost(c)
                            if cc == 0:
                                free_blk_cards += 1
                            elif cc <= energy:
                                costed_blk_costs.append(cc)
                    costed_blk_costs.sort()
                    rem_e = energy
                    affordable_blk_cards = free_blk_cards
                    for cc in costed_blk_costs:
                        if cc <= rem_e:
                            affordable_blk_cards += 1
                            rem_e -= cc
                    setup += min(need, stats.get("dexteritypower", 0) * affordable_blk_cards) * block_value
                else:
                    setup += (
                        min(need, stats.get("dexteritypower", 0) * min(energy - cost, len(skills)))
                        * block_value
                    )
            else:
                setup += stats.get("dexteritypower", 0) * min(7.0, horizon * 0.95)
            if name not in ("SHACKLING_POTION", "FLEX_POTION"):
                setup += stats.get("strengthpower", 0) * min(9.0, horizon * (1 + attack_density))
            elif name == "FLEX_POTION":
                if self.card_potion_mechanics and hard_or_lethal:
                    flex_hits = 0 if all_damage_capped else _playable_attack_hits(energy)
                    setup += stats.get("strengthpower", 0) * flex_hits
                elif self.card_potion_mechanics and all_damage_capped:
                    setup += 0.0
                else:
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
            elif self.scorer_fixes and not potion and name == "CALCULATED_GAMBLE":
                draw = min(draw, 10)
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
            if self.enemy_mechanics and not potion and item.get("type") == "Skill":
                # Vital Spark boosts enemy attack base damage by +amount per hit whenever a Skill is played this turn.
                vs_extra = 0.0
                for e in enemies:
                    vs = _power(e.get("powers"), "VITAL_SPARK")
                    if vs > 0 and incoming(e) > 0 and not intangible:
                        hits_e = max(1, count_hits(e))
                        weak_mult = 0.75 if _power(e.get("powers"), "WEAK") > 0 else 1.0
                        vs_extra += hits_e * vs * weak_mult
                if vs_extra > 0:
                    setup -= block_value * vs_extra
            if self.card_potion_mechanics and not potion:
                if name == "SHADOWMELD":
                    playable_blk = _budget_playable_block(max(0, energy - cost), exclude_idx=item["index"])
                    shadow_extra = min(max(0.0, need), playable_blk)
                    block += shadow_extra
                    if shadow_extra >= 7.0:
                        setup += 4.0
                elif name == "PANACHE":
                    setup += stats.get("panachedamage", 0) * len(enemies) * min(3.5, horizon * 0.45)
                elif name == "LETHALITY":
                    setup += (stats.get("lethalitypower", 0) / 100.0) * 9.0 * min(
                        5.0, horizon * (0.6 + attack_density)
                    )
                elif name == "ENLIGHTENMENT":
                    setup += 5.0 * sum(
                        max(0, _cost(c) - 1)
                        for c in hand.values()
                        if c["index"] != item["index"] and c.get("type") in ("Attack", "Skill", "Power")
                    )
                elif name == "NIGHTMARE" and horizon >= 3.0 and need < hp:
                    best_copy = max(
                        (
                            self.card_value(c, deck=deck)
                            for c in hand.values()
                            if c["index"] != item["index"]
                            and c.get("type") in ("Attack", "Skill", "Power")
                        ),
                        default=0.0,
                    )
                    setup += min(24.0, 2.0 * best_copy)
                elif name == "FINISHER":
                    if (
                        any(
                            c["index"] != item["index"] and _cost(c) <= energy - cost
                            for c in attacks
                        )
                        and all(_damage(item, e) < e["hp"] + e.get("block", 0) for e in targets)
                    ):
                        setup -= 2.5
                elif name == "FLECHETTES" and skills and stats.get("calculatedhits", 0) > 0:
                    setup += 3.5
                elif name == "PRECISE_CUT":
                    other_playable = sum(
                        1
                        for c in playable_cards
                        if c["index"] != item["index"]
                        and _cost(c) <= energy
                        and _draw_count(c) == 0
                        and _shiv_count(c) == 0
                        and (
                            c.get("type") in ("Attack", "Power")
                            or need > 0
                            or (c.get("stats") or {}).get("poisonpower", 0) > 0
                            or (c.get("stats") or {}).get("weakpower", 0) > 0
                            or (c.get("stats") or {}).get("vulnerablepower", 0) > 0
                        )
                    )
                    if other_playable > 0 and offense > 3.5:
                        setup -= min(2.5, 1.25 * other_playable)
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
                    if self.card_potion_mechanics and name == "DUPLICATOR" and hard_or_lethal:
                        best_dup = 0.0
                        for c in playable_cards:
                            st_c = c.get("stats") or {}
                            c_val = 0.0
                            if c.get("type") == "Attack":
                                c_val = max((_effective_attack_dmg(c, e) for e in enemies), default=0.0)
                            c_blk = st_c.get("calculatedblock", st_c.get("block", 0))
                            if c_blk > 0:
                                c_val += block_value * min(need, c_blk)
                            c_psn = st_c.get("poisonpower", 0)
                            if c_psn > 0:
                                c_val += c_psn * min(4.0, horizon)
                            c_shv = _shiv_count(c)
                            if c_shv > 0:
                                c_val += c_shv * shiv_damage
                            if c.get("type") == "Power" or c_val == 0.0:
                                c_val = max(c_val, min(20.0, self.card_value(c, deck=deck)))
                            if c_val > best_dup:
                                best_dup = c_val
                        setup += best_dup * 0.95
                    else:
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
                net = raw - reserve
                if (
                    self.card_potion_mechanics
                    and hard_or_lethal
                    and net > 1.5
                    and name in ("FLEX_POTION", "DUPLICATOR", "SPEED_POTION")
                ):
                    # Play force-multiplier potions before 0-cost cards (which receive a +5.0 free bonus).
                    net += 6.5
                return net
            # Free useful effects and card draw can expose additional options before consuming energy.
            if self.enemy_mechanics and any_slow and not is_attack and raw > 0.15:
                if any(_cost(a) <= energy - cost and max((_damage(a, e) for e in enemies), default=0) >= 8 for a in attacks):
                    raw += min(2.5, 0.10 * max_attack)
            if cost == 0 and raw > 0.15:
                skip_free = (
                    (
                        gigantified
                        and is_attack
                        and max((_effective_attack_dmg(item, e) for e in enemies), default=0.0)
                        < max_attack * 0.65
                    )
                    or (duplicating and raw < 10.0)
                )
                if not skip_free:
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
        self.potion_effects_from_act = data.get("potion_effects_from_act", 4)
        self.draw_potions_from_act = data.get("draw_potions_from_act", 4)
        self.scorer_fixes = data.get("scorer_fixes", False)
        self.act2_mechanics = data.get("act2_mechanics", False)
        self.enemy_mechanics = data.get("enemy_mechanics", False)
        self.card_potion_mechanics = data.get("card_potion_mechanics", False)
        self.survival_search = data.get("survival_search", False)
        self.survival_beam = data.get("survival_beam", False)
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
    def from_data(cls, data):
        return cls(deepcopy(data))

    @classmethod
    def load(cls, path):
        return cls.from_data(json.loads(Path(path).read_text(encoding="utf-8")))

    def applies(self, state):
        return not self.rooms or state["context"]["room_type"] in self.rooms

    def prepare(self, state, base_policy):
        """Initialize fight-scoped encounter actor and boss tactics on a combat_play state."""
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
                potion_effects=plan.get("potion_effects", ctx["act"] >= self.potion_effects_from_act),
                draw_potions=plan.get("draw_potions", ctx["act"] >= self.draw_potions_from_act),
                mecha_plan=self.mecha_plan if ctx["act"] == 3 and ctx["room_type"] == "Elite" and formation_key(state) == "MECHA_KNIGHT" else None,
                intent_forecast=self.act3_intents if ctx["act"] == 3 and ctx["room_type"] in ("Monster", "Elite") else None,
                potion_timing=self.act3_potion_timing if ctx["act"] == 3 and ctx["room_type"] in ("Monster", "Elite") else 0,
                scorer_fixes=plan.get("scorer_fixes", self.scorer_fixes),
                act2_mechanics=plan.get("act2_mechanics", self.act2_mechanics),
                enemy_mechanics=plan.get("enemy_mechanics", self.enemy_mechanics),
                card_potion_mechanics=plan.get("card_potion_mechanics", self.card_potion_mechanics),
            )
            self.key = key

    def choose(self, state, base_policy):
        from .turn_planning import choose_turn, choose_turn_survival

        if state["decision"] != "combat_play":
            if self.boss_tactics and (choice := self.boss_tactics.curse_choice(state)) is not None:
                return choice
            if self.prompt_aware and state["decision"] in ("card_select", "card_reward"):
                from .selections import combat_selection

                return combat_selection(state, self.actor or base_policy)
            return (self.actor or base_policy)(state)
        ctx = state["context"]
        self.prepare(state, base_policy)
        actions = legal_actions(state)
        facing_plan = bool(self.boss_tactics and self.boss_tactics.plan.get("facing"))
        actor_act2_mech = bool(getattr(self.actor, "act2_mechanics", False))
        facing = self.boss_tactics.facing if (facing_plan and actor_act2_mech) else None
        focus_adjust = (
            (lambda sc: self.boss_tactics.adjust_focus(state, actions, sc))
            if (facing_plan and actor_act2_mech)
            else None
        )
        if facing_plan and not (actor_act2_mech and self.search_hand and self.survival_beam):
            scores = self.actor.combat_scores(state, actions)
            self.boss_tactics.adjust_targets(state, actions, scores)
            action = actions[max(range(len(actions)), key=scores.__getitem__)]
        else:
            search_hand = self.search_hand
            if self.actor.mecha_tactics:
                stage = self.actor.mecha_tactics.observe(state)
                if stage and stage in self.mecha_plan.get("search", {}):
                    search_hand = self.mecha_plan["search"][stage] == "beam"
            action = (
                choose_turn(
                    state,
                    self.actor,
                    survival_priority=self.survival_beam,
                    facing=facing,
                    score_adjust=focus_adjust,
                )
                if search_hand
                else self.actor.combat(state, actions)
            )
        if self.rerank_fight and state["round"] <= self.action_ranker.get("max_round", float("inf")):
            action = rerank(self.action_ranker, state, actions, action, self.actor)
        if self.actor.mecha_tactics:
            action = self.actor.mecha_tactics.rank(state, actions, action, self.actor)
        if self.survival_search and (actor_act2_mech or not facing_plan):
            action = choose_turn_survival(
                state,
                self.actor,
                action,
                facing=facing,
                score_adjust=focus_adjust,
            )
        if self.sandpit_threshold and ctx["room_type"] == "Boss":
            threshold = self.boss_tactics.escape_threshold(state, self.sandpit_threshold) if self.boss_tactics else self.sandpit_threshold
            action = escape_action(state, actions, action, threshold)
        if self.boss_tactics:
            self.boss_tactics.observe(action)
        return action
