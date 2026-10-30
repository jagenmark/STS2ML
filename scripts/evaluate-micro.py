"""Native encounter or Act 1 evaluation with fixed noncombat choices."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import time

from sts2rl.native import NativeSession, SAMPLER, legal_actions
from sts2rl.teacher import combat_result, heuristic, teach_root

ROOT = Path(__file__).resolve().parents[1]


def macro_action(state):
    actions = legal_actions(state)
    if state["decision"] == "rest_site":
        heal = next((o for o in state["options"] if o.get("option_id") == "HEAL"), None)
        if heal:
            return next(a for a in actions if a.args.get("option_index") == heal["index"])
    return actions[0]


def episode(index, args):
    folder = args.output.resolve() / f"episode-{index:04d}"
    hp = (15, 25, 40, 70)[index % 4]
    started = time.perf_counter()
    game = NativeSession(ROOT, folder / "game")
    search = None
    branches = 0
    try:
        policy = None
        if args.policy == "micro":
            from sts2rl.micro import load_micro
            policy = load_micro(args.checkpoint, device=args.device)
        if args.policy == "teacher":
            search = NativeSession(ROOT, folder / "search")
        seed = f"{args.prefix}{index:06d}"
        state = game.reset(seed, encounter="SHRINKER_BEETLE_WEAK", hp=hp) if args.scope == "encounter" else game.reset(seed)
        hp = state["player"]["hp"]
        for step in range(256 if args.scope == "encounter" else 2048):
            if args.scope == "encounter":
                result = combat_result(state)
            else:
                act = state.get("context", {}).get("act", state.get("act", 1))
                result = {"won": True, "hp": state["player"]["hp"]} if act > 1 else None
                if state.get("decision") == "game_over":
                    result = {"won": bool(state.get("victory")), "hp": state["player"]["hp"]}
            if result is not None:
                return {"index": index, "initial_hp": hp, "status": "complete", **result,
                        "steps": step, "branches": branches, "seconds": time.perf_counter() - started}
            actions = legal_actions(state)
            is_combat_choice = state["decision"] == "combat_play" or (
                state["decision"] == "card_select" and "combat_state" in state)
            if not is_combat_choice:
                action = macro_action(state)
            elif len(actions) == 1:
                action = actions[0]
            elif search:
                label = teach_root(search, game.fork(), state, samples=args.samples,
                                   seed=50000000 + index * 10000 + step)
                branches += label["branches"]
                action = next(a for a in actions if a.id == label["chosen_action_id"])
            else:
                action = policy(state) if policy else heuristic(state)
            state = game.step(action)
        raise RuntimeError("Evaluation truncated")
    except Exception as exc:
        return {"index": index, "initial_hp": hp, "status": "error", "error": f"{type(exc).__name__}: {exc}"}
    finally:
        game.close()
        if search:
            search.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--policy", choices=("heuristic", "teacher", "micro"), required=True)
    p.add_argument("--checkpoint", type=Path)
    p.add_argument("--device", default="cpu")
    p.add_argument("--episodes", type=int, default=16)
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--samples", type=int, default=8)
    p.add_argument("--prefix", default="MICROVALID001")
    p.add_argument("--scope", choices=("encounter", "act1"), default="encounter")
    args = p.parse_args()
    if args.policy == "micro" and not args.checkpoint:
        p.error("--checkpoint required for micro")
    if args.scope == "act1" and args.policy == "teacher":
        p.error("Teacher sampling is qualified only for the starter encounter")
    if min(args.episodes, args.workers) < 1 or args.samples < 2:
        p.error("Invalid evaluation budget")
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output / "config.json").exists():
        p.error("Use a fresh evaluation folder")
    (args.output / "config.json").write_text(json.dumps(vars(args), default=str, indent=2), encoding="utf-8")
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(episode, i, args) for i in range(args.episodes)]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            (args.output / "progress.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
            print(json.dumps(result), flush=True)
    complete = [r for r in results if r["status"] == "complete"]
    report = {"training_scope": SAMPLER, "evaluation_scope": args.scope, "policy": args.policy,
              "episodes": len(results), "completed": len(complete), "errors": len(results) - len(complete),
              "wins": sum(r["won"] for r in complete),
              "mean_hp_loss": sum(r["initial_hp"] - r["hp"] for r in complete) / len(complete) if complete else None,
              "interpretation": "Act 1 outcomes use fixed macro choices and are outside the model's training distribution"
                  if args.scope == "act1" else "Qualified isolated starter encounter",
              "results": sorted(results, key=lambda r: r["index"])}
    (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
