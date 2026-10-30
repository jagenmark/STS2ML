"""Reproduce the patch chain and accept only known source revisions.

Validates every edited file before writing anything. Temporary trees contain
source only; no game libraries, credentials, or saves are copied.
"""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "artifacts/upstreams/sts2-cli"
FILES = ("src/Sts2Headless/Program.cs", "src/Sts2Headless/RunSimulator.cs",
         "src/GodotStubs/Core.cs")
PATCHES = ("headless-runtime-identity.patch", "headless-public-observation.patch",
           "headless-training.patch")


def build_stages(folder, patches=PATCHES):
    for name in FILES:
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        original = subprocess.check_output(["git", "-C", str(UPSTREAM), "show", "HEAD:" + name])
        path.write_bytes(original.replace(b"\r\n", b"\n"))
    subprocess.run(["git", "init", "-q", str(folder)], check=True)
    stages = [{name: (folder / name).read_text(encoding="utf-8") for name in FILES}]
    for patch in patches:
        subprocess.run(["git", "-C", str(folder), "apply", str(ROOT / "scripts" / patch)], check=True)
        stages.append({name: (folder / name).read_text(encoding="utf-8") for name in FILES})
    return stages


def main():
    with tempfile.TemporaryDirectory(prefix="sts2-patches-") as temp:
        stages = build_stages(Path(temp))
    current = {name: (UPSTREAM / name).read_text(encoding="utf-8") for name in FILES}
    if current not in stages:
        raise SystemExit("Unexpected upstream source edits; refusing to overwrite")
    for name, text in stages[-1].items():
        (UPSTREAM / name).write_text(text, encoding="utf-8", newline="\n")
    print("Headless source matches the complete pinned patch chain")


if __name__ == "__main__":
    main()
