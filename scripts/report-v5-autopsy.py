"""Recompute descriptive statistics from the released lategame receipts (no game needed)."""

from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
from statistics import mean

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "docs/evidence"
RUNS = DEST / "silent-a10-v5-autopsy-runs.jsonl.gz"
DEV = DEST / "silent-a10-v5-autopsy-pairs.jsonl.gz"


def dist(v):
    return dict(
        zip(
            ("min", "q25", "median", "q75", "max"),
            np.round(np.percentile(v, [0, 25, 50, 75, 100]), 3).tolist(),
        )
    )


def death_stats(fs):
    turns = [f["native_death"]["round"] for f in fs]

    def bars(f):
        en = f["native_death"]["enemies"]
        return [e for e in en if e["id"] == "QUEEN"] if "QUEEN" in f["formation"] else en

    hp = [sum(e["hp"] for e in bars(f)) for f in fs]
    return dict(
        n=len(fs),
        hp=dist(hp),
        hp_le25=sum(x <= 25 for x in hp),
        round=dist(turns),
        board_hp=dist([sum(e["hp"] for e in f["native_death"]["enemies"]) for f in fs]),
        entry_hp=dist([f["opening"]["hp"] for f in fs]),
        out_per_round=round(sum(f["damage"].get("out", 0) for f in fs) / sum(turns), 2),
        in_per_round=round(sum(f["damage"].get("in", 0) for f in fs) / sum(turns), 2),
        turns=sum(turns),
        opening_belt=Counter(len(f["belt"]) for f in fs),
        potion_use_rounds=Counter(
            a["round"] for f in fs for a in f["actions"] if a["command"] == "use_potion"
        ),
        belt=Counter(len(f["terminal_belt"]) for f in fs),
    )


def deck_diff(mid):
    clear = [f["opening"] for f in mid if not f["died"]]
    dead = [f["opening"] for f in mid if f["died"]]
    features = {}
    for k in clear[0]:
        c, d = [r[k] for r in clear], [r[k] for r in dead]
        auc = mean(float(x > y) + 0.5 * (x == y) for x in c for y in d)
        features[k] = dict(
            clear_mean=round(mean(c), 3),
            death_mean=round(mean(d), 3),
            clear_median=dist(c)["median"],
            death_median=dist(d)["median"],
            clear_nonzero=sum(x > 0 for x in c),
            death_nonzero=sum(x > 0 for x in d),
            auc=round(auc, 3),
        )
    return features


def macros(rows):
    events = defaultdict(lambda: [0, 0, 0])
    ancient = defaultdict(lambda: defaultdict(lambda: [0, 0, 0]))
    camp = defaultdict(Counter)
    shop = defaultdict(Counter)
    items = defaultdict(Counter)
    removes = Counter()
    curses = defaultdict(Counter)
    rewards = defaultdict(Counter)
    for_act = defaultdict(Counter)
    no_poison = 0
    for row in rows:
        ornate = False
        removal = None
        for m in row["macro"]:
            act, choice = m["act"], m.get("choice")
            if (choice or "").endswith(".options.ORNATE") and "CLUMSY" in m.get("added_curses", ()):
                ornate = True
            if m["action"] == "remove_card":
                removal = m
            if (
                ornate
                and removal
                and removal["step"] + 1 == m["step"]
                and m["room"] == "Shop"
                and any(c == "CLUMSY" for c, _ in m.get("removed", ()))
            ):
                shop[act]["clumsy_after_ornate_removals"] += 1
                shop[act]["clumsy_after_ornate_price"] += removal["available"]["removal"]
            if m["decision"] == "event_choice" and choice:
                curses[choice].update(m.get("added_curses", ()))
                for_act[act][choice] += 1
                key = events[choice]
                key[0] += 1
                key[1] += max(0, -m["hp_delta"])
                key[2] += max(0, m["hp_delta"])
                if act > 1 and m["floor"] == 1 and ".INITIAL.options." in choice:
                    for o in m["offered"]:
                        x = ancient[act][o]
                        x[0] += 1
                        x[1] += int(o == choice)
                        x[2] += int(o == choice and row["outcome"]["a2_clear"])
            if m["decision"] == "rest_site":
                c = camp[act]
                c[choice] += 1
                if choice == "HEAL":
                    c["hp_gained"] += m["hp_delta"]
                    c["zero_heals"] += m["hp_delta"] == 0
                if "KINDLE" in m["offered"]:
                    c["kindle_legal"] += 1
                    c["kindle_taken"] += choice == "KINDLE"
                    if m["candle"] == 0:
                        c["expired_" + choice] += 1
            if m["decision"] == "card_reward":
                for c in set(m["offered_cards"]):
                    rewards[c]["offered"] += 1
                    rewards[c]["taken"] += int(c == m["picked_card"])
                    if c == "ACCELERANT" and m.get("printed_poison_sources", 0) > 0:
                        rewards[c]["offered_with_poison"] += 1
                        rewards[c]["whole_offer_skipped_with_poison"] += int(
                            m["picked_card"] is None
                        )
                    rewards[c]["whole_offer_skipped"] += int(m["picked_card"] is None)
            if m["decision"] == "shop":
                no_poison += m.get("printed_poison_sources") == 0
                shop[act][m["action"]] += 1
                if m["action"] == "leave_room":
                    shop[act]["leave_with_affordable_removal"] += "removal" in m["available"]
                    shop[act]["gold_on_leave"] += m["gold"]
                if m.get("item"):
                    items[m["action"]][m["item"]] += 1
            if m["decision"] == "card_select" and m["room"] == "Shop":
                removes.update(k for k, _ in m["removed"])
    return dict(
        event_choice_count_cost_heal=events,
        ancient_offered_picked_picked_reached_a3=ancient,
        camp=camp,
        shop=shop,
        items=items,
        shop_selection_cards_lost=removes,
        added_curses={k: v for k, v in curses.items() if v},
        events_by_act=for_act,
        card_rewards=rewards,
        accelerant_purchases_without_printed_poison=no_poison,
    )


def tactics(fs):
    report = {}
    groups = defaultdict(list)
    for f in fs:
        groups[f["formation"]].append(f)
    for group, ff in groups.items():
        totals = Counter()
        targets = Counter()
        fallback = Counter()
        selected = Counter()
        for f in ff:
            turns = defaultdict(list)
            facing = "ROCKET"
            for a in f["actions"]:
                turns[a["round"]].append(a)
                if a["eligible"]:
                    fallback[a["fallback"] or "covered"] += 1
                if a["target"]:
                    facing = a["target"]
                    if a["kind"] == "Attack":
                        targets[facing] += 1
                if a["selected"]:
                    selected.update(a["selected"])
                if a["command"] == "use_potion":
                    totals["potion_uses"] += 1
                    totals["round1_potion_uses"] += a["round"] == 1
                if a["kind"] == "Skill" and group == "TEST_SUBJECT":
                    totals["skills"] += 1
                    totals["skills_under_enrage"] += any(
                        "ENRAGE_POWER" in e[4] for e in a["enemies"]
                    )
                if (
                    group == "CRUSHER+ROCKET"
                    and a["command"] == "end_turn"
                    and len(a["enemies"]) == 2
                ):
                    e1, e2 = a["enemies"]
                    if e1[0] != facing:
                        e1, e2 = e2, e1
                    totals["both_alive_end_turns"] += 1
                    if (
                        e2[3] / 1.5 > e1[3]
                        and e2[3] + e1[3] > a["block"]
                        and "INTANGIBLE_POWER" not in a["powers"]
                    ):
                        totals["higher_unblocked_threat_behind"] += 1
                if a["command"] == "end_turn" and group == "THE_INSATIABLE":
                    totals["sandpit_one_end_turns"] += any(
                        e[4].get("SANDPIT_POWER") == 1 for e in a["enemies"]
                    )
            for r, actions in turns.items():
                if r <= 2:
                    playable = {c for a in actions for c in a["playable_powers"]}
                    if playable:
                        totals["early_rounds_with_playable_power"] += 1
                        totals["played_any_early_power"] += any(
                            a["kind"] == "Power" for a in actions
                        )
                if any("SLOTH_POWER" in a["powers"] for a in actions):
                    totals["sloth_rounds"] += 1
                    plays = [a for a in actions if a["command"] == "play_card"]
                    totals["sloth_rounds_ge3_plays"] += len(plays) >= 3
                    totals["sloth_basic_plays"] += sum(
                        a["card"] in ("STRIKE_SILENT", "DEFEND_SILENT") for a in plays
                    )
                    totals["sloth_plays"] += len(plays)
        report[group] = dict(
            n=len(ff),
            counters=totals,
            attack_targets=targets,
            selection=selected,
            eligible_by_fallback=fallback,
        )
    return report


def milestone(rs):
    return dict(
        n=len(rs),
        a1_clear=sum(r["a1_clear"] for r in rs),
        a2_boss=sum(any(a == 2 for a, _ in r["boss_fights"]) for r in rs),
        a2_clear=sum(r["a2_clear"] for r in rs),
        a3_boss=sum(any(a == 3 for a, _ in r["boss_fights"]) for r in rs),
        win=sum(r["win"] for r in rs),
        mean_floor=round(mean(17 * (r["act"] - 1) + r["floor"] for r in rs), 4),
    )


def paired(pairs):
    out = {}
    for mode in ("all", "default", "seeded"):
        ps = [p for p in pairs if mode == "all" or p["baseline"]["act_list"] == mode]
        b, t = ([p[k] for p in ps] for k in ("baseline", "prototype"))
        bm, tm = milestone(b), milestone(t)
        diff = np.array(
            [17 * (y["act"] - x["act"]) + y["floor"] - x["floor"] for x, y in zip(b, t)]
        )
        rng = np.random.default_rng(20261123)
        sims = sum(
            rng.choice(d, size=(10000, len(d))).sum(axis=1)
            for m in sorted({r["act_list"] for r in b})
            if len(d := diff[[r["act_list"] == m for r in b]])
        ) / len(b)
        out[mode] = dict(
            baseline=bm,
            prototype=tm,
            delta_floor=round(float(diff.mean()), 4),
            floor_ci95=np.percentile(sims, [2.5, 97.5]).round(4).tolist(),
            floor_wlt=[int(sum(diff > 0)), int(sum(diff < 0)), int(sum(diff == 0))],
            first_divergences=Counter(p["first_change"] for p in ps),
        )
        for key in ("a2_clear", "win"):
            out[mode][key + "_gain_loss"] = [
                sum(y[key] and not x[key] for x, y in zip(b, t)),
                sum(x[key] and not y[key] for x, y in zip(b, t)),
            ]
    return out


def approach_stats(rows):
    encounters = defaultdict(list)
    groups = defaultdict(list)
    replays = [r for r in rows if "approach_replay" in r]
    matched = [r for r in replays if r["approach_replay"]["matched"]]
    for row in matched:
        total = Counter()
        for room in row["approach_replay"]["rooms"]:
            loss = room["hp"] - room["exit_hp"]
            total[room["room"]] += loss
            encounters[(room["room"], room["enemies"])].append(loss)
        groups["clear" if row["outcome"]["a2_clear"] else "death"].append(total)
    return dict(
        replays=len(replays),
        matched=len(matched),
        opening_to_exit_hp_loss={
            room + "/" + name: dict(
                n=len(v), mean=round(mean(v), 2), median=dist(v)["median"], sum=sum(v)
            )
            for (room, name), v in encounters.items()
        },
        per_lobby_by_outcome={
            outcome: {kind: round(mean(r[kind] for r in vs), 2) for kind in ("Monster", "Elite")}
            for outcome, vs in groups.items()
        },
    )


def verify_panel(outcomes, collection):
    triples = [[r["index"], r["seed"], r["act_list"]] for r in outcomes]
    lock = hashlib.sha256(json.dumps(triples, separators=(",", ":")).encode()).hexdigest()
    if lock != collection["panel_sha256"]:
        raise ValueError("Episode panel fails locked identity check")


def main():
    rows = list(map(json.loads, gzip.open(RUNS)))
    assert len({r["outcome"]["seed"] for r in rows}) == len(rows) == 384
    fs = [f for r in rows for f in r["fights"]]
    mid = [f for f in fs if f["act"] == 2]
    dead = [f for f in fs if f["died"]]
    outcomes = [r["outcome"] for r in rows]
    verify_panel(outcomes, rows[0]["collection"])
    assert len(mid) == milestone(outcomes)["a2_boss"]
    assert len(dead) == len(mid) - sum(r["win"] for r in outcomes)
    hp_bands = defaultdict(Counter)
    for f in mid:
        hp = f["opening"]["hp"]
        key = "under_50" if hp < 50 else "50_to_64" if hp < 65 else "65_plus"
        hp_bands[key]["entered"] += 1
        hp_bands[key]["cleared"] += int(not f["died"])
    groups = defaultdict(list)
    for f in dead:
        groups[f["formation"]].append(f)
        groups[f"Act {f['act']} {f['room']}"].append(f)
    late = [r for r in rows if r["fights"]]
    data = dict(
        diagnostic_collection=rows[0]["collection"],
        act2_approach=approach_stats(rows),
        milestones={
            m: milestone([r for r in outcomes if m == "all" or r["act_list"] == m])
            for m in ("all", "default", "seeded")
        },
        deaths={k: death_stats(g) for k, g in groups.items()},
        a2_opening_hp_bands=hp_bands,
        prioritized_actions=[
            {
                "rank": 1,
                "scope": "macro",
                "test": "Protect HP on the route to the last Act 2 camp",
                "exposure": "Opening HP bands",
            },
            {
                "rank": 2,
                "scope": "draft/shop",
                "test": "Value Accelerant jointly with poison sources in free rewards",
                "exposure": "Unchosen reward and Act 2 boss-entry deck",
            },
            {
                "rank": 3,
                "scope": "boss tactics",
                "test": "Budget Frantic Escape before Sandpit expires, and card slots under Sloth",
                "exposure": "Act 2 fatal end-turns and prompts",
            },
            {
                "rank": 4,
                "scope": "multi-turn value",
                "test": "Value Queen and the remaining second boss together",
                "exposure": "First versus second fatal boss floor",
            },
            {
                "rank": 5,
                "scope": "macro",
                "test": "Correct signed Ancient effects and expired Candle camp actions",
                "exposure": "Locked paired dev comparison",
            },
        ],
        winners=[r for r in outcomes if r["win"]],
        a2_entries=Counter(f["formation"] for f in mid),
        deck_at_a2_boss=deck_diff(mid),
        deck_by_boss={
            k: deck_diff([f for f in mid if f["formation"] == k])
            for k in sorted({f["formation"] for f in mid if not f["died"]})
        },
        macros_all=macros(rows),
        macros_late_entrants=macros(late),
        fatal_fight_tactics=tactics(dead),
        all_late_fight_tactics=tactics(fs),
        belt_at_death=Counter(len(f["terminal_belt"]) for f in dead),
        belt_before_fatal_action=Counter(len(f["last_belt"]) for f in dead),
    )
    if DEV.is_file():
        pairs = list(map(json.loads, gzip.open(DEV)))
        assert len(pairs) == len({r["baseline"]["seed"] for r in pairs}) == 256
        for arm in ("baseline", "prototype"):
            verify_panel([p[arm] for p in pairs], pairs[0]["collection"])
        assert not {r["seed"] for r in outcomes} & {p["baseline"]["seed"] for p in pairs}
        data["paired_dev"] = paired(pairs)
        data["dev_collection"] = pairs[0]["collection"]
    for file in (RUNS, DEV, *sorted(DEST.glob("silent-a10-v5-win-V5DIAG_*.jsonl.gz"))):
        if file.is_file():
            data.setdefault("receipt_sha256", {})[file.name] = hashlib.sha256(
                file.read_bytes()
            ).hexdigest()
    dest = DEST / "silent-a10-v5-lategame-autopsy.json"
    dest.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
