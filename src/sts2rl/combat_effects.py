"""Resolve public block previews and ordered debuff applications."""
from math import comb


def power(powers, key):
    return next((p["amount"] for p in powers or [] if p["id"] == f"POWER.{key}_POWER"), 0)


def block_preview(stats, *, legacy_dex=0):
    # Hand stats are PreviewValue after the native Dexterity and Frail hooks.
    block = stats.get("calculatedblock", stats.get("block", 0))
    return max(0, block + legacy_dex) if block else 0


def debuff_order(item, stats, enemy, *, energy=0):
    """One entry per application. Artifact consumes applications, not their magnitudes."""
    name = item.get("id", "")
    if item.get("target_type") in ("Self", "AnyPlayer", "AnyAlly"):
        return ()
    poison = stats.get("poisonpower", stats.get("poison", 0))
    if name == "CARD.BUBBLE_BUBBLE" and power(enemy.get("powers"), "POISON") <= 0:
        poison = 0
    weak = stats.get("weakpower", stats.get("weak", 0))
    strength_loss = stats.get("strengthloss", 0)
    vulnerable = stats.get("vulnerablepower", 0)
    if name == "CARD.MALAISE":
        strength_loss = weak = energy + int(bool(item.get("upgrades")))
    if name == "CARD.EXPOSE":
        vulnerable = stats.get("power", 2)
    if name == "POTION.SHACKLING_POTION":
        strength_loss = stats.get("strengthpower", 0)
    applications = [("poison", poison)] * (stats.get("repeat", 1) if name == "CARD.BOUNCING_FLASK" else 1)
    applications.extend((("strength_loss", strength_loss), ("weak", weak), ("vulnerable", vulnerable)))
    return tuple((kind, amount) for kind, amount in applications if amount > 0)


def landed_debuffs(item, applications, artifact, *, targets=1):
    """Expected amounts on one target, including random bounces onto its remaining Artifact."""
    if item.get("id") == "CARD.EXPOSE":
        artifact = 0
    random_target = item.get("target_type") == "RandomEnemy" and targets > 1
    if random_target and item.get("id") == "CARD.BOUNCING_FLASK" and applications:
        # Bouncing Flask makes independent uniform draws, with replacement.
        hits = len(applications)
        chance = 1 / targets
        landed = sum((k - artifact) * comb(hits, k) * chance**k * (1 - chance)**(hits - k)
                     for k in range(artifact + 1, hits + 1))
        kind, dose = applications[0]
        return {kind: dose * landed}
    result = {}
    for kind, amount in applications[max(0, artifact):]:
        result[kind] = result.get(kind, 0) + (amount / targets if random_target else amount)
    return result
