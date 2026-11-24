"""Read-only one-turn leaf diagnostics. All inputs precede the physical action."""

from collections import Counter
from functools import lru_cache
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from sts2rl.combat_search_v2.state import END_TURN, power
from sts2rl.combat_search_v2.transitions import advance

GRAPH = "902623ec3f1515721552bdc672fbda5224b61bbf"
TABLE = "9092ea410524db1a9dfeac52188f358790717942"


def prepare_rules(directory):
    for rev, src, dest in (
        (GRAPH, "next_intent.py", "graph.py"),
        (TABLE, "next_intent.py", "table.py"),
        (GRAPH, "enemy_move_graphs.json", "graphs.json"),
    ):
        (directory / dest).write_bytes(
            subprocess.check_output(["git", "show", f"{rev}:src/sts2rl/combat_search_v2/{src}"])
        )


@lru_cache
def rules(directory):
    modules = []
    for stem in ("graph", "table"):
        name = f"sts2rl.combat_search_v2._audit_{stem}"
        spec = spec_from_file_location(name, Path(directory) / f"{stem}.py")
        module = module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        modules.append(module)
    return *modules, json.loads((Path(directory) / "graphs.json").read_bytes())


def axes(line, power_slots):
    state = line.state
    remaining = sum(max(0, e.hp - min(e.hp, power(e.powers, "POISON"))) for e in state.enemies)
    setup = sum(m.kind == "play_card" and m.slot in power_slots for m in line.path)
    return state.hp + state.block, -remaining, setup


def witnesses(lines, band, power_slots):
    best = max((line.score[1] for line in lines), default=0)
    distinct = {}
    for line in lines:
        if line.score[1] >= best - band:
            key = line.root, axes(line, power_slots)
            if key not in distinct or line.score > distinct[key].score:
                distinct[key] = line
    ranked = sorted(distinct.items(), key=lambda item: item[1].score, reverse=True)
    for i, ((root, a), first) in enumerate(ranked):
        for (other, b), second in ranked[i + 1 :]:
            if root == other or a[0] == b[0]:
                continue
            safer, faster = (a, b) if a[0] > b[0] else (b, a)
            if faster[1] >= safer[1] + 3 or faster[2] > safer[2]:
                return first, second
    return ()


def pile_signals(state, view):
    draw, discard = state.draw, state.discard
    signals = set()
    if len(draw) < 5 and discard:
        signals.add("reshuffle_possible")
    if len(draw) >= 5 and discard:

        def density(pile, feature):
            return sum(feature(c) for c in pile) / len(pile)

        for name, pred in (
            ("attack_density", lambda c: c.kind == "Attack"),
            ("block_density", lambda c: power(c.stats, "block") > 0),
        ):
            if abs(density(draw, pred) - density(discard, pred)) >= 0.25:
                signals.add(name)
            hand_count = sum(
                c["type"] == "Attack"
                if name == "attack_density"
                else (c.get("stats") or {}).get("block", 0) > 0
                for c in view["hand"]
            )
            live_density = (sum(map(pred, draw)) + sum(map(pred, discard)) + hand_count) / (
                len(draw) + len(discard) + len(view["hand"])
            )
            if abs(density(draw, pred) - live_density) >= 0.15:
                signals.add("live_" + name)
        if {c.name for c in draw if c.kind == "Power"} ^ {
            c.name for c in discard if c.kind == "Power"
        }:
            signals.add("power_location")
    return signals


def second_shape(graph, catalogue, state):
    # Ordinary, unconditional edges only. Refuse random/guard nodes, dynamic
    # previews and ambiguous matches. The next player can still kill or stun.
    shapes = []
    for e in state.enemies:
        if e.hp <= 0:
            continue
        options = set()
        for g in catalogue["graphs"].get(e.name, ()):
            nodes = g["nodes"]
            for node in nodes.values():
                if node["type"] != "MoveState" or not graph._matches(state, e, node):
                    continue
                target = nodes.get(node["follow"], {})
                if target.get("type") != "MoveState":
                    return None
                intents = graph._descriptors(target)
                if (
                    len(intents) != len(target["intents"])
                    or not intents
                    or any(not isinstance(hits, int) for _, _, hits in intents)
                ):
                    return None
                options.add(tuple(sorted((kind, hits) for kind, _, hits in intents)))
        if len(options) != 1:
            return None
        shapes.extend(options.pop())
    return tuple(shapes) if shapes else None


def intent_signals(root, line, directory, history):
    from dataclasses import replace

    graph, table, catalogue = rules(directory)
    pre = root
    for move in line.path:
        if move == END_TURN:
            break
        pre = advance(pre, move)
    else:
        return set()
    post = line.state
    signals = set()
    forecast = graph.project_next_intents(pre, post, catalogue, public_history=history)
    living = [e for e in post.enemies if e.hp > 0]
    legacy = [table.next_intent(post, e) for e in living]
    if living and all(legacy):
        signals.add("verified_table_t1")
    if len(forecast.worlds) == 1:
        future = forecast.worlds[0].state
        signals.add("graph_t1")
    elif "verified_table_t1" in signals:
        enemies = tuple(
            replace(
                e,
                intents=table.next_intent(post, e),
                preview_strength=power(e.powers, "STRENGTH"),
                preview_weak=bool(power(e.powers, "WEAK")),
            )
            if e.hp
            else e
            for e in post.enemies
        )
        future = replace(
            post,
            enemies=enemies,
            preview_vulnerable=bool(power(post.powers, "VULNERABLE")),
            preview_intangible=bool(power(post.powers, "INTANGIBLE")),
        )
    else:
        return signals
    signals.add("t1")

    def pressure(state):
        return sum((i.damage or 0) * i.hits for e in state.enemies if e.hp > 0 for i in e.intents)

    now, later = pressure(root), pressure(future)
    if bool(now) != bool(later) or abs(now - later) >= 8:
        signals.add("t1_shift")
    shape = second_shape(graph, catalogue, future)
    if shape:
        signals.add("t2_shape")
        attacking = any(i.damage is not None for e in future.enemies if e.hp > 0 for i in e.intents)
        if attacking != any("Attack" in k or k == "DeathBlow" for k, hits in shape):
            signals.add("t2_attack_switch")
    return signals


def analyze(root, result, lines, directory, view):
    counts = Counter(covered=1)
    # An immediate certified victory dominates all ordinary completed leaves.
    if result.line and result.line.state.outcome == "victory":
        counts["certified_victory"] = 1
        return counts
    if len({line.root for line in lines}) < 2:
        return counts
    counts["two_completed_roots"] = 1
    power_slots = {c.slot for c in root.hand if c.variant.kind == "Power"}
    pair = witnesses(lines, 5, power_slots)
    if pair:
        counts["trade5"] = 1
    else:
        pair = witnesses(lines, 10, power_slots)
    if pair:
        counts["trade10"] = 1
        graph, _, _ = rules(directory)
        projection = SimpleNamespace(
            state=root, enemy_indices=tuple(e["index"] for e in view["enemies"])
        )
        history = graph.public_intent_history(view, projection)
        signals = set.intersection(
            *(intent_signals(root, line, directory, history) for line in pair)
        )
        counts.update(signals)
        signals = pile_signals(root, view)
        if all(line.state.boundary.shuffle and line.state.discard for line in pair):
            counts["both_lines_reshuffle"] = 1
        counts.update(signals)
        if signals - {"reshuffle_possible"}:
            counts["composition"] = 1
        if signals:
            counts["pile"] = 1
    return counts
