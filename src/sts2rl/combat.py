"""Public combat state -> neural inputs, separate from replay/macro schema v1.

This is the state encoder for a future micro policy, not a trained combat agent.
It reads an explicit allowlist; seeds, engine internals and future moves cannot
enter its vocabulary or tensors. Descriptive text is retained by the native
protocol but is not language-understood by this encoder. Structured variables,
counter rules, card identities, modifiers and visible intents are inputs.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import torch
from torch import nn

from .encoding import PAD, UNK, Vocabulary

PILES = ("hand", "draw_pile", "discard_pile", "exhaust_pile", "play_pile")
CARD_FIELDS = (
    "cost", "costs_x", "star_cost", "stars_x", "type", "rarity", "target_type",
    "upgrades", "max_upgrades", "exhaust_on_next_play", "retain_this_turn", "sly_this_turn",
)
MAX_ENTITIES, MAX_ATTRIBUTES = 1024, 256


@dataclass
class Entity:
    zone: str
    identity: str
    attributes: dict[str, Any]


def _scalars(target: dict, prefix: str, source: dict | None) -> None:
    for name, value in (source or {}).items():
        if not isinstance(value, (str, int, float, bool, type(None))):
            raise ValueError(f"Non-scalar public attribute: {prefix}.{name}")
        target[f"{prefix}.{name}"] = value


def combat_entities(state: dict) -> list[Entity]:
    """Project only inspected public fields; reject incomplete old exports.

    Pile membership is explicit, with one entity per card including duplicates.
    Hand/enemy indices bind selectable targets; unordered piles have no indices.
    Unknown rule/counter values stay null, distinct from known zero.
    """
    if state.get("decision") == "card_select":
        entities = combat_entities(state["combat_state"])
        entities.append(Entity("selection", state.get("prompt") or "unknown", {
            "min_select": state["min_select"], "max_select": state["max_select"],
        }))
        for card in state["cards"]:
            attrs = {k: card.get(k) for k in (*CARD_FIELDS, "index", "upgraded")}
            _scalars(attrs, "stats", card.get("stats"))
            entities.append(Entity("selection_card", card["id"], attrs))
        if len(entities) > MAX_ENTITIES:
            raise ValueError("Selection exceeds explicit entity limit")
        return entities
    if state.get("decision") != "combat_play" or state.get("observation_version") != 2:
        raise ValueError("Requires a v2 native combat_play observation")
    player = state["player"]
    context = {k: state.get(k) for k in ("round", "energy", "max_energy", "stars", "orb_slots")}
    context.update({k: player.get(k) for k in ("hp", "max_hp", "block", "gold")})
    context.update({k: state.get("context", {}).get(k) for k in ("act", "floor", "room_type")})
    entities = [Entity("context", "player", context)]
    for zone in (*PILES, "deck"):
        cards = player.get("deck") if zone == "deck" else state.get(zone)
        if not isinstance(cards, list):
            raise ValueError(f"Missing public pile: {zone}")
        for card in cards:
            attrs = {k: card.get(k) for k in CARD_FIELDS}
            if zone == "hand":
                attrs.update(index=card["index"], can_play=card["can_play"])
            _scalars(attrs, "stats", card.get("stats"))
            for keyword in card.get("keywords") or []:
                attrs[f"keyword.{keyword}"] = True
            for modifier in ("enchantment_state", "affliction_state"):
                item = card.get(modifier) or {}
                for key in ("id", "amount", "show_counter", "counter", "status"):
                    attrs[f"{modifier}.{key}"] = item.get(key)
                _scalars(attrs, modifier + ".vars", item.get("vars"))
            for target in card.get("damage_by_target") or []:
                for key in ("damage", "repeat", "total_damage"):
                    attrs[f"target.{target['target_index']}.{key}"] = target.get(key)
            entities.append(Entity(zone, card["id"], attrs))
    for relic in player["relics"]:
        required = ("counter", "show_counter", "status", "is_used_up", "stack_count", "counter_rule")
        if any(key not in relic for key in required):
            raise ValueError("Incomplete relic state; rebuild the native exporter")
        attrs = {key: relic[key] for key in required if key != "counter_rule"}
        rule = relic["counter_rule"] or {}
        attrs["rule_known"] = relic["counter_rule"] is not None
        for key in ("unit", "threshold", "remaining", "effect", "effect_amount"):
            attrs[f"rule.{key}"] = rule.get(key)
        _scalars(attrs, "vars", relic.get("vars"))
        entities.append(Entity("relic", relic["id"], attrs))
    for enemy in state["enemies"]:
        attrs = {k: enemy.get(k) for k in ("index", "hp", "max_hp", "block", "intends_attack")}
        for i, intent in enumerate(enemy.get("intents") or []):
            for k in ("type", "damage", "hits", "total_damage"):
                attrs[f"intent.{i}.{k}"] = intent.get(k)
        for power in enemy.get("powers") or []:
            attrs[f"power.{power['id']}"] = power["amount"]
        entities.append(Entity("enemy", enemy["id"], attrs))
    for power in state.get("player_powers") or []:
        entities.append(Entity("player_power", power["id"], {"amount": power["amount"]}))
    for potion in player.get("potions") or []:
        attrs = {k: potion.get(k) for k in ("index", "target_type")}
        _scalars(attrs, "vars", potion.get("vars"))
        entities.append(Entity("potion", potion["id"], attrs))
    # Character-specific public state; no private AI/RNG or saved-property blobs.
    for orb in state.get("orbs") or []:
        entities.append(Entity("orb", orb["type"], {k: orb.get(k) for k in ("index", "passive", "evoke")}))
    if state.get("osty"):
        entities.append(Entity("ally", "osty", {k: state["osty"].get(k) for k in ("hp", "max_hp", "block")}))
    if len(entities) > MAX_ENTITIES or any(len(e.attributes) > MAX_ATTRIBUTES for e in entities):
        raise ValueError("Combat state exceeds explicit limits; no silent truncation")
    return entities


def combat_vocabulary(training_observations: list[dict]) -> Vocabulary:
    """Fit on training seeds only; held-out symbols map to UNK."""
    tokens = set()
    for state in training_observations:
        for entity in combat_entities(state):
            tokens.update((f"zone:{entity.zone}", f"entity:{entity.identity}"))
            for key, value in entity.attributes.items():
                tokens.add(f"field:{key}")
                if isinstance(value, str):
                    tokens.add(f"symbol:{value}")
    return Vocabulary((PAD, UNK, *sorted(tokens)))


def collate_combat(states: list[dict], vocab: Vocabulary, device: str = "cpu") -> dict[str, torch.Tensor]:
    if not states:
        raise ValueError("Empty combat batch")
    rows = [combat_entities(state) for state in states]
    shape = (len(rows), max(map(len, rows)))
    attr_shape = (*shape, max(len(e.attributes) for row in rows for e in row))
    batch = {
        "entities": torch.zeros(shape, dtype=torch.long),
        "zones": torch.zeros(shape, dtype=torch.long),
        "entity_mask": torch.zeros(shape, dtype=torch.bool),
        "fields": torch.zeros(attr_shape, dtype=torch.long),
        "symbols": torch.zeros(attr_shape, dtype=torch.long),
        "numbers": torch.zeros((*attr_shape, 2)),
        "attribute_mask": torch.zeros(attr_shape, dtype=torch.bool),
    }
    for b, row in enumerate(rows):
        for e, entity in enumerate(row):
            batch["entities"][b, e] = vocab.encode(f"entity:{entity.identity}")
            batch["zones"][b, e] = vocab.encode(f"zone:{entity.zone}")
            batch["entity_mask"][b, e] = True
            for a, (key, value) in enumerate(sorted(entity.attributes.items())):
                batch["fields"][b, e, a] = vocab.encode(f"field:{key}")
                batch["attribute_mask"][b, e, a] = True
                if isinstance(value, str):
                    batch["symbols"][b, e, a] = vocab.encode(f"symbol:{value}")
                elif value is not None:
                    if not isinstance(value, (int, float, bool)) or not math.isfinite(value):
                        raise ValueError(f"Non-finite/nonnumeric attribute: {key}")
                    # Signed log scale preserves counter distinctions and avoids
                    # large gold/damage values overwhelming the embeddings.
                    batch["numbers"][b, e, a] = torch.tensor([
                        math.copysign(math.log1p(abs(value)), value), 1.0,
                    ])
    return {k: v.to(device) for k, v in batch.items()}


class CombatStateEncoder(nn.Module):
    """Set-attention state module, ready to attach to micro action/value heads.

    Attributes are encoded jointly with their field name: nine attacks and nine
    gold are distinct features. Piles retain multiplicity without positions.
    Existing macro checkpoints are deliberately not loaded into this module.
    """
    def __init__(self, vocab_size: int, width: int = 64):
        super().__init__()
        if width < 4 or width % 4:
            raise ValueError("width must be a positive multiple of four")
        self.embedding = nn.Embedding(vocab_size, width, padding_idx=0)
        self.number = nn.Linear(2, width, bias=False)
        self.attribute = nn.Sequential(nn.Linear(width, width), nn.GELU(), nn.Linear(width, width))
        self.cls = nn.Parameter(torch.zeros(1, 1, width))
        self.encoder = nn.TransformerEncoder(nn.TransformerEncoderLayer(
            width, 4, width * 4, dropout=0, batch_first=True, norm_first=True,
        ), 2, norm=nn.LayerNorm(width), enable_nested_tensor=False)

    def forward(self, batch: dict[str, torch.Tensor]) -> tuple[torch.Tensor, torch.Tensor]:
        attrs = self.attribute(self.embedding(batch["fields"])
                               + self.embedding(batch["symbols"]) + self.number(batch["numbers"]))
        mask = batch["attribute_mask"].unsqueeze(-1)
        attrs = (attrs * mask).sum(2) / mask.sum(2).clamp_min(1).sqrt()
        entities = self.embedding(batch["entities"]) + self.embedding(batch["zones"]) + attrs
        tokens = torch.cat((self.cls.expand(entities.shape[0], -1, -1), entities), dim=1)
        padding = torch.cat((torch.zeros_like(batch["entity_mask"][:, :1]), ~batch["entity_mask"]), dim=1)
        encoded = self.encoder(tokens, src_key_padding_mask=padding)
        return encoded[:, 0], encoded[:, 1:]
