"""A small, trainable action scorer for Silent runs on the pinned A10 engine.

Weights govern both combat and deck building. All features come from the
current public decision, including the native damage previews and intent.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import json
import math
from pathlib import Path

from .act1 import MacroPolicy, is_combat_choice
from .card_effects import deck_engines, hand_value, persistent_value
from .native import legal_actions, runtime_identity, selected_cards
from .teacher import incoming

VERSION = 1
IDENTITY = runtime_identity(10)


@dataclass(frozen=True)
class RunWeights:
    block: float = 1.65
    focus: float = 0.55
    poison: float = 2.8
    setup: float = 1.0
    draw: float = 2.4
    free: float = 6.0
    cost_exponent: float = 0.9
    potion_reserve: float = 12.0
    draft_threshold: float = 8.2
    draft_defense: float = 1.15

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("version") != VERSION or data.get("runtime_identity") != IDENTITY:
            raise ValueError("Incompatible run policy version or runtime")
        values = data["weights"]
        if set(values) != {f.name for f in fields(cls)} or not all(
            type(v) in (int, float) and math.isfinite(v) and v > 0 for v in values.values()
        ):
            raise ValueError("Expected finite positive weights for all run-policy parameters")
        return cls(**values)

    def checkpoint(self):
        return {"version": VERSION, "runtime_identity": IDENTITY, "weights": asdict(self)}


def _power(powers, key):
    return next((p["amount"] for p in powers or [] if p["id"] == f"POWER.{key}_POWER"), 0)


def _card_id(card):
    return card.get("id", card.get("name", "")).removeprefix("CARD.").upper().replace(" ", "_")


def _cost(card):
    # Shops expose both a gold price and a card energy cost.
    return max(0, card.get("card_cost", card.get("cost", 1)))


def _shiv_count(card):
    stats = card.get("stats") or {}
    if _card_id(card) in {"BLADE_DANCE", "CLOAK_AND_DAGGER", "UP_MY_SLEEVE"}:
        return stats.get("cards", 0)
    return stats.get("shivs", 0)


def _hits(card):
    stats = card.get("stats") or {}
    if "calculatedhits" in stats:
        return max(0, stats["calculatedhits"])
    if _card_id(card) == "DAGGER_SPRAY":
        return 2
    return max(1, stats.get("repeat", 1))


def _damage(card, enemy):
    stats = card.get("stats") or {}
    preview = next((p for p in card.get("damage_by_target") or []
                    if p["target_index"] == enemy["index"]), {})
    if "total_damage" in preview:
        return preview["total_damage"]
    return preview.get("damage", stats.get("calculateddamage", stats.get("damage", 0))) * _hits(card)


def _setup_value(card):
    stats = card.get("stats") or {}
    value = (3 * stats.get("dexteritypower", 0) + 5 * stats.get("strengthpower", 0)
             + 4.5 * stats.get("poisonperturn", 0) + 2.5 * stats.get("envenompower", 0))
    if card.get("type") == "Power":
        value += 5
    return value


def _draw_count(card):
    if _shiv_count(card):
        return 0
    if _card_id(card) == "DAGGER_THROW":
        return 1
    return (card.get("stats") or {}).get("cards", 0)


class RunPolicy:
    def __init__(self, weights, *, macro_seed=0, deck_effects=False):
        self.weights = weights
        self.fallback = MacroPolicy(macro_seed)
        self.selection = None
        self.deck_effects = deck_effects

    def __call__(self, state):
        if state.get("runtime_identity") != IDENTITY:
            raise ValueError("Run policy requires the pinned Silent A10 runtime")
        if state["decision"] == "card_select":
            return self.select_cards(state)
        self.selection = None
        actions = legal_actions(state)
        if len(actions) == 1 and state["decision"] != "rest_site":
            return actions[0]
        if is_combat_choice(state) and state["decision"] == "combat_play":
            return self.combat(state, actions)
        return self.macro(state, actions)

    def combat(self, state, actions):
        scores = self.combat_scores(state, actions)
        return actions[max(range(len(actions)), key=scores.__getitem__)]

    def combat_scores(self, state, actions):
        w = self.weights
        enemies = [e for e in state["enemies"] if e["hp"] > 0]
        hands = {c["index"]: c for c in state["hand"]}
        potions = {p["index"]: p for p in state["player"]["potions"]}
        total_in = sum(incoming(e) for e in enemies)
        player = state["player"]
        need = max(0, total_in - player["block"])
        danger = min(2.0, need / max(1, player["hp"]))
        energy = state["energy"]
        crowded = len(enemies) > 1
        dexterity = _power(state.get("player_powers"), "DEXTERITY")
        strength = _power(state.get("player_powers"), "STRENGTH")
        boss = state.get("context", {}).get("room_type") in ("Boss", "Elite")
        engines = deck_engines(player["deck"]) if self.deck_effects else None

        def score(action):
            if action.kind == "end_turn":
                return 0.0
            potion = action.kind == "use_potion"
            if potion:
                item = potions[action.args["potion_index"]]
                stats = {k.lower(): v for k, v in (item.get("vars") or {}).items()}
                cost = 0
                block = stats.get("block", 0)
                if _card_id(item).endswith("FORTIFIER"):
                    block += 2 * player["block"]
                block += min(need, stats.get("bufferpower", 0) * 9)
                draw = stats.get("cards", 0)
                setup = (3 * stats.get("strengthpower", 0) + 2 * stats.get("dexteritypower", 0)
                         + 3 * stats.get("radiancepower", 0) + 6 * stats.get("regenpower", 0))
            else:
                item = hands[action.args["card_index"]]
                stats = item.get("stats") or {}
                cost = _cost(item)
                block = stats.get("calculatedblock", stats.get("block", 0))
                if block:
                    block = max(0, block + dexterity)
                draw = _draw_count(item)
                setup = _setup_value(item)
            target = action.args.get("target_index")
            affected = [e for e in enemies if e["index"] == target] if target is not None else enemies
            offense = 0
            mitigation = 0
            for enemy in affected:
                hp = enemy["hp"] + enemy.get("block", 0)
                if potion:
                    damage = stats.get("damage", 0)
                elif target is not None or item.get("type") == "Attack":
                    damage = _damage(item, enemy)
                else:
                    damage = 0
                poison = stats.get("poisonpower", 0)
                existing_poison = _power(enemy.get("powers"), "POISON")
                if _card_id(item) == "BUBBLE_BUBBLE" and existing_poison <= 0:
                    poison = 0
                if _power(enemy.get("powers"), "ARTIFACT") > 0:
                    poison = 0
                focus = 1 + w.focus * (1 - enemy["hp"] / max(1, enemy["max_hp"])) if crowded else 1
                offense += focus * (min(hp, damage) + min(enemy["hp"], poison * w.poison))
                if (damage + min(existing_poison + poison, enemy["hp"]) >= hp
                        or existing_poison + poison >= enemy["hp"]):
                    if damage > 0 or poison > 0:
                        offense += 14
                        mitigation += incoming(enemy)
                elif stats.get("weakpower", 0) and _power(enemy.get("powers"), "WEAK") <= 0:
                    mitigation += .25 * incoming(enemy)
                    offense += 2 * min(2, stats["weakpower"])
                if stats.get("vulnerablepower", 0) and not _power(enemy.get("powers"), "VULNERABLE"):
                    offense += 1.8 * min(4, energy + 1)
            if item.get("target_type") == "RandomEnemy" and len(affected) > 1:
                offense /= len(affected)
                mitigation /= len(affected)
            shivs = min(_shiv_count(item), max(0, 11 - len(hands)))
            offense += shivs * max(0, 4 + strength)
            block += stats.get("strengthloss", 0) * sum(e.get("intends_attack", False) for e in enemies)
            utility = offense + w.block * (1 + danger) * min(need, block + mitigation)
            utility += w.setup * setup * (1.4 if boss else 1)
            utility += w.draw * draw * (1 if energy > cost else .2)
            utility += 6 * min(stats.get("energy", 0), max(0, len(hands) - 1))
            if potion:
                heal = min(player["max_hp"] - player["hp"], player["max_hp"] * stats.get("healpercent", 0) / 100)
                utility += heal * (1 + danger)
                # The value of an unused slot declines when at capacity or in immediate danger.
                utility -= w.potion_reserve / (1 + 2 * danger + .6 * boss + .3 * (len(potions) >= 2))
            elif cost == 0 and utility > 0:
                utility += w.free
            if engines is not None and not potion:
                utility += hand_value(item, state, enemies, engines, incoming, w.block * (1 + danger))
            return (utility - .08 * cost) / max(1, cost) ** w.cost_exponent

        return [score(action) for action in actions]

    def card_value(self, card, *, targets=1.5, deck=()):
        w = self.weights
        stats = card.get("stats") or {}
        damage = stats.get("calculateddamage", stats.get("damage", 0)) * _hits(card)
        if card.get("costs_x") or _card_id(card) == "SKEWER":
            damage = stats.get("damage", 0) * 2.5
        if card.get("target_type") == "AllEnemies" or "ALL enemies" in (card.get("description") or ""):
            damage *= targets
        block = stats.get("calculatedblock", stats.get("block", 0))
        offense = damage + 4 * _shiv_count(card) + w.poison * stats.get("poisonpower", 0)
        defense = (block + 2 * min(3, stats.get("weakpower", 0)) + stats.get("strengthloss", 0))
        value = offense + w.draft_defense * defense + w.setup * _setup_value(card)
        value += w.draw * _draw_count(card) + 4 * stats.get("energy", 0)
        if self.deck_effects:
            value += 1.6 * persistent_value(card, deck_engines(deck)) + 7 * stats.get("intangiblepower", 0)
        cost = _cost(card)
        return value / max(1, cost) ** (.65 * w.cost_exponent) + (2 if cost == 0 and value > 0 else 0)

    def macro(self, state, actions):
        decision = state["decision"]
        player = state["player"]
        deck = player["deck"]
        if decision in ("card_reward", "shop", "bundle_select"):
            def draft(card):
                copies = sum(_card_id(c) == _card_id(card) for c in deck)
                return self.card_value(card, deck=deck) - 1.5 * copies
            threshold = self.weights.draft_threshold + .35 * max(0, len(deck) - 12)
            if decision == "bundle_select":
                return max(actions, key=lambda a: sum(draft(c) - threshold for c in state["bundles"][a.args["bundle_index"]]["cards"]))
            if decision == "card_reward":
                cards = {c["index"]: c for c in state["cards"]}
                return max(actions, key=lambda a: draft(cards[a.args["card_index"]]) - threshold
                           if a.kind == "select_card_reward" else 0)
            cards = {c["index"]: c for c in state["cards"]}
            def buy(action):
                if action.kind == "buy_card":
                    return draft(cards[action.args["card_index"]]) - threshold
                if action.kind == "buy_relic":
                    return 5
                if action.kind == "buy_potion":
                    return 2 if not player["potions"] else .25
                return 0
            return max(actions, key=buy)
        if decision == "rest_site":
            options = {o["index"]: o["option_id"] for o in state["options"]}
            target = "HEAL" if player["hp"] / player["max_hp"] < .77 else "SMITH"
            action = next((a for a in actions if options.get(a.args.get("option_index")) == target), actions[0])
            self.selection = "upgrade" if options.get(action.args.get("option_index")) == "SMITH" else None
            return action
        return self.fallback(state)

    def select_cards(self, state):
        origin = state.get("selection_source") or {}
        upgrade = self.selection == "upgrade" and not is_combat_choice(state)
        self.selection = None
        keep = origin.get("kind") == "end_turn" or origin.get("id") == "POTION.LIQUID_MEMORIES"
        def value(card):
            if upgrade:
                return self.card_value({**card, **(card.get("after_upgrade") or {})}) - self.card_value(card)
            return (1 if keep else -1) * (self.card_value(card) - (8 if "Sly" in (card.get("keywords") or []) else 0))
        ranked = sorted(((value(c), c["index"]) for c in state["cards"]), key=lambda item: -item[0])
        count = min(state["max_select"], max(state["min_select"], sum(v > 0 for v, _ in ranked)))
        return selected_cards(state, [index for _, index in ranked[:count]])
