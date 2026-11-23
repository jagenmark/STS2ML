"""Small terminal and coverage counters for release verification."""
from collections import Counter, defaultdict


class EpisodeSummary:
    def __init__(self):
        self.coverage = defaultdict(Counter)
        self.death = None
        self.fight = None
        self.formation = None
        self.native = Counter()
        self.independent_native = Counter()
        self.mismatches = []
        self.exits = []

    def audit(self, record, second_audit=None):
        if oracle := record.get("oracle"):
            self.native[oracle[1]] += 1
            self.independent_native[(second_audit or oracle)[1]] += 1
            if second_audit and second_audit != oracle:
                record["independent_oracle"] = second_audit
            if oracle[1] == "mismatch":
                self.mismatches.append(record)

    def fight_exit(self, before, after):
        if not before.get("in_combat") or (after.get("in_combat") and after["decision"] != "game_over"):
            return
        act, floor, room = self.fight
        if act == 3 or (act == 2 and room == "Boss"):
            died = after["decision"] == "game_over" and not after.get("victory")
            self.exits.append([act, floor, room, self.formation, 0 if died else after["player"]["hp"], not died])

    def observe(self, before, after, fallback):
        view = before.get("combat_state", before)
        ctx = view.get("context") or {}
        act, room = ctx.get("act"), ctx.get("room_type")
        in_combat = before.get("in_combat", False)
        if in_combat:
            key = (act, ctx.get("floor"), room)
            if self.fight != key:
                self.fight = key
                self.formation = "+".join(
                    e["id"].removeprefix("MONSTER.") for e in view.get("enemies", ()) if e["hp"] > 0
                )
            group = "act2_boss" if act == 2 and room == "Boss" else "act3" if act == 3 else None
            eligible = (before["decision"] != "combat_play" or any(c["can_play"] for c in view["hand"])
                        or any(p["can_use"] for p in view["player"].get("potions", ())))
            if group and eligible and fallback is not None:
                self.coverage[group][fallback or "covered"] += 1
                encounter = (ctx.get("boss") or {}).get("id") if room == "Boss" else self.formation
                self.coverage[f"{group}/{encounter}"][fallback or "covered"] += 1
        else:
            self.fight = None
        if after.get("decision") == "game_over" and after.get("victory") is False:
            self.death = {"act": act, "room": room, "formation": self.formation if in_combat else None,
                          "boss": (ctx.get("boss") or {}).get("id") if room == "Boss" else None}
