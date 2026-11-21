"""Public deck, event and camp choices fitted to paired native continuations."""

from __future__ import annotations

import json
from pathlib import Path
import re

from .native import legal_actions
from .encounter_draft import matchup_features
from .offer_policy import OfferModel, draft_prior, draft_prior_parts, offer_features, offer_type
from .run_policy import IDENTITY, INFERENCE_IDENTITY, _card_id, _cost, _hits, _shiv_count


def strategy_kind(state):
    if state.get("in_combat"):
        return None
    decision = state["decision"]
    if decision == "event_choice":
        if state.get("event_name") == "Neow":
            return "neow"
        if state["context"]["act"] > 1 and state["context"]["floor"] == 1:
            return "ancient"
        return "event"
    return {"card_reward": "card", "rest_site": "camp", "shop": "shop"}.get(decision)


def _deck_strength(deck):
    attacks = block = poison = shivs = discards = sly = 0
    for card in deck:
        stats = card.get("stats") or {}
        attacks += card.get("type") == "Attack"
        block += bool(stats.get("block"))
        poison += bool(stats.get("poisonpower") or stats.get("poisonperturn"))
        shivs += bool(_shiv_count(card))
        discards += "Discard" in (card.get("description") or "")
        sly += "Sly" in (card.get("keywords") or [])
    return attacks, block, poison, shivs, discards, sly


def _event_terms(option, hp, maximum, gold):
    desc = (option.get("description") or "").lower()
    var = {
        k.lower(): v for k, v in (option.get("vars") or {}).items() if isinstance(v, (int, float))
    }
    text = re.sub(r"\{(\w+)\}", lambda m: str(var.get(m[1], m[0])), desc)

    def amount(pattern):
        match = re.search(pattern, text)
        return float(match[1]) if match else 0.0

    heal = min(maximum - hp, amount(r"heal (\d+) hp"))
    hp_cost = amount(r"lose (\d+) hp")
    max_hp = (
        amount(r"(?:gain|raise your max hp by) (\d+)(?: max hp|\b)") if "max hp" in text else 0.0
    )
    return {
        "heal": heal / 12,
        "hurt": hp_cost / 12,
        "danger": float(hp_cost > 0 and hp_cost >= hp),
        "maxhp": (max_hp - amount(r"lose (\d+) max hp")) / 8,
        "gold": (
            amount(r"gain (\d+) gold")
            - amount(r"(?:lose|pay) (\d+) gold")
            - (gold if "lose all" in text and "gold" in text else 0)
        )
        / 75,
        "curse": float("curse" in desc or "guilty" in desc),
        "relic": float("relic" in desc and ("obtain" in desc or "gain" in desc)),
        "upgrade": float("upgrade" in desc),
        "transform": float("transform" in desc),
        "potion": float("potion" in desc and ("procure" in desc or "gain" in desc)),
        "permanent_energy": float(
            ("each turn" in desc or "every turn" in desc) and "energy" in desc
        ),
    }


def strategy_arms(state, policy, opening=None, *, matchups=False, group_probability=None):
    kind = strategy_kind(state)
    if not kind or state.get("runtime_identity") != INFERENCE_IDENTITY.get():
        raise ValueError("Expected a public Silent A10 strategy decision")
    player = state["player"]
    deck = player["deck"]
    hp = player["hp"] / max(1, player["max_hp"])
    act = state["context"]["act"]
    floor = state["context"]["floor"]
    boss = (state["context"].get("boss") or {}).get("id", "")
    attacks, blocks, poison, shivs, discards, sly = _deck_strength(deck)
    arms = []
    for action in legal_actions(state):
        features = {}
        prior = 0.0
        if kind in ("neow", "event", "ancient"):
            option = next(
                (o for o in state["options"] if o["index"] == action.args.get("option_index")), {}
            )
            key = option.get("text_key") or option.get("title", action.kind)
            term = _event_terms(option, player["hp"], player["max_hp"], player["gold"])
            features = {"event:" + key: 1.0, **{"event/" + k: v for k, v in term.items() if v}}
            prior = (
                2.3 * term["heal"]
                - 2.5 * term["hurt"]
                - 35 * term["danger"]
                + 1.8 * term["maxhp"]
                + term["gold"]
                - 2 * term["curse"]
                + 2 * term["relic"]
                + term["upgrade"]
                + term["permanent_energy"]
            )
            if kind == "ancient":
                words = (option.get("description") or "").lower()
                variables = {
                    k.lower(): v
                    for k, v in (option.get("vars") or {}).items()
                    if isinstance(v, (float, int))
                }
                energy = "energy" in words and ("turn" in words or "each combat" in words)
                ongoing_draw = "draw" in words and (
                    "each turn" in words or "start of your turn" in words
                )
                upgrades = (
                    variables.get("cards", 1) if "upgrade" in words and "pickup" in words else 0
                )
                strength = variables.get("strengthpower", 0) if "turn" in words else 0
                carry = {
                    "energy": float(energy),
                    "draw": float(ongoing_draw),
                    "upgrades": upgrades / 3,
                    "strength": strength,
                    "turn-block": float("block" in words and "turn" in words),
                    "potion-slots": variables.get("potionslots", 0),
                    "heal-need": (1 - hp) * term["heal"],
                }
                features.update({"ancient/" + k: v for k, v in carry.items() if v})
                prior += (
                    4.7 * energy
                    + 2.8 * ongoing_draw
                    + 1.1 * upgrades
                    + 2.0 * strength
                    + 0.8 * carry["potion-slots"]
                )
            if kind == "neow" and opening:
                prior = opening.predict(*offer_features(state, action, policy))
            if key in ("TRIAL.confirm.ABANDON", "TRIAL.pages.REJECT.options.DOUBLE_DOWN"):
                prior = -1000.0
        elif kind == "camp":
            option = next(
                (o for o in state["options"] if o["index"] == action.args.get("option_index")), {}
            )
            name = option.get("option_id", action.kind)
            features = {"camp:" + name: 1.0}
            if name == "HEAL":
                recovered = min(0.30, 1 - hp)
                features.update(
                    {
                        "heal:amount": recovered / 0.30,
                        "heal:missing": 1 - hp,
                        "heal:critical": float(hp < 0.38),
                        "heal:near-boss": floor >= 13,
                        "heal:act": (act - 1) / 2,
                    }
                )
                prior = 12 * (0.72 - hp)
        elif kind in ("card", "shop"):
            card = None
            if action.kind in ("select_card_reward", "buy_card"):
                card = next(c for c in state["cards"] if c["index"] == action.args["card_index"])
            if card:
                cid = _card_id(card)
                stats = card.get("stats") or {}
                copies = sum(_card_id(c) == cid for c in deck)
                value = policy.card_value(card, deck=deck)
                cost = _cost(card)
                attack = stats.get("calculateddamage", stats.get("damage", 0)) * _hits(card) / 10
                block = stats.get("calculatedblock", stats.get("block", 0)) / 8
                psn = (stats.get("poisonpower", 0) + 3 * stats.get("poisonperturn", 0)) / 5
                shiv = _shiv_count(card) / 3
                scaling = float(card.get("type") == "Power")
                features = {
                    "card:" + cid: 1.0,
                    "type:" + card.get("type", ""): 1.0,
                    "card:take": 1.0,
                    "take:deck-size": (len(deck) - 14) / 6,
                    "take:copies": copies,
                    "take:cost": cost / 2,
                    "take:value": value / 10,
                    "take:attack": attack,
                    "take:low-offense": attack * (8 - attacks) / 4,
                    "take:block": block,
                    "take:low-defense": block * (7 - blocks) / 3,
                    "take:poison": psn,
                    "take:poison-deck": psn * min(3, poison) / 2,
                    "take:shiv": shiv,
                    "take:shiv-deck": shiv * min(3, shivs) / 2,
                    "take:sly-deck": ("Sly" in (card.get("keywords") or [])) * min(4, discards) / 2,
                    "take:discard-deck": ("Discard" in (card.get("description") or ""))
                    * min(4, sly)
                    / 2,
                    "take:power-late": scaling * (act - 1),
                    "take:power-boss": scaling * floor / 16,
                    "take:aoe": float("ALL enemies" in (card.get("description") or "")),
                    "boss/" + boss + "/attack": attack,
                    "boss/" + boss + "/block": block,
                }
                if matchups and kind == "card":
                    features.update(matchup_features(card, deck, state["context"], group_probability))
                prior = draft_prior(value, copies, len(deck), policy.weights.draft_threshold, 0.35)
                if kind == "card" and opening and offer_type(state):
                    prior = opening.predict(*offer_features(state, action, policy))
            elif kind == "card" and opening and offer_type(state):
                prior = opening.predict(*offer_features(state, action, policy))
            if kind == "shop" and action.kind != "leave_room":
                features["shop:" + action.kind] = 1.0
                if action.kind == "remove_card":
                    curses = sum(
                        c.get("type") == "Curse" and _card_id(c) != "ASCENDERS_BANE" for c in deck
                    )
                    features["shop:removable-curses"] = curses
                    features["shop:price"] = state["card_removal_cost"] / 100
                    prior = 4.5 if curses else 0.7
                    arms.append((action, prior, features))
                    continue
                item = card or next(
                    x
                    for x in state["relics" if action.kind == "buy_relic" else "potions"]
                    if x["index"] == next(iter(action.args.values()))
                )
                price = item["cost"]
                features["shop:price"] = price / 100
                features["shop:balance"] = price / max(1, player["gold"])
                if not card:
                    features["shop/item:" + item.get("name", "")] = 1.0
                    prior = (
                        3.0
                        if action.kind == "buy_relic"
                        else (1.5 if not player["potions"] else 0.4)
                    )
        arms.append((action, prior, features))
    return arms


class StrategyModel(OfferModel):
    def __init__(self, weights, kinds, strength=1.0, strengths_by_kind=None, card_offsets=None):
        super().__init__(weights)
        self.kinds = frozenset(kinds)
        self.strength = strength
        self.strengths_by_kind = strengths_by_kind or {}
        self.card_offsets = card_offsets or {}
        self.uses_matchups = any(k.startswith("matchup/") for k in weights)

    def choose(self, state, policy, opening=None, *, group_probability=None, explanation=None):
        arms = strategy_arms(state, policy, opening, matchups=self.uses_matchups,
                             group_probability=group_probability)
        kind = strategy_kind(state)
        strength = self.strengths_by_kind.get(kind, self.strength)
        offsets = {}
        if kind == "card" and self.card_offsets:
            act = state["context"]["act"] - 1
            for card in state["cards"]:
                name = _card_id(card)
                key = name + "+" if card.get("upgrades") or card.get("upgraded") else name
                values = self.card_offsets.get(key, self.card_offsets.get(name))
                if values is not None:
                    offsets[card["index"]] = values[act]
        totals = []
        options = []
        for action, prior, features in arms:
            index = action.args.get("card_index")
            offset = offsets.get(index, 0.0)
            strategy_score = strength * self.predict(0.0, features)
            total = prior + strategy_score + offset
            totals.append(total)
            if explanation is not None and kind == "card":
                card = next((c for c in state["cards"] if c["index"] == index), None)
                base = prior
                prior_terms = {}
                if opening is not None and offer_type(state):
                    base, opening_features = offer_features(state, action, policy)
                    prior_terms = opening.contributions(opening_features)
                base_parts = draft_prior_parts(
                    card, state["player"]["deck"], policy, 0.2 if opening and offer_type(state) else 0.35,
                )
                options.append({
                    "action": action.command(), "card": card["id"] if card else "skip",
                    "prior_base": base, "prior_base_parts": base_parts, "prior_terms": prior_terms, "prior": prior,
                    "strategy_terms": self.contributions(features, strength),
                    "strategy": strategy_score, "card_offset": offset, "total": total,
                })
        winner = max(range(len(arms)), key=totals.__getitem__)
        if explanation is not None and kind == "card":
            explanation.update({
                "context": state["context"], "group_probability": group_probability,
                "prior_source": "opening_model" if opening is not None and offer_type(state) else "card_heuristic",
                "strategy_strength": strength, "chosen": options[winner]["card"],
                "chosen_action": arms[winner][0].command(), "options": options,
            })
        return arms[winner][0]

    def save(self, path):
        with Path(path).open("x", encoding="utf-8") as stream:
            json.dump(
                {
                    "version": 1,
                    "runtime_identity": IDENTITY,
                    "weights": self.weights,
                    "kinds": sorted(self.kinds),
                    "strength": self.strength,
                    "strengths_by_kind": self.strengths_by_kind,
                    "card_offsets": self.card_offsets,
                },
                stream,
                indent=2,
            )

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("version") != 1 or data.get("runtime_identity") != IDENTITY:
            raise ValueError("Incompatible strategy model")
        return cls(
            data["weights"],
            data["kinds"],
            data["strength"],
            data.get("strengths_by_kind"),
            data.get("card_offsets"),
        )
