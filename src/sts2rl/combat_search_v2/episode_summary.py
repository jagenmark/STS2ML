"""Small terminal and coverage counters for release verification."""
from collections import Counter, defaultdict


class EpisodeSummary:
    def __init__(self):
        self.coverage = defaultdict(Counter)
        self.death = None
        self.fight = None
        self.formation = None

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
