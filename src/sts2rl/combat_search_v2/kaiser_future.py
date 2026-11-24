"""Two public successor moves of the pinned A10 Kaiser graphs (902623e)."""
from .state import power

# Ordered from each arm's initial move. The host exposes the combat round and
# current intent even when Intangible makes several damage previews identical.
# Each row contains intent kinds, base damage per hit, hit count and Strength gain.
_CYCLES = {
    "CRUSHER": (
        (("Attack",), 14, 1, 0), (("Attack",), 4, 1, 0),
        (("Attack", "Debuff"), 7, 2, 0), (("Buff",), 0, 0, 3),
        (("Attack", "Defend"), 14, 1, 0),
    ),
    "ROCKET": (
        (("Attack",), 4, 1, 0), (("Attack",), 20, 1, 0),
        (("Buff",), 0, 0, 3), (("Attack",), 35, 1, 0), (("Sleep",), 0, 0, 0),
    ),
}


def future_defense(state):
    completed = state.outcome == "completed"
    # Completed nodes have advanced exactly one simulated round. Their intent
    # rows still describe the old moves. No native next-turn board is consulted.
    phase = (state.round - 1 - completed) % 5
    live = [e for e in state.enemies if e.hp > 0]
    surrounded = len(live) == 2 and power(state.powers, "SURROUNDED") and state.facing >= 0
    weak_rate = 0.4 if any(r.name == "PAPER_KRANE" and not r.used for r in state.relics) else 0.25
    value = 0.0
    for enemy in live:
        cycle = _CYCLES[enemy.name]
        kinds, _, _, gain = cycle[phase]
        if tuple(i.kind for i in enemy.intents) != kinds:
            continue  # e.g. a substituted stun has no qualified successor here
        strength = power(enemy.powers, "STRENGTH") + (0 if completed else gain)
        weak = power(enemy.powers, "WEAK") - (0 if completed else 1)
        behind = surrounded and state.facing != enemy.slot
        for ahead, discount in ((1, 1.0), (2, 0.5)):
            _, base, hits, gain = cycle[(phase + ahead) % 5]
            damage = hits * max(0, base + strength)
            strength += gain
            # Player durations have already ticked at the completed boundary.
            ticks = ahead - int(completed)
            if power(state.powers, "INTANGIBLE") > ticks:
                continue
            if power(state.powers, "VULNERABLE") > ticks:
                damage *= 1.5
            if weak >= ahead:
                value += discount * weak_rate * damage * (1.5 if behind else 1)
            if ahead == 1 and behind:
                # Re-targeting next turn can avoid this exposure, but costs a
                # targeted play. Discount it against the four-point current HP term.
                value -= 0.75 * 0.5 * damage
    return value


def focused_progress(rocket_progress, rocket_hp, crusher_hp):
    # Smoothly reward finishing the last 30 HP of Crusher only when Rocket
    # would still need at least 45 more damage. Ordinary early chip earns zero.
    finish = max(0, min(30 - crusher_hp, (rocket_hp - crusher_hp - 45) / 2))
    return rocket_progress + 1.5 * finish
