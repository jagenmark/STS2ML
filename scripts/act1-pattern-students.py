"""Run a matched Silent A10 Act 1 forecast ablation using v0.111.0 Spire Codex move graphs."""

import argparse
import hashlib
import json
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import torch
from torch.nn import functional as F

from sts2rl.encounter import EncounterPolicy
from sts2rl.combat_effects import power
from sts2rl.enemy_forecast import WATERFALL_GIANT, attack_hits, waterfall_after_card, waterfall_forecast
from sts2rl.native import NativeSession, digest
from sts2rl.provenance import mc_provenance, require_provenance
from sts2rl.routing import RoomModel
from sts2rl.run_policy import RunWeights
from sts2rl.tactical_student import action_examples, make_network, pack
from sts2rl.teacher import CONTINUATION, incoming

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "artifacts/a10-push/release/challenger"
HOST = ROOT / "artifacts/a10-push/host-v9/src/Sts2Headless/bin/Curriculum/net9.0/Sts2Headless.dll"


def signature(enemy):
    return sorted(
        "Attack" if "Attack" in i["type"] else "Debuff" if "Debuff" in i["type"] else i["type"]
        for i in enemy.get("intents") or []
    )


def predict(enemy, turn, graphs, player_powers=()):
    giant = waterfall_forecast(enemy, turn, accelerant=power(player_powers, "ACCELERANT"))
    if giant is not None:
        damage = giant.certain_damage
        if damage is None:
            return None
        return (WATERFALL_GIANT, "Steam Eruption" if giant.eruption_forced else "Pressurize",
                int(damage > 0), damage)
    graph = graphs.get(enemy["id"].split(".")[-1])
    if not graph:
        return
    moves, nodes, initial = graph
    sig = signature(enemy)
    node = initial
    for _ in range(turn - 1):
        node = nodes.get(node, {}).get("next")
        if node is None:
            break

    def matches(n):
        move = moves.get(n.get("move_id"), {})
        return sorted(move.get("intent", "").split(" + ")) == sig

    candidates = (
        [nodes[node]]
        if node in nodes and matches(nodes[node])
        else [n for n in nodes.values() if matches(n)]
    )
    forecasts = set()
    for n in candidates:
        nxt = moves.get(nodes.get(n.get("next"), {}).get("move_id"))
        if not nxt:
            return
        dmg = nxt.get("damage") or {}
        attack = "Attack" in nxt.get("intent", "")
        if attack and not dmg.get("normal"):
            return
        hits = dmg.get("hit_count", 1) if attack else 0
        if not isinstance(hits, int):
            return
        forecasts.add((hits, hits * (dmg.get("ascension") or dmg.get("normal", 0))))
    if len(forecasts) == 1:
        hits, damage = forecasts.pop()
        return (enemy["id"], "+".join(sig), hits, damage)


def load_graphs(folder):
    # https://github.com/ptrlrd/spire-codex/blob/main/data-beta/v0.111.0/eng/monsters.json
    source = (folder / "monsters.json").read_bytes()
    if (
        hashlib.sha256(source).hexdigest()
        != "7c378bbdeb4120e52335e2840f87ce85d3b597370ba4fd531a2fd7a99beeaee1"
    ):
        raise ValueError("Expected the v0.111.0 monster snapshot used in verification")
    graphs = {}
    for monster in json.loads(source):
        pattern = monster.get("attack_pattern") or {}
        nodes = {n["id"]: n for n in pattern.get("states", [])}
        initial = next(
            (
                k
                for k, n in nodes.items()
                if n.get("move_id") == pattern.get("initial_move") and n.get("move_id")
            ),
            None,
        )
        graphs[monster["id"]] = ({m["id"]: m for m in monster["moves"]}, nodes, initial)
    return graphs


def permitted_prediction(enemy, state, graphs, allowed):
    rule = predict(enemy, state["round"], graphs, state.get("player_powers"))
    if rule and (enemy["id"] == WATERFALL_GIANT or allowed is None or rule in allowed):
        return rule
    return None


def inputs(state, scorer, predictions, forecast_columns=9):
    groups, choices = action_examples(state, scorer)
    giant = next((e for e in state["enemies"] if e["id"] == WATERFALL_GIANT and e["hp"] > 0), None)
    accelerant = power(state.get("player_powers"), "ACCELERANT")
    branches = waterfall_forecast(giant, state["round"], accelerant=accelerant) if giant else None
    cards = {card["index"]: card for card in state["hand"]} if branches else {}
    normal = branches.normal_damage if branches else None
    eruption = branches.eruption_damage if branches else None
    known = [v for v in predictions.values() if v]
    for group, c in zip(groups, choices, strict=True):
        action = group[0]
        target_index = action.args.get("target_index")
        target = predictions.get(target_index)
        after = known
        if (branches and not branches.eruption_forced and not branches.final_phase
                and action.kind == "play_card" and target_index == giant["index"]):
            projected = waterfall_after_card(giant, state["round"], cards[action.args["card_index"]],
                                             accelerant=accelerant)
            if projected.eruption_forced:
                target = (WATERFALL_GIANT, "Steam Eruption", 1, projected.eruption_damage)
                after = [rule for index, rule in predictions.items() if index != target_index and rule]
                after.append(target)
        c["x"].extend(
            [
                len(after) / 3,
                sum(v[3] for v in after) / 30,
                sum(v[2] for v in after) / 5,
                float(bool(target)),
                target[3] / 30 if target else 0,
                target[2] / 5 if target else 0,
            ]
        )
        if forecast_columns == 9:
            # Keep a genuine zero-damage Siphon distinct from an unknown normal move.
            c["x"].extend([float(normal is not None), (normal or 0) / 30, (eruption or 0) / 30])
    return groups, choices


def play(args):
    folder, stage, index, prefix, bundle, host = args
    seed = f"{prefix}{index:04}"
    graphs = load_graphs(folder)
    scorer = EncounterPolicy(RunWeights.load(bundle / "weights.json"), macro_seed=7103 + index)
    router = RoomModel.load(bundle / "room_model.json")
    arms = ["verify"] if stage == "verify" else ["baseline", "forecast"]
    allowed = (
        set(tuple(k) for k in json.loads((folder / "rules.json").read_text()))
        if stage == "test"
        else None
    )
    out = []
    torch.set_num_threads(1)
    for arm in arms:
        scorer = EncounterPolicy(scorer.weights, macro_seed=7103 + index)
        if stage == "test":
            saved = torch.load(folder / f"{arm}.pt", map_location="cpu", weights_only=True)
            if isinstance(saved, dict):
                require_provenance(saved, "feature_provenance", study_provenance(folder, bundle))
                params, vocab, width = saved["weights"], saved["vocab"], saved["inputs"]
                forecast_columns = 9
            else:
                params, vocab, width = saved
                forecast_columns = 6
            model = make_network(48, width, len(vocab) + 1)
            model.load_state_dict(params)
            model.eval()
        checks = defaultdict(lambda: [0, 0, 0, 0])
        fights = []
        last = {}
        prev = None
        with NativeSession(ROOT, folder / seed / arm, host_path=host, act_list="seeded") as game:
            s = game.reset(seed)
            opening = digest(s)
            if stage == "test" and isinstance(saved, dict):
                if any(seed == used_seed or opening == used_digest
                       for used_seed, used_digest in saved["development_openings"]):
                    raise ValueError(f"Evaluation seed or opening overlaps development data: {seed}")
            first_biome = s["context"]["act_name"]
            for _ in range(3000):
                ctx = s.get("context") or {}
                combat = s["decision"] == "combat_play"
                if (
                    fights
                    and "loss" not in fights[-1]
                    and (
                        s.get("in_combat") is False
                        or s["decision"] == "game_over"
                        or ctx.get("floor") != fights[-1]["floor"]
                    )
                ):
                    fights[-1]["loss"] = fights[-1]["hp"] - max(0, s["player"]["hp"])
                if ctx.get("act", 1) > 1 or s["decision"] == "game_over":
                    clear = ctx.get("act", 1) > 1
                    assert not clear or any(f["room"] == "Boss" for f in fights)
                    break
                if combat:
                    key = (ctx["floor"], s["round"])
                    fresh = key != prev
                    if not fights or fights[-1]["floor"] != key[0]:
                        fights.append(
                            dict(
                                room=ctx["room_type"],
                                floor=key[0],
                                enemies=[e["id"] for e in s["enemies"]],
                                hp=s["player"]["hp"],
                                turns=0,
                                covered=0,
                            )
                        )
                    predictions = {}
                    for e in s["enemies"]:
                        if e["hp"] <= 0:
                            continue
                        identity = (e["index"], e["id"])
                        if fresh and prev == (key[0], key[1] - 1) and last.get(identity):
                            rule = last[identity]
                            # Verify move attack count regardless of damage modifiers.
                            hits = attack_hits(e)
                            checks[rule][0] += 1
                            checks[rule][1] += hits == rule[2]
                            modifiers = {
                                "POWER.STRENGTH_POWER",
                                "POWER.WEAK_POWER",
                                "POWER.VULNERABLE_POWER",
                                "POWER.INTANGIBLE_POWER",
                            }
                            powers = (e.get("powers") or []) + (s.get("player_powers") or [])
                            if not any(power["id"] in modifiers for power in powers):
                                checks[rule][2] += 1
                                checks[rule][3] += incoming(e) == rule[3]
                        rule = permitted_prediction(e, s, graphs, allowed)
                        if rule:
                            predictions[e["index"]] = rule
                            if not fresh and rule[1] == "Steam Eruption":
                                # A player action can make the wind-up visible mid-turn.
                                last[identity] = rule
                    if fresh:
                        last = {
                            (e["index"], e["id"]): predictions.get(e["index"]) for e in s["enemies"]
                        }
                        fights[-1]["turns"] += 1
                        fights[-1]["covered"] += bool(predictions)
                    prev = key
                    if stage == "test":
                        groups, choices = inputs(s, scorer, predictions, forecast_columns)
                        batch = pack([{"choices": choices}], vocab)
                        if arm == "baseline":
                            batch[0][:, :, -forecast_columns:] = 0
                        with torch.inference_mode():
                            a = groups[int(model(*batch).argmax())][0]
                    else:
                        a = scorer(s)
                elif s["decision"] == "map_select":
                    a = router.choose(s, game.public_map())
                else:
                    a = scorer(s)
                s = game.step(a)
            else:
                raise RuntimeError("Unfinished Act 1")
        out.append(
            dict(
                seed=seed,
                arm=arm,
                opening=opening,
                biome=first_biome,
                clear=clear,
                fights=fights,
                checks=[[k, *v] for k, v in checks.items()],
            )
        )
    return out


def report(folder):
    import numpy as np

    by_room, by_encounter = defaultdict(list), defaultdict(list)
    comparisons = []
    rows = []
    out = {"models": [], "biomes": {}}
    openings = None
    for name, location in [
        ("174", folder),
        ("175", folder / "init-175"),
        ("176", folder / "init-176"),
    ]:
        pairs = json.loads((location / "test.json").read_text())
        keys = [(a["seed"], a["opening"]) for a, b in pairs]
        if openings is None:
            openings = keys
        assert keys == openings and len(set(keys)) == len(keys)
        for a, b in pairs:
            assert a["opening"] == b["opening"] and a["seed"] == b["seed"]
        comparisons.append([int(b["clear"]) - int(a["clear"]) for a, b in pairs])
        out["models"].append(
            {
                "init": name,
                "clears": [sum(pair[i]["clear"] for pair in pairs) for i in (0, 1)],
                "only_baseline": comparisons[-1].count(-1),
                "only_forecast": comparisons[-1].count(1),
            }
        )
        for pair in pairs:
            for row in pair:
                rows.append(row)
                for f in row["fights"]:
                    by_room[row["arm"], f["room"]].append(f)
                    by_encounter[row["arm"], " + ".join(sorted(f["enemies"]))].append(f)
    for biome in sorted({r["biome"] for r in rows}):
        out["biomes"][biome] = {
            arm: [
                sum(r["clear"] for r in rows if r["arm"] == arm and r["biome"] == biome),
                sum(r["arm"] == arm and r["biome"] == biome for r in rows),
            ]
            for arm in ("baseline", "forecast")
        }
    for group, items in [("rooms", by_room), ("encounters", by_encounter)]:
        out[group] = {
            "/".join(k): {
                "fights": len(fs),
                "mean_hp_loss": sum(f["loss"] for f in fs) / len(fs),
                "covered_turns": sum(f["covered"] for f in fs),
                "turns": sum(f["turns"] for f in fs),
            }
            for k, fs in sorted(items.items())
        }
    checks = [c for r in rows if r["arm"] == "forecast" for c in r["checks"]]
    out["heldout_forecast_checks"] = np.sum([c[1:] for c in checks], axis=0).tolist()
    delta = np.mean(comparisons, axis=0)
    draws = np.random.default_rng(42).choice(delta, (20000, len(delta))).mean(axis=1)
    out["clear_rate_difference"] = delta.mean()
    out["seed_bootstrap_95"] = np.quantile(draws, [0.025, 0.975]).tolist()
    (folder / "report.json").write_text(json.dumps(out, indent=2) + "\n")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("folder", type=Path)
    p.add_argument("stage", choices=["verify", "train", "test", "report"])
    p.add_argument("--seeds", type=int, default=64)
    p.add_argument("--init", type=int, default=174)
    p.add_argument("--host", type=Path, default=HOST)
    p.add_argument("--bundle", type=Path, default=BUNDLE, help="Challenger directory with weights and room model")
    p.add_argument("--teachers", type=Path, help="Fresh versioned MC collection for student fitting")
    p.add_argument("--prefix", help="Use a fresh namespace for native verification or evaluation")
    args = p.parse_args()
    folder = args.folder.resolve()
    if args.stage == "report":
        report(folder)
        return
    if args.stage == "train":
        if args.teachers is None:
            p.error("Training requires --teachers with a matching MC continuation")
        allowed = {tuple(rule) for rule in json.loads((folder / "rules.json").read_text())}
        train(folder, allowed, args.init, args.teachers, args.bundle)
        return
    with ProcessPoolExecutor(6) as pool:
        prefix = args.prefix or f"ACT1PAT{args.stage.upper()}"
        results = list(pool.map(play, [(folder, args.stage, i, prefix, args.bundle, args.host)
                                       for i in range(args.seeds)]))
    (folder / f"{args.stage}.json").write_text(json.dumps(results))
    if args.stage == "verify":
        counts = defaultdict(lambda: [0, 0, 0, 0, set()])
        for (row,) in results:
            for k, n, ok, clean, exact in row["checks"]:
                c = counts[tuple(k)]
                c[0] += n
                c[1] += ok
                c[2] += clean
                c[3] += exact
                if clean:
                    c[4].add(row["seed"])
        allowed = {
            k
            for k, (n, ok, clean, exact, seeds) in counts.items()
            if k[0] != WATERFALL_GIANT and n == ok and clean == exact and len(seeds) >= 2
        }
        (folder / "rules.json").write_text(json.dumps(sorted(allowed)))
        if args.teachers:
            train(folder, allowed, args.init, args.teachers, args.bundle)
    else:
        for a, b in results:
            assert a["opening"] == b["opening"] and a["biome"] == b["biome"]


def study_provenance(folder, bundle):
    from sts2rl.provenance import feature_provenance
    from sts2rl import enemy_forecast

    def source_hash(path):
        return hashlib.sha256(Path(path).read_text(encoding="utf-8").encode()).hexdigest()

    return {"actions": feature_provenance(RunWeights.load(bundle / "weights.json")),
            "study_code": source_hash(__file__), "forecast_code": source_hash(enemy_forecast.__file__),
            "rules": hashlib.sha256(json.dumps(sorted(json.loads((folder / "rules.json").read_text())),
                                              separators=(",", ":")).encode()).hexdigest()}


def train(folder, allowed, init, teachers, bundle):
    graphs = load_graphs(folder)
    scorer = EncounterPolicy(RunWeights.load(bundle / "weights.json"))
    teacher = mc_provenance(CONTINUATION)
    rows = []
    development = set()
    verification = folder / "verify.json"
    if verification.is_file():
        development.update((row["seed"], row["opening"]) for row, in json.loads(verification.read_text()))
    for path in sorted(teachers.glob("run-*/teacher.jsonl")):
        result = path.with_name("result.json")
        if not result.is_file() or json.loads(result.read_text())["status"] != "complete":
            continue
        with (path.parent / "game/rpc.jsonl").open(encoding="utf-8") as trace:
            root = json.loads(next(trace))
        if root["command"].get("cmd") != "training_restore" or root["command"].get("history"):
            raise ValueError(f"Missing native training opening for {path.parent}")
        development.add((root["command"]["seed"], root["response_digest"]))
        for line in path.read_text().splitlines():
            r = json.loads(line)
            require_provenance(r, "teacher_provenance", teacher)
            require_provenance(r, "continuation", CONTINUATION)
            s = r["observation"]
            if s["decision"] != "combat_play":
                continue
            preds = {
                e["index"]: k
                for e in s["enemies"]
                if e["hp"] > 0 and (k := permitted_prediction(e, s, graphs, allowed)) is not None
            }
            groups, choices = inputs(s, scorer, preds)
            label = next(
                i for i, g in enumerate(groups) if any(a.id == r["chosen_action_id"] for a in g)
            )
            rows.append(dict(choices=choices, label=label))
    if not rows:
        raise ValueError("No version-matched combat decisions in the specified teacher collection")
    vocab = {
        s: i + 1 for i, s in enumerate(sorted({c["token"] for r in rows for c in r["choices"]}))
    }
    x, t, m = pack(rows, vocab)
    labels = torch.tensor([r["label"] for r in rows])
    torch.set_num_threads(1)
    for arm in ["baseline", "forecast"]:
        torch.manual_seed(init)
        model = make_network(48, x.shape[-1], len(vocab) + 1)
        opt = torch.optim.AdamW(model.parameters(), lr=0.001)
        features = x.clone()
        if arm == "baseline":
            features[:, :, -9:] = 0
        for _ in range(24):
            for idx in torch.randperm(len(rows)).split(64):
                opt.zero_grad()
                F.cross_entropy(model(features[idx], t[idx], m[idx]), labels[idx]).backward()
                opt.step()
        torch.save({"weights": model.state_dict(), "vocab": vocab, "inputs": x.shape[-1],
                    "development_openings": sorted(development),
                    "teacher_provenance": teacher, "feature_provenance": study_provenance(folder, bundle)},
                   folder / f"{arm}.pt")
    print(
        len(allowed),
        "verified rules;",
        len(rows),
        "training decisions;",
        int(((x[:, 0, -9] > 0) | (x[:, 0, -3] > 0) | (x[:, 0, -1] > 0)).sum()),
        "covered",
    )


if __name__ == "__main__":
    main()
