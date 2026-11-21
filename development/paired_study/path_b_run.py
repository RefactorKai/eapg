"""Prepare and replay the narrowed Path B growth queue with independent output checks."""

import argparse
from io import BytesIO
import json
from pathlib import Path
import tarfile

from development import gate1_sandbox as gate
from . import path_b_cases as cases, predict


MODES = {
    "plain": (),
    "ubsan": ("-fsanitize=undefined", "-fno-sanitize-recover=undefined"),
    **{flag: ("-" + flag, "-DPATH_B_COUNT") for flag in ("O0", "O2", "O3")},
}
SUPPORT = {
    91: "src/animation/runtime/track_sampling_job.cc",
    93: "src/operation/relateng/RelateGeometry.cpp",
    94: "core/src/histogram.cc",
    102: "src/pugixml.cpp",
    103: "src/password.cpp",
    109: "src/fft.hpp",
    120: "src/algorithm/construct/MaximumInscribedCircle.cpp",
    121: "src/LogarithmicIntegral.cpp",
    124: "include/generate_phi.hpp",
    126: "include/generate_phi.hpp",
}


def write(path, obj):
    data = predict.canonical(obj)
    with path.open("xb") as file:
        file.write(data)
    return predict.digest(data)


def prepare(rank, output):
    row = json.loads(cases.pinned(cases.DRAFT, cases.DRAFT_SHA))["rows"][rank - 1]
    plain, counted, edits = cases.prepared_sources(rank, cases.originals(row))
    samples = cases.workload(rank, row)
    output.mkdir(parents=True)
    for side in cases.VARIANTS:
        (output / f"{side}.cpp").write_bytes(plain[side])
        (output / f"{side}-counted.cpp").write_bytes(counted[side])
    return write(output / "prepared.json", {
        "schema": "eapg.path-b.preparation.v1", "held_out_used": False,
        "id": cases.CASES[rank], "rank": rank, "events": cases.EVENTS[rank], "spans": edits,
        "draft_sha256": cases.DRAFT_SHA, "samples": samples,
    })


def run_grid(binary, samples, counted):
    payload = BytesIO()
    with tarfile.open(fileobj=payload, mode="w") as archive:
        for index, sample in enumerate(samples):
            data = sample["input"].encode()
            item = tarfile.TarInfo(f"{index:02d}-{int(sample['size'])}.input")
            item.size = len(data)
            archive.addfile(item, BytesIO(data))
    result = gate.invoke([
        "/bin/sh", "-ec",
        r'''
            tar -xf -
            for f in *.input; do
                name=$(basename "$f" .input)
                status=0
                if [ "$1" = counted ]; then
                    EAPG_N=$(printf '%s' "$name" | cut -d- -f2) \
                        /program < "$f" > "$name.out" 2> "$name.err" 3> "$name.count" || status=$?
                else
                    /program < "$f" > "$name.out" 2> "$name.err" || status=$?
                    : > "$name.count"
                fi
                printf '%s\n' "$status" > "$name.status"
            done
            tar -cf - ./*.out ./*.err ./*.count ./*.status
        ''',
        "path-b-grid", "counted" if counted else "plain",
    ], data=payload.getvalue(), binary=binary, timeout=12)
    rows = []
    with tarfile.open(fileobj=BytesIO(gate.checked_output(result)), mode="r:") as archive:
        for index, sample in enumerate(samples):
            prefix = f"./{index:02d}-{sample['size']}"
            code, stdout, stderr, wire = [archive.extractfile(prefix + suffix).read()
                                         for suffix in (".status", ".out", ".err", ".count")]
            code = int(code)
            counts = [int(value) for value in wire.split()]
            ceiling = max(2_000_000, 5 * sample["size"] ** 2)
            if code == 85 and counted and len(counts) == 2 and sum(counts) >= ceiling:
                status = "tick_cap"
            elif code or stderr:
                status = "ubsan_or_process_failure"
            elif stdout.split() != [value.encode() for value in sample["expected"]]:
                status = "invalid_output"
            elif counted and (len(counts) != 2 or min(counts) < 0 or sum(counts) >= ceiling):
                status = "invalid_counter"
            else:
                status = "complete"
            row = {"status": status, "exit": code, "output_sha256": predict.digest(stdout),
                   "stderr_sha256": predict.digest(stderr)}
            if status != "complete":
                row.update({"stdout_excerpt": stdout[:200].decode(errors="replace"),
                            "stderr_excerpt": stderr[:1200].decode(errors="replace")})
            if counted:
                row["counts"] = counts
            rows.append(row)
    return rows


def measure(output, bundle, side, *modes):
    sources = bundle["spans"][side]
    plain = cases.pinned(output / f"{side}.cpp", sources["plain_sha256"])
    counted = cases.pinned(output / f"{side}-counted.cpp", sources["instrumented_sha256"])
    gate.checked_output(gate.invoke(["g++", "-std=c++17", "-fsyntax-only", "-x", "c++", "-"], data=plain))
    measurements = {}
    for mode in modes:
        instrumented = mode.startswith("O")
        binary = gate.compile_cpp(counted if instrumented else plain, *MODES[mode])
        measurements[mode] = run_grid(binary, bundle["samples"], instrumented)
    return measurements


def blind_observations(bundle, original):
    observations = []
    for i, sample in enumerate(bundle["samples"]):
        if sample["stream"] == "challenge":
            continue
        observation = {"stream": sample["stream"], "size": sample["size"], "status": "complete"}
        for side in ("target", "reference"):
            modes = original[side]
            rows = [modes[mode][i] for mode in MODES]
            status = "complete"
            if any(row["status"] not in {"complete", "tick_cap"} for row in rows):
                status = "invalid_output"
            elif any(row["status"] == "tick_cap" for row in rows):
                status = "tick_cap"
            elif any(row != rows[2] for row in rows[3:]):
                raise ValueError(f"Optimization levels disagree for {side} at {sample['size']}")
            if status != "complete":
                if observation["status"] != "invalid_output":
                    observation["status"] = status
                observation[side] = None
            else:
                row = rows[2]
                observation[side] = {"work": row["counts"][0], "advances": 0, "episodes": [],
                                     "output_sha256": predict.digest(" ".join(sample["expected"]).encode())}
        observations.append(observation)
    return observations


def seal_prediction(bundle, original):
    observations = blind_observations(bundle, original)
    blind = {"id": bundle["id"], "units": [], "observations": observations,
             "span_map_sha256": predict.digest(predict.canonical({
                 side: bundle["spans"][side]["original_sha256"] for side in ("target", "reference")
             }))}
    traces = {"schema": "eapg.paired.traces.v1", "cases": [blind]}
    try:
        predict.validate_traces(traces)
        validation = "fixed geometric predictor schema"
    except ValueError as failure:
        if str(failure) != "expected six distinct geometric sizes per stream":
            raise
        # Keep the census ladders and validate exact membership before using the predictor.
        grid = [(s["stream"], s["size"]) for s in bundle["samples"] if s["stream"] != "challenge"]
        if len(set(grid)) != len(grid) or grid != [(r["stream"], r["size"]) for r in observations]:
            raise ValueError("Blind grid differs from the registered census workload")
        for obs in observations:
            for side in ("target", "reference"):
                if obs[side] is not None:
                    predict.validate_side(obs[side], set())
        validation = "registered census grid with predictor side checks"
    result = predict.analyze_case(blind)
    return {"input": traces, "input_sha256": predict.digest(predict.canonical(traces)),
            "predictor_sha256": predict.digest(Path(predict.__file__).read_bytes()),
            "validation": validation, "result": result}


def run(output, prep_sha, dest):
    bundle = json.loads(cases.pinned(output / "prepared.json", prep_sha))
    original = {side: measure(output, bundle, side, *MODES) for side in ("target", "reference")}
    blind = seal_prediction(bundle, original)
    prediction_sha = write(dest.with_suffix(".prediction.json"), blind)
    print(f"{bundle['id']} blind prediction sealed", flush=True)
    execution = original | {
        side: measure(output, bundle, side, *MODES) for side in ("restored", "sham")
    }
    return write(dest, {"schema": "eapg.path-b.execution.v1", "held_out_used": False,
                        "id": bundle["id"], "rank": bundle["rank"], "prep_sha256": prep_sha,
                        "prediction_sha256": prediction_sha, "execution": execution,
                        "compiler": gate.checked_output(gate.invoke(["g++", "--version"])).decode().splitlines()[0],
                        "launcher_sha256": predict.digest(Path(gate.__file__).read_bytes())})


def replay_queue(folder, pins):
    failures = []
    consecutive = []
    for rank, prep_sha in zip(cases.CASES, pins, strict=True):
        output = folder / str(rank)
        first, second = (output / f"run{i}.json" for i in (1, 2))
        try:
            for dest in (first, second):
                print(run(output, prep_sha, dest), flush=True)
            if (first.read_bytes() != second.read_bytes() or
                    first.with_suffix(".prediction.json").read_bytes() !=
                    second.with_suffix(".prediction.json").read_bytes()):
                raise ValueError("Execution or prediction differs on replay")
        except (RuntimeError, ValueError) as failure:
            failures.append((rank, str(failure)))
            consecutive.append(str(failure))
            print(f"{rank} failed: {failure}", flush=True)
            if len(consecutive) >= 3 and len(set(consecutive[-3:])) == 1:
                break
        else:
            consecutive.clear()
            print(f"{rank} byte-exact replay passed", flush=True)
    if failures:
        raise SystemExit(f"Case failures: {failures}")


def preprocess_support(dest):
    draft = json.loads(cases.pinned(cases.DRAFT, cases.DRAFT_SHA))
    if list(SUPPORT) != draft["a4_draft_support_blockers"]:
        raise ValueError("Support paths differ from the pinned closure list")
    rows = []
    for rank, unit in SUPPORT.items():
        row = draft["rows"][rank - 1]
        source = row["phase_a"]["sources_sha256"][unit]
        attempts = {}
        for side, key in (("target", "old_sha256"), ("reference", "new_sha256")):
            data = cases.pinned(cases.CUSTODY / "cppperf-blobs" / source[key], source[key])
            result = gate.invoke(["g++", "-std=c++17", "-E", "-x", "c++", "-"], data=data)
            diagnostic = result.stderr.decode(errors="replace")
            if result.timed_out or not result.returncode or "No such file or directory" not in diagnostic:
                raise ValueError(f"Unexpected single-TU dependency result for {rank} {side}")
            attempts[side] = {"source_sha256": source[key], "exit": result.returncode,
                              "diagnostic": diagnostic, "stdout_sha256": predict.digest(result.stdout)}
        rows.append({"rank": rank, "unit": unit, "attempts": attempts, "cxx_executed": False,
                     "documented_boundary": row["phase_a"]["source_build"]})
    return write(dest, {"schema": "eapg.path-b.support.v1", "held_out_used": False, "rows": rows})


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    actions = cli.add_subparsers(dest="action", required=True)
    prep = actions.add_parser("prepare")
    prep.add_argument("rank", type=int, choices=cases.CASES)
    prep.add_argument("output", type=Path)
    execute = actions.add_parser("run")
    execute.add_argument("output", type=Path)
    execute.add_argument("sha256")
    execute.add_argument("dest", type=Path)
    queue = actions.add_parser("replay-queue")
    queue.add_argument("folder", type=Path)
    queue.add_argument("pins", nargs=len(cases.CASES))
    support = actions.add_parser("preprocess-support")
    support.add_argument("dest", type=Path)
    args = cli.parse_args()
    if args.action == "prepare":
        print(prepare(args.rank, args.output))
    elif args.action == "replay-queue":
        replay_queue(args.folder, args.pins)
    elif args.action == "preprocess-support":
        print(preprocess_support(args.dest))
    else:
        if args.dest.exists() or args.dest.with_suffix(".prediction.json").exists():
            cli.error("use fresh execution and prediction paths")
        print(run(args.output, args.sha256, args.dest))


if __name__ == "__main__":
    main()
