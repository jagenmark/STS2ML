"""Versioned public combat projection. Only this module reads the observation."""
from dataclasses import dataclass, replace

SCHEMA = 1
HAND_CAP = 10
Powers = tuple[tuple[str, int], ...]
CARD_STATS = (
    "afterimagepower", "block", "blur", "bufferpower", "cards", "damage", "energy",
    "poisonpower", "repeat", "skills", "strengthloss", "vulnerablepower", "weakpower",
)
POTION_STATS = (
    "Block", "Cards", "Damage", "DexterityPower", "Energy", "IntangiblePower",
    "PlatingPower", "PoisonPower", "StrengthPower", "ThornsPower", "VulnerablePower", "WeakPower",
)
RELIC_STATS = ("Block", "Cards", "Damage", "DexterityPower", "Energy", "ExtraDamage", "StrengthPower", "Turns")


class Unsupported(ValueError):
    """The projection or a transition lacks a qualified public rule."""


def entry(value):
    return value.split(".", 1)[-1]


def integer(value):
    if type(value) not in (int, float) or int(value) != value:
        raise Unsupported("nonintegral public value")
    return int(value)


def numbers(values, keys):
    values = values or {}
    return tuple((name.lower(), integer(values[name])) for name in keys if name in values)


def power(powers, name):
    for key, value in powers:
        if key == name:
            return value
    return 0


def set_power(powers, name, value):
    if not value and not power(powers, name):
        return powers
    return tuple(sorted((*((key, n) for key, n in powers if key != name),
                         *(((name, value),) if value else ()))))


def add_power(powers, name, amount):
    return set_power(powers, name, power(powers, name) + amount)


@dataclass(frozen=True, slots=True, order=True)
class Variant:
    name: str
    kind: str
    cost: int
    target: str
    upgrade: int = 0
    keywords: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()
    modifier: tuple[tuple[str, str, int], ...] = ()
    stats: Powers = ()


@dataclass(frozen=True, slots=True)
class Card:
    slot: int
    variant: Variant


@dataclass(frozen=True, slots=True)
class Potion:
    slot: int
    name: str
    target: str
    usable: bool
    stats: Powers = ()


@dataclass(frozen=True, slots=True)
class Relic:
    name: str
    counter: int | None
    used: bool
    stats: Powers = ()
    status: str = "Normal"
    stacks: int = 1


@dataclass(frozen=True, slots=True)
class Intent:
    kind: str
    damage: int | None = None
    hits: int = 1


@dataclass(frozen=True, slots=True)
class Enemy:
    slot: int
    name: str
    hp: int
    max_hp: int
    block: int
    powers: Powers
    intents: tuple[Intent, ...]
    # Root modifiers identify the meaning of the rounded public attack preview.
    preview_strength: int
    preview_weak: bool
    attack_delta: int = 0


@dataclass(frozen=True, slots=True)
class Play:
    card: Card
    target: int = -1
    x: int = 0
    replay: bool = False


@dataclass(frozen=True, slots=True)
class Effect:
    kind: str
    amount: int = 0
    play: Play | None = None
    slots: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class Prompt:
    operation: str
    candidates: tuple[int, ...]
    minimum: int
    maximum: int


@dataclass(frozen=True, slots=True)
class Boundary:
    reason: str
    count: int = 0
    shuffle: bool = False


@dataclass(frozen=True, slots=True)
class Move:
    kind: str
    slot: int = -1
    target: int = -1
    selection: tuple[int, ...] = ()


END_TURN = Move("end_turn")


@dataclass(frozen=True, slots=True)
class State:
    hp: int
    max_hp: int
    block: int
    energy: int
    max_energy: int
    round: int
    act: int
    room: str
    powers: Powers
    enemies: tuple[Enemy, ...]
    hand: tuple[Card, ...]
    draw: tuple[Variant, ...] = ()
    discard: tuple[Variant, ...] = ()
    exhaust: tuple[Variant, ...] = ()
    play: tuple[Variant, ...] = ()
    potions: tuple[Potion, ...] = ()
    relics: tuple[Relic, ...] = ()
    next_slot: int = 0
    preview_vulnerable: bool = False
    preview_intangible: bool = False
    prompt: Prompt | None = None
    queue: tuple[Effect, ...] = ()
    boundary: Boundary | None = None
    outcome: str = ""  # victory, dead, or completed
    spent: int = 0
    schema: int = SCHEMA
    floor: int = 0
    seal_gold: int = 0
    additional_public_energy: int = 0
    late: bool = False
    facing: int = -1
    preview_facing: int = -1
    sloth_plays: int = -1
    right_hand_return: bool = False
    bound_used: bool = False
    aeon_plays: int = -1
    curse_number: int = -1
    curse_options: tuple = ()
    tender_plays: int = -1
    reattach_pending: bool = True
    remnant_floor: int | None = None
    v61_rules: bool = False
    kaiser_v63: bool = False
    puzzle_triggered: bool = False
    melted_fan: bool = False

    @property
    def hallway(self):
        return self.late and self.act == 2 and self.room in ("Monster", "Elite")


@dataclass(frozen=True, slots=True)
class Projection:
    state: State
    hand_indices: tuple[int, ...]
    enemy_indices: tuple[int, ...]
    potion_indices: tuple[int, ...]
    prompt_indices: tuple[int, ...]
    playable: tuple[bool, ...]
    # Kept outside the state hash used for continuation deduplication.
    formation: tuple[str, ...]


def _variant(card, *, pile=False):
    flags = tuple(key for key in ("costs_x", "stars_x", "exhaust_on_next_play",
                                  "retain_this_turn", "sly_this_turn") if card.get(key))
    star = integer(card.get("star_cost", -1))
    if star > 0:
        flags += ("star_cost",)
    modifiers = []
    for key in ("enchantment_state", "affliction_state"):
        if modifier := card.get(key):
            modifiers.append((key, entry(modifier["id"]), integer(modifier.get("amount", 0))))
    for key in ("enchantment", "affliction"):
        if card.get(key) and not card.get(f"{key}_state"):
            modifiers.append((key, "unqualified", 0))
    return Variant(entry(card["id"]), card["type"], integer(card["cost"]), card["target_type"],
                   integer(card.get("upgrades", 0)), tuple(sorted(card.get("keywords") or ())),
                   flags, tuple(modifiers), numbers(card.get("stats"), CARD_STATS) if pile else ())


def _powers(rows):
    # The host's list order can be relevant to hooks. The qualified subset uses
    # explicit priorities, and disallows duplicate owners with indistinct IDs.
    result = tuple(sorted((entry(row["id"]).removesuffix("_POWER"), integer(row["amount"]))
                          for row in rows or ()))
    if len({name for name, _ in result}) != len(result):
        raise Unsupported("duplicate power")
    return result


def _indices(rows):
    indices = tuple(integer(row["index"]) for row in rows)
    if len(set(indices)) != len(indices):
        raise Unsupported("duplicate physical index")
    return indices


def project(public, *, late_prompts=False):
    """Read explicit fields only, with stable local slots and unordered piles."""
    decision = public["decision"]
    is_prompt = decision == "card_select"
    if is_prompt and public.get("in_combat"):
        view = public["combat_state"]
    elif decision == "combat_play":
        view = public
    else:
        raise Unsupported("decision")
    if view.get("observation_version") != 2 or view.get("pile_order") != "unordered":
        raise Unsupported("observation schema")
    if view.get("orbs"):
        raise Unsupported("active orb")
    if (view.get("osty") or {}).get("alive"):
        raise Unsupported("living Osty")
    player, ctx = view["player"], view["context"]
    hand = view["hand"]
    if len(hand) > HAND_CAP:
        raise Unsupported("hand capacity")
    enemy_rows = view["enemies"]
    enemies = []
    for slot, row in enumerate(enemy_rows):
        powers = _powers(row.get("powers"))
        intents = tuple(Intent(intent["type"], integer(intent["damage"]) if "damage" in intent
                               else None, integer(intent.get("hits", 1)))
                        for intent in row.get("intents") or ())
        enemies.append(Enemy(slot, entry(row["id"]), integer(row["hp"]), integer(row["max_hp"]),
                             integer(row.get("block", 0)), powers, intents,
                             power(powers, "STRENGTH"), power(powers, "WEAK") > 0))
    piles = []
    for key in ("draw", "discard", "exhaust", "play"):
        zone = tuple(sorted(_variant(card, pile=True) for card in view[f"{key}_pile"]))
        if integer(view.get(f"{key}_pile_count", len(zone))) != len(zone):
            raise Unsupported(f"{key} pile count")
        piles.append(zone)
    potion_rows = player["potions"]
    potions = tuple(Potion(slot, entry(p["id"]), p["target_type"], p["can_use"],
                           numbers(p.get("vars"), (*POTION_STATS, "Repeat") if late_prompts and
                                   entry(p["id"]) == "STABLE_SERUM" else POTION_STATS))
                    for slot, p in enumerate(potion_rows))
    relics = tuple(Relic(entry(r["id"]), integer(r["counter"]) if r.get("counter") is not None else None,
                         bool(r.get("is_used_up")), numbers(r.get("vars"), RELIC_STATS), r.get("status", "Normal"),
                         integer(r.get("stack_count", 1))) for r in player.get("relics", ()))
    powers = _powers(view.get("player_powers"))
    state = State(integer(player["hp"]), integer(player["max_hp"]), integer(player.get("block", 0)),
                  integer(view["energy"]), integer(view["max_energy"]), integer(view["round"]),
                  integer(ctx["act"]), ctx["room_type"], powers, tuple(enemies),
                  tuple(Card(i, _variant(card)) for i, card in enumerate(hand)),
                  *piles, potions, relics, len(hand), power(powers, "VULNERABLE") > 0,
                  power(powers, "INTANGIBLE") > 0, floor=integer(ctx.get("floor", 0)),
                  seal_gold=integer(player["gold"]) if any(r.name == "SEAL_OF_GOLD" for r in relics) else 0)
    prompt_indices = ()
    if late_prompts and state.act == 2 and state.room == "Elite" and any(
            e.name.startswith("DECIMILLIPEDE_SEGMENT_") for e in enemies):
        history = view.get("public_combat_history") or ()
        # A segment which was alive at this turn's public opening can miss
        # its first move. An earlier knockout might already be due to revive.
        names = {e.name for e in enemies if e.hp > 0}
        if history and history[-1].get("round") == state.round:
            names = {entry(e["id"]) for e in history[-1]["enemies"] if e["hp"] > 0}
        state = replace(state, reattach_pending=names != {
            "DECIMILLIPEDE_SEGMENT_FRONT", "DECIMILLIPEDE_SEGMENT_MIDDLE", "DECIMILLIPEDE_SEGMENT_BACK"})
    if late_prompts and tuple(e.name for e in enemies) == ("KNOWLEDGE_DEMON",):
        history = view.get("public_combat_history") or ()
        if ([h.get("round") for h in history] == list(range(1, state.round + 1))
                and all(len(h["enemies"]) == 1 and h["enemies"][0]["id"] == "MONSTER.KNOWLEDGE_DEMON"
                        for h in history)):
            prior = [h["enemies"][0]["intents"] for h in history[:-1]]
            if all(not any(i["type"] == "Stun" for i in intents) for intents in prior):
                state = replace(state, curse_number=sum(intents == [{"type": "Debuff"}] for intents in prior))
    if is_prompt:
        state, prompt_indices = _public_prompt(public, state, late_prompts)
    return Projection(state, _indices(hand), _indices(enemy_rows), _indices(potion_rows), prompt_indices,
                      tuple(card["can_play"] for card in hand),
                      tuple(e.name for e in enemies))


def _public_prompt(public, state, late_prompts=False):
    source = public.get("selection_source") or {}
    card = entry(source.get("id", ""))
    if (late_prompts and source == {"kind": "end_turn"} and len(state.enemies) == 1
            and state.enemies[0].name == "KNOWLEDGE_DEMON" and not state.play
            and public.get("min_select") == public.get("max_select") == 1):
        from .late_encounters import curse_options
        rows = public["cards"]
        for ordinal in range(3):
            options = curse_options(ordinal)
            if len(rows) == 2 and all(entry(row["id"]) == name and
                (row.get("stats") or {}).get(name.lower().replace("_", "") + "power") == amount
                for (name, amount), row in zip(options, rows)):
                return replace(state, prompt=Prompt("KNOWLEDGE_CURSE", (0, 1), 1, 1),
                               curse_number=ordinal, curse_options=options), _indices(rows)
    mittens = (late_prompts and state.round > 1 and source == {"kind": "end_turn"} and not state.play
               and any(r.name == "TOASTY_MITTENS" for r in state.relics)
               and public.get("min_select") == public.get("max_select") == 1)
    if mittens:
        card = "TOASTY_MITTENS"
    elif source.get("kind") != "play_card" or (card not in ("SURVIVOR", "ACROBATICS", "PREPARED", "DAGGER_THROW")
                                              and not (late_prompts and card == "HIDDEN_DAGGERS")):
        raise Unsupported("selection operation")
    if not mittens and (len(state.play) != 1 or state.play[0].name != card):
        raise Unsupported("selection continuation")
    rows = public["cards"]
    if len(rows) != len(state.hand) or any(
        entry(row["id"]) != c.variant.name or bool(row.get("upgraded")) != bool(c.variant.upgrade)
        for row, c in zip(rows, state.hand)
    ):
        raise Unsupported("selection mapping")
    lo, hi = integer(public["min_select"]), integer(public["max_select"])
    if not 0 <= lo <= hi <= len(rows):
        raise Unsupported("selection bounds")
    return replace(state, prompt=Prompt(card, tuple(c.slot for c in state.hand), lo, hi)), _indices(rows)


def root_move(projected, kind, args):
    """Translate stamped native arguments without reading stamps or action IDs."""
    target = -1
    if "target_index" in args:
        position = projected.enemy_indices.index(args["target_index"])
        target = tuple(e.slot for e in projected.state.enemies if e.hp > 0)[position]
    if kind == "play_card":
        slot = projected.state.hand[projected.hand_indices.index(args["card_index"])].slot
        return Move(kind, slot, target)
    if kind == "use_potion":
        slot = projected.state.potions[projected.potion_indices.index(args["potion_index"])].slot
        return Move(kind, slot, target)
    if kind in ("select_cards", "skip_select"):
        indices = tuple(map(int, args["indices"].split(","))) if kind == "select_cards" else ()
        return Move("select_cards", selection=tuple(
            projected.state.prompt.candidates[projected.prompt_indices.index(i)] for i in indices))
    if kind == "end_turn":
        return END_TURN
    raise Unsupported("root action")
