"""Measure isolated native-engine episodes; this is not a trained game policy.

Requires the pinned sts2-cli Release build with the diagnostic identity patch,
the local .NET SDK, and psutil. Logs and results stay under artifacts/.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import random
import statistics
import subprocess
import threading
import time

import psutil

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "artifacts/upstreams/sts2-cli"
DOTNET = ROOT / "artifacts/tools/dotnet/dotnet.exe"
HOST = UPSTREAM / "src/Sts2Headless/bin/Release/net9.0/Sts2Headless.dll"
REVISION = "fec723a21741a1a33a4f54dc9b28c50df31d6e45"
ASSEMBLY_VERSION = "0.1.0+41cef1ea4657c524aa50e870df009e56337e8c32"


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(path)


def action(state: dict, rng: random.Random) -> dict:
    """A fixed, deliberately simple baseline using only exported choices."""
    decision = state.get("decision")
    args = {}
    if decision == "map_select":
        choice = rng.choice(state["choices"])
        name, args = "select_map_node", {k: choice[k] for k in ("col", "row")}
    elif decision == "combat_play":
        playable = [c for c in state.get("hand", [])
                    if c.get("can_play") and c.get("cost", 99) <= state.get("energy", 0)]
        if playable:
            card = playable[0]
            name, args = "play_card", {"card_index": card["index"]}
            if card.get("target_type") == "AnyEnemy":
                enemies = [e for e in state.get("enemies", []) if e.get("hp", 0) > 0]
                args["target_index"] = enemies[0]["index"]
        else:
            name = "end_turn"
    elif decision in ("event_choice", "rest_site"):
        choices = [o for o in state.get("options", [])
                   if not o.get("is_locked") and o.get("is_enabled", True)]
        if choices:
            choice = choices[0]
            if decision == "rest_site":
                choice = next((o for o in choices if o.get("option_id") == "HEAL"), choice)
            name, args = "choose_option", {"option_index": choice["index"]}
        else:
            name = "leave_room"
    elif decision == "card_reward":
        cards = state.get("cards", [])
        name = "select_card_reward" if cards else "skip_card_reward"
        if cards:
            args = {"card_index": cards[0]["index"]}
    elif decision == "bundle_select":
        name, args = "select_bundle", {"bundle_index": 0}
    elif decision == "card_select":
        minimum = state.get("min_select", 1)
        if minimum == 0:
            name = "skip_select"
        else:
            cards = state.get("cards", [])
            if len(cards) < minimum:
                raise ValueError("not enough selectable cards")
            name, args = "select_cards", {
                "indices": ",".join(str(c["index"]) for c in cards[:minimum]),
            }
    elif decision == "shop":
        name = "leave_room"
    elif decision == "unknown":
        name = "proceed"
    else:
        raise ValueError(f"unsupported decision: {decision}")
    return {"cmd": "action", "action": name, "args": args}


class MemoryMonitor:
    def __init__(self):
        self.lock = threading.Lock()
        self.processes = {}
        self.peak_total = 0
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.sample, daemon=True)

    def sample(self):
        while not self.stop.wait(0.05):
            total = 0
            with self.lock:
                for item in self.processes.values():
                    try:
                        rss = item["process"].memory_info().rss
                        item["peak_rss"] = max(item["peak_rss"], rss)
                        total += rss
                    except psutil.Error:
                        pass
            self.peak_total = max(self.peak_total, total)


def episode(seed: str, folder: Path, monitor: MemoryMonitor, timeout: float,
            ascension: int, max_steps: int) -> dict:
    folder.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    env.update(DOTNET_ROOT=str(DOTNET.parent), STS2_LIB=str(UPSTREAM / "lib"),
               STS2_GAME_DIR=str(UPSTREAM / "lib"), DOTNET_CLI_TELEMETRY_OPTOUT="1")
    for name in ("APPDATA", "LOCALAPPDATA"):
        path = folder / name.lower()
        path.mkdir()
        env[name] = str(path)
    rng = random.Random(seed)
    started = time.perf_counter()
    result = {"seed": seed, "ascension": ascension, "status": "error", "actions": 0}
    process = None
    tracker = {"peak_rss": 0}
    observations = hashlib.sha256()
    timings = []
    state = {}
    try:
        with (folder / "engine.log").open("w", encoding="utf-8") as errors, \
                (folder / "trace.jsonl").open("w", encoding="utf-8") as trace:
            process = subprocess.Popen(
                [str(DOTNET), str(HOST)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=errors, text=True, encoding="utf-8", bufsize=1, cwd=folder, env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            tracker["process"] = psutil.Process(process.pid)
            with monitor.lock:
                monitor.processes[process.pid] = tracker
            responses = queue.Queue()

            def read_output():
                try:
                    for line in process.stdout:
                        responses.put(line)
                finally:
                    responses.put(None)

            reader = threading.Thread(target=read_output, daemon=True)
            reader.start()

            def read():
                while True:
                    remaining = timeout - (time.perf_counter() - started)
                    if remaining <= 0:
                        raise TimeoutError("episode wall time exceeded")
                    try:
                        line = responses.get(timeout=min(30, remaining))
                    except queue.Empty:
                        raise TimeoutError("no engine response within bounded wait") from None
                    if line is None:
                        raise RuntimeError("engine stdout closed")
                    if line.startswith("{"):
                        return json.loads(line)

            def send(command: dict):
                before = time.perf_counter()
                process.stdin.write(json.dumps(command) + "\n")
                process.stdin.flush()
                response = read()
                duration = time.perf_counter() - before
                trace.write(json.dumps({"command": command, "response": response,
                                        "seconds": duration}) + "\n")
                if response.get("type") == "error":
                    raise RuntimeError(json.dumps(response))
                if command["cmd"] != "quit":
                    identity = response.get("runtime_identity", {})
                    if identity != {"character": "SILENT", "ascension": ascension,
                                    "assembly_version": ASSEMBLY_VERSION}:
                        raise RuntimeError(f"native runtime identity mismatch: {identity}")
                    observations.update(json.dumps(response, sort_keys=True).encode())
                return response, duration

            ready = read()
            if ready.get("type") != "ready":
                raise RuntimeError(f"unexpected handshake: {ready}")
            result["startup_seconds"] = time.perf_counter() - started
            state, result["reset_seconds"] = send({
                "cmd": "start_run", "character": "Silent", "ascension": ascension, "seed": seed,
            })
            repeats = Counter()
            while state.get("decision") != "game_over":
                if result["actions"] >= max_steps:
                    result["status"] = "truncated"
                    break
                key = json.dumps(state, sort_keys=True)
                repeats[key] += 1
                if repeats[key] > 20:
                    raise RuntimeError("repeated state without progress")
                state, duration = send(action(state, rng))
                timings.append(duration)
                result["actions"] += 1
            else:
                result.update(status="terminal", victory=bool(state.get("victory")))
            result.update(act=state.get("act"), floor=state.get("floor"),
                          hp=state.get("player", {}).get("hp"))
            result["terminal_seconds"] = time.perf_counter() - started
            cpu = tracker["process"].cpu_times()
            result["cpu_seconds"] = cpu.user + cpu.system
            send({"cmd": "quit"})
            process.wait(timeout=5)
            reader.join(timeout=2)
            if process.returncode:
                raise RuntimeError(f"engine exit code: {process.returncode}")
    except Exception as error:
        result.update(status="error", error=f"{type(error).__name__}: {error}",
                      act=state.get("act"), floor=state.get("floor"))
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            if process.stdin:
                process.stdin.close()
            if process.stdout:
                process.stdout.close()
            with monitor.lock:
                monitor.processes.pop(process.pid, None)
        result.update(wall_seconds=time.perf_counter() - started,
                      peak_rss_mib=tracker["peak_rss"] / 1024**2,
                      observation_sha256=observations.hexdigest(),
                      mean_action_ms=1000 * statistics.mean(timings) if timings else None)
        write_json(folder / "result.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--runs", type=int, default=16)
    parser.add_argument("--workers", nargs="+", type=int, default=[1, 2, 4, 8])
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--max-steps", type=int, default=2000)
    parser.add_argument("--ascension", type=int, default=10)
    args = parser.parse_args()
    if args.runs < 1 or args.repeats < 1 or any(w < 1 or w > 16 for w in args.workers):
        parser.error("positive runs/repeats and 1..16 workers required")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    def sha(path):
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    report = {"started_at": datetime.now(timezone.utc).isoformat(),
              "upstream_revision": REVISION, "ascension": args.ascension,
              "policy": "first-playable/first-reward/heal/random-route-v1; no search or ML",
              "timing": "fresh process per episode; includes startup/reset/JSON/logging/shutdown",
              "ram_sampling_interval_seconds": 0.05,
              "host_sha256": sha(HOST), "engine_sha256": sha(UPSTREAM / "lib/sts2.dll"),
              "original_engine_sha256": sha(UPSTREAM / "lib/sts2.dll.original"),
              "batches": []}
    seed_results = {}
    for repeat in range(args.repeats):
        order = args.workers if repeat % 2 == 0 else list(reversed(args.workers))
        for workers in order:
            label = f"repeat-{repeat + 1}-workers-{workers}"
            print(f"Starting {label}, {args.runs} identical seeds", flush=True)
            monitor = MemoryMonitor()
            monitor.thread.start()
            start = time.perf_counter()
            results = []
            try:
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    futures = [executor.submit(
                        episode, f"S2BENCH{i:03d}", output / label / f"seed-{i:03d}",
                        monitor, args.timeout, args.ascension, args.max_steps,
                    ) for i in range(1, args.runs + 1)]
                    for future in as_completed(futures):
                        result = future.result()
                        results.append(result)
                        print(json.dumps({k: result[k] for k in
                              ("seed", "status", "actions", "wall_seconds", "peak_rss_mib")}),
                              flush=True)
            finally:
                monitor.stop.set()
                monitor.thread.join()
            elapsed = time.perf_counter() - start
            terminals = [r for r in results if r["status"] == "terminal"]
            matches = all(seed_results.setdefault(r["seed"], r["observation_sha256"])
                          == r["observation_sha256"] for r in results)
            batch = {"workers": workers, "repeat": repeat + 1, "wall_seconds": elapsed,
                     "completed": len(terminals), "errors": len(results) - len(terminals),
                     "wins": sum(r.get("victory", False) for r in terminals),
                     "terminal_runs_per_hour": 3600 * len(terminals) / elapsed,
                     "mean_episode_seconds": statistics.mean(r["wall_seconds"] for r in results),
                     "median_episode_seconds": statistics.median(r["wall_seconds"] for r in results),
                     "actions_per_second": sum(r["actions"] for r in results) / elapsed,
                     "peak_total_rss_mib": monitor.peak_total / 1024**2,
                     "identical_observations_across_workers": matches,
                     "episodes": sorted(results, key=lambda r: r["seed"])}
            report["batches"].append(batch)
            write_json(output / "report.json", report)
            print(json.dumps({k: v for k, v in batch.items() if k != "episodes"}), flush=True)
            if len(terminals) != args.runs or not matches:
                print("Stopping scaling after errors or differing observations", flush=True)
                return 2
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    write_json(output / "report.json", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
