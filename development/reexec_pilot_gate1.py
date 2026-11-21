"""Re-execute the committed pilot through the frozen pipeline and Gate 1."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import platform
import subprocess

import gate1_sandbox as gate1
import reexec_pilot as pilot


RECEIPT = pilot.RECEIPT.with_name("pilot100_gate1_receipt.json")
COMPILER = "15.2.0"


class Gate1Subprocess:
    """The frozen pilot's subprocess interface, with no host fallback."""

    SubprocessError = subprocess.SubprocessError
    TimeoutExpired = subprocess.TimeoutExpired

    def __init__(self):
        self.binaries = {}

    def run(self, command, *, input, timeout, text, capture_output, env=None, preexec_fn=None):
        try:
            if not text or not capture_output:
                raise ValueError("Expected captured text subprocess output")
            return self._run(command, input.encode("utf-8"), timeout, env)
        except Exception as error:
            # The frozen preprocessing and execution paths catch Exception and fall back.
            raise SystemExit(f"Gate 1 failed for {command}: {error}") from error

    def _run(self, command, data, timeout, env):
        match command:
            case ["g++", "-E", "-P", "-x", "c++", "-"] | ["g++", "-std=c++17", "-fsyntax-only", "-x", "c++", "-"]:
                result = gate1.invoke(command, data=data, timeout=timeout)
            case ["g++", "-std=c++17", "-O2", "-x", "c++", "-", "-o", output]:
                self.binaries[output] = gate1.compile_cpp(data)
                return subprocess.CompletedProcess(command, 0, "", "")
            case [binary] if binary in self.binaries:
                program = self.binaries[binary]
                if env is None:
                    result = gate1.execute(program, data, timeout=timeout)
                else:
                    scale = int(env["EAPG_N"])
                    if not 0 < scale <= gate1.MAX_SCALE:
                        raise ValueError("EAPG_N is outside the counter scale range")
                    # Preserve the archived pilot's stderr counter format, not candidate environment.
                    result = gate1.invoke(["/usr/bin/env", f"EAPG_N={scale}", "/program"],
                                          data=data, binary=program, timeout=timeout)
            case _:
                raise ValueError("Unexpected frozen-pipeline subprocess; no host fallback")
        return subprocess.CompletedProcess(command, 0, decode(gate1.checked_output(result)), decode(result.stderr))


def decode(data):
    return data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def reexecute():
    compiler = decode(gate1.checked_output(gate1.invoke(["g++", "-dumpfullversion"]))).strip()
    if compiler != COMPILER:
        raise SystemExit(f"Expected Gate 1 GCC {COMPILER}, found {compiler}")
    published = pilot.load_published()
    archived_raw = pilot.RECEIPT.read_bytes()
    archived = json.loads(archived_raw)
    gen = pilot.load_frozen_pipeline()
    pilot.check_receipt_static(gen, archived, published)
    runs = {}
    for mode in pilot.PROXY_DEFAULTS:
        gen = pilot.load_frozen_pipeline(mode)
        gen.subprocess = Gate1Subprocess()
        print(f"Re-executing {mode} pilot through Gate 1 (GCC {compiler})", flush=True)
        runs[mode] = pilot.reexecute(gen, pilot.embedded_corpus(gen, published))
    report, differences, *_ = pilot.evaluate(published, archived, runs["linear"], runs["unit"])
    if runs["linear"]["tables_tex_sha256"] != archived["tables_tex_sha256"]:
        differences.append("Generated LaTeX tables differ from the archived receipt")
    return {
        "schema": "eapg.pilot100_gate1/v1",
        "compiler": f"g++ {compiler}",
        "compiler_flags": ["-std=c++17", "-O2"],
        "python": platform.python_version(),
        "sandbox": "development/gate1_sandbox.py",
        "sandbox_sha256": sha256(Path(gate1.__file__).read_bytes()).hexdigest(),
        "pipeline_sha256": pilot.PIPELINE_SHA,
        "published_pilot_sha256": pilot.PILOT_SHA,
        "archived_receipt_sha256": sha256(archived_raw).hexdigest(),
        "counters_sha256": {mode: digest(run["counters"]) for mode, run in runs.items()},
        "tables_tex_sha256": {mode: run["tables_tex_sha256"] for mode, run in runs.items()},
        "comparison": report,
        "differences": differences,
    }


def validate(fresh, expected=None):
    differences = fresh["differences"]
    if differences:
        raise SystemExit(f"Sandboxed pilot differs from the archive ({len(differences)} differences; see report above)")
    if expected is not None and fresh != expected:
        changed = pilot.diff_fields(expected, fresh)
        raise SystemExit(f"Sandboxed pilot receipt differs at: {', '.join(changed)}")


def main():
    if not __debug__:
        raise RuntimeError("Run without Python optimization so assertions remain active")
    cli = argparse.ArgumentParser(description=__doc__)
    mode = cli.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Re-execute and check the committed Gate 1 receipt.")
    mode.add_argument("--write-receipt", type=Path, help="Write a receipt to a new path.")
    args = cli.parse_args()
    expected = json.loads(RECEIPT.read_bytes()) if args.check else None
    if args.check and not isinstance(expected, dict):
        cli.error("Expected an object in the committed Gate 1 receipt.")
    fresh = reexecute()
    report = json.dumps(fresh, indent=2) + "\n"
    print(report, end="", flush=True)
    validate(fresh, expected)
    if args.write_receipt:
        with args.write_receipt.open("x", encoding="utf-8", newline="\n") as file:
            file.write(report)
    else:
        print("Verified sandboxed pilot receipt (0 skipped).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
