"""Gate 1 execution and checkpoint replay for the frozen benchmark expansion.

Pass the exact manifest and compact bundle as consecutive newline-terminated
JSON records via stdin. Run through development/run_sandbox_container.sh with
python -B -m development.paired_study.expansion_run --bundle-sha256 PIN.
On the host, the same input plus --check CHECKPOINT replays without executing.
"""

import argparse
import base64
from collections import Counter, defaultdict
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from development import gate1_sandbox as gate
from . import predict
from .path_b_run import MODES


MANIFEST_SHA = "5b432d827f324c073eb7ed14b4df4b5d18f5eb2a90c4d97d358405a800d27346"
PROTOCOL_SHA = "8a9692457cdba6d9b2860717b8bc254dae47dc48eebe7baacabb17a82007953e"
HELD_SHA = "6bc97deac805d67528e1939481c75745f51cf7350c0d3ee757598eb55c5dad01"
AGREEMENT_DRAW_SHA = "e15d89ed6808527a91a6dd9188162dad4a280baefe44653fe5a9f5c97b521ced"
HELD_LABEL = "desk_unrateable"
SOURCES = {"pie-validation": "PIE", "pie-train": "PIE", "codenet": "CodeNet",
           "github-performance-fix": "GitHub"}
SIDES = ("target", "reference", "restored", "sham")
DESK_STOPS = {
    "source": """source_derived_oracle_failure source_derived_numeric_oracle_failure
        source_derived_undefined_behavior forced_avx forced_x86_native isa_or_arch_locked
        concurrency_or_cache_layout graphics_driver_or_host_api unsupported_dependencies""",
    "contract": """fixed_contract insufficient_workload_ladder alignment_boundary
        no_common_calibrated_work no_common_restoring_event no_executable_work_delta
        no_matching_work_delta no_isolated_restoration""",
    "route": """missing_pinned_dependency missing_pinned_dependency_and_calibration
        unverified_assertion_configuration unverified_cache_cutoff_alignment unverified_calibrated_cache_work""",
}
CAPS = ("tick_cap", "wall_timeout", "memory_cap", "tasks_cap", "file_cap", "cpu_cap")
ARTIFACTS = ("oracle", "workload", "counter_calibration", "intervention")


def digest(raw):
    return sha256(raw).hexdigest()


def require(valid, message):
    if not valid:
        raise ValueError(message)


def is_pin(value):
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) is not None


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def json_pin(value):
    return digest(dump(value).encode())


def rank(row):
    return digest(dump(["eapg-expansion-v1", row["corpus"], row["cluster_id"], row["id"]]).encode()), row["id"]


def decode(value):
    return base64.b64decode(value, validate=True)


def artifact(record):
    raw = decode(record["base64"])
    require(raw and digest(raw) == record["sha256"], "missing or mismatched evidence artifact")
    return raw


def validate_fixture(row, fixture):
    require(fixture.get("evidence", {}).keys() == set(ARTIFACTS),
            "missing independent oracle, workload, counter or intervention evidence")
    proofs = {name: json.loads(artifact(record)) for name, record in fixture["evidence"].items()}
    for side in ("slow", "fast"):
        original = fixture["originals"][side]
        files = {entry["path"]: entry["sha256"] for entry in row[side]["files"]}
        require(files.get(original["path"]) == digest(decode(original["source"])),
                "fixture original does not match frozen source")
    require(set(fixture["variants"]) == set(SIDES), "requires target/reference/restored/sham")
    for variant in fixture["variants"].values():
        require(all(0 < len(decode(variant[mode])) <= gate.FILE_CAP for mode in ("plain", "counted")),
                "fixture source is empty or too large")
    streams = defaultdict(list)
    for sample in fixture["samples"]:
        size = sample["size"]
        require(type(size) is int and 0 < size <= gate.MAX_SCALE, "invalid sample size")
        require(type(sample["stream"]) is str and sample["stream"], "invalid stream name")
        require(type(sample["input"]) is str and type(sample["expected"]) is str,
                "missing sample input or independent oracle output")
        require(len(sample["input"].encode()) <= gate.FILE_CAP and
                len(sample["expected"].encode()) <= gate.FILE_CAP, "sample exceeds file limit")
        streams[sample["stream"]].append(size)
    require(len(streams) == 3, "requires three registered streams")
    for sizes in streams.values():
        sizes.sort()
        require(len(sizes) == 6 and len(set(sizes)) == 6, "requires six sizes per stream")
        require(all(a * sizes[1] == b * sizes[0] for a, b in zip(sizes, sizes[1:])),
                "sizes must be geometric")
    bindings = {
        "oracle": [sample["expected"] for sample in fixture["samples"]],
        "workload": [[sample["stream"], sample["size"], sample["input"]] for sample in fixture["samples"]],
        "counter_calibration": {side: variant["counted"] for side, variant in fixture["variants"].items()},
        "intervention": fixture["variants"],
    }
    for name, value in bindings.items():
        proof = proofs[name]
        require(proof.get("binding_sha256") == json_pin(value) and isinstance(proof.get("rationale"), str)
                and proof["rationale"].strip(), f"{name} evidence does not bind to the fixture")


def held_scope(bundle, entries, required, amendment_pin, held_pin):
    if amendment_pin is None:
        require("scope_exception" not in bundle, "missing approved S1 amendment SHA-256")
        return {}
    scope = bundle["scope_exception"]
    require(scope["amendment"]["sha256"] == amendment_pin, "wrong S1 amendment SHA-256")
    artifact(scope["amendment"])
    require(scope["held"]["sha256"] == held_pin, "wrong S1 held-list SHA-256")
    holds = json.loads(artifact(scope["held"]))
    decisions = {}
    for hold in holds:
        key = f'{hold["corpus"]}:{hold["pair_id"]}'
        require(key in required and key not in decisions, "invalid or duplicate S1 held pair")
        row = entries[key]
        require(hold["reason"] == ("no_independent_repository_spec" if row["frame"] == "Repository"
                                   else "unbundled_statement_images"),
                "S1 held list does not match frozen cohort or allowed hold reasons")
        decisions[key] = {"status": HELD_LABEL, "reason": hold["reason"]}
    return decisions


def load_inputs(stream, bundle_pin, *, manifest_pin=MANIFEST_SHA, amendment_pin=None, held_pin=HELD_SHA):
    manifest_raw, bundle_raw = stream.readline(), stream.readline()
    require(digest(manifest_raw) == manifest_pin, "wrong frozen manifest SHA-256")
    manifest = json.loads(manifest_raw)
    require(manifest["protocol_sha256"] == PROTOCOL_SHA and manifest["status"] == "scrape_frozen"
            and manifest["held_out_used"] is False, "manifest is not frozen under this protocol")
    require(bundle_raw.strip(), "missing adjudicated S1 labels and case fixtures")
    require(digest(bundle_raw) == bundle_pin, "wrong adjudicated S1/fixture bundle SHA-256")
    bundle = json.loads(bundle_raw)
    require(bundle.get("schema") == "eapg.expansion.inputs.v1" and
            bundle.get("manifest_sha256") == manifest_pin, "S1/fixture bundle is not bound to this manifest")
    rows = sorted(manifest["pairs"], key=rank)
    entries = {f'{row["corpus"]}:{row["id"]}': row for row in rows}
    require(len(entries) == len(rows), "duplicate frozen pair identifiers")
    required = {key for key, row in entries.items() if not row.get("intake_stop")}
    holds = held_scope(bundle, entries, required, amendment_pin, held_pin)
    desk = bundle.get("desk")
    require(isinstance(desk, dict) and desk.keys() == required - holds.keys(), "incomplete S1 coverage")
    evidence = bundle.get("desk_evidence", {})
    require(all(is_pin(evidence.get(key)) for key in ("packet_sha256", "rater_a_sha256", "rater_b_sha256"))
            and evidence["rater_a_sha256"] != evidence["rater_b_sha256"], "missing blind S1 evidence pins")
    if amendment_pin is None:
        require(is_pin(evidence.get("adjudication_sha256")), "missing blind S1 adjudication pin")
    else:
        require(evidence.get("agreement_draw_sha256") == AGREEMENT_DRAW_SHA,
                "missing fixed S1 agreement-draw pin")
    passes = set()
    for key, judgment in desk.items():
        require(isinstance(judgment.get("evidence"), str) and judgment["evidence"].strip(),
                f"{key}: missing S1 rationale")
        if judgment.get("status") == "pass":
            require(judgment.get("reason") is None and judgment.get("bucket") is None,
                    "S1 pass carries a stop reason or bucket")
            passes.add(key)
        else:
            require(judgment.get("status") in ("desk_excluded", "desk_blocked") and
                    judgment.get("reason") in DESK_STOPS.get(judgment.get("bucket"), "").split(),
                    f"{key}: invalid S1 stop")
    fixtures = bundle.get("fixtures")
    require(isinstance(fixtures, dict) and fixtures.keys() == passes,
            "need exactly one pinned fixture for each S1 pass")
    for key, fixture in fixtures.items():
        validate_fixture(entries[key], fixture)
    desk = {**desk, **holds}
    header = {
        "schema": "eapg.expansion.checkpoint.v1", "manifest_sha256": manifest_pin,
        "protocol_sha256": PROTOCOL_SHA, "bundle_sha256": bundle_pin, "compiler": "15.2.0",
        "runner_sha256": digest(Path(__file__).read_bytes()),
        "gate1_sha256": digest(Path(gate.__file__).read_bytes()),
        "fit_sha256": digest(Path(predict.__file__).read_bytes()),
        "amendment_sha256": amendment_pin, "held_list_sha256": held_pin if holds else None,
        "s1_design": "amendment_1" if amendment_pin else "adjudicated",
        "modes": list(MODES), "node_filter_applied": False,
    }
    return header, entries, desk, fixtures


def normalized(raw):
    return digest(b" ".join(raw.split()))


def observation(result, expected=None, size=None, *, sanitizer=False):
    stats = {key: int(value) for key, value in result.events.items()}
    rc = result.returncode
    caps = set()
    if result.timed_out:
        caps.add("wall_timeout")
    if stats.get("memory.events.oom_kill", 0):
        caps.add("memory_cap")
    if stats.get("pids.events.max", 0):
        caps.add("tasks_cap")
    if rc in (-25, 153):
        caps.add("file_cap")
    if rc in (-24, 152):
        caps.add("cpu_cap")
    counts = None
    if size is not None and len(result.counter_wire) <= gate.COUNTER_CAP:
        words = result.counter_wire.split()
        if len(words) == 2 and all(word.isdigit() and len(word) <= 20 for word in words):
            counts = list(map(int, words))
    ceiling = max(2_000_000, 5 * size**2) if size is not None else None
    if rc == 85 and counts is not None and sum(counts) >= ceiling:
        caps.add("tick_cap")
    out = normalized(result.stdout)
    dependency_missing = expected is None and bool(re.search(
        rb"fatal error: [^\n]+: No such file or directory", result.stderr
    ))
    if caps:
        status = "capped"
    elif (sanitizer and rc and b"runtime error:" in result.stderr) or (
        expected is not None and not rc and out != expected
    ):
        status = "invalid_output"
    elif rc or (expected is not None and result.stderr):
        status = "process_failure"
    elif size is not None and (counts is None or sum(counts) >= ceiling):
        status = "invalid_counter"
    else:
        status = "complete"
    return {"status": status, "exit": rc, "timed_out": result.timed_out, "caps": sorted(caps),
            "events": stats, "counter": counts, "counter_sha256": digest(result.counter_wire),
            "dependency_missing": dependency_missing,
            "normalized_stdout_sha256": out, "stdout_sha256": digest(result.stdout),
            "stderr_sha256": digest(result.stderr)}


def stage(fn, *args, **kwargs):
    failures = []
    for _ in range(3):
        try:
            return fn(*args, **kwargs), failures
        except gate.SandboxStageFailure as error:
            return error.result, failures
        except (RuntimeError, OSError, subprocess.SubprocessError) as error:
            failures.append(str(error))
    return None, failures


def event(receipt, name, fn, *args, expected=None, size=None, sanitizer=False, **kwargs):
    result, failures = stage(fn, *args, **kwargs)
    if result is None:
        receipt.append({"step": name, "status": "infrastructure_failure", "attempt_errors": failures,
                        "caps": ["file_cap"] if any(
                            error == "Sandbox output exceeded the per-file limit" for error in failures
                        ) else []})
        return None
    receipt.append({"step": name, "attempt_errors": failures,
                    **observation(result, expected, size, sanitizer=sanitizer)})
    if expected is not None:
        receipt[-1]["expected_stdout_sha256"] = expected
    return result


def measure(fixture, raw):
    for side in ("slow", "fast"):
        pinned = decode(fixture["originals"][side]["source"])
        result = event(raw, ["preprocess", side], gate.invoke,
                       ["g++", "-std=c++17", "-E", "-x", "c++", "-", "-o", "/dev/null"], data=pinned)
        if result is None or raw[-1]["status"] != "complete":
            return
    binaries = {}
    for side in SIDES:
        for mode, flags in MODES.items():
            counted = mode.startswith("O")
            source = decode(fixture["variants"][side]["counted" if counted else "plain"])
            command = ["/bin/sh", "-ec",
                       'g++ -std=c++17 -O2 "$@" -x c++ - -o /tmp/program; exec cat /tmp/program',
                       "expansion-compile", *flags]
            result = event(raw, ["compile", side, mode], gate.invoke, command, data=source, timeout=25)
            if result is None or raw[-1]["status"] != "complete":
                return
            if not result.stdout.startswith(b"\x7fELF"):
                raw[-1]["status"] = "process_failure"
                return
            binaries[side, mode] = result.stdout
    for index, sample in enumerate(fixture["samples"]):
        expected = normalized(sample["expected"].encode())
        for (side, mode), binary in binaries.items():
            scale = sample["size"] if mode.startswith("O") else None
            result = event(raw, ["execute", index, side, mode], gate.execute, binary, sample["input"].encode(),
                           counter_scale=scale, expected=expected, size=scale, sanitizer=mode == "ubsan")
            if result is None or raw[-1]["status"] == "invalid_output":
                return


def disposition(raw, fixture):
    if any(event["status"] == "infrastructure_failure" for event in raw):
        return "execution_infrastructure_failure", {}
    prep = [e for e in raw if e["step"][0] == "preprocess"]
    if any(e["status"] == "process_failure" and e.get("dependency_missing") for e in prep):
        return "support_boundary_closed", {}
    if len(prep) != 2 or any(e["status"] != "complete" for e in prep):
        return None, {}
    grid = [e for e in raw if e["step"][0] == "execute"]
    if any(e["status"] == "invalid_output" for e in grid):
        return "execution_oracle_failure", {}
    if len(grid) != len(fixture["samples"]) * len(SIDES) * len(MODES) or any(
            e["status"] not in ("complete", "capped") for e in grid):
        return None, {}
    metrics = {tuple(e["step"][1:]): e for e in grid}
    streams = {sample["stream"]: [] for sample in fixture["samples"]}
    for index, sample in enumerate(fixture["samples"]):
        counts = {}
        for side in SIDES:
            points = [metrics[index, side, mode] for mode in MODES]
            uncapped = [point["counter"] for point in points[2:] if point["status"] == "complete"]
            if uncapped and any(count != uncapped[0] for count in uncapped):
                return None, {}
            if all(point["status"] == "complete" for point in points):
                counts[side] = uncapped[0]
        if "target" in counts and "sham" in counts and counts["target"] != counts["sham"]:
            return None, {}
        if len(counts) != len(SIDES):
            continue
        streams[sample["stream"]].append((sample["size"], *(counts[side][0] for side in SIDES[:3])))
    required_modes = {(side, mode) for side in SIDES for mode in MODES}
    if {tuple(e["step"][2:]) for e in grid if e["status"] == "complete"} != required_modes:
        return None, {}
    fits, restoration = {}, {}
    for name, points in streams.items():
        points.sort()
        fits[name] = predict.calculate_fit([point[:3] for point in points]) if all(
            min(point[1:3]) > 0 for point in points
        ) else None
        restoration[name] = [
            {"size": size, "excess": target - reference, "recovered": target - restored,
             "passes": 5 * (target - restored) >= 4 * (target - reference)}
            for size, target, reference, restored in points[-2:] if target > reference
        ]
    fit_details = {"fits": fits, "restoration": restoration}
    if not all(fits.values()):
        return "insufficient_fit", fit_details
    alert = all(fit["slope"] >= 0.50 and fit["largest_ratio"] >= 1.50 for fit in fits.values())
    return "alert" if alert else "no_alert", fit_details


def checkpoint(key, row, desk, fixtures, raw):
    judgment = desk.get(key)
    if key in fixtures:
        label, details = disposition(raw, fixtures[key])
    else:
        require(not raw, "execution record for a desk or intake stop")
        label, details = row.get("intake_stop") or judgment["status"], {}
    return {"id": key, "source": SOURCES[row["corpus"]], "cluster": row["cluster_id"],
            "quarantined": row["quarantined"], "desk": judgment, "terminal": label,
            "measurements": raw, **details}


def replay(stream, header, entries, desk, fixtures):
    require(json.loads(stream.readline()) == header, "checkpoint does not match inputs or runner")
    saved = []
    keys = iter(entries)
    for line in stream:
        require(line.endswith("\n"), "truncated checkpoint record")
        row = json.loads(line)
        key = next(keys, None)
        require(key is not None, "extra checkpoint records")
        if key in fixtures:
            validate_trace(row["measurements"], fixtures[key])
        require(row == checkpoint(key, entries[key], desk, fixtures, row["measurements"]),
                "checkpoint order or measurements disagree")
        saved.append(row)
        if row["terminal"] is None:
            require(not stream.readline(), "checkpoint continued after unresolved disposition")
            break
    return saved


def validate_trace(raw, fixture):
    expected = [(["preprocess", side], None) for side in ("slow", "fast")]
    expected.extend((["compile", side, mode], None) for side in SIDES for mode in MODES)
    expected.extend((["execute", index, side, mode], normalized(sample["expected"].encode()))
                    for index, sample in enumerate(fixture["samples"])
                    for side in SIDES for mode in MODES)
    require(raw and len(raw) <= len(expected), "invalid measurement length")
    for i, (event, (step, oracle)) in enumerate(zip(raw, expected)):
        require(event["step"] == step and event.get("status") in (
            "complete", "capped", "process_failure", "invalid_output", "invalid_counter", "infrastructure_failure",
        ) and set(event["caps"]) <= set(CAPS), "invalid measurement order or status")
        if event["status"] == "infrastructure_failure":
            require(len(event["attempt_errors"]) == 3, "missing infrastructure retry evidence")
        elif oracle is not None:
            require(event.get("expected_stdout_sha256") == oracle, "wrong oracle pin in checkpoint")
            if event["status"] == "complete":
                require(event["normalized_stdout_sha256"] == oracle, "successful output differs from oracle")
        stops = event["status"] in ("infrastructure_failure", "invalid_output") or (
            step[0] != "execute" and event["status"] != "complete")
        require(not stops or i == len(raw) - 1, "checkpoint measures after a failed prerequisite")
    require(len(raw) == len(expected) or stops, "measurement prefix stopped before a terminal event")


def summarize(entries, saved):
    result = {source: Counter({"drawn": 0, "processed": 0, "compile_attempted": 0, "compiled": 0,
                              "run_attempted": 0, "executed": 0, "fitted": 0,
                              "node_filter_excluded": 0, "not_desk_rateable": 0,
                              **dict.fromkeys((*CAPS, *(f"{stage}_{cap}" for stage in (
                                  "preprocess", "compile", "execute") for cap in CAPS)), 0)})
              for source in set(SOURCES.values())}
    for row in entries.values():
        result[SOURCES[row["corpus"]]]["drawn"] += 1
    for row in saved:
        counts = result[row["source"]]
        counts["processed"] += 1
        counts["not_desk_rateable"] += row["terminal"] == HELD_LABEL
        raw = row["measurements"]
        stages = {e["step"][0] for e in raw}
        counts["compile_attempted"] += "compile" in stages
        counts["compiled"] += sum(e["step"][0] == "compile" and e["status"] == "complete"
                                  for e in raw) == len(SIDES) * len(MODES)
        counts["run_attempted"] += "execute" in stages
        counts["executed"] += row["terminal"] in ("execution_oracle_failure", "insufficient_fit", "alert", "no_alert")
        counts["fitted"] += row["terminal"] in ("alert", "no_alert")
        for claim, events in (("all", raw), ("compile", [e for e in raw if e["step"][0] == "compile"]),
                              ("execute", [e for e in raw if e["step"][0] == "execute"]),
                              ("preprocess", [e for e in raw if e["step"][0] == "preprocess"])):
            for cap in {cap for e in events for cap in e["caps"]}:
                counts[cap if claim == "all" else f"{claim}_{cap}"] += 1
    return {"node_filter_applied": False, "by_source": result,
            "complete": len(entries) == len(saved) and all(row["terminal"] for row in saved)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, epilog=(
        "stdin: frozen manifest line, adjudicated S1/fixture bundle line, then an optional checkpoint "
        "for --resume. See the pinned input schema in load_inputs. stdout: JSONL checkpoints. "
        "--check replays a saved checkpoint and emits operational counts, not P1–P3."
    ))
    parser.add_argument("--bundle-sha256", required=True)
    parser.add_argument("--amendment-sha256", help="approved dated amendment pin for the exact S1 held list")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--check", type=Path)
    actions.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    try:
        header, entries, desk, fixtures = load_inputs(
            sys.stdin.buffer, args.bundle_sha256, amendment_pin=args.amendment_sha256
        )
        if args.check:
            with args.check.open(encoding="utf-8") as stream:
                print(dump(summarize(entries, replay(stream, header, entries, desk, fixtures))))
            return
        saved = replay((line.decode() for line in sys.stdin.buffer), header, entries, desk, fixtures) if args.resume else []
        require(not saved or saved[-1]["terminal"] is not None, "unresolved disposition; review checkpoint before resuming")
        require(os.environ.get("container") == "docker" and Path("/.dockerenv").is_file(),
                "run only in the pinned Gate 1 container")
        compiler = gate.checked_output(gate.invoke(["g++", "-dumpfullversion"])).decode().strip()
        require(compiler == header["compiler"], "requires pinned GCC 15.2.0")
        print(dump(header), flush=True)
        for row in saved:
            print(dump(row), flush=True)
        for key, entry in list(entries.items())[len(saved):]:
            raw = []
            if key in fixtures:
                measure(fixtures[key], raw)
            row = checkpoint(key, entry, desk, fixtures, raw)
            print(dump(row), flush=True)
            require(row["terminal"] is not None, "failure has no frozen terminal label; see raw checkpoint")
    except (KeyError, TypeError, AttributeError, ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        parser.exit(2, f"expansion runner: {error}\n")


if __name__ == "__main__":
    main()
