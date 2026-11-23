"""Measure HP spent on the approach for the fixed diagnostic Act 2 boss cohort."""

from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import json
from pathlib import Path
import runpy
from tempfile import TemporaryDirectory

from sts2rl.run_bundle import load_bundle
from sts2rl.run_evaluation import play_episode
from sts2rl.run_policy import RunWeights

CONFIG = runpy.run_path(str(Path(__file__).with_name("collect-v5-autopsy.py")))


def replay(outcome):
    rooms = []
    skipped_ancients = []
    current = None

    def transition(step, before, action, after, fallback):
        nonlocal current
        view = before.get("combat_state", before)
        ctx = view.get("context") or {}
        if before["decision"] == "map_select" and ctx.get("act") == 2 and ctx.get("floor") == 0:
            ancient = [node for node in before["choices"] if node["type"] == "Ancient"]
            if ancient and not any(
                (node["col"], node["row"]) == (action.args["col"], action.args["row"])
                for node in ancient
            ):
                skipped_ancients.append(
                    dict(
                        step=step,
                        choices=before["choices"],
                        action=action.command(),
                        next_room=after["context"]["room_type"],
                    )
                )
        if not before.get("in_combat") or ctx.get("act") != 2 or ctx.get("room_type") == "Boss":
            return
        if current is None:
            current = dict(
                floor=ctx["floor"],
                room=ctx["room_type"],
                enemies="+".join(e["id"].split(".")[-1] for e in view["enemies"]),
                hp=view["player"]["hp"],
                max_hp=view["player"]["max_hp"],
                potion_uses=0,
            )
        current["potion_uses"] += action.kind == "use_potion"
        if not after.get("in_combat"):
            rooms.append({**current, "exit_hp": after["player"]["hp"]})
            current = None

    role, options = load_bundle(CONFIG["BUNDLE"])
    with TemporaryDirectory() as temp:
        result = play_episode(
            (
                CONFIG["ROOT"],
                CONFIG["HOST"],
                Path(temp) / "run",
                outcome["seed"],
                outcome["index"],
                role,
                asdict(RunWeights.load(options["weights"])),
                None,
                {
                    **options,
                    "seeded_acts": outcome["act_list"] == "seeded",
                    "compact_combat_summary": True,
                    "transition_hook": transition,
                },
            )
        )
    keys = ("act", "floor", "steps", "win", "status", "boss_fights", "death")
    matched = all(result.get(k) == outcome.get(k) for k in keys)
    return dict(
        seed=outcome["seed"],
        skipped_ancients=skipped_ancients,
        matched=matched,
        rooms=rooms if matched else [],
        **({} if matched else {"replay": {k: result.get(k) for k in keys}}),
    )


def main():
    work = CONFIG["WORK"]
    panel = json.loads((work / "V5DIAG/lock.json").read_bytes())["panel"]
    cohort = []
    for _, seed, _ in panel:
        row = json.loads((work / "V5DIAG" / seed / "result.json").read_bytes())
        if any(act == 2 for act, _ in row["boss_fights"]):
            cohort.append(row)
    with ProcessPoolExecutor(4) as pool:
        matches = list(pool.map(replay, cohort))
    skipped = {}
    for match in matches:
        choices = match.pop("skipped_ancients")
        if match["matched"] and choices:
            skipped[match["seed"]] = choices
    (work / "ancient-missing.json").write_text(json.dumps(skipped))
    (work / "approaches.json").write_text(json.dumps(matches))
    print(sum(r["matched"] for r in matches), "/", len(matches), flush=True)


if __name__ == "__main__":
    main()
