"""Reduce local native receipts into shareable per-run lategame evidence."""

import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from sts2rl.teacher import incoming

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "artifacts/v5-autopsy/V5DIAG"
EVIDENCE = ROOT / "docs/evidence"
SCALERS = ("FOOTWORK", "AFTERIMAGE", "WELL_LAID_PLANS", "NOXIOUS_FUMES", "ACCURACY", "CATALYST")


def name(item):
    return item["id"].split(".")[-1]


def card_key(c):
    return [name(c), c.get("upgrades", int(c.get("upgraded", False)))]


def effects(desc):
    d = (desc or "").lower()
    return dict(
        energy="{energy:energyicons" in d,
        draw=any(w in d for w in ("draw {cards", "draw 1", "draw an additional", "draw a card")),
    )


def profile(p):
    deck, relics = p["deck"], p["relics"]
    cnt = Counter(name(c) for c in deck)
    n = len(deck)
    aoe = sum("all enemies" in (c.get("description") or "").lower() for c in deck)
    block = sum(
        any((c.get("stats") or {}).get(k, 0) > 0 for k in ("block", "calculatedblock"))
        for c in deck
    )
    flags = [
        effects(r["description"])
        for r in relics
        if not r.get("is_used_up") and r.get("status") != "Disabled"
    ]
    return dict(
        size=n,
        upgrades=sum(card_key(c)[1] for c in deck),
        powers=sum(c["type"] == "Power" for c in deck),
        aoe=aoe,
        poison_sources=sum(
            any((c.get("stats") or {}).get(k, 0) > 0 for k in ("poisonpower", "poisonperturn"))
            for c in deck
        ),
        accelerants=cnt["ACCELERANT"],
        hp_fraction=p["hp"] / p["max_hp"],
        block_density=block / n,
        hp=p["hp"],
        max_hp=p["max_hp"],
        potions=len(p["potions"]),
        energy_relics=sum(f["energy"] for f in flags),
        draw_relics=sum(f["draw"] for f in flags),
        named_scalers=sum(cnt[k] for k in SCALERS),
        **{k: cnt[k] for k in SCALERS},
    )


def option_id(o):
    return o.get("text_key") or o.get("option_id") or o.get("title")


def macro(v):
    s, act = v["before"], v["action"]
    ctx, p, after = s["context"], s["player"], v["after_player"]
    row = dict(
        act=ctx["act"],
        floor=ctx["floor"],
        room=ctx["room_type"],
        step=v["step"],
        decision=s["decision"],
        action=act["action"],
        hp=p["hp"],
        max_hp=p["max_hp"],
        hp_delta=after.get("hp", p["hp"]) - p["hp"],
        gold=p["gold"],
        gold_delta=after.get("gold", p["gold"]) - p["gold"],
    )
    args = act["args"]
    if s["decision"] in ("event_choice", "rest_site"):
        available = [
            o for o in s["options"] if not o.get("is_locked") and o.get("is_enabled", True)
        ]
        picked = next((o for o in available if o["index"] == args.get("option_index")), {})
        row.update(
            event=s.get("event_name"),
            offered=[option_id(o) for o in available],
            choice=option_id(picked),
        )
        if s["decision"] == "event_choice":

            def curses(player):
                return Counter(name(c) for c in player.get("deck", ()) if c.get("type") == "Curse")

            row["added_curses"] = list((curses(after) - curses(p)).elements())
            row["offer_text"] = {option_id(o): o["description"] for o in available}
        else:
            candle = next((r for r in p["relics"] if name(r) == "PUMPKIN_CANDLE"), None)
            row["candle"] = candle["counter"] if candle else None
        row["relic_gains"] = list(
            (
                Counter(name(r) for r in after.get("relics", []))
                - Counter(name(r) for r in p["relics"])
            ).elements()
        )
    elif s["decision"] == "shop":
        available = {}
        for group, key in (
            ("cards", "card_index"),
            ("relics", "relic_index"),
            ("potions", "potion_index"),
        ):
            for item in s[group]:
                if (
                    item["is_stocked"]
                    and item["cost"] <= p["gold"]
                    and item.get("can_procure", True)
                ):
                    available[item["name"]] = item["cost"]
                    if args.get(key) == item["index"]:
                        row.update(item=item["name"], price=item["cost"])
        if s.get("card_removal_available") and s["card_removal_cost"] <= p["gold"]:
            available["removal"] = s["card_removal_cost"]
        row["available"] = available
        if row.get("item") == "Accelerant":
            row["printed_poison_sources"] = profile(p)["poison_sources"]
    elif s["decision"] == "card_reward":
        row["offered_cards"] = [name(c) for c in s["cards"]]
        if "ACCELERANT" in row["offered_cards"]:
            row["printed_poison_sources"] = profile(p)["poison_sources"]
        row["picked_card"] = next(
            (name(c) for c in s["cards"] if c["index"] == args.get("card_index")), None
        )
    elif s["decision"] == "card_select":
        chosen = {int(i) for i in args.get("indices", "").split(",") if i}
        row.update(
            selected=[card_key(c) for c in s["cards"] if c["index"] in chosen],
            removed=list(
                (
                    Counter(tuple(card_key(c)) for c in p["deck"])
                    - Counter(tuple(card_key(c)) for c in after.get("deck", p["deck"]))
                ).elements()
            ),
        )
    return row


def fight(records, native):
    start, end = records[0], records[-1]
    s = start["before"].get("combat_state", start["before"])
    p = s["player"]
    ctx = s["context"]
    form = "+".join(name(e) for e in s["enemies"] if e["hp"] > 0)
    totals = Counter()
    death = None
    # Include the native action entering combat, e.g. passive opening damage.
    for step in range(start["step"] - 1, end["step"] + 1):
        for hit in native[step]:
            if "target" in hit:
                totals["in" if hit["target"] == "PLAYER" else "out"] += hit["UnblockedDamage"]
            elif "enemies" in hit and step == end["step"]:
                death = hit
    actions = []
    for r in records:
        before = r["before"]
        view = before.get("combat_state", before)
        command, args = r["action"]["action"], r["action"]["args"]
        card = next((c for c in view["hand"] if c["index"] == args.get("card_index")), None)
        enemies = view["enemies"]
        target = next((name(e) for e in enemies if e["index"] == args.get("target_index")), None)
        potions = view["player"]["potions"]
        pot = next((name(q) for q in potions if q["index"] == args.get("potion_index")), None)
        choices = set(args.get("indices", "").split(","))
        actions.append(
            dict(
                step=r["step"],
                round=view["round"],
                energy=view["energy"],
                hp=view["player"]["hp"],
                block=view["player"]["block"],
                command=command,
                card=name(card) if card else None,
                kind=card["type"] if card else None,
                pot=pot,
                target=target,
                fallback=r["fallback"],
                eligible=before["decision"] != "combat_play"
                or any(c["can_play"] for c in view["hand"])
                or any(q["can_use"] for q in potions),
                powers=[name(q) for q in view.get("player_powers") or []],
                playable_powers=[
                    name(c) for c in view["hand"] if c["can_play"] and c["type"] == "Power"
                ],
                enemies=[
                    [
                        name(e),
                        e["hp"],
                        e["max_hp"],
                        incoming(e),
                        {name(q): q["amount"] for q in e.get("powers") or []},
                    ]
                    for e in enemies
                ],
                selected=[name(c) for c in before.get("cards", ()) if str(c["index"]) in choices],
            )
        )
    fatal = end["next_decision"] == "game_over" and end["after_player"]["hp"] == 0
    row = dict(
        act=ctx["act"],
        floor=ctx["floor"],
        room=ctx["room_type"],
        formation=form,
        opening=profile(p),
        deck=[card_key(c) for c in p["deck"]],
        relics=[name(r) for r in p["relics"]],
        belt=[name(q) for q in p["potions"]],
        terminal_belt=[name(q) for q in end["after_player"]["potions"]],
        last_belt=[
            (name(q), q.get("can_use"))
            for q in end["before"].get("combat_state", end["before"])["player"]["potions"]
        ],
        native_death=death if fatal else None,
        died=fatal,
        damage=totals,
        actions=actions,
    )
    if fatal and death is None:
        raise ValueError(f"Missing native death witness at {ctx} step {end['step']}")
    return row


def reduce_run(folder):
    outcome = json.loads((folder / "result.json").read_bytes())
    if outcome["status"] != "complete" or outcome.get("abandoned"):
        raise ValueError(f"Incomplete run {folder}")
    native = defaultdict(list)
    with (folder / "native.jsonl").open() as stream:
        if json.loads(next(stream)) != {"ready": True}:
            raise ValueError("Uninitialized native observer")
        for line in stream:
            r = json.loads(line)
            native[r["step"]].append(r)
    macro_steps = []
    fights = defaultdict(list)
    with gzip.open(folder / "trace.gz") as stream:
        for line in stream:
            v = json.loads(line)
            s = v["before"]
            if s.get("in_combat"):
                ctx = s.get("combat_state", s)["context"]
                fights[ctx["act"], ctx["floor"]].append(v)
            elif s["decision"] in (
                "rest_site",
                "event_choice",
                "shop",
                "card_select",
                "card_reward",
            ):
                macro_steps.append(macro(v))
    return dict(
        outcome={
            k: outcome[k]
            for k in (
                "seed",
                "index",
                "act_list",
                "status",
                "act",
                "floor",
                "death",
                "a1_clear",
                "a2_clear",
                "win",
                "boss_fights",
                "steps",
            )
        },
        macro=macro_steps,
        fights=[fight(records, native) for records in fights.values()],
    )


def compact_pair(seed):
    arms = {}
    for key, folder in (("baseline", "V5DEV"), ("prototype", "V5DEV-fix")):
        row = json.loads((WORK.parent / folder / seed / "result.json").read_bytes())
        if row["seed"] != seed or row["status"] != "complete" or row.get("abandoned"):
            raise ValueError(f"Incomplete dev pair {seed}")
        arms[key] = {
            k: row[k]
            for k in (
                "seed",
                "index",
                "act_list",
                "status",
                "act",
                "floor",
                "steps",
                "a1_clear",
                "a2_clear",
                "boss_fights",
                "win",
                "trajectory_sha256",
                "macro_choices",
            )
        }
    base, proto = arms.values()
    why = "identical"
    first_difference = None
    if base["trajectory_sha256"] != proto["trajectory_sha256"]:
        why = "unattributed"
        for a, b in zip(base["macro_choices"], proto["macro_choices"]):
            if a != b:
                first_difference = {"baseline": a, "prototype": b}
                if a[:2] == b[:2]:
                    why = f"{a[2]} -> {b[2]}"
                break
    same_macro_choices = [r[::2] for r in base["macro_choices"]] == [
        r[::2] for r in proto["macro_choices"]
    ]
    for arm in arms.values():
        del arm["macro_choices"]
    return {
        **arms,
        "first_change": why,
        "first_macro_difference": first_difference,
        "same_macro_steps_and_choices": same_macro_choices,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dev", action="store_true")
    args = p.parse_args()
    manifest_dir = WORK.parent / "V5DEV" if args.dev else WORK
    manifest = json.loads((manifest_dir / "lock.json").read_bytes())
    order = manifest.pop("panel")
    if args.dev:
        treatment = json.loads((WORK.parent / "V5DEV-fix/lock.json").read_bytes())
        assert treatment.pop("panel") == order
        assert treatment["fix"] is True and manifest["fix"] is False
        assert {**treatment, "fix": False} == manifest
        manifest["prototype_fix"] = True
        manifest["prototype_attempts_retried"] = len(
            list((WORK.parent / "V5DEV-fix").glob("*.attempt-*"))
        )
    manifest["attempts_retried"] = len(list(manifest_dir.glob("*.attempt-*")))
    if not args.dev and (WORK.parent / "wins.json").exists():
        manifest["replayed_victories"] = json.loads((WORK.parent / "wins.json").read_bytes())
    if not args.dev and (WORK.parent / "parity.json").exists():
        manifest["observer_parity"] = json.loads((WORK.parent / "parity.json").read_bytes())
    if not args.dev and (WORK.parent / "ancient-missing.json").is_file():
        manifest["skipped_ancient_map_transitions"] = json.loads(
            (WORK.parent / "ancient-missing.json").read_bytes()
        )
    path = EVIDENCE / "silent-a10-v5-autopsy-runs.jsonl.gz"
    approaches_file = WORK.parent / "approaches.json"
    approaches = (
        {r["seed"]: r for r in json.loads(approaches_file.read_bytes())}
        if not args.dev and approaches_file.is_file()
        else {}
    )
    if args.dev:
        path = EVIDENCE / "silent-a10-v5-autopsy-pairs.jsonl.gz"
    with TemporaryDirectory(dir=EVIDENCE) as temp:
        target = Path(temp) / path.name
        with gzip.GzipFile(str(target), "wb", mtime=0) as stream:
            for _, seed, _ in order:
                row = compact_pair(seed) if args.dev else reduce_run(WORK / seed)
                if seed in approaches:
                    row["approach_replay"] = approaches[seed]
                if seed == order[0][1]:
                    row["collection"] = manifest
                stream.write(json.dumps(row, separators=(",", ":")).encode() + b"\n")
        target.replace(path)


if __name__ == "__main__":
    main()
