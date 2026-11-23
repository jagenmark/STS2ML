"""Reduce local native receipts into shareable per-run lategame evidence."""

import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path

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
            elif s["decision"] in ("rest_site", "event_choice", "shop", "card_select"):
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


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--partial", type=Path)
    args = p.parse_args()
    order = json.loads((WORK / "lock.json").read_bytes())["panel"]
    path = args.partial or EVIDENCE / "silent-a10-v5-autopsy-runs.jsonl.gz"
    with gzip.GzipFile(str(path), "wb", mtime=0) as stream:
        for _, seed, _ in order:
            if args.partial and not (WORK / seed / "result.json").exists():
                continue
            row = reduce_run(WORK / seed)
            stream.write(json.dumps(row, separators=(",", ":")).encode() + b"\n")


if __name__ == "__main__":
    main()
