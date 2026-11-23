"""Current round resolution up to the next public reveal."""
from dataclasses import replace

from .encounters import STRANGLER, after_death, after_move, before_move, encounter_reason
from .state import HAND_CAP, add_power, power, set_power
from .transitions import _put, boundary, lose_hp

_HAND_DAMAGE = {"BURN": 2, "WITHER": 3, "INFECTION": 3}


def _hurt(state, amount, *, bypass=False):
    hp, block, powers = lose_hp(state.hp, state.block, state.powers, amount, bypass=bypass)
    return replace(state, hp=hp, block=block, powers=powers, outcome="" if hp else "dead")


def _hand_end(state):
    hand = state.hand
    for relic in state.relics:
        if relic.used:
            continue
        if relic.name == "CLOAK_CLASP":
            state = replace(state, block=state.block + power(relic.stats, "block") * len(hand))
        if relic.name == "ORICHALCUM" and not state.block:
            state = replace(state, block=power(relic.stats, "block"))
    constrict = power(state.powers, "CONSTRICT")
    if constrict and any(e.name == STRANGLER and e.hp > 0 for e in state.enemies):
        state = _hurt(state, constrict)
        if state.outcome:
            return state
    remaining = []
    status_keep = []
    retain = power(state.powers, "WELL_LAID_PLANS")
    for c in hand:
        v = c.variant
        amount = _HAND_DAMAGE.get(v.name, 0)
        if amount:
            state = _hurt(state, amount)
            if state.outcome:
                return state
        if "Ethereal" in v.keywords:
            state = _put(state, "exhaust", v)
        elif retain or "Retain" in v.keywords or "retain_this_turn" in v.flags:
            (status_keep if amount else remaining).append(c)
        else:
            state = _put(state, "discard", v)
    # End-of-turn status actions move retained cards after the ordinary hand.
    return replace(state, hand=tuple((*remaining, *status_keep)))


def _enemy_start(state):
    for slot in range(len(state.enemies)):
        enemy = state.enemies[slot]
        if enemy.hp <= 0:
            continue
        poison = power(enemy.powers, "POISON")
        hp, block, powers = lose_hp(enemy.hp, 0, enemy.powers, poison, bypass=True)
        if poison:
            powers = add_power(powers, "POISON", -1)
        enemy = replace(enemy, hp=hp, block=block, powers=powers)
        state = replace(state, enemies=(*state.enemies[:slot], enemy, *state.enemies[slot + 1:]))
        if enemy.hp == 0:
            state = after_death(state, enemy)
            if state.outcome or state.boundary:
                return state
    return state


def attack_amount(state, enemy, intent):
    # An unchanged rounded preview is exact. When the modifier changes,
    # require every base value compatible with the rounded preview to agree.
    before = (3 if enemy.preview_weak else 4) * (3 if state.preview_vulnerable else 2)
    after = (3 if power(enemy.powers, "WEAK") else 4) * (
        3 if power(state.powers, "VULNERABLE") else 2)
    delta = power(enemy.powers, "STRENGTH") - enemy.preview_strength + enemy.attack_delta
    shown = intent.damage
    if delta == 0 and before == after:
        return shown
    if shown == 0 and delta > 0:
        return None
    minimum = (8 * shown + before - 1) // before
    maximum = (8 * (shown + 1) - 1) // before
    lo = max(0, minimum + delta) * after // 8
    hi = max(0, maximum + delta) * after // 8
    return lo if lo == hi else None


def _enemy_actions(state):
    for slot in range(len(state.enemies)):
        enemy = state.enemies[slot]
        if enemy.hp <= 0:
            continue
        state = before_move(state, enemy)
        if state.outcome:
            return state
        enemy = state.enemies[slot]
        if not enemy.intents:
            return boundary(state, "missing enemy intent")
        for intent in enemy.intents:
            if intent.damage is None:
                if "Attack" in intent.kind or intent.kind == "DeathBlow":
                    return boundary(state, "missing attack damage")
                continue
            amount = attack_amount(state, enemy, intent)
            if amount is None or not 1 <= intent.hits <= 25:
                return boundary(state, "ambiguous attack preview")
            for _ in range(intent.hits):
                state = _hurt(state, amount)
                if state.outcome:
                    return state
        state = after_move(state, enemy)
        if state.boundary:
            return state
        enemy = state.enemies[slot]
        powers = _tick(enemy.powers, ("WEAK", "VULNERABLE", "INTANGIBLE"))
        state = replace(state, enemies=(*state.enemies[:slot], replace(enemy, powers=powers, attack_delta=0),
                                       *state.enemies[slot + 1:]))
    return state


def _tick(powers, durations):
    for name in durations:
        if power(powers, name) > 0:
            powers = add_power(powers, name, -1)
    return powers


def _start_player(state):
    powers = _tick(state.powers, ("WEAK", "VULNERABLE", "FRAIL", "INTANGIBLE", "BLUR"))
    for name in ("BURST", "DUPLICATION", "NO_DRAW", "TAINTED"):
        powers = set_power(powers, name, 0)
    energy = state.max_energy
    relics = []
    for relic in state.relics:
        if relic.name == "HAPPY_FLOWER" and relic.counter is not None and not relic.used:
            threshold = power(relic.stats, "turns")
            if threshold <= 0:
                return boundary(state, "happy flower counter")
            counter = (relic.counter + 1) % threshold
            if not counter:
                energy += power(relic.stats, "energy")
            relic = replace(relic, counter=counter)
        relics.append(relic)
    state = replace(state, powers=powers, energy=energy, round=state.round + 1,
                    block=state.block if power(state.powers, "BLUR") else 0, relics=tuple(relics))
    if poison := power(powers, "POISON"):
        state = _hurt(state, poison, bypass=True)
        state = replace(state, powers=add_power(state.powers, "POISON", -1))
        if state.outcome:
            return state
    for name in ("NIGHTMARE", "TOOLS_OF_THE_TRADE"):
        if power(powers, name):
            return boundary(state, f"start/{name}")
    count = min(5, HAND_CAP - len(state.hand), len(state.draw) + len(state.discard))
    return boundary(replace(state, outcome="completed"), "next turn", count, count > len(state.draw))


def resolve(state):
    if state.outcome:
        return state
    if reason := encounter_reason(state):
        return boundary(state, reason)
    state = _hand_end(state)
    if state.outcome:
        return state
    state = _enemy_start(state)
    if state.outcome or state.boundary:
        return state
    state = _enemy_actions(state)
    if state.outcome or state.boundary:
        return state
    return _start_player(state)
