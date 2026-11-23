"""Current round resolution up to the next public reveal."""
from dataclasses import replace

from .encounters import STRANGLER, STUN, after_damage, after_move, before_move, encounter_reason
from .state import Boundary, HAND_CAP, add_power, power, set_power
from .transitions import boundary, lose_hp, outside_hand

_HAND_DAMAGE = {"BURN": 2, "WITHER": 3, "INFECTION": 3, "TOXIC": 5, "BECKON": 6}


def _lethal(state):
    if any(p.name == "FAIRY_IN_A_BOTTLE" for p in state.potions):
        return boundary(replace(state, outcome=""), "automatic fairy potion")
    return replace(state, outcome="dead")


def _hurt(state, amount, *, bypass=False):
    hp, block, powers = lose_hp(state.hp, state.block, state.powers, amount, bypass=bypass)
    state = replace(state, hp=hp, block=block, powers=powers)
    return state if hp else _lethal(state)


def _hand_end(state):
    hand = state.hand
    for relic in state.relics:
        if relic.used:
            continue
        if relic.name == "CLOAK_CLASP":
            state = replace(state, block=state.block + power(relic.stats, "block") * len(hand))
        if relic.name == "ORICHALCUM" and not state.block:
            state = replace(state, block=power(relic.stats, "block"))
        if relic.name == "RIPPLE_BASIN" and relic.status == "Active":
            state = replace(state, block=state.block + power(relic.stats, "block"))
    constrict = power(state.powers, "CONSTRICT")
    if constrict and any(e.name == STRANGLER and e.hp > 0 for e in state.enemies):
        state = _hurt(state, constrict)
        if state.outcome or state.boundary:
            return state
    remaining = []
    status_keep = []
    discard = list(state.discard)
    exhaust = list(state.exhaust)
    retain = power(state.powers, "WELL_LAID_PLANS")
    for c in hand:
        v = c.variant
        amount = _HAND_DAMAGE.get(v.name, 0)
        if amount:
            state = _hurt(state, amount, bypass=v.name == "BECKON")
            if state.outcome or state.boundary:
                return state
        if "Ethereal" in v.keywords:
            exhaust.append(outside_hand(v))
        elif retain or "Retain" in v.keywords or "retain_this_turn" in v.flags:
            (status_keep if amount else remaining).append(c)
        else:
            discard.append(outside_hand(v))
    powers = state.powers
    for name in ("SPEED_POTION", "ANTICIPATE"):
        if temporary := power(powers, name):
            powers = add_power(set_power(powers, name, 0), "DEXTERITY", -temporary)
    # End-of-turn status actions move retained cards after the ordinary hand.
    return replace(state, hand=(*remaining, *status_keep),
                   discard=tuple(sorted(discard)), exhaust=tuple(sorted(exhaust)),
                   powers=powers, block=state.block + power(powers, "PLATING"))


def _enemy_start(state):
    for slot in range(len(state.enemies)):
        enemy = state.enemies[slot]
        if enemy.hp <= 0:
            continue
        poison = power(enemy.powers, "POISON")
        if not poison and not enemy.block:
            continue
        carried = enemy.block if power(enemy.powers, "BURROWED") else 0
        hp, block, powers = lose_hp(enemy.hp, carried, enemy.powers, poison, bypass=True)
        if poison:
            powers = add_power(powers, "POISON", -1)
        before = enemy
        enemy = replace(enemy, hp=hp, block=block, powers=powers)
        state = replace(state, enemies=(*state.enemies[:slot], enemy, *state.enemies[slot + 1:]))
        if enemy.hp < before.hp:
            state = after_damage(state, before, enemy)
            if state.outcome or state.boundary:
                return state
    return state


def attack_amount(state, enemy, intent):
    # An unchanged rounded preview is exact. When the modifier changes,
    # require every base value compatible with the rounded preview to agree.
    after_weak = power(enemy.powers, "WEAK") > 0
    weak = 12 if (enemy.preview_weak or after_weak) and any(
        r.name == "PAPER_KRANE" and not r.used for r in state.relics) else 15
    before = (weak if enemy.preview_weak else 20) * (3 if state.preview_vulnerable else 2)
    after = (weak if after_weak else 20) * (
        3 if power(state.powers, "VULNERABLE") else 2)
    delta = power(enemy.powers, "STRENGTH") - enemy.preview_strength + enemy.attack_delta
    shown = intent.damage
    intangible = power(state.powers, "INTANGIBLE") > 0
    if state.preview_intangible and shown == 1:
        minimum = (40 + before - 1) // before
        return 1 if intangible and max(0, minimum + delta) * after // 40 >= 1 else None
    if delta == 0 and before == after and not intangible:
        return shown
    if shown == 0 and delta > 0:
        return None
    minimum = (40 * shown + before - 1) // before
    maximum = (40 * (shown + 1) - 1) // before
    lo = max(0, minimum + delta) * after // 40
    hi = max(0, maximum + delta) * after // 40
    if intangible:
        lo, hi = min(lo, 1), min(hi, 1)
    return lo if lo == hi else None


def _enemy_actions(state):
    for slot in range(len(state.enemies)):
        enemy = state.enemies[slot]
        if enemy.hp <= 0:
            continue
        state = before_move(state, enemy)
        if state.outcome:
            return _lethal(state) if state.outcome == "dead" else state
        enemy = state.enemies[slot]
        if not enemy.intents:
            return boundary(state, "missing enemy intent")
        hp, block, powers = state.hp, state.block, state.powers
        prior_powers = enemy.powers
        fully_blocked = False
        thorns = power(powers, "THORNS")
        for intent in enemy.intents:
            if intent.damage is None:
                if "Attack" in intent.kind or intent.kind == "DeathBlow":
                    return boundary(state, "missing attack damage")
                continue
            amount = attack_amount(state, enemy, intent)
            if amount is None or not 1 <= intent.hits <= 25:
                return boundary(state, "ambiguous attack preview")
            fully_blocked = amount > 0 and block >= amount * intent.hits
            for _ in range(intent.hits):
                hp, block, powers = lose_hp(hp, block, powers, amount)
                if not hp:
                    return _lethal(replace(state, hp=0, block=block, powers=powers))
                if amount and thorns:
                    from .transitions import _damage

                    if state.enemies[slot].hp <= thorns:
                        return boundary(state, "lethal player thorns")
                    state = _damage(state, slot, thorns)
                    if state.boundary or state.outcome:
                        return state
                    updated = state.enemies[slot]
                    if updated.intents != enemy.intents:
                        return boundary(state, "player thorns changed enemy move")
        if (hp, block, powers) != (state.hp, state.block, state.powers):
            state = replace(state, hp=hp, block=block, powers=powers)
        state = after_move(state, state.enemies[slot])
        if state.boundary:
            return state
        enemy = state.enemies[slot]
        powers = _tick(enemy.powers, (name for name in ("WEAK", "VULNERABLE", "INTANGIBLE")
                                      if power(prior_powers, name)))
        intents = STUN if fully_blocked and power(powers, "IMBALANCED") else enemy.intents
        if powers != enemy.powers or enemy.attack_delta or intents != enemy.intents:
            state = replace(state, enemies=(*state.enemies[:slot], replace(enemy, powers=powers, attack_delta=0,
                                                                          intents=intents),
                                           *state.enemies[slot + 1:]))
    return state


def _tick(powers, durations):
    for name in durations:
        if power(powers, name) > 0:
            powers = add_power(powers, name, -1)
    return powers


def _start_player(state, prior_powers):
    durations = ("WEAK", "VULNERABLE", "FRAIL", "INTANGIBLE", "BLUR")
    powers = _tick(state.powers, (name for name in durations if power(prior_powers, name)))
    bonus_draw = power(powers, "DRAW_CARDS_NEXT_TURN")
    for name in ("BURST", "DUPLICATION", "NO_DRAW", "TAINTED", "DRAW_CARDS_NEXT_TURN"):
        powers = set_power(powers, name, 0)
    powers = _tick(powers, ("PLATING",))
    max_energy = state.max_energy
    energy = max_energy + power(powers, "ENERGY_NEXT_TURN")
    powers = set_power(powers, "ENERGY_NEXT_TURN", 0)
    relics = []
    for relic in state.relics:
        if relic.name == "HAPPY_FLOWER" and relic.counter is not None and not relic.used:
            threshold = power(relic.stats, "turns")
            if threshold <= 0:
                return boundary(state, "happy flower counter")
            counter = (relic.counter + 1) % threshold
            if not counter:
                energy += power(relic.stats, "energy")
            relic = replace(relic, counter=counter, status="Active" if counter == threshold - 1 else "Normal")
        if not relic.used:
            if relic.name == "RIPPLE_BASIN":
                relic = replace(relic, status="Active")
            if relic.name == "KUSARIGAMA":
                relic = replace(relic, counter=0, status="Normal")
            if relic.name == "SPARKLING_ROUGE" and state.round == 2:
                powers = add_power(powers, "STRENGTH", power(relic.stats, "strengthpower"))
                powers = add_power(powers, "DEXTERITY", power(relic.stats, "dexteritypower"))
            if relic.name == "PAELS_BLOOD" or (relic.name == "RING_OF_THE_DRAKE"
                                               and state.round < power(relic.stats, "turns")):
                bonus_draw += power(relic.stats, "cards")
            if ((relic.name == "PAELS_TEARS" and state.energy > 0)
                    or (relic.name == "CANDELABRA" and state.round == 1)):
                energy += power(relic.stats, "energy")
            if relic.name == "PAELS_FLESH":
                if state.round == 1:
                    relic = replace(relic, counter=2)
                elif state.round == 2:
                    buff = power(relic.stats, "energy")
                    max_energy += buff
                    energy += buff
                    relic = replace(relic, counter=None, status="Active")
        relics.append(relic)
    block = state.block if power(state.powers, "BLUR") else 0
    hp = state.hp
    if poison := power(powers, "POISON"):
        hp, block, powers = lose_hp(hp, block, powers, poison, bypass=True)
        powers = add_power(powers, "POISON", -1)
    if not hp:
        return _lethal(replace(state, hp=hp, block=block, powers=powers))
    reveal = None
    outcome = "completed"
    for name in ("NIGHTMARE", "TOOLS_OF_THE_TRADE"):
        if hp and power(powers, name):
            reveal, outcome = Boundary(f"start/{name}"), ""
            break
    if outcome == "completed":
        count = min(5 + bonus_draw, HAND_CAP - len(state.hand), len(state.draw) + len(state.discard))
        reveal = Boundary("next turn", count, count > len(state.draw))
    if fumes := power(powers, "NOXIOUS_FUMES"):
        from .transitions import _debuff

        for enemy in state.enemies:
            if enemy.hp > 0:
                state = _debuff(state, enemy.slot, "POISON", fumes)
    return replace(state, hp=hp, block=block, powers=powers, energy=energy, max_energy=max_energy,
                   round=state.round + 1,
                   relics=tuple(relics), boundary=reveal, outcome=outcome)


def resolve(state):
    if state.outcome or state.boundary:
        return state
    if reason := encounter_reason(state):
        return boundary(state, reason)
    state = _hand_end(state)
    if state.outcome or state.boundary:
        return state
    state = _enemy_start(state)
    if state.outcome or state.boundary:
        return state
    prior_powers = state.powers
    state = _enemy_actions(state)
    if state.outcome or state.boundary:
        return state
    return _start_player(state, prior_powers)
