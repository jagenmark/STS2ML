"""Audit executed Rocket slams after play, in a second pinned host with no controller."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import gzip
import hashlib
import json
import os
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
from unittest.mock import patch

from kaiser import ROOT, episode
from kaiser_v63b import cohort, metrics
from sts2rl.native import NativeSession, digest


class BoardTranscript:
    """Verify the original raw hash even when The Trial picks a new cosmetic number."""
    def __init__(self):
        self.digests = []
        self.trial = {}

    def observe(self, board):
        if board.get("event_name") == "The Trial" and any(
                "EntrantNumber" in opt.get("vars", {}) for opt in board.get("options", [])):
            self.trial[len(self.digests)] = board
        self.digests.append(digest(board).encode())

    def verify(self, expected):
        def checksum(values):
            return hashlib.sha256(b"".join(values)).hexdigest()

        raw = checksum(self.digests)
        if raw == expected:
            return {"replay_sha256": raw}
        assert self.trial, (raw, expected)
        work = list(self.digests)
        for entrant in range(1001):
            for index, board in self.trial.items():
                opts = [{**opt, "vars": {**opt["vars"], "EntrantNumber": entrant}}
                        if "EntrantNumber" in opt.get("vars", {}) else opt for opt in board["options"]]
                work[index] = digest({**board, "options": opts}).encode()
            if checksum(work) == expected:
                return {"replay_sha256": raw, "original_entrant_number": entrant,
                        "trial_steps": sorted(self.trial)}
        raise AssertionError(("unexplained public board difference", raw, expected))


def attacks(job):
    path, triple, observer = job
    row = json.loads(gzip.decompress(path.read_bytes()))
    if not row["opening"]:
        return None
    tape = row.get("kaiser_replay")
    with TemporaryDirectory() as tmp:
        out = Path(tmp)
        if tape is None:
            # The historical diagnostic collector kept only transcript hashes.
            copyfile(path.with_name("kaiser_config.json"), out / "kaiser_config.json")
            bundle = path.parents[1] / "arm4/policy/policy.json"
            episode((bundle, out, triple, False, "treatment"), kaiser_metrics=metrics)
            regenerated = json.loads(gzip.decompress((out / path.name).read_bytes()))
            assert all(row[k] == regenerated[k] for k in ("commands", "opening", "native", "kaiser_metrics"))
            tape = regenerated["kaiser_replay"]
        transcript = hashlib.sha256()
        boards = BoardTranscript()
        hits = out / "hits.jsonl"
        turns = {}
        facing = "ROCKET"
        with patch.dict(os.environ, DOTNET_STARTUP_HOOKS=str(observer), KAISER_ATTACK_RECEIPT=str(hits)):
            with NativeSession(ROOT, out / "replay", host_path=os.environ["CSV2DEV_HOST"], act_list=triple[2]) as game:
                before = game.reset(triple[1])
                for command in tape:
                    boards.observe(before)
                    transcript.update(json.dumps(command, sort_keys=True).encode() + b"\n")
                    view = before.get("combat_state", before)
                    arms = {e["index"]: e["id"].removeprefix("MONSTER.") for e in view.get("enemies", [])}
                    if set(arms.values()) == {"CRUSHER", "ROCKET"} and before.get("in_combat"):
                        turns.setdefault(view["round"], facing)
                        target = command["args"].get("target_index")
                        if command["action"] in ("play_card", "use_potion") and target in arms:
                            facing = arms[target]
                    before = game._request(command)
        assert transcript.hexdigest() == row["commands"]
        verification = boards.verify(row["public_boards"])
        assert before["decision"] == "game_over"
        events = [json.loads(line) for line in hits.read_text().splitlines()]
        for event in events:
            assert event["facing"] in ("Left", "Right", None)
            event["opening_facing"] = turns.get(event["round"])
        assert len(events) <= row["kaiser_metrics"].get("rocket_big_intents", 0)
        return dict(seed=row["seed"], arm=path.parent.name, commands=row["commands"],
                    public_boards=row["public_boards"], board_verification=verification, events=events)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("panel", choices=("diagnostic", "dev"))
    p.add_argument("folder", type=Path)
    p.add_argument("observer", type=Path)
    p.add_argument("--workers", required=True, choices=[12], type=int)
    args = p.parse_args()
    folder = args.folder.resolve()
    jobs = [(folder / arm / (t[1] + ".json.gz"), t, args.observer.resolve())
            for t in cohort(args.panel) for arm in ("v63", "v63b")]
    counts = Counter()
    with gzip.open(folder / "executed.jsonl.gz", "xt", encoding="utf-8") as output, ProcessPoolExecutor(12) as pool:
        for r in pool.map(attacks, jobs):
            if r:
                output.write(json.dumps(r, separators=(",", ":")) + "\n")
                counts[r["arm"]] += len(r["events"])
    print(counts)


if __name__ == "__main__":
    main()
