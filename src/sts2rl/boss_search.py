"""Choose an Act 1 boss policy using independently resampled native fight continuations."""

import hashlib
import json
from pathlib import Path
from random import Random

from .encounter import EncounterPolicy, STYLES, combat_features
from .fight_rollout import fight
from .native import ACT1_SAMPLER, NativeError, NativeSession, canonical_json
from .run_policy import IDENTITY


class BossSearch:
    def __init__(self, path, root, host, folder):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("version") != 1 or data.get("runtime_identity") != IDENTITY:
            raise ValueError("Incompatible boss search configuration")
        self.styles = data["styles"]
        self.worlds = data["worlds"]
        if not (
            1 <= self.worlds <= 12
            and 2 <= len(self.styles) <= 8
            and len(set(self.styles)) == len(self.styles)
            and all(s in STYLES for s in self.styles)
        ):
            raise ValueError("Invalid boss search portfolio or sample budget")
        self.root, self.host, self.folder = Path(root), host, Path(folder)
        self.actor = self.worker = None
        self.started = False
        self.metrics = {"roots": 0, "simulations": 0, "style": None, "errors": []}

    def close(self):
        if self.worker is not None:
            self.worker.close()

    def choose(self, game, original, policy):
        state = game.state
        ctx = state["context"]
        if ctx["act"] != 1 or ctx["room_type"] != "Boss" or not state.get("in_combat"):
            return original
        if self.actor is not None:
            return self.actor(state)
        if self.started or state["decision"] != "combat_play":
            return original
        self.started = True
        if state["round"] != 1 or not state.get("act1_search_support", {}).get("supported"):
            return original
        # No seed, replay command, game RNG or future draw order enters this random key.
        public = [
            combat_features(state),
            [(c["id"], c.get("upgrades", 0)) for c in state["hand"]],
            [(p["id"], p["index"]) for p in state["player"]["potions"]],
        ]
        master = Random(
            int.from_bytes(
                hashlib.sha256(b"silent-boss-worlds-v1" + canonical_json(public)).digest()[:8],
                "big",
            )
        )
        worlds = [master.getrandbits(62) for _ in range(self.worlds)]
        self.metrics["roots"] += 1
        fork = game.fork()
        totals = {s: 0.0 for s in self.styles}
        try:
            self.worker = NativeSession(
                self.root,
                self.folder,
                ascension=10,
                host_path=self.host,
                timeout=18,
                act_list=game.act_list,
            )
            for world in worlds:
                for style in self.styles:
                    self.worker.restore(fork)
                    root = self.worker.sample(world, profile=ACT1_SAMPLER)
                    actor = EncounterPolicy(policy.weights, style=style)
                    end = fight(self.worker, root, actor)
                    self.metrics["simulations"] += 1
                    totals[style] += (
                        32 * end["won"]
                        + 0.20 * end["hp"]
                        + 5 * (1 - end["remaining"])
                        + 0.35 * end["potions"]
                    )
            best = max(self.styles, key=totals.__getitem__)
            self.metrics["style"] = best
            self.metrics["mean_values"] = {k: v / self.worlds for k, v in totals.items()}
            self.actor = EncounterPolicy(policy.weights, style=best)
            return self.actor(state)
        except (NativeError, TimeoutError, ValueError, RuntimeError) as exc:
            self.metrics["errors"].append(str(exc))
            return original
        finally:
            self.close()
