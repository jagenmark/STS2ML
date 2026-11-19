"""Use the public cause of a prompt to distinguish taking, improving and discarding cards."""

from .native import legal_actions, selected_cards
from .run_policy import _cost, _hits, _shiv_count
from .teacher import incoming


def selection_goal(state, action):
    if state["decision"] == "shop" and action.kind == "remove_card":
        return "remove"
    if state["decision"] not in ("rest_site", "event_choice"):
        return None
    option = next(
        (o for o in state.get("options", []) if o["index"] == action.args.get("option_index")), {}
    )
    if option.get("option_id") == "SMITH":
        return "upgrade"
    text = (option.get("description") or "").lower()
    if "transform" in text or "remove" in text and "deck" in text:
        return "remove"
    if "upgrade" in text and "random" not in text:
        return "upgrade"
    if "enchant" in text or "duplicate" in text:
        return "enhance"
    if ("choose" in text or "select" in text) and ("add" in text or "obtain" in text):
        return "take"
    return None


def combat_selection(state, actor):
    view = state.get("combat_state") or {}
    if not view:
        return actor.select_cards(state)
    player = view["player"]
    enemies = view["enemies"]
    energy = view["energy"]
    source = state.get("selection_source") or {}
    origin = source.get("id", "").split(".")[-1]
    keep = source.get("kind") == "end_turn" or origin in {
        "SEEKER_STRIKE",
        "NIGHTMARE",
        "HEADBUTT",
        "HAND_TRICK",
        "DECISIONS_DECISIONS",
        "LIQUID_MEMORIES",
        "TOUCH_OF_INSANITY",
        "DROPLET_OF_PRECOGNITION",
    }
    if state["decision"] == "card_reward":
        keep = True
    potions = {
        "ATTACK_POTION",
        "SKILL_POTION",
        "POWER_POTION",
        "COLORLESS_POTION",
        "LIQUID_MEMORIES",
    }
    free = origin in potions
    need = max(0, sum(incoming(e) for e in enemies) - player["block"])

    def usefulness(c):
        stats = c.get("stats") or {}
        cost = 0 if free else _cost(c)
        durable = actor.card_value(c, deck=player["deck"])
        damage = stats.get("calculateddamage", stats.get("damage", 0)) * _hits(c) + 4 * _shiv_count(
            c
        )
        if "ALL enemies" in (c.get("description") or ""):
            damage *= len(enemies)
        guard = min(need, stats.get("calculatedblock", stats.get("block", 0)))
        poison = stats.get("poisonpower", 0) * (
            2.3 if view["context"]["room_type"] == "Boss" else 1.6
        )
        gain = (
            damage
            + 1.65 * guard
            + poison
            + (0.6 * durable if c.get("type") == "Power" else 0.16 * durable)
        ) / max(1, cost) ** 0.65
        if cost > energy and source.get("kind") != "end_turn" and origin != "NIGHTMARE":
            gain *= 0.25
        if c.get("type") in ("Curse", "Status", "Quest"):
            gain -= 18
        return gain + 0.25 * durable

    def value(c):
        v = usefulness(c)
        if keep:
            return v
        sly = c.get("sly_this_turn") or "Sly" in (c.get("keywords") or [])
        if sly:
            return 14 + max(0, v)
        return -v

    if state["decision"] == "card_reward":
        by_index = {c["index"]: c for c in state["cards"]}
        actions = legal_actions(state)
        return max(
            actions,
            key=lambda a: (
                value(by_index[a.args["card_index"]]) if a.kind == "select_card_reward" else -1.0
            ),
        )
    ranks = sorted(state["cards"], key=value, reverse=True)
    count = min(state["max_select"], max(state["min_select"], sum(value(c) > 0 for c in ranks)))
    return selected_cards(state, [c["index"] for c in ranks[:count]])
