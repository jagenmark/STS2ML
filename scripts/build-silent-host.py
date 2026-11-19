"""Build an isolated Linux A10 host from the pinned checkout and existing local game assets."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "artifacts/upstreams/sts2-cli"
REVISION = "fec723a21741a1a33a4f54dc9b28c50df31d6e45"


def git(*args):
    return subprocess.check_output(["git", "-C", str(UPSTREAM), *args])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True, help="A new directory for the private host build")
    args = p.parse_args()
    if os.name != "posix":
        p.error("Use scripts/setup-headless.ps1 on Windows")
    if git("rev-parse", "HEAD").decode().strip() != REVISION:
        p.error("The prepared native checkout has a different revision")
    sdk = ROOT / "artifacts/tools/dotnet/dotnet"
    assets = ("lib", "localization_eng", "localization_zhs")
    if not sdk.is_file() or any(not (UPSTREAM / d).is_dir() for d in assets) or not (UPSTREAM / "lib/sts2.dll").is_file():
        p.error("The prepared local SDK, game DLLs and extracted localization directories are required")
    dest = args.output.resolve()
    dest.mkdir(parents=True, exist_ok=False)
    files = git("ls-tree", "--name-only", "-r", "HEAD", "--", "src/GodotStubs", "src/Sts2Headless")
    for name in files.decode().splitlines():
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(git("show", "HEAD:" + name))
    build_stages = runpy.run_path(str(ROOT / "scripts/apply-headless-patches.py"))["build_stages"]
    with TemporaryDirectory() as temp:
        for name, contents in build_stages(Path(temp))[-1].items():
            (dest / name).write_text(contents, encoding="utf-8")
    for name in ("ObservationExport.cs", "PresentationFix.cs", "TrainingSupport.cs"):
        shutil.copyfile(ROOT / "scripts/headless" / name, dest / "src/Sts2Headless" / name)
    for name in assets:
        (dest / name).symlink_to((UPSTREAM / name).resolve(), target_is_directory=True)
    feed = dest / "empty-feed"
    feed.mkdir()
    env = {**os.environ, "DOTNET_CLI_HOME": str(dest / "dotnet-home"), "DOTNET_CLI_TELEMETRY_OPTOUT": "1"}
    subprocess.run([str(sdk), "build", str(dest / "src/Sts2Headless/Sts2Headless.csproj"), "-c", "Curriculum",
                    "--source", str(feed), "--disable-build-servers"], env=env, check=True)
    binary = dest / "src/Sts2Headless/bin/Curriculum/net9.0"
    files = (binary / "Sts2Headless.dll", binary / "GodotSharp.dll", dest / "lib/sts2.dll")
    hashes = {str(p.relative_to(dest)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    (dest / "manifest.json").write_text(json.dumps({"revision": REVISION, "sha256": hashes}, indent=2) + "\n")
    print(binary / "Sts2Headless.dll")


if __name__ == "__main__":
    main()
