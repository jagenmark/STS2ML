"""Current round resolution up to the next public reveal."""
from dataclasses import replace

from .encounters import STRANGLER, after_death, after_move, before_move, encounter_reason
from .state import Boundary, HAND_CAP, add_power, power, set_power
from .transitions import boundary, lose_hp, outside_hand

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
    discard = list(state.discard)
    exhaust = list(state.exhaust)
    retain = power(state.powers, "WELL_LAID_PLANS")
    for c in hand:
        v = c.variant
        amount = _HAND_DAMAGE.get(v.name, 0)
        if amount:
            state = _hurt(state, amount)
            if state.outcome:
                return state
        if "Ethereal" in v.keywords:
            exhaust.append(outside_hand(v))
        elif retain or "Retain" in v.keywords or "retain_this_turn" in v.flags:
            (status_keep if amount else remaining).append(c)
        else:
            discard.append(outside_hand(v))
    # End-of-turn status actions move retained cards after the ordinary hand.
    return replace(state, hand=(*remaining, *status_keep),
                   discard=tuple(sorted(discard)), exhaust=tuple(sorted(exhaust)))


def _enemy_start(state):
    for slot in range(len(state.enemies)):
        enemy = state.enemies[slot]
        if enemy.hp <= 0:
            continue
        poison = power(enemy.powers, "POISON")
        if not poison and not enemy.block:
            continue
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
    intangible = power(state.powers, "INTANGIBLE") > 0
    if state.preview_intangible and shown == 1:
        minimum = (8 + before - 1) // before
        return 1 if intangible and max(0, minimum + delta) * after // 8 >= 1 else None
    if delta == 0 and before == after and not intangible:
        return shown
    if shown == 0 and delta > 0:
        return None
    minimum = (8 * shown + before - 1) // before
    maximum = (8 * (shown + 1) - 1) // before
    lo = max(0, minimum + delta) * after // 8
    hi = max(0, maximum + delta) * after // 8
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
            return state
        enemy = state.enemies[slot]
        if not enemy.intents:
            return boundary(state, "missing enemy intent")
        hp, block, powers = state.hp, state.block, state.powers
        for intent in enemy.intents:
            if intent.damage is None:
                if "Attack" in intent.kind or intent.kind == "DeathBlow":
                    return boundary(state, "missing attack damage")
                continue
            amount = attack_amount(state, enemy, intent)
            if amount is None or not 1 <= intent.hits <= 25:
                return boundary(state, "ambiguous attack preview")
            for _ in range(intent.hits):
                hp, block, powers = lose_hp(hp, block, powers, amount)
                if not hp:
                    return replace(state, hp=0, block=block, powers=powers, outcome="dead")
        if (hp, block, powers) != (state.hp, state.block, state.powers):
            state = replace(state, hp=hp, block=block, powers=powers)
        state = after_move(state, enemy)
        if state.boundary:
            return state
        enemy = state.enemies[slot]
        powers = _tick(enemy.powers, ("WEAK", "VULNERABLE", "INTANGIBLE"))
        if powers != enemy.powers or enemy.attack_delta:
            state = replace(state, enemies=(*state.enemies[:slot], replace(enemy, powers=powers, attack_delta=0),
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
    block = state.block if power(state.powers, "BLUR") else 0
    hp = state.hp
    if poison := power(powers, "POISON"):
        hp, block, powers = lose_hp(hp, block, powers, poison, bypass=True)
        powers = add_power(powers, "POISON", -1)
    reveal = None
    outcome = "completed" if hp else "dead"
    for name in ("NIGHTMARE", "TOOLS_OF_THE_TRADE"):
        if hp and power(powers, name):
            reveal, outcome = Boundary(f"start/{name}"), ""
            break
    if outcome == "completed":
        count = min(5, HAND_CAP - len(state.hand), len(state.draw) + len(state.discard))
        reveal = Boundary("next turn", count, count > len(state.draw))
    return replace(state, hp=hp, block=block, powers=powers, energy=energy, round=state.round + 1,
                   relics=tuple(relics), boundary=reveal, outcome=outcome)


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
    prior_powers = state.powers
    state = _enemy_actions(state)
    if state.outcome or state.boundary:
        return state
    return _start_player(state, prior_powers)
