"""Rebuild historical bundles and replay CSV2DEV and CSV11DEV on the pinned host."""
from concurrent.futures import ProcessPoolExecutor
import gzip
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
import zipfile
import os

import phase1_gate as gate
import v6_gate
import v66
from sts2rl.run_bundle import load_bundle
from v64 import DOC, ROOT


def sha(data):
    return hashlib.sha256(data).hexdigest()


def files(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


def frozen_episode(job):
    arm, bundle, config, mode, i = job

    def load(_):
        role, opts = load_bundle(bundle)
        if arm == "kaiser":
            opts["combat_search_v2_config"] = config
        return role, opts

    with TemporaryDirectory() as tmp, patch.object(gate, "load_bundle", load):
        return gate.episode((Path(os.environ["CSV2DEV_HOST"]), Path(tmp), arm, mode, i, False, False, False))


def replay_v66(job):
    root, arm, bundle, row = job
    v66.run_arm(root / arm, bundle, row)
    return arm, row[1]


def main(out, base_root):
    out.mkdir(parents=True, exist_ok=False)
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=base_root, text=True).strip() == (
        "a584f1b79b944ce2d46ee32c0cd378e54b380ef6")
    pins = runpy.run_path(str(ROOT / "scripts/verify-silent-v6.py"))
    assert sha(Path(os.environ["CSV2DEV_HOST"]).read_bytes()) == pins["HOST_SHA"]
    assert sha((ROOT / "artifacts/upstreams/sts2-cli/lib/sts2.dll").read_bytes()) == pins["GAME_SHA"]
    assert not os.getenv("DOTNET_STARTUP_HOOKS")
    qualification = dict(profiles={}, frozen={}, csv2dev={}, v66_replays={})
    base_policy = Path("releases/silent-a10-mecha-knight/challenger/policy.json")
    frozen = Path("releases/silent-a10-v2-tactics/challenger")
    release = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", "efd9877", "--", frozen], text=True).splitlines()
    for name in release:
        original = subprocess.check_output(["git", "show", "efd9877:" + name])
        assert original == (ROOT / name).read_bytes()
        qualification["frozen"][name] = sha(original)
    assert len(release) == len(files(ROOT / frozen)) == 10
    archived = DOC / "v66-silent-cards-batch1-receipts.zip"
    with TemporaryDirectory() as tmp, zipfile.ZipFile(archived) as z, ProcessPoolExecutor(12) as pool:
        temp = Path(tmp)
        old = runpy.run_path(str(base_root / "scripts/build-batch1-challengers.py"))
        new = runpy.run_path(str(ROOT / "scripts/build-batch1-challengers.py"))
        prior_hashes = json.loads(z.read("qualification/qualification.json"))["profiles"]
        built = {}
        for profile in old["PROFILES"]:
            a = old["build_batch1_bundle"](base_root / base_policy, temp / "old" / profile, profile=profile)
            b = new["build_batch1_bundle"](ROOT / base_policy, temp / "new" / profile, profile=profile)
            before, after = files(a.parent), files(b.parent)
            assert before == after
            hashes = {k: sha(v) for k, v in after.items()}
            if profile in prior_hashes:
                assert hashes == prior_hashes[profile]
            qualification["profiles"][profile] = hashes
            built[profile] = b
        arm4 = built["all_v2_search_v6"]
        config = json.loads(load_bundle(arm4)[1]["combat_search_v2_config"].read_bytes())
        kaiser = temp / "kaiser_config.json"
        kaiser.write_text(json.dumps({**config, "kaiser_v63": True}))
        for variant in ("off", "active", "shadow", "v5", "kaiser"):
            if variant in ("off", "active", "shadow"):
                jobs = [(variant, None, bundle, mode, i) for i in range(6)
                        for bundle in gate.BUNDLES for mode in ("default", "seeded")]
                rows = list(pool.map(v6_gate.episode, jobs))
                name = variant
            else:
                bundle = ROOT / frozen / "policy.json" if variant == "v5" else arm4
                jobs = [(variant, bundle, kaiser, mode, i) for i in range(12) for mode in ("default", "seeded")]
                rows = list(pool.map(frozen_episode, jobs))
                name = variant + "-candidate"
            data = json.dumps(rows).encode()
            assert data == z.read("qualification/" + name + ".json"), variant
            (out / (name + ".json")).write_bytes(data)
            qualification["csv2dev"][variant] = dict(n=len(rows), sha256=sha(data))
            print("CSV2DEV", variant, len(rows), flush=True)
        bundles = v66.build(temp / "replays")
        manifest = json.loads(z.read("manifest.json"))
        assert {k: sha(p.read_bytes()) for k, p in bundles.items()} == manifest["bundles"]
        jobs = [(temp / "replays", arm, bundles[arm], row) for row in v66.cohort() for arm in ("arm1", "arm2")]
        reference = {arm: {r["seed"]: r for r in map(json.loads, gzip.decompress(z.read(arm + ".jsonl.gz")).splitlines())}
                     for arm in ("arm1", "arm2")}
        for arm, seed in pool.map(replay_v66, jobs):
            path = temp / "replays" / arm / (seed + ".json.gz")
            actual = json.loads(gzip.decompress(path.read_bytes()))
            expected = reference[arm][seed]
            del actual["latency_us"], expected["latency_us"]
            assert actual == expected, (arm, seed)
            qualification["v66_replays"][arm + "/" + seed] = actual["commands"]
    (out / "compatibility.json").write_text(json.dumps(qualification, indent=2))
    print("Verified builders, frozen files, CSV2DEV receipts and both complete v6.6 arms.", flush=True)


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
