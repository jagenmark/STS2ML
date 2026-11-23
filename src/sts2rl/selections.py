"""Use the public cause of a prompt to distinguish taking, improving and discarding cards."""

from .native import legal_actions, selected_cards
from .run_policy import _cost, _hits, _shiv_count
from .teacher import incoming


def selection_goal(state, action, *, detailed=False):
    if state["decision"] == "shop" and action.kind == "remove_card":
        return "remove"
    if detailed and state["decision"] == "shop" and action.kind == "buy_relic":
        relic = next(
            (r for r in state.get("relics", []) if r["index"] == action.args.get("relic_index")),
            {},
        )
        text = (relic.get("description") or "").lower()
        if "transform" in text:
            return "transform"
        if "remove" in text:
            return "remove"
        if "upgrade" in text and "random" not in text:
            return "upgrade"
        if "duplicate" in text or "additional copy" in text:
            return "duplicate"
        if "enchant" in text:
            return "enchant"
        return None
    if state["decision"] not in ("rest_site", "event_choice"):
        return None
    option = next(
        (o for o in state.get("options", []) if o["index"] == action.args.get("option_index")), {}
    )
    if option.get("option_id") == "SMITH":
        return "upgrade"
    text = (option.get("description") or "").lower()
    if detailed:
        if "transform" in text:
            return "transform"
        if "remove" in text:
            return "remove"
        if "upgrade" in text and "random" not in text:
            return "upgrade"
        if "duplicate" in text or "additional copy" in text:
            return "duplicate"
        if "enchant" in text:
            return "enchant"
        if ("choose" in text or "select" in text) and ("add" in text or "obtain" in text):
            return "take"
        return None
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
    card_pot_mech = bool(getattr(actor, "card_potion_mechanics", False))
    sel_fixes_v4 = bool(getattr(actor, "selection_fixes_v4", False))
    player = view["player"]
    enemies = view["enemies"]
    energy = view["energy"]
    source = state.get("selection_source") or {}
    origin = source.get("id", "").split(".")[-1]
    potions = {
        "ATTACK_POTION",
        "SKILL_POTION",
        "POWER_POTION",
        "COLORLESS_POTION",
        "LIQUID_MEMORIES",
    }
    keep_origins = {
        "SEEKER_STRIKE",
        "NIGHTMARE",
        "HEADBUTT",
        "HAND_TRICK",
        "DECISIONS_DECISIONS",
        "LIQUID_MEMORIES",
        "TOUCH_OF_INSANITY",
        "DROPLET_OF_PRECOGNITION",
    }
    if sel_fixes_v4:
        keep_origins |= {
            "ATTACK_POTION",
            "SKILL_POTION",
            "POWER_POTION",
            "COLORLESS_POTION",
            "DISCOVERY",
        }
        has_wlp = any(
            "WELL_LAID_PLANS" in p.get("id", "") and p.get("amount", 0) > 0
            for p in (view.get("player_powers") or ())
        )
        end_turn_retain = (
            source.get("kind") == "end_turn"
            and state.get("min_select", 0) == 0
            and has_wlp
        )
        keep = end_turn_retain or origin in keep_origins
    else:
        keep = source.get("kind") == "end_turn" or origin in keep_origins
    if state["decision"] == "card_reward":
        keep = True
    free = origin in potions or (sel_fixes_v4 and origin == "DISCOVERY")
    need = max(0, sum(incoming(e) for e in enemies) - player["block"])

    def usefulness(c):
        stats = c.get("stats") or {}
        cost = 0 if free else _cost(c)
        if card_pot_mech and not keep and c.get("id") == "CARD.GRAND_FINALE":
            hand_cards = view.get("hand") or ()
            match = next((h for h in hand_cards if h.get("index") == c.get("index") and h.get("id") == c.get("id")), None)
            if match is not None and "can_play" in match:
                gf_playable = bool(match["can_play"])
            elif "can_play" in c:
                gf_playable = bool(c["can_play"])
            else:
                gf_playable = view.get("draw_pile_count") == 0
            if not gf_playable:
                return -5.0
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
        unplayable_now = (
            cost > energy and source.get("kind") != "end_turn" and origin != "NIGHTMARE"
        )
        if unplayable_now:
            gain *= 0.25
        if c.get("type") in ("Curse", "Status", "Quest"):
            gain -= 18
        total = gain + 0.25 * durable
        if card_pot_mech and not keep and unplayable_now and c.get("type") not in ("Curse", "Status", "Quest"):
            return total * 0.15
        return total

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
