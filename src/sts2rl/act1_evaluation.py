"""Paired held-out Act 1 comparisons of heuristic, student and MC assistance."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import combinations
import json
from pathlib import Path
import statistics
import time

from .act1 import run_act1, save_json


def compare_act1(arms):
    indexed = {name: {r["index"]: r for r in rows} for name, rows in arms.items()}
    if not indexed or any(len(indexed[name]) != len(rows) for name, rows in arms.items()):
        raise ValueError("Missing policies or duplicate evaluation indices")
    indices = set(next(iter(indexed.values())))
    if any(set(rows) != indices for rows in indexed.values()):
        raise ValueError("Policies must attempt the same evaluation seeds")
    for index in indices:
        if len({rows[index]["group"] for rows in indexed.values()}) != 1:
            raise ValueError("Evaluation seed groups differ between policies")
        if len({rows[index].get("ascension", 10) for rows in indexed.values()}) != 1:
            raise ValueError("Evaluation ascensions differ between policies")
    paired = sorted(i for i in indices if all(rows[i]["status"] == "complete" for rows in indexed.values()))

    def stats(rows):
        complete = [r for r in rows if r["status"] == "complete"]
        clears = sum(r["cleared_act1"] for r in complete)
        return {"attempted": len(rows), "completed": len(complete), "act1_clears": clears,
                "clear_rate_over_completed": clears / len(complete) if complete else None,
                "mean_max_floor": statistics.fmean(r["max_floor"] for r in complete) if complete else None,
                "mean_seconds": statistics.fmean(r["seconds"] for r in complete) if complete else None,
                "median_seconds": statistics.median(r["seconds"] for r in complete) if complete else None,
                "search_errors": sum(len(r.get("search_errors", [])) for r in rows),
                "run_errors": [{k: r.get(k) for k in ("index", "status", "error")}
                               for r in rows if r["status"] != "complete"]}

    comparisons = {}
    for left, right in combinations(indexed, 2):
        a, b = indexed[left], indexed[right]
        comparisons[f"{left}_vs_{right}"] = {
            "paired_runs": len(paired),
            "left_only_clears": sum(a[i]["cleared_act1"] and not b[i]["cleared_act1"] for i in paired),
            "right_only_clears": sum(b[i]["cleared_act1"] and not a[i]["cleared_act1"] for i in paired),
            "both_clear": sum(a[i]["cleared_act1"] and b[i]["cleared_act1"] for i in paired),
            "neither_clears": sum(not a[i]["cleared_act1"] and not b[i]["cleared_act1"] for i in paired),
            "mean_floor_difference_left_minus_right": statistics.fmean(a[i]["max_floor"] - b[i]["max_floor"] for i in paired) if paired else None,
            "mean_seconds_difference_left_minus_right": statistics.fmean(a[i]["seconds"] - b[i]["seconds"] for i in paired) if paired else None,
        }
    return {"attempted_seed_groups": len(indices), "complete_paired_seed_groups": len(paired),
            "excluded_pair_indices": sorted(indices - set(paired)),
            "policies": {name: stats(rows) for name, rows in arms.items()},
            "comparisons": comparisons,
            "limitations": ["Errors are not defeats; paired comparisons exclude a seed if any policy failed.",
                            "MC policy searches only configured roots, with heuristic continuation and fallback.",
                            "Same macro policy and random seed, but combat outcomes can change later choices.",
                            "Small paired sample; these metrics do not establish the cause of a performance gap."]}


def evaluate_three_way(root, output, *, episodes, prefix, macro_checkpoint, micro_policy,
                       samples, roots_per_fight, query_probability, workers, protocol,
                       ascension=10, condition_ascension=False, host_path=None):
    """Run all three policies before reporting failures. Never train on these rows."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    roles = {"heuristic": None, "micro": micro_policy, "teacher": None}
    protocol = {**protocol, "prefix": prefix, "episodes": episodes, "samples": samples,
                "roots_per_fight": roots_per_fight, "query_probability": query_probability,
                "workers": workers, "roles": list(roles), "held_out": True}
    protocol.update(ascension=ascension, condition_ascension=condition_ascension,
                    host_path=str(Path(host_path).resolve()) if host_path else None)
    save_json(output / "evaluation-protocol.json", protocol)
    arms = {}
    for name, policy in roles.items():
        folder = output / ("evaluation-" + name)
        report_path = output / (name + "-evaluation.json")
        if report_path.exists():
            previous = json.loads(report_path.read_text(encoding="utf-8"))
            if previous.get("protocol") == protocol and len(previous["runs"]) == episodes and all(r["status"] == "complete" for r in previous["runs"]):
                arms[name] = previous["runs"]
                continue
        stamp = time.time_ns()
        if folder.exists():
            if not folder.resolve().is_relative_to(output.resolve()):
                raise ValueError("Evaluation folder resolves outside the experiment")
            folder.rename(output / f"incomplete-evaluation-{name}-{stamp}")
        if report_path.exists():
            report_path.rename(output / f"previous-{name}-evaluation-{stamp}.json")
        results, started = [], time.perf_counter()
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(run_act1, root, folder, i, prefix=prefix,
                teacher=name == "teacher", micro_policy=policy, macro_checkpoint=macro_checkpoint,
                samples=samples, roots_per_fight=roots_per_fight, query_probability=query_probability,
                stop_file=output / "STOP", ascension=ascension,
                condition_ascension=condition_ascension, host_path=host_path) for i in range(episodes)]
            for future in as_completed(futures):
                results.append(future.result())
                save_json(output / "evaluation-progress.json", {"policy": name, "completed": len(results),
                          "total": episodes, "wall_seconds": time.perf_counter() - started}, best_effort=True)
        results.sort(key=lambda r: r["index"])
        arms[name] = results
        save_json(report_path, {"protocol": protocol, "wall_seconds": time.perf_counter() - started,
                               "summary": compare_act1({name: results})["policies"][name], "runs": results})
    report = compare_act1(arms)
    save_json(output / "policy-comparison.json", report)
    return report
