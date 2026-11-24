"""Fixed-work whole-turn beam over the immutable public state."""
from dataclasses import dataclass, replace
import math
from time import perf_counter_ns

from .encounters import encounter_reason
from .state import END_TURN, Move, State
from .transitions import admission, advance, legal
from .value import SURVIVED, UNRESOLVED, interim, leaf_value


@dataclass(frozen=True, slots=True)
class Config:
    version: int = 1
    width: int = 8
    depth: int = 10
    children: int = 256
    potion_reserve: float = 7.0
    value_win_weight: float = 0.0
    v6_late_coverage: bool = False
    v61_act2_hallways_act3: bool = False
    v61_boss_safe: bool = False
    power_leaf_v62: bool = False
    early_escape_v62: bool = False
    kaiser_v63: bool = False
    wax_fan_v64: bool = False
    silent_cards_v66: bool = False
    silent_cards_v67: bool = False

    def late_root(self, act, room):
        if act == 3:
            return self.v6_late_coverage or self.v61_act2_hallways_act3 or self.v61_boss_safe
        if act == 2 and room == "Boss":
            return self.v6_late_coverage or self.v61_boss_safe
        return act == 2 and room in ("Monster", "Elite") and (self.v61_act2_hallways_act3 or self.v61_boss_safe)

    def __post_init__(self):
        if (any(type(v) is not int for v in (self.version, self.width, self.depth, self.children))
                or any(type(v) is not bool for v in (self.v6_late_coverage, self.v61_act2_hallways_act3,
                                                      self.v61_boss_safe, self.power_leaf_v62, self.early_escape_v62,
                                                      self.kaiser_v63, self.wax_fan_v64, self.silent_cards_v66, self.silent_cards_v67))
                or self.version != 1 or not 2 <= self.width <= 32 or not 2 <= self.depth <= 10
                or not self.width <= self.children <= 1024
                or type(self.potion_reserve) not in (int, float)
                or not math.isfinite(self.potion_reserve) or self.potion_reserve < 0
                or type(self.value_win_weight) not in (int, float)
                or not math.isfinite(self.value_win_weight) or self.value_win_weight < 0):
            raise ValueError("Invalid combat search v2 configuration")
        if self.silent_cards_v67:
            object.__setattr__(self, "silent_cards_v66", True)


@dataclass(frozen=True, slots=True)
class Line:
    state: State
    path: tuple[Move, ...]
    score: tuple[int, float]
    root: int


@dataclass(frozen=True, slots=True)
class Result:
    choice: Move
    line: Line | None = None
    root_scores: tuple[tuple[int, float] | None, ...] = ()
    no_potion: Line | None = None
    with_potion: Line | None = None
    root_count: int = 0
    covered_roots: int = 0
    attempts: int = 0
    duplicates: int = 0
    width_pruned: int = 0
    reached_depth: int = 0
    child_cap: bool = False
    depth_cap: bool = False
    fallback: str = ""
    boundary_counts: tuple[tuple[str, int], ...] = ()
    leaf_ns: int | None = None


@dataclass(frozen=True, slots=True)
class _Node:
    state: State
    path: tuple[Move, ...]
    root: int
    priority: tuple[float, float]


class _Search:
    def __init__(self, root_moves, champion, config, model, record_timing, boss_safe, curse_preferences):
        self.config = config
        self.champion = champion
        self.root_moves = root_moves
        self.attempts = self.duplicates = self.width_pruned = self.reached_depth = 0
        self.child_cap = self.depth_cap = False
        self.boundaries = {}
        self.scores = [None] * len(root_moves)
        self.certified = [None] * len(root_moves)
        self.strata = [None, None]
        self.seen = {}
        self.model = model
        self.record_timing = record_timing
        self.leaf_ns = None
        self.kaiser = False
        self.boss_safe = boss_safe
        self.curse_preferences = curse_preferences

    def continuations(self, state):
        if self.boss_safe and state.curse_options:
            if self.curse_preferences is None:
                return ()
            other = state.curse_options[1][0]
            index = int(other in self.curse_preferences)
            return (Move("select_cards", selection=(index,)),)
        return legal(state)

    def key(self, line):
        return line.score, line.root == self.champion, -line.root, -len(line.path)

    def leaf(self, state, path, root):
        if state.boundary and not state.outcome:
            reason = state.boundary.reason
            self.boundaries[reason] = self.boundaries.get(reason, 0) + 1
        started = (perf_counter_ns() if self.record_timing and self.leaf_ns is None
                   and state.outcome == "completed" else None)
        score = leaf_value(state, self.config.potion_reserve, self.model, self.config.value_win_weight,
                           boss_safe=self.boss_safe, power_leaf_v62=self.config.power_leaf_v62)
        if started is not None:
            self.leaf_ns = perf_counter_ns() - started
        line = Line(state, path, score, root)
        previous = self.scores[root]
        if previous is None or self.key(line) > self.key(previous):
            self.scores[root] = line
        if line.score[0] == UNRESOLVED:
            return
        previous = self.certified[root]
        if previous is None or self.key(line) > self.key(previous):
            self.certified[root] = line
        stratum = int(state.spent > 0)
        previous = self.strata[stratum]
        if previous is None or self.key(line) > self.key(previous):
            self.strata[stratum] = line

    def child(self, state, path, root, move):
        if len(path) >= self.config.depth:
            self.depth_cap = True
            return None
        if self.attempts >= self.config.children:
            self.child_cap = True
            return None
        self.attempts += 1
        path = (*path, move)
        self.reached_depth = max(self.reached_depth, len(path))
        successor = advance(state, move)
        if successor.boundary or successor.outcome:
            self.leaf(successor, path, root)
            return None
        priority = interim(successor, self.config.potion_reserve, boss_safe=self.boss_safe,
                           power_leaf_v62=self.config.power_leaf_v62)
        return _Node(successor, path, root, priority)

    def finish(self, node):
        if node.state.prompt is None:
            pending = self.child(node.state, node.path, node.root, END_TURN)
            if pending and pending.state.curse_options:
                for move in self.continuations(pending.state):
                    self.child(pending.state, pending.path, pending.root, move)

    def _rank(self, node, axis=0):
        return (*node.priority[axis:], *node.priority[:axis], node.root == self.champion, -node.root)

    def beam(self, frontier):
        unique = {}
        for node in frontier:
            old = unique.get(node.state)
            if old is not None:
                self.duplicates += 1
            if old is None or self._rank(node) > self._rank(old):
                unique[node.state] = node
        available = []
        for node in unique.values():
            previous = self.seen.get(node.state)
            rank = (len(node.path), node.root != self.champion, node.root)
            if previous is not None and previous <= rank:
                self.duplicates += 1
            else:
                available.append(node)
        safety = sorted(available, key=self._rank, reverse=True)
        progress = sorted(available, key=lambda node: self._rank(node, 1), reverse=True)
        width = self.config.width
        retained = []
        retained_states = set()

        def take(ordered, quota, predicate):
            for node in ordered:
                if quota == 0 or len(retained) == width:
                    break
                if node.state not in retained_states and predicate(node):
                    retained.append(node)
                    retained_states.add(node.state)
                    quota -= 1

        # Guaranteed continuation slots, charged to the same fixed total cap.
        take(safety, 1, lambda n: n.root == self.champion)
        for spent, quota in ((False, (width + 1) // 2), (True, width // 2)):
            def predicate(node):
                return bool(node.state.spent) == spent

            quota -= sum(predicate(n) for n in retained)
            if quota > 0:
                take(safety, (quota + 1) // 2, predicate)
                take(progress, quota // 2, predicate)
        take(progress, (width - len(retained) + 1) // 2, lambda n: True)
        take(safety, width, lambda n: True)
        self.width_pruned += len(available) - len(retained)
        for node in retained:
            self.seen[node.state] = (len(node.path), node.root != self.champion, node.root)
        return retained

    def run(self, state):
        self.kaiser = state.kaiser_v63
        frontier = []
        order = sorted(range(len(self.root_moves)), key=lambda i: i != self.champion)
        # Give every root a first-step trial before extending an individual root.
        for root in order:
            node = self.child(state, (), root, self.root_moves[root])
            if node:
                frontier.append(node)
        # Each root gets a completed-turn comparator where a stable state is
        # reachable directly. Pending operations receive their own first trial
        # before global pruning, including the mandatory End Turn afterward.
        for node in frontier:
            if node.state.prompt is None:
                self.finish(node)
                continue
            for move in self.continuations(node.state):
                child = self.child(node.state, node.path, node.root, move)
                if child:
                    self.finish(child)
                if self.scores[node.root] is not None or self.child_cap:
                    break

        for _ in range(1, self.config.depth):
            if not frontier or self.child_cap:
                break
            parents = self.beam(frontier)
            frontier = []
            # Round-robin widths preserve the reserved nodes under a late cap.
            moves = [iter(move for move in self.continuations(node.state) if move != END_TURN) for node in parents]
            active = list(zip(parents, moves))
            while active and not self.child_cap:
                remaining = []
                for node, choices in active:
                    move = next(choices, None)
                    if move is not None:
                        child = self.child(node.state, node.path, node.root, move)
                        if child:
                            frontier.append(child)
                            self.finish(child)
                        remaining.append((node, choices))
                    if self.child_cap:
                        break
                active = remaining

        return self.result()

    def result(self):
        champion = self.root_moves[self.champion]
        known = [line for line in self.certified if line is not None]
        best = max(known, key=self.key, default=None)
        champion_known = self.certified[self.champion]
        fallback = ""
        if best is None or best.score[0] < SURVIVED:
            fallback = "no certified survival"
        elif self.kaiser and best.state.outcome == "victory":
            pass
        elif self.kaiser and champion_known is not None and champion_known.state.outcome == "dead":
            # A witnessed surviving alternative beats the champion's best certified death.
            pass
        elif champion_known is None:
            fallback = "champion continuation unresolved"
        elif (self.child_cap or self.depth_cap) and not self.kaiser and any(line is None for line in self.certified):
            fallback = "uncertified root at cap"
        elif any(line is None for line in self.scores):
            fallback = "uncompared root at cap" if self.child_cap or self.depth_cap else "uncompared root"
        elif self.root_moves[self.champion].kind == "use_potion" and self.strata[0] is None:
            fallback = "no no-potion comparison"
        if fallback:
            best = self.scores[self.champion]
        choice = self.root_moves[best.root] if best and not fallback else champion
        return Result(choice, best, tuple(line.score if line else None for line in self.scores),
                      *self.strata, len(self.root_moves), sum(line is not None for line in self.scores),
                      self.attempts, self.duplicates, self.width_pruned, self.reached_depth,
                      self.child_cap, self.depth_cap, fallback, tuple(sorted(self.boundaries.items())),
                      self.leaf_ns)


def search(projected, roots, champion, config=Config(), *, model=None, record_timing=False, curse_preferences=None):
    """Only a projection and local action coordinates enter the online kernel."""
    state = projected.state
    late = config.late_root(state.act, state.room)
    v61_rules = late and (config.v61_act2_hallways_act3 or config.v61_boss_safe)
    kaiser = config.kaiser_v63 and late and state.act == 2 and state.room == "Boss" and bool(state.enemies) and all(
        e.name in ("CRUSHER", "ROCKET") for e in state.enemies)
    if (state.late != late or state.v61_rules != v61_rules or state.kaiser_v63 != kaiser
            or state.silent_cards_v66 != config.silent_cards_v66 or state.silent_cards_v67 != config.silent_cards_v67):
        projected = replace(projected, state=replace(state, late=late, v61_rules=v61_rules, kaiser_v63=kaiser,
                                                     silent_cards_v66=config.silent_cards_v66, silent_cards_v67=config.silent_cards_v67))
    boss_safe = config.v61_boss_safe and state.act == 2 and state.room == "Boss"
    if boss_safe and state.curse_options:
        return Result(champion, root_count=len(roots), fallback="champion knowledge curse")
    if reason := encounter_reason(projected.state) or admission(projected):
        return Result(champion, root_count=len(roots), fallback=reason)
    if champion not in roots or roots != legal(projected.state):
        return Result(champion, root_count=len(roots), fallback="root legal mismatch")
    if len(roots) < 2:
        return Result(champion, root_count=len(roots), fallback="forced")
    if len(roots) > config.children:
        return Result(champion, root_count=len(roots), fallback="root exceeds child cap", child_cap=True)
    return _Search(roots, roots.index(champion), config, model, record_timing, boss_safe, curse_preferences).run(projected.state)
