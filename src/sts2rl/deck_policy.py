"""Value a card against the current deck's damage, protection and scaling needs."""

from __future__ import annotations

import json
from pathlib import Path

from .native import legal_actions, selected_cards
from .selections import selection_goal
from .run_policy import IDENTITY, _card_id, _cost, _hits, _shiv_count


def card_profile(card):
    name = _card_id(card)
    stats = card.get("stats") or {}
    desc = card.get("description") or ""
    cost = _cost(card)
    hits = _hits(card)
    if name in ("FLECHETTES", "FINISHER"):
        hits = 2.4
    if name in ("SKEWER", "VOLLEY"):
        hits, cost = 2.2, 2
    if name in ("TWIN_STRIKE", "UPROAR"):
        hits = 2
    shivs = _shiv_count(card) + (stats.get("cards", 0) if name == "BLADE_OF_INK" else 0)
    damage = stats.get("calculateddamage", stats.get("damage", 0)) * hits + 4 * shivs
    poison = stats.get("poisonpower", 0)
    block = stats.get("calculatedblock", stats.get("block", 0))
    weak = stats.get("weakpower", 0)
    aoe = float("ALL enemies" in desc)
    draw = stats.get("cards", 0) if ("Draw" in desc or "draw" in desc) and not shivs else 0
    if "Draw 1 card" in desc or name == "DAGGER_THROW":
        draw = 1
    source = float("Discard" in desc and ("card" in desc.lower() or "Hand" in desc))
    sly = float("Sly" in (card.get("keywords") or []))
    if name == "FISTICUFFS":
        block += damage
    if name in ("UP_MY_SLEEVE",):
        cost = max(1, cost - 1)
    return damage, poison, block, weak, shivs, aoe, draw, source, sly, cost


def deck_context(deck):
    counts = {
        "n": len(deck),
        "power": 0,
        "attack": 0,
        "poison": 0,
        "block": 0,
        "shiv": 0,
        "discard": 0,
        "sly": 0,
        "aoe": 0,
        "noxious": 0,
        "accuracy": 0,
        "afterimage": 0,
        "dexterity": 0,
        "accel": 0,
    }
    copies = {}
    for c in deck:
        name = _card_id(c)
        stats = c.get("stats") or {}
        damage, poison, block, _, shivs, aoe, _, discards, sly, _ = card_profile(c)
        counts["power"] += c.get("type") == "Power"
        counts["attack"] += damage >= 8
        counts["block"] += block >= 7
        counts["poison"] += poison + 3 * stats.get("poisonperturn", 0)
        counts["noxious"] += stats.get("poisonperturn", 0)
        counts["shiv"] += shivs
        counts["discard"] += discards
        counts["sly"] += sly
        counts["aoe"] += aoe * (damage + 1.8 * poison)
        counts["accuracy"] += stats.get("accuracypower", 0)
        counts["dexterity"] += stats.get("dexteritypower", 0)
        counts["afterimage"] += stats.get("afterimagepower", 0)
        counts["accel"] += stats.get("accelerant", 0)
        copies[name] = copies.get(name, 0) + 1
    return counts, copies


class DeckPolicy:
    def __init__(self, data):
        if data.get("version") != 1 or data.get("runtime_identity") != IDENTITY:
            raise ValueError("Incompatible deck evaluation model")
        self.scaling = data.get("scaling", 1.0)
        self.threshold = data.get("threshold", 9.0)
        self.defense = data.get("defense", 1.0)
        self.duplicate = data.get("duplicate", 1.6)
        self.learned = data.get("learned", {})
        self.merchant = data.get("merchant")
        self.prompt_aware = data.get("prompt_aware", False)
        self.prompt = None
        self.scope = frozenset(
            data.get("scope", ["card_reward", "bundle_select", "shop", "rest_site"])
        )
        self.to_upgrade = False

    @classmethod
    def load(cls, path):
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def terms(self, card, ctx, deck_info):
        counts, copies = deck_info
        name = _card_id(card)
        st = card.get("stats") or {}
        dmg, psn, block, weak, shivs, aoe, draw, discards, sly, cost = card_profile(card)
        act = ctx["act"]
        early = act == 1 and ctx["floor"] <= 9
        fast = 1.24 if counts["attack"] <= 2 and early else 0.94 if counts["attack"] >= 5 else 1.04
        guard = (
            1.18 if counts["block"] <= 1 and not early else 0.96 if counts["block"] >= 4 else 1.04
        )
        attack = (
            (dmg + shivs * counts["accuracy"] * 0.7)
            * fast
            * (1 + aoe * (0.32 if counts["aoe"] < 15 else 0.16))
        )
        defense = (
            block
            + (3.0 if early else 4.0) * min(2, weak)
            + min(10, st.get("strengthloss", 0) * 1.5)
        ) * guard
        if name in ("DODGE_AND_ROLL", "TORIC_TOUGHNESS", "BLUR"):
            defense += block * (0.62 if name != "BLUR" else 0.3)
        if name == "MALAISE":
            defense += 18.0
            cost = 2
        attack += (
            psn
            * (1.7 if early and not counts["poison"] else 2.6)
            * (1 + 0.30 * aoe)
            * (1 + 0.4 * min(2, counts["accel"]))
        )
        if name == "BUBBLE_BUBBLE" and counts["poison"] < 3:
            attack -= psn * 1.8
        if name == "OUTBREAK":
            attack += min(20, 5 + 0.6 * counts["poison"])
        power = (
            st.get("dexteritypower", 0) * (1.3 if name == "ANTICIPATE" else 5.4)
            + st.get("strengthpower", 0) * 6
            + st.get("poisonperturn", 0) * 8.5
            + st.get("afterimagepower", 0) * 16
            + st.get("envenompower", 0) * 13
            + st.get("serpentformpower", 0) * 7
            + st.get("thornspower", 0) * 3.2
            + st.get("speedsterpower", 0) * (2.8 + min(3, counts["discard"] * 0.6))
            + st.get("accuracypower", 0) * min(5, 0.6 + counts["shiv"] * 0.47)
            + st.get("phantombladespower", 0) * min(2, 0.3 + counts["shiv"] * 0.22)
            + st.get("accelerant", 0) * min(29, counts["poison"] * 1.45 + 5 * counts["noxious"])
            + st.get("intangiblepower", 0) * 11.0
            + st.get("dansemacabrepower", 0) * 1.8
        )
        if name in (
            "INFINITE_BLADES",
            "TOOLS_OF_THE_TRADE",
            "WELL_LAID_PLANS",
            "BULLET_TIME",
            "STORM_OF_STEEL",
            "TRACKING",
            "FINESSE",
            "CALCULATED_GAMBLE",
            "BURST",
            "DOPPELGANGER",
            "PHANTOM_BLADES",
        ):
            power += {
                "INFINITE_BLADES": 13 + counts["accuracy"],
                "TOOLS_OF_THE_TRADE": 8.5 + min(7, counts["sly"] * 2),
                "WELL_LAID_PLANS": 12.5,
                "BULLET_TIME": 19.0,
                "STORM_OF_STEEL": 11.0 + min(9, counts["sly"] * 1.8),
                "TRACKING": 9.0,
                "FINESSE": 1.0,
                "CALCULATED_GAMBLE": 6.0 + min(10, counts["sly"] * 2.0),
                "BURST": 10.0,
                "DOPPELGANGER": 5.0,
                "PHANTOM_BLADES": 1.0,
            }[name]
        utility = (
            2.8 * draw
            + st.get("energy", 0) * 5.0
            + st.get("vulnerablepower", 0) * 2.2
            + discards * min(6, counts["sly"] * 1.7)
            + sly * min(12, counts["discard"] * 2.4)
            - 1.35 * st.get("hploss", 0)
        )
        if name == "EXPOSE":
            utility += 8.5
        if name == "SEEKER_STRIKE":
            utility += 4.5
        if name == "GLASS_KNIFE":
            attack -= 2.0
        if name == "GRAND_FINALE":
            attack *= 0.18
        if name == "PRECISE_CUT":
            attack *= 0.67
        if name == "TACTICIAN" or name == "REFLEX":
            utility -= 4.0
        if "Ethereal" in (card.get("keywords") or []) and cost >= 2:
            utility -= 1.0
        if card.get("type") in ("Curse", "Status", "Quest"):
            utility -= 16.0
        divisor = max(1, cost) ** 0.8
        power *= 1.12 if act >= 2 else 0.82 if early else 1.0
        return {
            "attack": attack / divisor,
            "block": defense / divisor,
            "scaling": power / divisor,
            "utility": utility / divisor,
            "free": float(cost == 0 and attack + defense + power + utility > 1) * 2.7,
            "copies": copies.get(name, 0),
            "size": max(0, counts["n"] - 14) / 6,
            "card:" + name: 1.0,
            "power-duplicates": float(card.get("type") == "Power") * max(0, counts["power"] - 2),
            "is_attack": float(card.get("type") == "Attack"),
            "early": float(early),
            "late": float(act >= 2),
        }

    def grade(self, card, ctx, info):
        v = self.terms(card, ctx, info)
        return (
            v["attack"]
            + self.defense * v["block"]
            + self.scaling * v["scaling"]
            + v["utility"]
            + v["free"]
            - self.duplicate * v["copies"]
            - 0.8 * v["power-duplicates"]
            - 1.65 * v["size"]
            - self.threshold
            + sum(self.learned.get(k, 0.0) * x for k, x in v.items())
        )

    def observe(self, state, action):
        if self.prompt_aware and not state.get("in_combat") and state["decision"] != "card_select":
            self.prompt = selection_goal(state, action)

    def choose(self, state, base):
        d = state["decision"]
        ctx = state["context"]
        player = state["player"]
        deck = player["deck"]
        info = deck_context(deck)

        def grade(c):
            return self.grade(c, ctx, info)

        if d == "card_select" and (self.to_upgrade or self.prompt):
            self.to_upgrade = False

            def benefit(c):
                up = c.get("after_upgrade") or {}
                if not up:
                    return -100.0
                gain = grade({**c, **up}) - grade(c)
                return gain + 0.08 * max(0, grade(c) + self.threshold)

            if self.prompt in ("enhance", "take"):
                benefits = grade
            elif self.prompt == "remove":

                def benefits(c):
                    return -grade(c)
            else:
                benefits = benefit
            self.prompt = None
            ranks = sorted(state["cards"], key=benefits, reverse=True)
            n = min(len(ranks), state["max_select"])
            return selected_cards(state, [c["index"] for c in ranks[:n]])
        self.to_upgrade = False
        acts = legal_actions(state)
        if d == "card_reward":
            cards = {c["index"]: c for c in state["cards"]}
            return max(
                acts,
                key=lambda a: (
                    grade(cards[a.args["card_index"]]) if a.kind == "select_card_reward" else 0.0
                ),
            )
        if d == "bundle_select":
            return max(
                acts,
                key=lambda a: sum(
                    grade(c) for c in state["bundles"][a.args["bundle_index"]]["cards"]
                ),
            )
        if d == "rest_site":
            a = base(state)
            self.to_upgrade = any(
                o.get("option_id") == "SMITH" and o["index"] == a.args.get("option_index")
                for o in state["options"]
            )
            return a
        if d == "shop" and self.merchant:
            from .merchant import merchant_choice

            return merchant_choice(state, grade, **self.merchant)
        if d == "shop":

            def value(a):
                if a.kind == "buy_card":
                    c = next(c for c in state["cards"] if c["index"] == a.args["card_index"])
                    return grade(c) - 0.03 * c["cost"]
                if a.kind == "buy_relic":
                    r = next(r for r in state["relics"] if r["index"] == a.args["relic_index"])
                    desc = r.get("description") or ""
                    return (
                        5.2
                        + 2.5 * any(s in desc for s in ("energy", "Block", "Strength", "Dexterity"))
                        - 0.006 * r["cost"]
                    )
                if a.kind == "remove_card":
                    return (
                        7.0
                        if any(
                            c["type"] == "Curse" and _card_id(c) != "ASCENDERS_BANE" for c in deck
                        )
                        else (2.0 if len(deck) > 14 else 0.6)
                    )
                if a.kind == "buy_potion":
                    return 2.1 if not player["potions"] else 0.4
                return 0.0

            return max(acts, key=value)
        return base(state)
