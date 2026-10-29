"""Compact set-attention macro policy and outcome value model.

No positional encoding is used: changing deck/relic enumeration order leaves the
state prediction invariant, and permuting legal candidates permutes their scores.
This model learns observational imitation/outcomes; it does not estimate causal
card value or establish playing strength without native held-out evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import nn
from torch.nn import functional as F

from .encoding import ACTION_FEATURE_DIM, NUMERIC_DIM, STATE_FEATURE_DIM


@dataclass(frozen=True)
class ModelConfig:
    vocab_size: int
    d_model: int = 128
    n_heads: int = 4
    n_layers: int = 3
    ff_multiplier: int = 4
    dropout: float = 0.0

    def __post_init__(self) -> None:
        if self.vocab_size < 2:
            raise ValueError("vocab_size must include PAD and UNK")
        if self.d_model < 4 or self.n_heads < 1 or self.d_model % self.n_heads:
            raise ValueError("d_model must be >=4 and divisible by n_heads")
        if self.n_layers < 1 or self.ff_multiplier < 1:
            raise ValueError("n_layers and ff_multiplier must be positive")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("dropout must be in [0, 1)")


class MacroPolicyValue(nn.Module):
    def __init__(self, config: ModelConfig) -> None:
        super().__init__()
        self.config = config
        width = config.d_model
        self.embedding = nn.Embedding(config.vocab_size, width, padding_idx=0)
        self.entity_type_embedding = nn.Embedding(4, width, padding_idx=0)
        self.state_features = nn.Linear(STATE_FEATURE_DIM, width, bias=False)
        self.action_features = nn.Linear(ACTION_FEATURE_DIM, width, bias=False)
        self.numeric = nn.Sequential(nn.Linear(NUMERIC_DIM, width), nn.GELU(), nn.Linear(width, width))
        self.cls = nn.Parameter(torch.empty(1, 1, width))
        nn.init.normal_(self.cls, std=0.02)
        self.encoder = nn.TransformerEncoder(
            nn.TransformerEncoderLayer(
                d_model=width,
                nhead=config.n_heads,
                dim_feedforward=width * config.ff_multiplier,
                dropout=config.dropout,
                activation="gelu",
                batch_first=True,
                norm_first=True,
            ),
            num_layers=config.n_layers,
            norm=nn.LayerNorm(width),
            enable_nested_tensor=False,
        )
        self.action_attention = nn.MultiheadAttention(
            width, config.n_heads, dropout=config.dropout, batch_first=True
        )
        self.policy_head = nn.Sequential(
            nn.Linear(width * 4, width), nn.GELU(), nn.Linear(width, 1)
        )
        self.value_head = nn.Sequential(nn.Linear(width, width), nn.GELU(), nn.Linear(width, 1))

    @property
    def parameter_count(self) -> int:
        return sum(parameter.numel() for parameter in self.parameters() if parameter.requires_grad)

    def count_parameters(self) -> int:
        return self.parameter_count

    def forward(self, batch: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
        if not bool(batch["action_mask"].any(dim=1).all()):
            raise ValueError("Every decision must have at least one legal candidate")
        entity_states = (
            self.embedding(batch["state_tokens"])
            + self.entity_type_embedding(batch["state_types"])
            + self.state_features(batch["state_features"])
        )
        context = self.embedding(batch["context_tokens"]).sum(dim=1) + self.numeric(batch["numeric"])
        cls = self.cls.expand(entity_states.shape[0], -1, -1) + context.unsqueeze(1)
        tokens = torch.cat((cls, entity_states), dim=1)
        padding = torch.cat(
            (
                torch.zeros((tokens.shape[0], 1), dtype=torch.bool, device=tokens.device),
                ~batch["state_mask"],
            ),
            dim=1,
        )
        encoded = self.encoder(tokens, src_key_padding_mask=padding)
        state = encoded[:, 0]
        actions = (
            self.embedding(batch["action_tokens"])
            + self.embedding(batch["action_kinds"])
            + self.action_features(batch["action_features"])
        )
        attended, _ = self.action_attention(
            actions, encoded, encoded, key_padding_mask=padding, need_weights=False
        )
        global_states = state.unsqueeze(1).expand(-1, actions.shape[1], -1)
        policy_logits = self.policy_head(
            torch.cat((global_states, actions, attended, actions * attended), dim=-1)
        ).squeeze(-1)
        policy_logits = policy_logits.masked_fill(~batch["action_mask"], -torch.inf)
        return {"policy_logits": policy_logits, "value_logits": self.value_head(state).squeeze(-1)}


def policy_value_loss(
    outputs: dict[str, torch.Tensor],
    batch: dict[str, torch.Tensor],
    value_weight: float = 0.5,
) -> dict[str, torch.Tensor]:
    """Masked imitation CE plus terminal-outcome BCE, with independent labels.

    An unfinished replay can supervise the policy while contributing no value
    loss. A record with neither label contributes differentiable zero loss.
    """
    if value_weight < 0:
        raise ValueError("value_weight must be nonnegative")
    zero = outputs["value_logits"].sum() * 0.0
    policy_mask, value_mask = batch["policy_mask"], batch["value_mask"]
    policy_loss = zero
    if bool(policy_mask.any()):
        selected_targets = batch["policy_targets"][policy_mask]
        selected_legal = batch["action_mask"][policy_mask]
        if bool((selected_targets < 0).any()) or bool((selected_targets >= selected_legal.shape[1]).any()):
            raise ValueError("Policy targets must reference candidate indices")
        if not bool(selected_legal.gather(1, selected_targets.unsqueeze(1)).all()):
            raise ValueError("Policy target refers to a masked candidate")
        policy_loss = F.cross_entropy(outputs["policy_logits"][policy_mask], selected_targets)
    value_loss = zero
    if bool(value_mask.any()):
        value_loss = F.binary_cross_entropy_with_logits(
            outputs["value_logits"][value_mask], batch["value_targets"][value_mask]
        )
    return {
        "loss": policy_loss + value_weight * value_loss,
        "policy_loss": policy_loss,
        "value_loss": value_loss,
    }
