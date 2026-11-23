"""Run the preregistered five-arm Silent A10 ablation, with one fresh process per lobby."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from sts2rl.combat_effects import power
from sts2rl.deployed_controller import DeployedController
from sts2rl.native import canonical_json, digest
from sts2rl.run_bundle import freeze_bundle, load_bundle
from sts2rl.run_evaluation import play_episode
from sts2rl.run_policy import RunWeights, _card_id

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence"
PANEL = EVIDENCE / "silent-a10-v51-dev-panel.json"
RELEASE = ROOT / "releases/silent-a10-v2-tactics"
BUNDLE = RELEASE / "challenger/policy.json"
HOST = ROOT / "artifacts/v5-autopsy/native-host/src/Sts2Headless/bin/Curriculum/net9.0/Sts2Headless.dll"
GAME = ROOT / "artifacts/upstreams/sts2-cli/lib/sts2.dll"
WORK = ROOT / "artifacts/v51-autopsy/dev"
TRACKED_CARDS = {"ACCELERANT", "ACCURACY", "PHANTOM_BLADES", "INFINITE_BLADES"}


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def locked_experiment():
    spec = json.loads(PANEL.read_bytes())
    rows = spec["panel"]
    reserved = ("V5DIAG", "V5DEV", "M4", "CSV", "VAL256", "SEEDED128", "TRUE_SEEDED", "REP512")
    official = json.loads((RELEASE / "benchmark.json").read_bytes())["seed_order"]
    sealed = {seed for group in official.values() for _, seed, _ in group}
    names = {seed for _, seed, _ in rows}
    if (len(sealed) != 896 or names & sealed or any(s.startswith(reserved) for s in names)
            or rows != [[i, f"V51DEV_{i:04d}", "seeded" if i % 2 else "default"] for i in range(256)]
            or digest(rows) != spec["panel_sha256"]
            or digest(rows) != "53b6f1cb00bf63aeb33069451b97fa0b62b5e045237dc82f1d497f4135c71b43"):
        raise ValueError("Fresh V51DEV panel lock or disjointness check failed")
    return spec


class Telemetry:
    def __init__(self):
        self.counts = Counter()
        self.a2_boss = None
        self.a2_hp = None
        self.trajectory = hashlib.sha256()
        self.shops = set()
        self.removal_cost = None

    def observe(self, step, before, action, after, fallback):
        self.trajectory.update(canonical_json([action.snapshot, action.command()]))
        view = before.get("combat_state", before)
        ctx = view.get("context") or {}
        decision = before["decision"]
        player = before["player"]
        kind = action.kind
        counts = self.counts
        in_combat = before.get("in_combat")
        if in_combat and ctx.get("act") == 2 and ctx.get("room_type") == "Boss":
            boss = ctx["boss"]["id"]
            if self.a2_boss is None:
                self.a2_boss, self.a2_hp = boss, view["player"]["hp"]
            if boss != self.a2_boss:
                raise ValueError("Multiple Act 2 boss identities")
            if decision == "combat_play":
                sloth = power(view.get("player_powers"), "SLOTH")
                if kind == "play_card":
                    card = next(c for c in view["hand"] if c["index"] == action.args["card_index"])
                    cid = _card_id(card)
                    if boss == "KNOWLEDGE_DEMON_BOSS" and sloth:
                        counts["sloth_plays"] += 1
                        counts["sloth_basics"] += cid in ("STRIKE_SILENT", "DEFEND_SILENT")
                        counts["sloth_powers"] += card["type"] == "Power"
                    if boss == "THE_INSATIABLE_BOSS" and cid == "FRANTIC_ESCAPE":
                        counts["escape_plays"] += 1
                if (kind == "end_turn" and boss == "THE_INSATIABLE_BOSS"
                        and any(power(e.get("powers"), "SANDPIT") == 1 for e in view["enemies"])):
                    counts["sandpit_one_ends"] += 1
                    counts["sandpit_one_fatal_ends"] += after["decision"] == "game_over" and not after["victory"]
        if not in_combat and decision == "card_reward":
            picked = None
            for card in before["cards"]:
                if card["index"] == action.args.get("card_index"):
                    picked = _card_id(card)
            for name in {_card_id(c) for c in before["cards"]} & TRACKED_CARDS:
                counts[name + "_free_offers"] += 1
                counts[name + "_free_takes"] += name == picked
        if decision == "shop":
            for c in before["cards"]:
                name = _card_id(c)
                if name in TRACKED_CARDS and c.get("is_stocked") and c["cost"] <= player["gold"]:
                    self.shops.add((ctx["act"], ctx["floor"], name))
                    if kind == "buy_card" and c["index"] == action.args["card_index"]:
                        counts[name + "_shop_buys"] += 1
        if self.removal_cost is not None and decision == "card_select":
            def clumsy(p):
                return sum(_card_id(c) == "CLUMSY" for c in p["deck"])
            if clumsy(after["player"]) < clumsy(player):
                counts["clumsy_removals"] += 1
                counts["clumsy_gold"] += self.removal_cost
        self.removal_cost = before["card_removal_cost"] if kind == "remove_card" else None
        if kind == "choose_option":
            opt = next(o for o in before["options"] if o["index"] == action.args["option_index"])
            key = opt.get("text_key", "")
            if key in ("THIS_OR_THAT.pages.INITIAL.options.ORNATE", "THIS_OR_THAT.pages.INITIAL.options.PLAIN"):
                counts[key.rsplit(".", 1)[1]] += 1
            if decision == "rest_site":
                if any(o["option_id"] == "KINDLE" and o.get("is_enabled", True) and not o.get("is_locked")
                       for o in before["options"]):
                    counts["kindle_legal"] += 1
                counts["camp_" + opt["option_id"]] += 1
                if ctx["act"] == 2 and ctx["floor"] == 15:
                    counts["last_a2_camp_" + opt["option_id"]] += 1
        if kind == "select_map_node" and ctx["act"] in (2, 3):
            roots = [p for p in before["choices"] if p["type"] == "Ancient" and p["row"] == 0]
            if roots:
                counts["ancient_available"] += 1
                counts["ancient_visited"] += any(
                    p["row"] == action.args["row"] and p["col"] == action.args["col"] for p in roots
                )

    def result(self):
        for _, _, name in self.shops:
            self.counts[name + "_affordable_shops"] += 1
        return dict(a2_boss=self.a2_boss, a2_hp=self.a2_hp, counts=self.counts,
                    trajectory_sha256=self.trajectory.hexdigest())


def episode(job):
    output, index, seed, mode, arm, bundle = job
    path = output / arm / (seed + ".json")
    role, opts = load_bundle(bundle)
    telemetry = Telemetry()
    with TemporaryDirectory(dir=output) as scratch:
        row = play_episode((ROOT, HOST, Path(scratch) / "run", seed, index, role,
                            asdict(RunWeights.load(opts["weights"])), None, {
                                **opts, "seeded_acts": mode == "seeded", "compact_combat_summary": True,
                                "transition_hook": telemetry.observe,
                            }))
    row.update(arm=arm, **telemetry.result())
    if row["status"] != "complete" or row.get("abandoned"):
        failure = path.with_suffix(f".failed-{os.getpid()}.json")
        failure.write_bytes(canonical_json(row))
        raise RuntimeError(f"{seed}/{arm}: {row.get('error', row['status'])}")
    if bool(row["a2_boss"]) != any(a == 2 for a, _ in row["boss_fights"]):
        raise ValueError(f"{arm}/{seed}: missing Act 2 boss evidence")
    temp = path.with_suffix(".tmp")
    temp.write_bytes(canonical_json(row))
    temp.replace(path)
    return arm, seed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=WORK)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if os.getenv("DOTNET_STARTUP_HOOKS") or any(os.getenv(k) != "1" for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS")):
        parser.error("Run without startup hooks and set BLAS/OMP threads to 1")
    spec = locked_experiment()
    if [checksum(p) for p in (BUNDLE, HOST, GAME)] != [
        spec[k] for k in ("baseline_manifest_sha256", "host_sha256", "game_sha256")
    ]:
        raise ValueError("Frozen bundle, native host or game differs from preregistration")
    # Refuse to mix code versions on resumption.
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    tracked = ["src", "scripts/collect-v51-autopsy.py", str(PANEL.relative_to(ROOT)), str(BUNDLE.parent.relative_to(ROOT))]
    subprocess.run(["git", "diff", "--exit-code", "HEAD", "--", *tracked], cwd=ROOT, check=True)
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=args.resume)
    role, opts = load_bundle(BUNDLE)
    bundles = {"v5": BUNDLE}
    for arm, flags in spec["arms"].items():
        (folder / arm).mkdir(exist_ok=args.resume)
        if flags:
            dest = folder / arm / "bundle"
            bundles[arm] = dest / "policy.json" if dest.exists() else freeze_bundle(
                {"args": {**opts, **dict.fromkeys(flags, True), "roles": [role]}}, dest
            )
        deployed = DeployedController.from_bundle(bundles[arm])
        if sorted(k for k in spec["arms"]["combined"] if getattr(deployed.policy, k)) != sorted(flags):
            raise ValueError(f"Incorrect switches for {arm}")
    lock = {"commit": source, "prereg_sha256": checksum(PANEL), "panel_sha256": spec["panel_sha256"],
            "bundles": {a: checksum(p) for a, p in bundles.items()}}
    manifest = folder / "lock.json"
    if manifest.exists() and json.loads(manifest.read_bytes()) != lock:
        raise ValueError("Different experiment already present")
    manifest.write_bytes(canonical_json(lock))
    jobs = [(folder, i, s, mode, arm, bundles[arm]) for i, s, mode in spec["panel"] for arm in spec["arms"]
            if not (folder / arm / (s + ".json")).exists()]
    print(f"{len(jobs)} episodes on {args.workers} workers; panel {spec['panel_sha256']}", flush=True)
    with ProcessPoolExecutor(args.workers) as pool:
        for n, (arm, seed) in enumerate(pool.map(episode, jobs), 1):
            if n % 64 == 0 or n == len(jobs):
                print(f"{n}/{len(jobs)} {arm} {seed}", flush=True)


if __name__ == "__main__":
    main()
