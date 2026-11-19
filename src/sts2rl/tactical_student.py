"""A compact per-effect neural student of the visible-hand turn planner."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .native import legal_actions
from .run_policy import IDENTITY, RunPolicy, RunWeights, _card_id, _cost, _damage, _draw_count, _power, _shiv_count
from .teacher import equivalent_groups, heuristic_score, incoming


def action_examples(state, policy):
    if state.get("runtime_identity") != IDENTITY or state["decision"] != "combat_play":
        raise ValueError("Tactical student requires a public Silent A10 combat hand")
    actions = legal_actions(state)
    scores = policy.combat_scores(state, actions)
    by_id = {a.id: s for a, s in zip(actions, scores, strict=True)}
    groups = equivalent_groups(state, actions)
    reps = [g[0] for g in groups]
    enemies = [e for e in state["enemies"] if e["hp"] > 0]
    hand = {c["index"]: c for c in state["hand"]}
    potions = {p["index"]: p for p in state["player"]["potions"]}
    pl = state["player"]
    hp = pl["hp"] / pl["max_hp"]
    inc = sum(incoming(e) for e in enemies)
    need = max(0, inc - pl["block"])
    playable = [c for c in hand.values() if c.get("can_play")]
    available_block = sum((c.get("stats") or {}).get("block", 0) for c in playable)
    remaining_damage = {e["index"]: sum(_damage(c, e) for c in playable if c["type"] == "Attack") for e in enemies}
    energy = state["energy"]
    max_score = max(scores)
    base_scores = [heuristic_score(state, a) for a in reps]
    max_base = max(base_scores)
    context = [hp, pl["hp"] / 50, pl["block"] / 15, min(2., need / max(1, pl["hp"])),
               inc / 20, need / 20, energy / 3, len(hand) / 6, len(playable) / 5,
               len(enemies) / 3, available_block / 15, state["round"] / 8,
               sum(e["hp"] for e in enemies) / 100, len(potions) / 2,
               state["context"]["act"] / 3, state["context"]["floor"] / 17,
               float(state["context"]["room_type"] == "Boss"), float(state["context"]["room_type"] == "Elite")]
    examples = []
    for a, old_score in zip(reps, base_scores, strict=True):
        is_card = a.kind == "play_card"
        potion = a.kind == "use_potion"
        item = hand[a.args["card_index"]] if is_card else potions[a.args["potion_index"]] if potion else {}
        stats = ({k.lower(): v for k, v in (item.get("vars") or {}).items()} if potion else item.get("stats") or {})
        target = next((e for e in enemies if a.args.get("target_index") == e["index"]), None)
        affected = [target] if target else enemies
        damages = [stats.get("damage", 0) if potion else _damage(item, e) if item.get("type") == "Attack" else 0
                   for e in affected]
        damage = sum(min(d, e["hp"] + e.get("block", 0)) for e, d in zip(affected, damages, strict=True))
        threat_removed = sum(incoming(e) for e, d in zip(affected, damages, strict=True) if d >= e["hp"] + e.get("block", 0))
        health = target["hp"] + target.get("block", 0) if target else 0
        block = stats.get("calculatedblock", stats.get("block", 0))
        score = by_id[a.id]
        numeric = context + [float(is_card), float(potion), float(a.kind == "end_turn"),
              float(item.get("type") == "Attack"), float(item.get("type") == "Power"),
              _cost(item) / 3 if is_card else 0, damage / 15, threat_removed / 15, block / 10,
              min(need, block) / 10, stats.get("poisonpower", 0) / 6, stats.get("weakpower", 0) / 2,
              _draw_count(item) / 3, _shiv_count(item) / 3, stats.get("energy", 0),
              health / 40, health / max(1, target["max_hp"]) if target else 0,
              incoming(target) / 15 if target else 0,
              _power(target.get("powers"), "POISON") / 8 if target else 0,
              (remaining_damage[target["index"]] - health) / 20 if target else 0,
              score / 15, (score - max_score) / 10, old_score / 15, (old_score - max_base) / 10]
        examples.append({"token": _card_id(item) if item else a.kind,
                         "x": [round(max(-8., min(8., float(v))), 5) for v in numeric]})
    return groups, examples


def make_network(width, inputs, symbols):
    from torch import nn
    import torch

    class Ranker(nn.Module):
        def __init__(self):
            super().__init__()
            self.token = nn.Embedding(symbols, 12, padding_idx=0)
            self.action = nn.Sequential(nn.Linear(inputs + 12, width), nn.LayerNorm(width), nn.GELU(),
                                        nn.Linear(width, width), nn.GELU())
            self.score = nn.Sequential(nn.Linear(2 * width, width), nn.GELU(), nn.Linear(width, 1))

        def forward(self, x, tokens, mask):
            encoded = self.action(torch.cat((x, self.token(tokens)), dim=-1))
            context = encoded.masked_fill(~mask.unsqueeze(-1), -1e4).amax(dim=1, keepdim=True)
            logits = self.score(torch.cat((encoded, context.expand_as(encoded)), dim=-1)).squeeze(-1)
            return logits.masked_fill(~mask, -1e4)
    return Ranker()


def pack(rows, vocab):
    import torch
    max_actions = max(len(r["choices"]) for r in rows)
    x = np.zeros((len(rows), max_actions, len(rows[0]["choices"][0]["x"])), dtype=np.float32)
    token = np.zeros((len(rows), max_actions), dtype=np.int64)
    mask = np.zeros((len(rows), max_actions), dtype=bool)
    for i, row in enumerate(rows):
        choices = row["choices"]
        n = len(choices)
        x[i, :n] = [c["x"] for c in choices]
        token[i, :n] = [vocab.get(c["token"], 0) for c in choices]
        mask[i, :n] = True
    return torch.from_numpy(x), torch.from_numpy(token), torch.from_numpy(mask)


class TacticalStudent:
    def __init__(self, checkpoint):
        import torch
        data = torch.load(checkpoint, map_location="cpu", weights_only=True)
        if data["version"] != 1 or data["runtime_identity"] != IDENTITY:
            raise ValueError("Incompatible tactical student")
        self.vocab = data["vocab"]
        self.feature_policy = RunPolicy(RunWeights(**data["feature_weights"]))
        self.model = make_network(data["width"], data["inputs"], 1 + len(self.vocab))
        self.model.load_state_dict(data["state_dict"])
        self.model.eval()

    def __call__(self, state):
        import torch
        groups, features = action_examples(state, self.feature_policy)
        with torch.inference_mode():
            logits = self.model(*pack([{"choices": features}], self.vocab))
        return groups[int(logits[0].argmax())][0]


def read_training_runs(folders):
    import gzip
    runs, seen = [], set()
    for folder in folders:
        config = json.loads((Path(folder).parent / "config.json").read_text())
        for p in sorted(Path(folder).glob("run-*/actions.jsonl.gz")):
            result = json.loads((p.parent / "result.json").read_text())
            if result["status"] != "complete":
                continue
            seed = result["seed"]
            if seed in seen:
                raise ValueError("Training inputs contain a repeated game seed")
            seen.add(seed)
            with gzip.open(p, "rt", encoding="utf-8") as stream:
                records = [json.loads(line) for line in stream]
            if records:
                runs.append((seed, records, config["weights"]["weights"]))
    return runs
