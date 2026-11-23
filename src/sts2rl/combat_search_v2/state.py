"""Versioned public combat projection. Only this module reads the observation."""
from dataclasses import dataclass, replace

SCHEMA = 1
HAND_CAP = 10
Powers = tuple[tuple[str, int], ...]


class Unsupported(ValueError):
    """The projection or a transition lacks a qualified public rule."""


def entry(value):
    return value.split(".", 1)[-1]


def integer(value):
    if type(value) not in (int, float) or int(value) != value:
        raise Unsupported("nonintegral public value")
    return int(value)


def numbers(values):
    return tuple(sorted((name.lower(), integer(value)) for name, value in (values or {}).items()))


def power(powers, name):
    return next((value for key, value in powers if key == name), 0)


def set_power(powers, name, value):
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
                   flags, tuple(modifiers), numbers(card.get("stats")) if pile else ())


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


def project(public):
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
    potions = tuple(Potion(slot, entry(p["id"]), p["target_type"], p["can_use"], numbers(p.get("vars")))
                    for slot, p in enumerate(potion_rows))
    relics = tuple(Relic(entry(r["id"]), integer(r["counter"]) if r.get("counter") is not None else None,
                         bool(r.get("is_used_up")), numbers(r.get("vars")), r.get("status", "Normal"),
                         integer(r.get("stack_count", 1))) for r in player.get("relics", ()))
    powers = _powers(view.get("player_powers"))
    state = State(integer(player["hp"]), integer(player["max_hp"]), integer(player.get("block", 0)),
                  integer(view["energy"]), integer(view["max_energy"]), integer(view["round"]),
                  integer(ctx["act"]), ctx["room_type"], powers, tuple(enemies),
                  tuple(Card(i, _variant(card)) for i, card in enumerate(hand)),
                  *piles, potions, relics, len(hand), power(powers, "VULNERABLE") > 0,
                  power(powers, "INTANGIBLE") > 0)
    prompt_indices = ()
    if is_prompt:
        state, prompt_indices = _public_prompt(public, state)
    return Projection(state, _indices(hand), _indices(enemy_rows), _indices(potion_rows), prompt_indices,
                      tuple(card["can_play"] for card in hand),
                      tuple(e.name for e in enemies))


def _public_prompt(public, state):
    source = public.get("selection_source") or {}
    card = entry(source.get("id", ""))
    if source.get("kind") != "play_card" or card not in ("SURVIVOR", "ACROBATICS", "PREPARED"):
        raise Unsupported("selection operation")
    if len(state.play) != 1 or state.play[0].name != card:
        raise Unsupported("selection continuation")
    # No native public replay count at a prompt. A replay can have depleted
    # the last visible stack before suspending, so require independent proof
    # of its continuation (the online wrapper reconciles a prior public line).
    if power(state.powers, "BURST") or power(state.powers, "DUPLICATION"):
        raise Unsupported("selection replay")
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
    if kind == "play_card":
        slot = projected.hand_indices.index(args["card_index"])
        target = projected.enemy_indices.index(args["target_index"]) if "target_index" in args else -1
        return Move(kind, slot, target)
    if kind == "use_potion":
        target = projected.enemy_indices.index(args["target_index"]) if "target_index" in args else -1
        return Move(kind, projected.potion_indices.index(args["potion_index"]), target)
    if kind in ("select_cards", "skip_select"):
        indices = tuple(map(int, args["indices"].split(","))) if kind == "select_cards" else ()
        return Move("select_cards", selection=tuple(projected.prompt_indices.index(i) for i in indices))
    if kind == "end_turn":
        return END_TURN
    raise Unsupported("root action")
