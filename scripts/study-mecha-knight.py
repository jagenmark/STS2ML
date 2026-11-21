"""Collect replayable Mecha Knight openings and measure frozen policies in the native game."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import gzip
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from sts2rl.act1 import save_json
from sts2rl.combat_effects import power
from sts2rl.encounter import EncounterModel
from sts2rl.mecha_knight import phase
from sts2rl.native import NativeError, NativeSession, ReplayFork, digest
from sts2rl.run_bundle import load_bundle
from sts2rl.run_evaluation import act_start
from sts2rl.run_policy import RunPolicy, RunWeights
from sts2rl.teacher import incoming

ROOT = Path(__file__).resolve().parents[1]
MODEL = "MONSTER.MECHA_KNIGHT"
ENTER = {"cmd": "enter_room", "type": "elite", "encounter": "MECHA_KNIGHT_ELITE"}
POTIONS = (
    "BLOCK_POTION",
    "GHOST_IN_A_JAR",
    "ENERGY_POTION",
    "SWIFT_POTION",
    "LUCKY_TONIC",
    "WEAK_POTION",
)


def read(path):
    return json.loads(path.read_bytes())


def read_case(path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def map_visits(path, fork):
    visits = []
    with path.open(encoding="utf-8") as stream:
        first = json.loads(next(stream))
        history = list(first["command"]["history"])
        if history != list(fork.history) or first["response_digest"] != fork.expected_digest:
            raise ValueError("Training map continuation begins at a different physical state")
        last = first["response_digest"]
        for line in stream:
            obs = json.loads(line)
            command = obs["command"]
            if command["cmd"] == "get_map":
                continue
            if command["cmd"] != "action":
                raise ValueError("Unexpected control command in a natural map continuation")
            if command["action"] == "select_map_node":
                row = command["args"]["row"]
                if row >= 14:
                    break
                visits.append((row, list(history), last))
            history.append(command)
            last = obs["response_digest"]
    return visits


def prepare(a):
    entries = read(a.maps / "index.json")
    if any(e["partition"] != a.partition for e in entries) or len(entries) != len(
        {e["seed"] for e in entries}
    ):
        raise ValueError("Invalid map partition")
    if a.limit:
        entries = sorted(entries, key=lambda e: digest(["mecha-map-sampling-v1", e["seed"]]))[
            : a.limit
        ]
    origins = {e["seed"]: act_start(a.maps / e["seed"] / "rpc.jsonl", 3) for e in entries}
    if any(origins[e["seed"]].expected_digest != e["map_digest"] for e in entries):
        raise ValueError("Map history differs from registered prefix")
    a.output.mkdir(parents=True, exist_ok=False)
    index = {}

    def add(seed, kind, history, state_hash, commands, location):
        spec = origins[seed].specification
        key = digest([spec, history, state_hash, commands])
        if key not in index:
            case = {
                "case": key,
                "seed": seed,
                "partition": a.partition,
                "kind": kind,
                "location": location,
                "spec": spec,
                "history": history,
                "root": state_hash,
                "setup": commands,
            }
            with gzip.open(a.output / (key + ".json.gz"), "wt", encoding="utf-8") as f:
                json.dump(case, f, separators=(",", ":"))
            index[key] = {
                k: case[k] for k in ("case", "seed", "partition", "kind", "location", "root")
            }

    for folder in a.natural or ():
        for f in sorted(folder.glob("*.json.gz")):
            group = read_case(f)
            seed = group["seed"]
            if seed not in origins:
                continue
            origin = origins[seed]
            if group["specification"] != origin.specification or group.get("act") != 3:
                raise ValueError("Unexpected natural lobby")
            for start in group["starts"]:
                if start["formation"] != "MECHA_KNIGHT" or start["room"] != "Elite":
                    continue
                history = group["history"][: start["step"]]
                if history[: len(origin.history)] != list(origin.history):
                    raise ValueError("Natural fight used a different Act 3 entry")
                add(seed, "natural", history, start["root"], [], start["floor"])
    for e in entries:
        seed = e["seed"]
        f = origins[seed]
        if a.runs:
            path = a.runs / seed / "game/rpc.jsonl"
            visits = map_visits(path, f)
            seen = set()
            for target in (0, 4, 8, 12):
                row, history, state_hash = min(visits, key=lambda v: abs(v[0] - target))
                if state_hash not in seen:
                    add(seed, "practice", history, state_hash, [ENTER], row)
                    seen.add(state_hash)
            if a.potions:
                row, history, state_hash = min(visits, key=lambda v: abs(v[0] - 5))
                which = int(digest(seed)[:8], 16) % len(POTIONS)
                add(
                    seed,
                    "potion_practice",
                    history,
                    state_hash,
                    [{"cmd": "set_player", "potions": [POTIONS[which]]}, ENTER],
                    row,
                )
        elif a.entry_practice:
            add(seed, "practice", list(f.history), f.expected_digest, [ENTER], 0)
    save_json(a.output / "index.json", list(index.values()))
    print(
        json.dumps(
            {
                k: sum(e["kind"] == k for e in index.values())
                for k in ("natural", "practice", "potion_practice")
            }
        )
    )


def brief(state, action, phase):
    player = state["player"]
    e = next(e for e in state["enemies"] if e["hp"] > 0)
    item = None
    if action.kind == "play_card":
        item = next(c for c in state["hand"] if c["index"] == action.args["card_index"])
    elif action.kind == "use_potion":
        item = next(p for p in player["potions"] if p["index"] == action.args["potion_index"])
    return {
        "phase": phase,
        "round": state["round"],
        "root": digest(state),
        "hp": player["hp"],
        "block": player["block"],
        "energy": state["energy"],
        "foe_hp": e["hp"],
        "foe_block": e.get("block", 0),
        "incoming": incoming(e),
        "artifact": power(e.get("powers"), "ARTIFACT"),
        "strength": power(e.get("powers"), "STRENGTH"),
        "weak": power(e.get("powers"), "WEAK"),
        "hand": [c["id"] for c in state["hand"]],
        "potions": [p["id"] for p in player["potions"]],
        "action": action.command(),
        "item": item["id"] if item else action.kind,
    }


def restore(game, case, stream):
    spec = case["spec"]
    if stream:
        st = game.reset(spec["seed"])
        for cmd in case["history"]:
            st = game._request(cmd)
        if digest(st) != case["root"]:
            raise ValueError("Streamed prefix failed native verification")
        game.state, game.history = st, list(case["history"])
    else:
        st = game.restore(ReplayFork(spec, tuple(case["history"]), case["root"]))
    for cmd in case["setup"]:
        st = game._request(cmd)
        if cmd["cmd"] == "set_player":
            if [p["id"].split(".")[-1] for p in st["player"]["potions"]] != cmd["potions"]:
                raise ValueError("Practice potion setup did not take effect")
        game.state = st
    return st


def simulate(game, case, config, weights, stream):
    st = restore(game, case, stream)
    macro = RunPolicy(weights)
    actor = EncounterModel(config)
    last_windup = 0
    first = None
    turns = []
    actions = []
    log = []
    remaining = None
    phase_actions = []
    for _ in range(650):
        if st["decision"] == "game_over" or not st.get("in_combat"):
            if first is None:
                raise ValueError("Mecha Knight was never observed")
            win = st["decision"] != "game_over" or st["victory"]
            return {
                "won": win,
                "hp": st["player"]["hp"] if win else 0,
                "potions": len(st["player"]["potions"]),
                "remaining": 0 if win else remaining,
                "opening": first,
                "terminal": digest(st),
                "turns": turns,
                "decisions": log,
                "actions": actions,
                "phase_actions": phase_actions,
            }
        action = actor.choose(st, macro)
        if st["decision"] == "combat_play":
            foes = [e for e in st["enemies"] if e["hp"] > 0]
            if len(foes) != 1 or foes[0]["id"] != MODEL or st["context"]["room_type"] != "Elite":
                raise ValueError("Unexpected enemy in Mecha Knight scenario")
            first = first or digest(st)
            foe = foes[0]
            remaining = foe["hp"] / max(1, foe["max_hp"])
            rnd = st["round"]
            if not turns or turns[-1]["round"] != rnd:
                turns.append(
                    {
                        "round": rnd,
                        "hp": st["player"]["hp"],
                        "foe_hp": foe["hp"],
                        "incoming": incoming(foe),
                        "intents": [i["type"] for i in foe.get("intents") or []],
                    }
                )
            stage = phase(st, last_windup)
            if stage == "windup":
                last_windup = rnd
            if stage:
                phase_actions.append(len(actions))
                log.append(brief(st, action, stage))
        actions.append(action.command())
        st = game.step(action)
    raise ValueError("Unfinished native fight")


def run_one(task):
    file, folder, host, bundle = task
    case = read_case(file)
    _, opts = load_bundle(bundle)
    config = read(opts["encounter_model"])
    weights = RunWeights.load(opts["weights"])
    row = {k: case[k] for k in ("case", "seed", "partition", "kind")}
    with TemporaryDirectory() as tmp:
        for stream in (False, True):
            try:
                with NativeSession(
                    ROOT,
                    Path(tmp) / str(stream),
                    host_path=host,
                    act_list=case["spec"].get("act_list", "default"),
                    timeout=80,
                ) as game:
                    row.update(simulate(game, case, config, weights, stream))
                break
            except (NativeError, TimeoutError) as exc:
                if stream:
                    row["error"] = str(exc)
    save_json(folder / (case["case"] + ".json"), row)


def run(a):
    entries = read(a.cases / "index.json")
    if a.kind:
        entries = [e for e in entries if e["kind"] in a.kind]
    a.output.mkdir(parents=True, exist_ok=False)
    save_json(
        a.output / "design.json",
        {
            "cases": sha(a.cases / "index.json"),
            "host": sha(a.host),
            "bundles": {b.parent.name: sha(b) for b in a.bundles},
        },
    )
    tasks = []
    for b in a.bundles:
        target = a.output / b.parent.name
        target.mkdir()
        tasks.extend(
            (a.cases / (e["case"] + ".json.gz"), target, a.host.resolve(), b) for e in entries
        )
    with ProcessPoolExecutor(a.workers) as pool:
        list(pool.map(run_one, tasks))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("prepare")
    q.add_argument("--maps", required=True, type=Path)
    q.add_argument("--partition", choices=("train", "development", "test"), required=True)
    q.add_argument("--runs", type=Path)
    q.add_argument("--natural", nargs="+", type=Path)
    q.add_argument("--entry-practice", action="store_true")
    q.add_argument("--potions", action="store_true")
    q.add_argument("--limit", type=int)
    r = sub.add_parser("run")
    r.add_argument("--cases", required=True, type=Path)
    r.add_argument("--host", required=True, type=Path)
    r.add_argument("--bundles", required=True, nargs="+", type=Path)
    r.add_argument("--workers", type=int, default=3)
    r.add_argument("--kind", nargs="+", choices=("natural", "practice", "potion_practice"))
    for s in (q, r):
        s.add_argument("--output", required=True, type=Path)
    a = p.parse_args()
    prepare(a) if a.cmd == "prepare" else run(a)


if __name__ == "__main__":
    main()
