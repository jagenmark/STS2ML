"""Freeze Batch 1 & Batch 2 ablation challenger bundles without altering historical releases.

Supports independent ablations:
- survival: emergency lethal-survival lookahead + survival-priority beam semantics
- scorer: Silent combat scorer fixes + mechanics/persistent/potions from Act 1
- shop: marginal removal pricing, concave retained-gold value, potion capacity, optional selections
- all: combines Batch 1 (survival + scorer + shop)
- route: exact probability-Bellman deck/potion-aware routing on primary + late routers
- draft: unified monotone take-vs-skip card drafting (zero legacy human offsets)
- batch2: combines Batch 2 (route + draft)
- all_v2: combines Batch 1 + Batch 2
- all_v2_clean: live-verified Batch 1 + Batch 2 without marginal_removal, plus THE_KIN_BOSS=isolate
- all_v2_tactics: all_v2_clean plus REP512-validated Act 2 Boss, Soul Fysh, and Act 2 Hallway tactics
- all_v2_mech: all_v2_tactics plus 896-seed-validated act2_mechanics (guaranteed_damage cutoff, Illusion+Minion, Curl Up, Kaiser Crab Surrounded/Crab Rage survival)
- all_v2_mech_v3: all_v2_mech plus 896-seed-validated enemy_mechanics (Plow, Vital Spark, Slippery, Adaptable, Slow) and card_potion_mechanics (Boss/Elite force-multiplier potions, Shadowmeld, Knife Trap, Strangle, missing Silent cards, combat discard)
- all_v2_p1_v4: all_v2_mech_v3 plus 896-seed-validated deck_size_penalty=0.0, selection_fixes_v4, combat_fixes_v4, event_fixes_v4, and shop_fixes_v4
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from sts2rl.act1 import save_json
from sts2rl.run_bundle import freeze_bundle, load_bundle

SEARCH_PROFILES = ("all_v2_search_v5", "all_v2_search_heur_v5", "all_v2_search_v6")
MODEL_SHA256 = "24debeaaa81c0095cf252807e05e858cf53b8dcbf23ed2e9eb274f267112cb0b"

PROFILES = (
    "survival",
    "scorer",
    "shop",
    "all",
    "route",
    "draft",
    "batch2",
    "all_v2",
    "all_v2_clean",
    "all_v2_tactics",
    "all_v2_mech",
    "all_v2_mech_v3",
    "all_v2_p1_v4",
    *SEARCH_PROFILES,
    "v64_control", "unified_size_165", "unified_size_0", "trap_cleanup_v65", "unified_draft_v65",
)


_ENCOUNTER_KEYS = (
    "survival_search",
    "survival_beam",
    "scorer_fixes",
    "act2_mechanics",
    "enemy_mechanics",
    "card_potion_mechanics",
    "selection_fixes_v4",
    "combat_fixes_v4",
    "potion_effects_from_act",
    "draw_potions_from_act",
)
_MERCHANT_KEYS = ("marginal_removal", "gold_curve", "potion_capacity", "shop_fixes_v4")


def build_batch1_bundle(base: Path, output: Path, *, profile: str = "all") -> Path:
    if profile not in PROFILES:
        raise ValueError(f"Unknown Batch 1/2 profile: {profile!r}")
    role, opts = load_bundle(base)
    v64 = profile if profile in ("v64_control", "unified_size_165", "unified_size_0") else None
    v65 = profile if profile in ("trap_cleanup_v65", "unified_draft_v65") else None
    if v64 or v65:
        profile = "all_v2_search_v6"
    arm4 = profile == "all_v2_search_v6"
    if profile in SEARCH_PROFILES:
        if any(opts.get(k) for k in ("combat_search_v2", "combat_search_v2_shadow", "combat_search_v2_config", "combat_value_v2")):
            raise ValueError("Start from a search-free base for the search profiles")
        models = Path(__file__).resolve().parents[1] / "docs/combat-search-v2/models"
        opts.update(combat_search_v2=True, combat_search_v2_config=models / "v5-search.json")
        if arm4:
            opts["combat_search_v2_config"] = models / "v6-search.json"
        if profile == "all_v2_search_v5":
            checkpoint = models / "combat_value_v3.npz"
            if hashlib.sha256(checkpoint.read_bytes()).hexdigest() != MODEL_SHA256:
                raise ValueError("Frozen Schema 3 checkpoint checksum mismatch")
            opts["combat_value_v2"] = checkpoint
        profile = "all_v2_p1_v4"
    encounter = json.loads(opts["encounter_model"].read_bytes())
    deck = json.loads(opts["deck_model"].read_bytes())
    room = json.loads(opts["room_model"].read_bytes()) if "room_model" in opts else None
    late_room = (
        json.loads(opts["late_room_model"].read_bytes()) if "late_room_model" in opts else None
    )
    strategy = (
        json.loads(opts["strategy_model"].read_bytes()) if "strategy_model" in opts else None
    )

    dirty = (
        any(encounter.get(k) for k in _ENCOUNTER_KEYS)
        or encounter.get("mechanics_from_act", 4) != 4
        or encounter.get("persistent_from_act", 4) != 4
        or bool((encounter.get("mecha_knight") or {}).get("v2_burn"))
        or bool(deck.get("optional_selections"))
        or any((deck.get("merchant") or {}).get(k) for k in _MERCHANT_KEYS)
        or bool((room or {}).get("survival_weighted"))
        or bool((late_room or {}).get("survival_weighted"))
        or bool((strategy or {}).get("unified_draft"))
        or bool((strategy or {}).get("event_fixes_v4"))
        or (strategy is not None and float(strategy.get("offset_scale", 1.0)) != 1.0)
        or (strategy is not None and "deck_size_penalty" in strategy and float(strategy["deck_size_penalty"]) != 0.12)
    )
    if dirty:
        raise ValueError("Base bundle already has Batch 1/2 settings; start from a clean baseline")

    full_v2 = (
        "all_v2",
        "all_v2_clean",
        "all_v2_tactics",
        "all_v2_mech",
        "all_v2_mech_v3",
        "all_v2_p1_v4",
    )
    if profile in ("route", "batch2", *full_v2):
        routers = [(name, payload) for name, payload in (("room_model", room), ("late_room_model", late_room)) if payload is not None]
        if not routers:
            raise ValueError(f"Profile {profile!r} requires at least one v2 room model in the base bundle")
        for name, payload in routers:
            if payload.get("version") != 2:
                raise ValueError(f"Profile {profile!r} requires a v2 {name} (got version={payload.get('version')!r})")
    if profile in ("draft", "batch2", *full_v2) and strategy is None:
        raise ValueError(f"Profile {profile!r} requires a strategy_model in the base bundle")

    if profile in ("survival", "all", *full_v2):
        encounter["survival_search"] = True
        encounter["survival_beam"] = True
    if profile in ("scorer", "all", *full_v2):
        encounter["scorer_fixes"] = True
        encounter["mechanics_from_act"] = 1
        encounter["persistent_from_act"] = 1
        encounter["potion_effects_from_act"] = 1
        encounter["draw_potions_from_act"] = 1
        if isinstance(encounter.get("mecha_knight"), dict):
            encounter["mecha_knight"] = {**encounter["mecha_knight"], "v2_burn": True}
    if profile in ("all_v2_clean", "all_v2_tactics", "all_v2_mech", "all_v2_mech_v3", "all_v2_p1_v4"):
        encounter["overrides"] = {**(encounter.get("overrides") or {}), "THE_KIN_BOSS": "isolate"}
    if profile in ("all_v2_tactics", "all_v2_mech", "all_v2_mech_v3", "all_v2_p1_v4"):
        encounter["overrides"] = {**encounter["overrides"], "SOUL_FYSH_BOSS": "isolate"}
        boss_plans = dict(encounter.get("act2_boss_plans") or {})
        boss_plans["THE_INSATIABLE_BOSS"] = {"style": "tempo", "escape": "cheap"}
        boss_plans["KNOWLEDGE_DEMON_BOSS"] = {
            **(boss_plans.get("KNOWLEDGE_DEMON_BOSS") or {}),
            "style": "engine",
            "style_weights": {"potion": 0.30, "guard": 1.65},
        }
        boss_plans["KAISER_CRAB_BOSS"] = {
            **(boss_plans.get("KAISER_CRAB_BOSS") or {}),
            "focus": "MONSTER.CRUSHER",
            "focus_bonus": 5,
        }
        encounter["act2_boss_plans"] = boss_plans
        encounter["act2_hallways"] = {
            "plans": {
                "hunter_tender_beam": {"style": "engine", "tender": True, "search": "beam"},
                "entomancer_tempo": {"style": "tempo"},
                "prism_isolate": {"style": "isolate"},
                "myte_pot_aggr": {"style": "engine", "style_weights": {"potion": 0.30, "guard": 1.65}},
            },
            "by_formation": {
                "HUNTER_KILLER": "hunter_tender_beam",
                "ENTOMANCER": "entomancer_tempo",
                "INFESTED_PRISM": "prism_isolate",
                "MYTE+MYTE": "myte_pot_aggr",
            },
        }
    if profile in ("all_v2_mech", "all_v2_mech_v3", "all_v2_p1_v4"):
        encounter["act2_mechanics"] = True
    if profile in ("all_v2_mech_v3", "all_v2_p1_v4"):
        encounter["enemy_mechanics"] = True
        encounter["card_potion_mechanics"] = True
    if profile == "all_v2_p1_v4":
        encounter["selection_fixes_v4"] = True
        encounter["combat_fixes_v4"] = True
    if profile in ("shop", "all", *full_v2):
        deck["optional_selections"] = True
        merchant = dict(deck.get("merchant") or {"reserve": 1.0, "permanent": 1.1})
        merchant.update(
            marginal_removal=(
                profile
                not in (
                    "all_v2_clean",
                    "all_v2_tactics",
                    "all_v2_mech",
                    "all_v2_mech_v3",
                    "all_v2_p1_v4",
                )
            ),
            gold_curve=True,
            potion_capacity=True,
        )
        if profile == "all_v2_p1_v4":
            merchant["shop_fixes_v4"] = True
        deck["merchant"] = merchant
    if profile in ("route", "batch2", *full_v2):
        if room is not None:
            room["survival_weighted"] = True
        if late_room is not None:
            late_room["survival_weighted"] = True
    if profile in ("draft", "batch2", *full_v2) and strategy is not None:
        strategy["unified_draft"] = True
        strategy["deck_size_penalty"] = 0.0 if profile == "all_v2_p1_v4" else 0.12
        strategy["offset_scale"] = 0.0
        if profile == "all_v2_p1_v4":
            strategy["event_fixes_v4"] = True
        if arm4:
            strategy["power_draft"] = "accelerant_only"

    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    if v64 or v65:
        config = json.loads(opts["combat_search_v2_config"].read_bytes())
        save_json(output / "search_config.json", {**config, "kaiser_v63": True, "wax_fan_v64": True})
        opts["combat_search_v2_config"] = output / "search_config.json"
        if v65 == "trap_cleanup_v65":
            deck[v65] = strategy[v65] = True
        elif v65 == "unified_draft_v65":
            deck.update(unified_draft_v65=True, size_penalty=0.0)
        elif v64 != "v64_control":
            deck.update(unified_draft_v64=True, size_penalty=-1.65 if v64 == "unified_size_165" else 0.0)
    if profile in ("survival", "scorer", "all", *full_v2):
        save_json(output / "encounter_model.json", encounter)
        opts["encounter_model"] = output / "encounter_model.json"
    if profile in ("shop", "all", *full_v2):
        save_json(output / "deck_model.json", deck)
        opts["deck_model"] = output / "deck_model.json"
    if profile in ("route", "batch2", *full_v2):
        if room is not None:
            save_json(output / "room_model.json", room)
            opts["room_model"] = output / "room_model.json"
        if late_room is not None:
            save_json(output / "late_room_model.json", late_room)
            opts["late_room_model"] = output / "late_room_model.json"
    if profile in ("draft", "batch2", *full_v2) and strategy is not None:
        save_json(output / "strategy_model.json", strategy)
        opts["strategy_model"] = output / "strategy_model.json"
    return freeze_bundle({"args": {**opts, "roles": [role]}}, output / "policy")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        type=Path,
        default=Path("releases/silent-a10-mecha-knight/challenger/policy.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", choices=PROFILES, default="all")
    args = parser.parse_args()
    path = build_batch1_bundle(args.base, args.output, profile=args.profile)
    print(path)


if __name__ == "__main__":
    main()
