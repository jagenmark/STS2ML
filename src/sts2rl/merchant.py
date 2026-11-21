"""Choose an affordable basket while retaining gold for subsequent shops."""

from .native import legal_actions
from .run_policy import _card_id


def merchant_choice(state, grade, *, reserve, permanent):
    player = state["player"]
    gold = player["gold"]
    act = state["context"]["act"]
    floor = state["context"]["floor"]
    hp = player["hp"] / player["max_hp"]
    cards = player["deck"]
    actions = legal_actions(state)
    leave = next(a for a in actions if a.kind == "leave_room")
    budget = gold
    # Value declines near the end of the last act, when there may be no further merchant.
    unit = reserve * (0.035 if act == 3 and floor >= 8 else 0.070)
    offers = []
    for action in actions:
        kind = action.kind
        if kind == "leave_room":
            continue
        if kind == "remove_card":
            cost = state["card_removal_cost"]
            curse = any(c.get("type") == "Curse" and _card_id(c) != "ASCENDERS_BANE" for c in cards)
            value = 15.0 if curse else 3.0 + min(4.0, max(0, len(cards) - 13) * 0.28)
        else:
            category, key = {
                "buy_card": ("cards", "card_index"),
                "buy_relic": ("relics", "relic_index"),
                "buy_potion": ("potions", "potion_index"),
            }[kind]
            item = next(x for x in state[category] if x["index"] == action.args[key])
            cost = item["cost"]
            desc = (item.get("description") or "").lower()
            name = item.get("name", "")
            if kind == "buy_card":
                value = 1.4 + max(-6, grade(item))
            elif kind == "buy_potion":
                value = (
                    (5.0 if not player["potions"] else 2.3)
                    + (2 if floor >= 12 else 0)
                    + 2 * (1 - hp)
                )
                if name in (
                    "Fairy in a Bottle",
                    "Ghost in a Jar",
                    "Ambergris",
                    "Heart of Iron",
                    "Mazaleth's Gift",
                    "Powdered Demise",
                ):
                    value += 7
                if "cannot" in desc:
                    value -= 2
            else:
                value = 12.0
                if "each combat" in desc or "every combat" in desc or "each turn" in desc:
                    value += 4.0
                if "strength" in desc or "dexterity" in desc:
                    value += 4.0
                if "energy" in desc or "free to play" in desc:
                    value += 5.0
                if "block" in desc and "combat" in desc:
                    value += 2.0
                if "heal" in desc or "max hp" in desc:
                    value += 3.5 * (1.35 - hp)
                if "card reward" in desc and "rare" not in desc:
                    value -= 1.5
                if name in (
                    "Kunai",
                    "Shuriken",
                    "Ornamental Fan",
                    "Tough Bandages",
                    "Tingsha",
                    "Letter Opener",
                    "Tungsten Rod",
                    "Meat on the Bone",
                    "Torii",
                    "Unceasing Top",
                    "Incense Burner",
                ):
                    value += 5.0
                if name in (
                    "White Star",
                    "Ceramic Fish",
                    "Tiny Chest",
                    "Juzu Bracelet",
                    "Dingy Rug",
                ):
                    value -= 5.0
                value *= permanent
        offers.append((action, cost, value))
    # Each listed purchase is available at most once at the current prices. Replan after the best first purchase.
    states = {0: (0.0, ())}
    for i, (_, cost, value) in enumerate(offers):
        for spent, (benefit, basket) in list(states.items()):
            price = spent + cost
            if price <= budget and benefit + value > states.get(price, (-float("inf"), ()))[0]:
                states[price] = (benefit + value, basket + (i,))

    def quality(entry):
        spent, (benefit, _) = entry
        retained = gold - spent
        savings = 0.0 if act == 3 else min(140, retained) * 0.019 * reserve
        return benefit - spent * unit + savings

    _, (_, best) = max(states.items(), key=quality)
    if not best:
        return leave
    first = max(
        best, key=lambda i: (offers[i][0].kind == "buy_relic", offers[i][2] - offers[i][1] * unit)
    )
    return offers[first][0]


class PendingRelicPurchase:
    """Track paid relics while their native card-selection prompt is being resolved."""

    def __init__(self):
        self.paid = {}

    def observe(self, before, action, after):
        if before.get("decision") == "map_select":
            self.paid.clear()
        if action.kind != "buy_relic" or after.get("decision") != "card_select":
            return
        if after["player"]["gold"] >= before["player"]["gold"] or len(after["player"]["relics"]) <= len(before["player"]["relics"]):
            return
        index = action.args["relic_index"]
        item = next(r for r in before["relics"] if r["index"] == index)
        self.paid[index] = (item["name"], item["cost"])

    def corrected_view(self, state, chosen):
        if chosen.kind != "buy_relic" or not self.paid:
            return None
        index = chosen.args["relic_index"]
        item = next(r for r in state["relics"] if r["index"] == index)
        if self.paid.get(index) != (item["name"], item["cost"]):
            return None
        return {**state, "relics": [
            {**r, "is_stocked": False} if self.paid.get(r["index"]) == (r["name"], r["cost"]) else r
            for r in state["relics"]
        ]}
