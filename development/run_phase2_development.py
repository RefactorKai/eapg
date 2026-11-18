"""Run authored fixtures or the single registered Phase 2 development pair."""

import argparse
from collections import defaultdict
from hashlib import sha256
from importlib.metadata import version
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import platform
import sys
from types import FunctionType

from gate1_sandbox import (COUNTER_CAP, FILE_CAP, SCRATCH_CAP, SandboxStageFailure,
                           checked_output, compile_cpp, execute, invoke)
from probe_gate1 import probe_boundaries, probe_cleanup, probe_private_scratch, probe_resource_limits


HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "artifacts/phase2_data"
WORKLOAD_SHA = "7b62a1aa49b27d116937ca1ed2a786f61ae3cfc7fc321eb175ecfaf96cee0bf7"
HISTORICAL_SHA = "6ebba4b60bfcff69e5dbbe66e9b8d74563a7bb0f69c2197213f24f7627aa56dd"
SANITIZER_FLAGS = ("-fsanitize=undefined", "-fno-sanitize-recover=undefined")


def load_module(name, path, expected=None):
    path = Path(path).resolve()
    source = path.read_bytes()
    digest = sha256(source).hexdigest()
    if expected is not None and digest != expected:
        raise ValueError(f"Pinned module hash mismatch: {path.name}")
    module = module_from_spec(spec_from_file_location(name, path))
    exec(compile(source, str(path), "exec"), module.__dict__)
    module.source_sha256 = digest
    return module


historical = load_module("historical_phase2_development", DATA / "run_development.py", HISTORICAL_SHA)


def load_pipeline(path):
    return load_module("phase2_candidate_pipeline", path)


class ProfileFailure(RuntimeError):
    def __init__(self, status, message, result=None):
        super().__init__(message)
        self.details = {"status": status, "message": message}
        if result is not None:
            self.details.update(returncode=result.returncode, timed_out=result.timed_out,
                                stderr=result.stderr[:2000].decode(errors="replace"), events=result.events)


def process_status(result):
    if result.timed_out:
        return "TIMEOUT_TLE"
    if int(result.events.get("memory.events.oom", 0)):
        return "MEMORY_LIMIT_MLE"
    if int(result.events.get("pids.events.max", 0)):
        return "TASK_LIMIT"
    if result.returncode == 0:
        return "CLEAN_COMPLETION"
    if result.returncode == 97:
        return "CAP_BREACHED"
    if result.returncode in (139, -11):
        return "CRASH_SIGSEGV"
    if result.returncode in (153, -25):
        return "OUTPUT_LIMIT"
    return "EXECUTION_ERROR"


def verify_preprocessing(result, stage):
    status = process_status(result)
    if status != "CLEAN_COMPLETION":
        raise ProfileFailure("PREPROCESS_ERROR" if status == "EXECUTION_ERROR" else status, stage, result)
    return result


normalize = FunctionType(historical.normalize.__code__,
                         {**historical.normalize.__globals__, "run": invoke, "check": verify_preprocessing})


def validate_counter(result, nodes, cap):
    if not result.timed_out and result.returncode == 98:
        raise ProfileFailure("INSTRUMENTATION_ERROR", "Instrumented emitter reported an I/O or setup failure", result)
    status = process_status(result)
    if status not in ("CLEAN_COMPLETION", "CAP_BREACHED"):
        raise ProfileFailure(status, "Instrumented program failed", result)
    wire = result.counter_wire
    try:
        if not 0 < len(wire) <= COUNTER_CAP or wire.count(b"\n") != 1 or not wire.endswith(b"\n"):
            raise ValueError("Missing, oversized, truncated, or repeated counter record")
        record = json.loads(wire, object_pairs_hook=historical.strict_object)
        if type(record) is not dict or set(record) != {"status", "total_ticks", "nodes"} or record["status"] != status:
            raise ValueError("Counter record and process status disagree")
        counters = record["nodes"]
        if type(counters) is not dict or set(counters) != {node["id"] for node in nodes}:
            raise ValueError("Counter record does not match the canonical node set")
        for counter in counters.values():
            if type(counter) is not dict or set(counter) != {"cnt", "work"} or any(
                    type(value) is not int or value < 0 for value in counter.values()):
                raise ValueError("Invalid counter values")
        total = record["total_ticks"]
        if type(total) is not int or total != sum(counter["work"] for counter in counters.values()):
            raise ValueError("Counter totals disagree with summed work")
        if (total < cap) != (status == "CLEAN_COMPLETION"):
            raise ValueError("Counter totals disagree with the tick ceiling")
    except ValueError as exc:
        raise ProfileFailure("INVALID_COUNTER", str(exc), result) from exc
    return record


def compile_stage(stage, source, *flags):
    try:
        return compile_cpp(source.encode(), *flags)
    except SandboxStageFailure as exc:
        status = process_status(exc.result)
        raise ProfileFailure("COMPILE_ERROR" if status == "EXECUTION_ERROR" else status, stage, exc.result) from exc


def compile_instrumented(pipeline, normalized, nodes):
    return compile_stage("instrumented build", historical.instrument(pipeline, normalized, nodes))


def run_profile(pipeline, binary, data, n, nodes):
    result = execute(binary, data, counter_scale=n)
    return result, validate_counter(result, nodes, pipeline.compute_tick_ceiling(n))


def profile_case(pipeline, source, data, n):
    normalized, aliases = normalize(pipeline, source)
    nodes = pipeline.extract_macro_nodes(normalized, aliases)
    result, record = run_profile(pipeline, compile_instrumented(pipeline, normalized, nodes), data, n, nodes)
    return normalized, nodes, result, record


def verify_transport(pipeline):
    fixtures = {
        "early_return": ("if (true) return 0; return 1;", "CLEAN_COMPLETION"),
        "helper_exit": ("finish();", "CLEAN_COMPLETION"),
        "fork_owner": ("if (fork() == 0) std::exit(0); int status; wait(&status); return 0;", "CLEAN_COMPLETION"),
        "tick_cap": ("for (;;) { int i = 0; i++; }", "CAP_BREACHED"),
        "closed_descriptor": ("close(64); return 0;", "INSTRUMENTATION_ERROR"),
        "duplicate_record": ('write(64, "{}\\n", 3); return 0;', "INVALID_COUNTER"),
        "oversized_record": ("char data[65537]{}; write(64, data, sizeof(data)); std::_Exit(0);", "INVALID_COUNTER"),
        "truncated_record": ('write(64, "{", 1); std::_Exit(0);', "INVALID_COUNTER"),
        "status_mismatch": ('const char s[] = "{\\"status\\":\\"CAP_BREACHED\\",\\"total_ticks\\":0,\\"nodes\\":{}}\\n"; '
                            "write(64, s, sizeof(s) - 1); std::_Exit(0);", "INVALID_COUNTER"),
        "forged_stdout_stderr": ('puts("{}"); fputs("{}\\n", stderr); return 0;', "CLEAN_COMPLETION"),
        "stdout_stderr_without_record": ('puts("{}"); fputs("{}\\n", stderr); std::_Exit(0);', "INVALID_COUNTER"),
        "abnormal_exit": ("std::abort();", "EXECUTION_ERROR"),
    }
    outcomes = {}
    for name, (body, expected) in fixtures.items():
        source = "#include <unistd.h>\n#include <sys/wait.h>\n#include <cstdlib>\n#include <cstdio>\n"
        if name == "helper_exit":
            source += "void finish() { std::exit(0); }\n"
        try:
            *_, record = profile_case(pipeline, source + f"int main() {{{body}}}\n", b"", 1)
            outcome = record["status"]
        except ProfileFailure as exc:
            outcome = exc.details["status"]
        if outcome != expected:
            raise RuntimeError(f"Counter fixture {name}: expected {expected}, saw {outcome}")
        outcomes[name] = outcome
    return outcomes


def run_probes(pipeline):
    outcomes = {}
    for probe in (probe_boundaries, probe_private_scratch, probe_resource_limits, probe_cleanup):
        probe()
        outcomes[probe.__name__] = "passed"
    outcomes["counter_transport"] = verify_transport(pipeline)
    return outcomes


def registered_payload(validation):
    workload_bytes = (DATA / "development_workload.json").read_bytes()
    if sha256(workload_bytes).hexdigest() != WORKLOAD_SHA:
        raise ValueError("Registered workload hash mismatch")
    workload = json.loads(workload_bytes)
    raw = validation.read_bytes()
    if sha256(raw).hexdigest() != historical.VAL_SHA:
        raise ValueError("PIE validation release hash mismatch")
    row, = (row for line in raw.splitlines() if line.strip() and
            (row := json.loads(line))["problem_id"] == workload["problem_id"] and
            (row["src_id"], row["tgt_id"]) == (workload["slow_submission_id"], workload["fast_submission_id"]))
    sources = {"slow": row["src_code"], "fast": row["tgt_code"]}
    for side, source in sources.items():
        if sha256(source.encode()).hexdigest() != workload[f"{side}_sha256"]:
            raise ValueError(f"Registered {side} source hash mismatch")
    return workload, sources


def verify_oracle(result, case, stage):
    status = process_status(result)
    if stage == "sanitizer" and b"runtime error:" in result.stderr and status == "EXECUTION_ERROR":
        status = "SANITIZER_FINDING"
    if status != "CLEAN_COMPLETION":
        raise ProfileFailure(status, f"{stage} failed at seed {case['seed']}, N={case['n']}", result)
    if result.stdout.split() != case["expected_stdout"].encode().split():
        raise ProfileFailure("OUTPUT_MISMATCH", f"{stage} oracle mismatch at seed {case['seed']}, N={case['n']}", result)


def profile_side(pipeline, source, cases):
    normalized, aliases = normalize(pipeline, source)
    nodes = pipeline.extract_macro_nodes(normalized, aliases)
    for stage, flags in (("original", ()), ("sanitizer", SANITIZER_FLAGS)):
        binary = compile_stage(stage + " build", source, *flags)
        for case in cases:
            verify_oracle(execute(binary, case["stdin"].encode()), case, stage)
    binary = compile_instrumented(pipeline, normalized, nodes)
    runs = defaultdict(list)
    for case in cases:
        result, record = run_profile(pipeline, binary, case["stdin"].encode(), case["n"], nodes)
        if record["status"] == "CLEAN_COMPLETION":
            verify_oracle(result, case, "instrumented")
        runs[str(case["seed"])].append({"n": case["n"], "returncode": result.returncode,
                                      "stdout": result.stdout.decode(errors="replace"), **record})
    fits = {}
    for seed, rows in runs.items():
        clean = [row for row in rows if row["status"] == "CLEAN_COMPLETION"]
        sizes = [row["n"] for row in clean]
        if len(sizes) < 4 or sizes[-1] < 8 * sizes[0]:
            raise ProfileFailure("INSUFFICIENT_SCALING_SIZES", f"Insufficient clean sizes for seed {seed}")
        fits[seed] = {
            node["id"]: {
                channel: pipeline.fit_dual_family_scaling(sizes, [row["nodes"][node["id"]][key] for row in clean])
                for channel, key in (("fit_hits", "cnt"), ("fit_work", "work"))
            }
            for node in nodes
        }
    return {"nodes": nodes, "fits": fits, "runs": runs, "normalized_sha256": sha256(normalized.encode()).hexdigest(),
            "plain_oracle_checks": len(cases), "sanitizer_oracle_checks": len(cases)}


def rank_by_seed(pipeline, slow):
    nodes = slow["nodes"]
    results = {}
    for seed, fits in slow["fits"].items():
        result = pipeline.evaluate_four_slicing_tiers(nodes, fits)
        candidates = result["c_pruned"]
        ranked = []
        if candidates:
            dynamics = pipeline.analyze_eapg_slicing(nodes, fits)
            dynamics.update(c_slice=candidates, r_search=1 - len(candidates) / len(nodes))
            skeleton = pipeline.format_eapg_skeleton(nodes, fits, dynamics)
            record = {"skeleton": skeleton, "slicing": result, "pilot_revision": pipeline.PILOT_REVISION}
            ranked = pipeline.rank_candidates_by_role_priority(record, use_loop_def_use=True, macro_nodes=nodes)
            if len(ranked) != len(candidates) or set(ranked) != set(candidates):
                raise RuntimeError(f"Ranker did not return the canonical candidate set for seed {seed}")
        result["ranked_candidates"] = ranked
        results[seed] = result
    return results


def provenance(pipeline):
    return {"pipeline_sha256": pipeline.source_sha256, "historical_transport_sha256": HISTORICAL_SHA,
            "development_code_sha256": {name: sha256((HERE / name).read_bytes()).hexdigest() for name in
                                        ("run_phase2_development.py", "gate1_sandbox.py", "probe_gate1.py")},
            "compiler": checked_output(invoke(["g++", "-dumpfullversion"])).decode().strip(),
            "kernel": platform.release(), "python": platform.python_version(),
            "parser": {name: version(name) for name in ("tree-sitter", "tree-sitter-cpp")},
            "flags": ["-std=c++17", "-O2"], "sanitizer_flags": SANITIZER_FLAGS,
            "limits": {"scratch_bytes": SCRATCH_CAP, "file_bytes": FILE_CAP, "counter_record_bytes": COUNTER_CAP,
                       "scope_memory_bytes": 768 * 1024**2, "scope_swap_bytes": 0, "scope_tasks": 24,
                       "scope_cpu_quota_percent": 100, "address_space_bytes": 512 * 1024**2,
                       "process_cpu_seconds": 8, "run_wall_seconds": 12, "compile_wall_seconds": 25}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipeline", type=Path, required=True)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--probes-only", action="store_true")
    modes.add_argument("--registered-validation", type=Path, metavar="PIE_VAL_JSONL")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not __debug__ or sys.platform != "linux":
        parser.error("Run on Linux without Python optimization")
    if args.registered_validation is not None and args.output is None:
        parser.error("The registered validation run requires a fresh --output path")
    if args.output is not None and args.output.exists():
        raise FileExistsError(args.output)
    deps = Path.home() / ".local/share/eapg-phase2/deps"
    if deps.is_dir():
        sys.path.insert(0, str(deps))
    pipeline = load_pipeline(args.pipeline)
    report = {"gate": run_probes(pipeline), "provenance": provenance(pipeline)}
    if args.registered_validation is not None:
        workload, sources = registered_payload(args.registered_validation)
        report.update(study="PIE validation feasibility, development only", workload_sha256=WORKLOAD_SHA,
                      validation_sha256=historical.VAL_SHA,
                      case={key: value for key, value in workload.items() if key != "inputs"})
        for side, source in sources.items():
            try:
                report[side] = profile_side(pipeline, source, workload["inputs"])
            except ProfileFailure as exc:
                report[side] = {"failure": exc.details}
        if "failure" not in report["slow"]:
            report["slices_by_seed"] = rank_by_seed(pipeline, report["slow"])
    if args.output is None:
        print(json.dumps(report, indent=2))
    else:
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(report, output, indent=2)
            output.write("\n")
    if any("failure" in report.get(side, {}) for side in ("slow", "fast")):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
