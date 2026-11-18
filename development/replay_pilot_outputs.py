"""Fresh sandboxed, byte-exact stdout comparison of the archived synthetic pilot."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import sys

from gate1_sandbox import execute
from probe_gate2_pilot import PILOT_SHA, PIPELINE_SHA, RELEASE
from run_phase2_development import compile_stage, load_module, process_status, provenance


COMMON_SIZES = (16, 24)
LOOP_BOUND_EXTRA_SIZES = (1, 2, 3, 8, 32, 64)


def load_frame(generator):
    raw = (RELEASE / "artifacts/scope_isolated_pilot/pilot100_results.json").read_bytes()
    if sha256(raw).hexdigest() != PILOT_SHA:
        raise ValueError("Published synthetic pilot hash mismatch")
    published = json.loads(raw)
    generated = generator.generate_pilot_100_corpus()
    if len(published) != 100 or len(generated) != 100 or len({row["pair_id"] for row in published}) != 100:
        raise ValueError("Expected the complete 100-pair synthetic pilot")

    frame = []
    for frozen, pair in zip(published, generated, strict=True):
        keys = ("pair_id", "problem_id", "mechanism_id", "slow_code", "fast_code")
        if any(frozen[key] != pair[key] for key in keys):
            raise ValueError(f"Generator and published pair differ for {frozen['pair_id']}")
        if tuple(frozen["stdout_equivalence_scales"]) != COMMON_SIZES:
            raise ValueError(f"Archived equivalence scales changed for {frozen['pair_id']}")
        extra = LOOP_BOUND_EXTRA_SIZES if pair["mechanism_id"] == "A1.4" else ()
        frame.append((pair, sorted(COMMON_SIZES + extra)))
    if sum(len(sizes) for _, sizes in frame) != 236:
        raise ValueError("Expected the 236 pair-size comparisons from the archived audit")
    return frame


def compare_pair(case):
    pair, sizes = case
    pair_id = pair["pair_id"]
    builds, binaries, runs = {}, {}, []
    for side in ("slow", "fast"):
        source = pair[f"{side}_code"]
        binary = compile_stage(f"{pair_id} {side} plain build", source)
        binaries[side] = binary
        builds[side] = {"source_sha256": sha256(source.encode()).hexdigest(),
                        "binary_sha256": sha256(binary).hexdigest()}

    for n in sizes:
        data = pair["input_gen"](n).encode()
        row = {"n": n, "stdin_sha256": sha256(data).hexdigest()}
        outputs = []
        for side, binary in binaries.items():
            result = execute(binary, data)
            status = process_status(result)
            if status != "CLEAN_COMPLETION":
                raise RuntimeError(f"{pair_id} N={n} {side}: {status}, exit {result.returncode}")
            row[side] = {"status": status, "returncode": result.returncode, "stdout_hex": result.stdout.hex()}
            outputs.append(result.stdout)
        if outputs[0] != outputs[1]:
            raise ValueError(f"{pair_id} N={n}: slow and fast stdout differ")
        runs.append(row)
    return {"pair_id": pair_id, "mechanism_id": pair["mechanism_id"], "builds": builds, "runs": runs}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--output", type=Path, required=True, help="New JSON report in an existing directory")
    args = cli.parse_args()
    if sys.platform != "linux" or args.output.exists() or not args.output.parent.is_dir():
        cli.error("Run in the unprivileged Linux sandbox with a new output path")

    generator = load_module("frozen_pilot_generator", RELEASE / "pipeline.py", PIPELINE_SHA)
    frame = load_frame(generator)
    toolchain = provenance(generator)
    del toolchain["sanitizer_flags"]
    toolchain["replay_sha256"] = sha256(Path(__file__).read_bytes()).hexdigest()
    with ThreadPoolExecutor(max_workers=4) as pool:
        pairs = list(pool.map(compare_pair, frame))
    report = {"schema": "eapg-pilot-output-agreement-v1", "pilot_sha256": PILOT_SHA,
              "provenance": toolchain, "common_sizes": COMMON_SIZES, "loop_bound_extra_sizes": LOOP_BOUND_EXTRA_SIZES,
              "comparison_count": sum(len(pair["runs"]) for pair in pairs), "pairs": pairs}
    raw = (json.dumps(report, indent=2, allow_nan=False) + "\n").encode()
    with args.output.open("xb") as stream:
        stream.write(raw)
    print(f"Replayed {report['comparison_count']} byte-exact stdout comparisons on {len(pairs)} synthetic pairs.")
    print(f"{sha256(raw).hexdigest()}  {args.output.name}")


if __name__ == "__main__":
    main()
