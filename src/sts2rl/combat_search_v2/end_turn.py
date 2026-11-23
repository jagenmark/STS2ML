"""Current round resolution up to the next public reveal."""
from dataclasses import replace
from . import late_encounters

from .encounters import STRANGLER, STUN, after_damage, after_move, before_move, encounter_reason
from .state import Boundary, HAND_CAP, add_power, power, set_power
from .transitions import boundary, lose_hp, outside_hand

_HAND_DAMAGE = {"BURN": 2, "WITHER": 3, "INFECTION": 3, "TOXIC": 5, "BECKON": 6}


def _lethal(state):
    if any(r.name == "LIZARD_TAIL" and not r.used for r in state.relics):
        return boundary(replace(state, outcome=""), "automatic lizard tail")
    if any(p.name == "FAIRY_IN_A_BOTTLE" for p in state.potions):
        return boundary(replace(state, outcome=""), "automatic fairy potion")
    return replace(state, outcome="dead")


def _player_damage(state, hp, block, powers, amount, *, bypass=False):
    rod = state.late and any(r.name == "TUNGSTEN_ROD" and not r.used for r in state.relics)
    return lose_hp(hp, block, powers, amount, bypass=bypass, reduction=int(rod))


def _hurt(state, amount, *, bypass=False):
    hp, block, powers = _player_damage(state, state.hp, state.block, state.powers, amount, bypass=bypass)
    if hp < state.hp and _puzzle(state):
        return boundary(state, "centennial puzzle draw")
    state = replace(state, hp=hp, block=block, powers=powers)
    return state if hp else _lethal(state)


def _puzzle(state):
    return any(r.name == "CENTENNIAL_PUZZLE" and not r.used for r in state.relics)


def _hand_end(state):
    hand = state.hand
    if state.late:
        if any(r.name == "STONE_CALENDAR" and r.counter == 7 for r in state.relics):
            return boundary(state, "stone calendar damage")
        if any("Ethereal" in c.variant.keywords for c in hand):
            if any(r.name == "FORGOTTEN_SOUL" for r in state.relics) and (
                    any(c.variant.name in _HAND_DAMAGE for c in hand) or power(state.powers, "CONSTRICT")):
                return boundary(state, "forgotten soul end turn ordering")
            state = late_encounters.on_exhaust(state, sum("Ethereal" in c.variant.keywords for c in hand))
            if state.boundary or state.outcome:
                return state
    if not state.block and any(r.name == "ORICHALCUM" and not r.used for r in state.relics) and any(
        r.name in ("RIPPLE_BASIN", "CLOAK_CLASP") and not r.used
        and (r.status == "Active" if r.name == "RIPPLE_BASIN" else bool(hand)) for r in state.relics
    ):
        return boundary(state, "simultaneous end-turn relic block")
    if power(state.powers, "PLATING") and (any(c.variant.name in _HAND_DAMAGE for c in hand)
                                           or any(r.name == "PARRYING_SHIELD" for r in state.relics)):
        return boundary(state, "plating and hand or shield ordering")
    if any(r.name == "JOSS_PAPER" for r in state.relics) and any("Ethereal" in c.variant.keywords for c in hand):
        return boundary(state, "joss paper ethereal exhaust")
    for relic in state.relics:
        if relic.used:
            continue
        if relic.name == "CLOAK_CLASP":
            state = replace(state, block=state.block + power(relic.stats, "block") * len(hand))
        if relic.name == "ORICHALCUM" and not state.block:
            state = replace(state, block=power(relic.stats, "block"))
        if relic.name == "RIPPLE_BASIN" and relic.status == "Active":
            state = replace(state, block=state.block + power(relic.stats, "block"))
    for relic in state.relics:
        if relic.name != "PARRYING_SHIELD" or relic.used or state.block < power(relic.stats, "block"):
            continue
        living = [e for e in state.enemies if e.hp > 0]
        if (not state.late or len(living) != 1 or living[0].hp <= power(relic.stats, "damage")
                or any(c.variant.name in _HAND_DAMAGE or c.variant.name == "DECAY" for c in hand)
                or power(state.powers, "CONSTRICT") or power(state.powers, "DISINTEGRATION")):
            return boundary(state, "parrying shield target")
        from .transitions import _damage
        state = _damage(state, living[0].slot, power(relic.stats, "damage"))
        if state.boundary or state.outcome:
            return state
    if amount := power(state.powers, "DISINTEGRATION"):
        if power(state.powers, "PLATING") or power(state.powers, "REGEN") or any(c.variant.name in _HAND_DAMAGE for c in hand):
            return boundary(state, "disintegration ordering")
        state = _hurt(state, amount)
        if state.outcome or state.boundary:
            return state
    if regen := power(state.powers, "REGEN"):
        if any(c.variant.name in _HAND_DAMAGE for c in hand) or power(state.powers, "CONSTRICT"):
            return boundary(state, "regen and hand damage ordering")
        state = replace(state, hp=min(state.max_hp, state.hp + regen), powers=add_power(state.powers, "REGEN", -1))
    if power(state.powers, "PHANTOM_BLADES") and any(c.variant.name == "SHIV" for c in hand):
        return boundary(state, "phantom blades retained shiv")
    constrict = power(state.powers, "CONSTRICT")
    if constrict and any(e.name == STRANGLER and e.hp > 0 for e in state.enemies):
        if power(state.powers, "PLATING"):
            return boundary(state, "plating and constrict ordering")
        state = _hurt(state, constrict)
        if state.outcome or state.boundary:
            return state
    remaining = []
    status_keep = []
    discard = list(state.discard)
    exhaust = list(state.exhaust)
    retain = power(state.powers, "WELL_LAID_PLANS") or (state.late and
             (power(state.powers, "RETAIN_HAND") or any(r.name == "RUNIC_PYRAMID" for r in state.relics)))
    for c in hand:
        v = c.variant
        amount = 2 if state.late and v.name == "DECAY" else _HAND_DAMAGE.get(v.name, 0)
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
    powers = _tick(state.powers, ("RETAIN_HAND",)) if state.late else state.powers
    if ritual := power(powers, "RITUAL"):
        powers = add_power(powers, "STRENGTH", ritual)
    if state.late and (flex := power(powers, "FLEX_POTION")):
        powers = add_power(set_power(powers, "FLEX_POTION", 0), "STRENGTH", -flex)
    for name in ("SPEED_POTION", "ANTICIPATE"):
        if temporary := power(powers, name):
            powers = add_power(set_power(powers, name, 0), "DEXTERITY", -temporary)
    # End-of-turn status actions move retained cards after the ordinary hand.
    return replace(state, hand=(*remaining, *status_keep),
                   discard=tuple(sorted(discard)), exhaust=tuple(sorted(exhaust)),
                   powers=powers, block=state.block + power(powers, "PLATING"))


def _enemy_start(state):
    crab = state.late and any(e.name in ("CRUSHER", "ROCKET") for e in state.enemies)
    if crab:
        state = replace(state, enemies=tuple(replace(e, block=0) if e.block else e for e in state.enemies))
    for slot in range(len(state.enemies)):
        enemy = state.enemies[slot]
        if enemy.hp <= 0:
            continue
        poison = power(enemy.powers, "POISON")
        if not poison and not enemy.block:
            continue
        carried = enemy.block if crab or power(enemy.powers, "BURROWED") else 0
        for _ in range(1 + min(max(0, poison - 1), power(state.powers, "ACCELERANT"))):
            enemy = state.enemies[slot]
            poison = power(enemy.powers, "POISON")
            hp, block, powers = lose_hp(enemy.hp, carried, enemy.powers, poison, bypass=True)
            if poison:
                powers = add_power(powers, "POISON", -1)
            updated = replace(enemy, hp=hp, block=block, powers=powers)
            state = replace(state, enemies=(*state.enemies[:slot], updated, *state.enemies[slot + 1:]))
            if hp < enemy.hp:
                state = after_damage(state, enemy, updated)
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
    scale = 40
    if state.late and power(state.powers, "SURROUNDED"):
        before *= 3 if enemy.slot != state.preview_facing else 2
        after *= 3 if enemy.slot != state.facing else 2
        scale *= 2
    delta = power(enemy.powers, "STRENGTH") - enemy.preview_strength + enemy.attack_delta
    shown = intent.damage
    intangible = power(state.powers, "INTANGIBLE") > 0
    if state.preview_intangible and shown == 1:
        minimum = (scale + before - 1) // before
        return 1 if intangible and max(0, minimum + delta) * after // scale >= 1 else None
    if delta == 0 and before == after and not intangible:
        return shown
    if shown == 0 and delta > 0:
        return None
    minimum = (scale * shown + before - 1) // before
    maximum = (scale * (shown + 1) - 1) // before
    lo = max(0, minimum + delta) * after // scale
    hi = max(0, maximum + delta) * after // scale
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
                before = hp
                hp, block, powers = _player_damage(state, hp, block, powers, amount)
                if state.late and hp < before and (cut := power(enemy.powers, "PAPER_CUTS")):
                    if state.max_hp <= cut:
                        return boundary(state, "paper cuts lethal max HP")
                    state = replace(state, max_hp=state.max_hp - cut)
                    hp = min(hp, state.max_hp)
                if state.late and hp < before and (stabs := power(enemy.powers, "PAINFUL_STABS")):
                    from .encounters import WOUND, add_cards
                    state = add_cards(state, "discard", WOUND, stabs)
                if hp < before and _puzzle(state):
                    return boundary(state, "centennial puzzle draw")
                if not hp:
                    return _lethal(replace(state, hp=0, block=block, powers=powers))
                if thorns:
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
        if state.boundary or state.prompt:
            return state
        enemy = state.enemies[slot]
        if state.late and (demise := power(enemy.powers, "DEMISE")):
            if demise >= enemy.hp or power(enemy.powers, "INTANGIBLE"):
                return boundary(state, "demise lethal or intangible")
            updated = replace(enemy, hp=enemy.hp - demise)
            state = replace(state, enemies=(*state.enemies[:slot], updated, *state.enemies[slot + 1:]))
            state = after_damage(state, enemy, updated)
            if state.boundary or state.outcome:
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
    mittens = state.late and any(r.name == "TOASTY_MITTENS" for r in state.relics)
    if not mittens:
        powers = _tick(powers, ("PLATING",))
    max_energy = state.max_energy
    energy = max_energy + power(powers, "ENERGY_NEXT_TURN")
    if state.late:
        bonus_draw -= power(powers, "MIND_ROT")
        if prep := power(powers, "PREP_TIME"):
            powers = add_power(powers, "VIGOR", prep)
        if power(powers, "CHAINS_OF_BINDING"):
            state = replace(state, hand=tuple(replace(c, variant=late_encounters.unbind(c.variant)) for c in state.hand),
                            **{z: tuple(sorted(late_encounters.unbind(v) for v in getattr(state, z)))
                               for z in ("draw", "discard", "exhaust")})
        if blades := power(powers, "INFINITE_BLADES"):
            from .transitions import _shiv
            if power(powers, "PHANTOM_BLADES") or len(state.hand) + blades + 5 >= HAND_CAP:
                return boundary(state, "infinite blades hand ordering")
            state = _shiv(state, blades)
    powers = set_power(powers, "ENERGY_NEXT_TURN", 0)
    additional_public_energy = 0
    if power(powers, "CLARITY"):
        powers = add_power(powers, "CLARITY", -1)
        bonus_draw += 1
    if power(powers, "RADIANCE"):
        powers = add_power(powers, "RADIANCE", -1)
        energy += 1
        additional_public_energy += 1
    relics = []
    for relic in state.relics:
        if state.late and not relic.used:
            if relic.name == "BREAD" and state.round == 1:
                max_energy += 1
                energy += 1
            if relic.name == "ICE_CREAM":
                energy += state.energy
                additional_public_energy += state.energy
            if relic.name in ("FIDDLE", "SNECKO_EYE"):
                bonus_draw += power(relic.stats, "cards")
            if relic.name in ("SHURIKEN", "KUNAI"):
                relic = replace(relic, counter=0, status="Normal")
            if relic.name == "STONE_CALENDAR":
                if relic.counter is None or relic.counter >= 6:
                    return boundary(state, "stone calendar activation")
                relic = replace(relic, counter=relic.counter + 1)
            if relic.name in ("MR_STRUGGLES", "MERCURY_HOURGLASS"):
                from .transitions import _damage

                dmg = state.round + 1 if relic.name == "MR_STRUGGLES" else power(relic.stats, "damage")
                for enemy in state.enemies:
                    if enemy.hp <= 0:
                        continue
                    if enemy.hp <= dmg or power(enemy.powers, "ASLEEP"):
                        return boundary(state, "start turn damage death or wake")
                    state = _damage(state, enemy.slot, dmg)
                    if state.boundary or state.outcome:
                        return state
        if relic.name in ("HAPPY_FLOWER", "PENDULUM") and relic.counter is not None and not relic.used:
            threshold = power(relic.stats, "turns")
            if threshold <= 0:
                return boundary(state, "happy flower counter")
            counter = (relic.counter + 1) % threshold
            if not counter:
                energy += power(relic.stats, "energy")
                bonus_draw += power(relic.stats, "cards")
            relic = replace(relic, counter=counter, status="Active" if counter == threshold - 1 else "Normal")
        if not relic.used:
            if relic.name == "SEAL_OF_GOLD":
                if state.seal_gold < 3:
                    return boundary(state, "seal of gold insufficient funds")
                state = replace(state, seal_gold=state.seal_gold - 3)
                energy += power(relic.stats, "energy")
                additional_public_energy += power(relic.stats, "energy")
            if relic.name == "CHANDELIER" and state.round == 2:
                energy += power(relic.stats, "energy")
                additional_public_energy += power(relic.stats, "energy")
            if relic.name == "POCKETWATCH":
                if relic.status == "Active":
                    bonus_draw += power(relic.stats, "cards")
                relic = replace(relic, counter=0, status="Active")
            if relic.name == "VELVET_CHOKER":
                relic = replace(relic, counter=0, status="Normal")
            if relic.name == "ART_OF_WAR":
                if relic.status == "Active":
                    energy += power(relic.stats, "energy")
                    additional_public_energy += power(relic.stats, "energy")
                relic = replace(relic, status="Active")
            if relic.name == "RIPPLE_BASIN":
                relic = replace(relic, status="Active")
            if relic.name in ("KUSARIGAMA", "LETTER_OPENER", "ORNAMENTAL_FAN"):
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
    if state.late and (rampart := sum(power(e.powers, "RAMPART") for e in state.enemies if e.hp > 0)):
        state = replace(state, enemies=tuple(replace(e, block=e.block + rampart) if e.name == "TURRET_OPERATOR"
                                            else e for e in state.enemies))
    block = state.block if power(state.powers, "BLUR") else 0
    if state.late and not block:
        block = min(state.block, sum(power(r.stats, "block") for r in state.relics if r.name == "STURDY_CLAMP"))
    if state.round == 1:
        block += sum(power(r.stats, "block") for r in state.relics if r.name == "HORN_CLEAT" and not r.used)
    if state.round == 2:
        block += sum(power(r.stats, "block") for r in state.relics if r.name == "CAPTAINS_WHEEL" and not r.used)
    hp = state.hp
    if poison := power(powers, "POISON"):
        hp, block, powers = _player_damage(state, hp, block, powers, poison, bypass=True)
        if hp < state.hp and _puzzle(state):
            return boundary(state, "centennial puzzle draw")
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
        if state.late and any(r.name == "TOASTY_MITTENS" for r in state.relics) and (
                len(state.hand) + count < 2 or power(powers, "INFINITE_BLADES") or power(powers, "NOXIOUS_FUMES")
                or any(r.name in ("MERCURY_HOURGLASS", "MR_STRUGGLES") for r in state.relics)):
            return boundary(state, "toasty mittens start turn ordering")
        reveal = Boundary("next turn", count, count > len(state.draw))
    if fumes := power(powers, "NOXIOUS_FUMES"):
        from .transitions import _debuff

        for enemy in state.enemies:
            if enemy.hp > 0:
                state = _debuff(state, enemy.slot, "POISON", fumes)
                if state.boundary:
                    return state
    return replace(state, hp=hp, block=block, powers=powers, energy=energy, max_energy=max_energy,
                   round=state.round + 1, additional_public_energy=additional_public_energy,
                   relics=tuple(relics), boundary=reveal, outcome=outcome, sloth_plays=0 if state.late else -1)


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
    if state.outcome or state.boundary or state.prompt:
        return state
    return _start_player(state, prior_powers)
