"""Materialize a Phase 2 development pipeline from the verified frozen release."""

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def build_candidate(output: Path, *, prospective: bool = False) -> str:
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    entries = dict(line.split("  ", 1)[::-1] for line in (ROOT / "SHA256SUMS").read_text(encoding="utf-8").splitlines() if line)
    frozen = (ROOT / "pipeline.py").read_bytes()
    if hashlib.sha256(frozen).hexdigest() != entries["pipeline.py"]:
        raise RuntimeError("Frozen pipeline SHA-256 mismatch")

    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="eapg-build-", dir=output.parent) as directory:
        staged = Path(directory) / "pipeline.py"
        staged.write_bytes(frozen.replace(b"\r\n", b"\n"))
        patches = ["phase2_pipeline.patch"]
        if prospective:
            patches.append("phase2_prospective.patch")
        for patch in patches:
            subprocess.run(["git", "-c", "core.autocrlf=false", "apply", "--whitespace=nowarn", str(HERE / patch)],
                           cwd=directory, env={**os.environ, "GIT_CEILING_DIRECTORIES": str(output.parent)}, check=True)
        # Preserve the line endings used by the recorded candidate digest.
        candidate = staged.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        compile(candidate, str(output), "exec")
        with output.open("xb") as stream:
            stream.write(candidate)
    return hashlib.sha256(candidate).hexdigest()


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("output", type=Path, help="new Python file for the materialized pipeline")
    cli.add_argument("--prospective", action="store_true", help="apply the follow-up fixes after the archived patch")
    args = cli.parse_args()
    output = args.output.resolve()
    try:
        digest = build_candidate(output, prospective=args.prospective)
    except FileExistsError as exc:
        cli.error(str(exc))
    print(f"{digest}  {output}")


if __name__ == "__main__":
    main()
