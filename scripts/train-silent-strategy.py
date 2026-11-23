"""Label deck, event, merchant and camp actions using matched complete native continuations."""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
from random import Random
from statistics import fmean

from sts2rl.act1 import save_json
from sts2rl.deployed_controller import DeployedController
from sts2rl.encounter import EncounterPolicy
from sts2rl.native import Action, NativeSession, ReplayFork, digest
from sts2rl.offer_policy import OfferModel, offer_type
from sts2rl.provenance import require_provenance, strategy_label_provenance
from sts2rl.routing import RoomModel
from sts2rl.run_bundle import load_bundle
from sts2rl.run_policy import RunPolicy, RunWeights
from sts2rl.strategy import StrategyModel, strategy_arms, strategy_kind
from sts2rl.trajectory import natural_specification, strategy_roots
from sts2rl.turn_planning import choose_turn

ROOT = Path(__file__).resolve().parents[1]
_UNSET = object()


def replay_controller_snapshots(
    session, source: Path, controller: DeployedController, target_steps, *, verify_policy=False
):
    """Replay the recorded prefix once and return cloned DeployedController snapshots at target steps."""
    wanted = set(target_steps)
    if not wanted:
        return {}
    max_step = max(wanted)
    with (Path(source) / "game/rpc.jsonl").open(encoding="utf-8") as stream:
        first = json.loads(next(stream))
        spec = natural_specification(first["command"])
        commands, fingerprints = [], [first["response_digest"]]
        for line in stream:
            row = json.loads(line)
            if row["command"]["cmd"] == "get_map":
                continue
            if row["command"]["cmd"] != "action":
                raise ValueError("Unexpected control command in recorded run")
            commands.append(row["command"])
            fingerprints.append(row["response_digest"])
            if len(commands) >= max_step:
                break
    if len(commands) < max_step:
        raise ValueError("Recorded trace shorter than requested strategy root")
    state = session.restore(ReplayFork(spec, (), fingerprints[0]))
    controller._sync_act(state)
    snapshots = {}
    if 0 in wanted:
        snapshots[0] = controller.clone()
    for step, cmd in enumerate(commands[:max_step]):
        # Construct the recorded Action directly so large multi-card selections do not enumerate the power set.
        kind, args = cmd["action"], cmd.get("args") or {}
        action = Action(digest([kind, args])[:20], kind, args, digest(state))
        if verify_policy:
            proposed = controller.choose(state, session)
            if proposed.command() != cmd:
                raise ValueError(
                    f"Bundle replay diverged at action {step}: {proposed.command()} != {cmd}"
                )
        before = state
        state = session.step(action)
        if digest(state) != fingerprints[step + 1]:
            raise ValueError("Prefix replay diverged from recorded trace")
        controller.observe(before, action, state)
        if step + 1 in wanted:
            snapshots[step + 1] = controller.clone()
    return snapshots


def follow(game, state, actor, router, opening, initial, start_act):
    action = initial
    boss_damage = 0.0
    for _ in range(1100):
        ctx = state["context"]
        if state["decision"] == "combat_play" and ctx["room_type"] == "Boss":
            enemies = state["enemies"]
            if enemies:
                boss_damage = max(
                    boss_damage,
                    1 - sum(e["hp"] for e in enemies) / max(1, sum(e["max_hp"] for e in enemies)),
                )
        if state["decision"] == "game_over" or ctx["act"] > start_act:
            clear = ctx["act"] > start_act or state.get("victory", False)
            floor = 17 if clear else ctx["floor"]
            # Absolute outcome values are compared only within a matched decision.
            return {
                "clear": clear,
                "floor": floor,
                "hp": state["player"]["hp"],
                "return": floor
                + 10 * clear
                + 2 * boss_damage
                + 0.05 * state["player"]["hp"] * clear,
            }
        if action is None:
            if state["decision"] == "map_select" and router is not None:
                action = router.choose(state, game.public_map())
            elif state["decision"] == "combat_play":
                action = (
                    actor(state)
                    if isinstance(actor, EncounterPolicy)
                    else choose_turn(state, actor)
                )
            elif offer_type(state) and opening:
                action = opening.choose(state, actor)
            else:
                action = actor(state)
        if state["decision"] == "rest_site" and any(
            o.get("option_id") == "SMITH" and o["index"] == action.args.get("option_index")
            for o in state["options"]
        ):
            actor.selection = "upgrade"
        state = game.step(action)
        action = None
    raise RuntimeError("Continuation exceeded action budget")


def follow_deployed(game, state, controller: DeployedController, initial, start_act, *, horizon="act"):
    """Follow the deployed bundle through the requested act or to the native run ending."""
    action = initial
    boss_damage = 0.0
    boss = None
    act, floor = start_act, 0
    for _ in range(3000 if horizon == "run" else 1100):
        ctx = state["context"]
        if horizon == "run":
            if ctx["act"] != act:
                act, floor, boss, boss_damage = ctx["act"], 0, None, 0.0
            floor = max(floor, ctx["floor"])
        if state["decision"] == "combat_play" and ctx["room_type"] == "Boss":
            if horizon == "run" and (act, ctx["floor"]) != boss:
                boss, boss_damage = (act, ctx["floor"]), 0.0
            enemies = state["enemies"]
            if enemies:
                boss_damage = max(
                    boss_damage,
                    1 - sum(e["hp"] for e in enemies) / max(1, sum(e["max_hp"] for e in enemies)),
                )
        if horizon == "run" and state["decision"] == "game_over":
            win = state["victory"]
            if type(win) is not bool or state.get("abandoned") or (win and act != 3):
                raise ValueError("Continuation lacks a complete native run outcome")
            return {
                "clear": act > start_act or win,
                "act": act,
                "win": win,
                "floor": floor,
                "hp": state["player"]["hp"],
                "return": 17 * (act - 1) + floor + 10 * win + 2 * boss_damage,
            }
        if horizon == "act" and (state["decision"] == "game_over" or ctx["act"] > start_act):
            clear = ctx["act"] > start_act or state.get("victory", False)
            floor = 17 if clear else ctx["floor"]
            return {
                "clear": clear,
                "floor": floor,
                "hp": state["player"]["hp"],
                "return": floor
                + 10 * clear
                + 2 * boss_damage
                + 0.05 * state["player"]["hp"] * clear,
            }
        if action is None:
            action = controller.choose(state, game)
        before = state
        state = game.step(action)
        controller.observe(before, action, state)
        action = None
    raise RuntimeError("Continuation exceeded action budget")


def collect(task):
    (
        folder,
        source,
        host,
        bundle,
        split_seed,
        max_roots,
        kinds,
        min_act,
        style,
        room_path,
        continuation_mode,
        unified_draft,
        deck_size_penalty,
        horizon,
    ) = task
    folder.mkdir(parents=True, exist_ok=False)
    _, settings = load_bundle(bundle)
    macro_seed = split_seed
    if horizon == "run":
        result = json.loads((source / "result.json").read_text(encoding="utf-8"))
        macro_seed = 7103 + result["index"]
    deployed = None
    if continuation_mode == "bundle":
        # Validate bundle compatibility up front before spawning native sessions.
        deployed = DeployedController.from_bundle(bundle, macro_seed=macro_seed)
    event_fixes_v4 = bool(deployed and deployed.strategy and deployed.strategy.event_fixes_v4)
    weights = RunWeights.load(settings["weights"])
    late_weights = (
        RunWeights.load(settings["late_weights"]) if settings.get("late_weights") else None
    )
    deck_effects = bool(settings.get("deck_effects", False))
    router_file = room_path or settings.get("room_model")
    router = RoomModel.load(router_file) if router_file else None
    opening = OfferModel.load(settings["offer_model"]) if settings.get("offer_model") else None
    stamp = strategy_label_provenance(
        bundle,
        continuation=continuation_mode,
        host_path=host,
        root=ROOT,
        collector=__file__,
        style=style,
        room_model=room_path,
        unified_draft=unified_draft,
        deck_size_penalty=deck_size_penalty,
        horizon=horizon,
    )
    roots = defaultdict(list)
    seed = None
    for state, fork in strategy_roots(source):
        seed = fork.specification["seed"]
        kind = strategy_kind(state)
        act = state["context"]["act"]
        arm_policy = (
            RunPolicy(
                late_weights if (act >= 2 and late_weights is not None) else weights,
                deck_effects=deck_effects,
            )
            if continuation_mode == "bundle"
            else RunPolicy(weights)
        )
        if (
            kind
            and (not kinds or kind in kinds)
            and act >= min_act
            and len(
                strategy_arms(
                    state,
                    arm_policy,
                    opening,
                    unified_draft=unified_draft,
                    deck_size_penalty=deck_size_penalty,
                    event_fixes_v4=event_fixes_v4,
                )
            )
            > 1
        ):
            roots[(act, kind)].append((state, fork))
    rng = Random(f"{split_seed}/{seed}")
    chosen = []
    for (act, kind), candidates in roots.items():
        n = 2 if kind == "card" else 1
        chosen.extend(
            (act, rng.random(), kind, s, fork)
            for s, fork in rng.sample(candidates, min(n, len(candidates)))
        )
    chosen.sort(key=lambda sample: (-sample[0], sample[1]))
    selected = chosen[:max_roots]
    session = None
    errors, rows = [], []
    snapshots = {}
    try:
        if continuation_mode == "bundle" and selected:
            first_fork = selected[0][4]
            try:
                session = NativeSession(
                    ROOT,
                    folder / f"engine-{len(errors):03d}",
                    host_path=host,
                    ascension=10,
                    timeout=45,
                    act_list=first_fork.specification.get("act_list", "default"),
                )
                snapshots = replay_controller_snapshots(
                    session,
                    source,
                    deployed,
                    [len(fork.history) for _, _, _, _, fork in selected],
                    verify_policy=horizon == "run",
                )
            except Exception as exc:
                errors.append({"root": "prefix_replay", "arm": "prefix_replay", "error": str(exc)})
                if session is not None:
                    session.close()
                    session = None
                selected = []
        for _, _, kind, state, fork in selected:
            base_controller = snapshots.get(len(fork.history))
            arm_policy = base_controller.policy if base_controller is not None else RunPolicy(weights)
            use_matchups = bool(
                base_controller is not None
                and base_controller.strategy is not None
                and base_controller.strategy.uses_matchups
            )
            group_prob = (
                base_controller.pool.group_probability
                if (base_controller is not None and base_controller.pool is not None)
                else None
            )
            arms = strategy_arms(
                state,
                arm_policy,
                opening,
                matchups=use_matchups,
                group_probability=group_prob,
                unified_draft=unified_draft,
                deck_size_penalty=deck_size_penalty,
                event_fixes_v4=event_fixes_v4,
            )
            if base_controller is not None and kind == "shop":
                # Drop stale already-paid relic purchases that native shop state rejects.
                arms = [
                    item
                    for item in arms
                    if base_controller.paid_relics.corrected_view(state, item[0]) is None
                ]
            if len(arms) <= 1:
                continue
            # Sample expensive merchant inventories uniformly, retaining leave as the reference.
            if kind == "shop" and len(arms) > 6:
                leave = next(a for a in arms if a[0].kind == "leave_room")
                arms = rng.sample([a for a in arms if a != leave], 5) + [leave]
            outcomes = []
            for arm, prior, features in arms:
                try:
                    if session is None or session.closed:
                        session = NativeSession(
                            ROOT,
                            folder / f"engine-{len(errors):03d}",
                            host_path=host,
                            ascension=10,
                            timeout=45,
                            act_list=fork.specification.get("act_list", "default"),
                        )
                    confirmed = session.restore(fork)
                    if continuation_mode == "bundle":
                        result = follow_deployed(
                            session,
                            confirmed,
                            base_controller.clone(),
                            arm,
                            state["context"]["act"],
                            horizon=horizon,
                        )
                    else:
                        continuation = (
                            EncounterPolicy(weights, macro_seed=split_seed, style=style)
                            if style
                            else RunPolicy(weights, macro_seed=split_seed)
                        )
                        result = follow(
                            session,
                            confirmed,
                            continuation,
                            router,
                            opening,
                            arm,
                            state["context"]["act"],
                        )
                    outcomes.append({"id": arm.id, "prior": prior, "features": features, **result})
                except Exception as exc:
                    errors.append({"root": fork.expected_digest, "arm": arm.id, "error": str(exc)})
                    if session is not None:
                        session.close()
                        session = None
                    break
            if len(outcomes) == len(arms):
                rows.append(
                    {
                        "group": seed,
                        "kind": kind,
                        "act": state["context"]["act"],
                        "root": fork.expected_digest,
                        "unified_draft": unified_draft,
                        "deck_size_penalty": deck_size_penalty,
                        "label_provenance": stamp,
                        "arms": outcomes,
                    }
                )
    finally:
        if session is not None:
            session.close()
    save_json(
        folder / "labels.json",
        {"seed": seed, "label_provenance": stamp, "roots": rows, "errors": errors},
    )
    return len(rows), len(errors)


def fit_strategy_roots(
    folders,
    *,
    continuation="legacy",
    unified_draft=False,
    deck_size_penalty=0.12,
    offset_scale=None,
    ridge=16.0,
    strength=1.0,
    base_strategy=None,
    residual_alpha=1.0,
    horizon="act",
):
    roots = []
    expected_stamp = _UNSET
    for folder in folders:
        for path in sorted(Path(folder).glob("run-*/labels.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            file_stamp = payload.get("label_provenance")
            if expected_stamp is _UNSET:
                expected_stamp = file_stamp
            elif file_stamp != expected_stamp:
                raise ValueError("Mixed strategy label provenance across input files")
            if file_stamp is None:
                if continuation != "legacy" or unified_draft or horizon != "act":
                    raise ValueError(
                        "Unstamped legacy labels cannot be fitted with --continuation bundle or --unified-draft"
                    )
            else:
                if file_stamp.get("horizon", "act") != horizon:
                    raise ValueError("Label horizon does not match --horizon")
                if file_stamp.get("continuation") != continuation:
                    raise ValueError(
                        f"Label continuation {file_stamp.get('continuation')!r} does not match --continuation {continuation!r}"
                    )
                if bool(file_stamp.get("unified_draft", False)) != bool(unified_draft):
                    raise ValueError(
                        "Label unified_draft setting does not match --unified-draft fit flag"
                    )
                if unified_draft and abs(float(file_stamp.get("deck_size_penalty", 0.12)) - deck_size_penalty) > 1e-9:
                    raise ValueError(
                        f"Label deck_size_penalty {file_stamp.get('deck_size_penalty')} != --deck-size-penalty {deck_size_penalty}"
                    )
            for r in payload["roots"]:
                if expected_stamp is not None:
                    require_provenance(r, "label_provenance", expected_stamp)
                elif "label_provenance" in r:
                    raise ValueError("Mixed stamped and unstamped roots in input files")
                if "unified_draft" in r and bool(r["unified_draft"]) != bool(unified_draft):
                    raise ValueError("Root unified_draft setting does not match --unified-draft")
                if (
                    unified_draft
                    and "deck_size_penalty" in r
                    and abs(float(r["deck_size_penalty"]) - deck_size_penalty) > 1e-9
                ):
                    raise ValueError("Root deck_size_penalty does not match --deck-size-penalty")
                roots.append(r)
    if len({(r["group"], r["root"]) for r in roots}) != len(roots):
        raise ValueError("Duplicate native roots in training inputs")

    def validation(root):
        return int.from_bytes(hashlib.sha256(root["group"].encode()).digest()[:4], "big") % 5 == 0

    if base_strategy is not None:
        base = StrategyModel.load(base_strategy)
        if base.unified_draft != bool(unified_draft):
            raise ValueError("Base strategy unified_draft does not match fit --unified-draft")
        if unified_draft and abs(base.deck_size_penalty - deck_size_penalty) > 1e-9:
            raise ValueError("Base strategy deck_size_penalty does not match --deck-size-penalty")
        if base.card_offsets and base.offset_scale != 0.0:
            raise ValueError("Card-only residual fit requires base strategy offset_scale == 0.0")
        card_roots = [r for r in roots if r["kind"] == "card"]
        if not card_roots:
            raise ValueError("No card roots available for card-only residual fit")
        card_strength = float(base.strengths_by_kind.get("card", base.strength))
        if card_strength <= 0:
            raise ValueError("Base strategy card strength must be positive")
        residual_roots = [
            {
                **r,
                "arms": [
                    {
                        **a,
                        "prior": a["prior"] + card_strength * base.predict(0.0, a["features"]),
                    }
                    for a in r["arms"]
                ],
            }
            for r in card_roots
        ]
        train = [r for r in residual_roots if not validation(r)]
        if not train:
            raise ValueError("No training card roots")
        delta_weights = OfferModel.fit(train, ridge=ridge).weights
        merged_weights = dict(base.weights)
        for key, value in delta_weights.items():
            merged_weights[key] = merged_weights.get(key, 0.0) + (residual_alpha / card_strength) * value
        model = StrategyModel(
            merged_weights,
            set(base.kinds) | {"card"},
            base.strength,
            dict(base.strengths_by_kind),
            dict(base.card_offsets),
            unified_draft=base.unified_draft,
            deck_size_penalty=base.deck_size_penalty,
            offset_scale=base.offset_scale if offset_scale is None else float(offset_scale),
            event_fixes_v4=base.event_fixes_v4,
        )
        metrics = {}
        dev = [r for r in residual_roots if validation(r)]
        if dev:
            def gain(r):
                arms = r["arms"]
                deployed = max(arms, key=lambda a: a["prior"])
                updated = max(
                    arms,
                    key=lambda a: a["prior"]
                    + residual_alpha * sum(delta_weights.get(k, 0.0) * v for k, v in a["features"].items()),
                )
                return updated["return"] - deployed["return"]

            changed = sum(
                max(r["arms"], key=lambda a: a["prior"])["id"]
                != max(
                    r["arms"],
                    key=lambda a: a["prior"]
                    + residual_alpha * sum(delta_weights.get(k, 0.0) * v for k, v in a["features"].items()),
                )["id"]
                for r in dev
            )
            metrics["card"] = {
                "roots": len(dev),
                "changed_roots": changed,
                "mean_gain_vs_deployed": fmean(map(gain, dev)),
            }
        report = {
            "mode": "card_residual",
            "roots": len(card_roots),
            "seeds": len({r["group"] for r in card_roots}),
            "fit_seeds": len({r["group"] for r in train}),
            "fit_roots": len(train),
            "branches": sum(len(r["arms"]) for r in card_roots),
            "ridge": ridge,
            "residual_alpha": residual_alpha,
            "delta_nonzero": sum(abs(v) > 1e-12 for v in delta_weights.values()),
            "validation": metrics,
        }
        return model, report

    train = [r for r in roots if not validation(r)]
    if not train:
        raise ValueError("No training roots")
    effective_offset_scale = (
        (0.0 if unified_draft else 1.0) if offset_scale is None else float(offset_scale)
    )
    model = StrategyModel(
        OfferModel.fit(train, ridge=ridge).weights,
        {r["kind"] for r in train},
        strength,
        unified_draft=unified_draft,
        deck_size_penalty=deck_size_penalty,
        offset_scale=effective_offset_scale,
    )
    metrics = {}
    for kind in model.kinds:
        dev = [r for r in roots if validation(r) and r["kind"] == kind]
        if dev:

            def gain(r):
                arms = r["arms"]
                initial = max(arms, key=lambda a: a["prior"])
                fitted = max(
                    arms,
                    key=lambda a: a["prior"] + strength * model.predict(0.0, a["features"]),
                )
                return fitted["return"] - initial["return"]

            metrics[kind] = {"roots": len(dev), "mean_gain": fmean(map(gain, dev))}
    report = {
        "roots": len(roots),
        "seeds": len({r["group"] for r in roots}),
        "fit_seeds": len({r["group"] for r in train}),
        "fit_roots": len(train),
        "branches": sum(len(r["arms"]) for r in roots),
        "by_kind": dict(Counter(r["kind"] for r in roots)),
        "validation": metrics,
    }
    return model, report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=("collect", "fit"))
    p.add_argument("--source", type=Path, nargs="+", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--host", type=Path)
    p.add_argument("--bundle", type=Path)
    p.add_argument("--seeds", type=int, default=250)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--roots", type=int, default=4)
    p.add_argument("--min-act", type=int, choices=(1, 2, 3), default=1)
    p.add_argument(
        "--kinds", nargs="+", choices=("card", "camp", "shop", "neow", "ancient", "event")
    )
    p.add_argument("--style", help="Use a fight-aware continuation policy for labels")
    p.add_argument("--room-model", type=Path)
    p.add_argument("--continuation", choices=("legacy", "bundle"), default="legacy")
    p.add_argument(
        "--horizon", choices=("act", "run"), default="act",
        help="Use whole-run returns from explicitly partitioned training trajectories",
    )
    p.add_argument("--unified-draft", action="store_true")
    p.add_argument("--deck-size-penalty", type=float, default=0.12)
    p.add_argument("--offset-scale", type=float, default=None)
    p.add_argument("--ridge", type=float, default=16.0)
    p.add_argument("--strength", type=float, default=1.0)
    p.add_argument("--base-strategy", type=Path, help="Fit a regularized card-only residual over this StrategyModel")
    p.add_argument("--residual-alpha", type=float, default=1.0)
    args = p.parse_args()
    if args.continuation == "bundle" and (args.style or args.room_model):
        p.error("--continuation bundle uses the bundle's own encounter and room models")
    if args.horizon == "run" and args.continuation != "bundle":
        p.error("--horizon run requires --continuation bundle")
    args.output.mkdir(parents=True, exist_ok=False)
    if args.mode == "collect":
        if not args.host or not args.bundle:
            p.error("Collection requires --host and --bundle")
        sources = [
            path.parent
            for folder in args.source
            for path in sorted(folder.glob("run-*/result.json"))
            if (result := json.loads(path.read_text()))["status"] == "complete"
            and result.get("opening_partition") != "test"
            and (args.horizon == "act" or result.get("opening_partition") == "train")
            and not result.get("abandoned")
            and result["act"] >= args.min_act
            and path.with_name("strategy.jsonl.gz").exists()
        ]
        if len(sources) < args.seeds:
            p.error(f"Only {len(sources)} complete recorded games available")
        tasks = [
            (
                args.output / f"run-{i:04d}",
                source,
                args.host,
                args.bundle,
                8321 + i,
                args.roots,
                args.kinds,
                args.min_act,
                args.style,
                args.room_model,
                args.continuation,
                args.unified_draft,
                args.deck_size_penalty,
                args.horizon,
            )
            for i, source in enumerate(sources[: args.seeds])
        ]
        with ProcessPoolExecutor(args.workers) as pool:
            for i, result in enumerate(pool.map(collect, tasks), 1):
                if i % 10 == 0:
                    print(i, result, flush=True)
        return
    model, report = fit_strategy_roots(
        args.source,
        continuation=args.continuation,
        unified_draft=args.unified_draft,
        deck_size_penalty=args.deck_size_penalty,
        offset_scale=args.offset_scale,
        ridge=args.ridge,
        strength=args.strength,
        base_strategy=args.base_strategy,
        residual_alpha=args.residual_alpha,
        horizon=args.horizon,
    )
    model.save(args.output / "strategy.json")
    save_json(args.output / "report.json", report)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
