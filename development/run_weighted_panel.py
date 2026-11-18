"""Seal and run the fixed library work-proxy calibration on authored code."""

import argparse
from collections import defaultdict
from hashlib import sha256
import json
from math import isqrt, log
from pathlib import Path
from statistics import correlation, linear_regression
import sys

from gate1_sandbox import execute
from run_phase2_development import (
    ProfileFailure, SANITIZER_FLAGS, compile_stage, historical, load_pipeline, normalize,
    provenance, run_profile, verify_oracle,
)
from weighted_panel_sources import SOURCES


HERE = Path(__file__).resolve().parent
OPTIMIZATIONS = ("-O2", "-O0", "-O3")
SIZES = (16, 32, 64, 128, 256, 512)
PANEL = (
    ("find", "first", lambda n: 0), ("find", "sqrt", lambda n: isqrt(n) - 1),
    ("find", "midpoint", lambda n: n // 2), ("find", "last", lambda n: n - 1),
    ("find", "absent", lambda n: n), ("count", "present", lambda n: n // 2),
    ("count", "absent", lambda n: n), ("reverse", "full", lambda n: 0),
)
GAP = 0.70


def digest(value):
    return sha256(value).hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2, allow_nan=False) + "\n").encode()


def design(pipeline):
    cells = []
    for op, workload, position in PANEL:
        inputs = []
        for n in SIZES:
            p = position(n)
            if op == "find":
                checksum, operations = n * p, n * min(p + 1, n)
            elif op == "count":
                checksum, operations = n * int(p < n), n * n
            else:
                checksum, operations = (n - 1) * ((n + 1) // 2), n * (n // 2)
            inputs.append({"n": n, "p": p, "stdin": f"{n} {p}\n", "checksum": checksum,
                           "expected_operations": operations})
        cells.append({"operation": op, "workload": workload, "inputs": inputs})
    return {"schema": "eapg-weighted-panel-lock-v1", "optimizations": list(OPTIMIZATIONS),
            "site_gap_threshold": GAP, "cells": cells, "provenance": provenance(pipeline),
            "study_files_sha256": {name: digest((HERE / name).read_bytes()) for name in
                                   ("WEIGHTED_PANEL_PROTOCOL.md", "run_weighted_panel.py", "weighted_panel_sources.py")},
            "source_sha256": {op: {"plain": digest(plain.encode()), "counted": digest(counted.encode())}
                              for op, (plain, counted) in SOURCES.items()}}


def collect(pipeline, cells, optimization):
    op = cells[0]["operation"]
    plain, counted = SOURCES[op]

    def unavailable(failure):
        workloads = {cell["workload"]: {"status": "INCOMPLETE", "rows": [
            {"n": case["n"], "p": case["p"], "stages": {"preparation": {"status": failure["status"]}}}
            for case in cell["inputs"]
        ]} for cell in cells}
        return {"failure": failure}, workloads

    try:
        normalized, aliases = normalize(pipeline, plain)
    except ProfileFailure as error:
        return unavailable(error.details)
    nodes = pipeline.extract_macro_nodes(normalized, aliases)
    targets = [n["id"] for n in nodes if f"std::{op}(" in n["source_preview"]
               and "data.size()" in n["weight_expr"]]
    if len(targets) != 1:
        return unavailable({"status": "UNRESOLVED_SITE", "candidate_ids": targets})
    target, = targets
    stage_inputs = {
        "original": (plain, (optimization,)), "counted": (counted, (optimization,)),
        "instrumented": (historical.instrument(pipeline, normalized, nodes), (optimization,)),
    }
    if optimization == "-O2":
        stage_inputs["sanitizer"] = (plain, (optimization, *SANITIZER_FLAGS))
    binaries, failures = {}, {}
    for stage, (source, flags) in stage_inputs.items():
        try:
            binaries[stage] = compile_stage(stage + " build", source, *flags)
        except ProfileFailure as error:
            failures[stage] = error.details

    collected, complete = defaultdict(list), defaultdict(list)
    for cell in cells:
        workload = cell["workload"]
        for case in cell["inputs"]:
            n = case["n"]
            data = case["stdin"].encode()
            row = {"n": n, "p": case["p"], "stages": {}}
            profiled_nodes = None
            for stage in stage_inputs:
                if stage in failures:
                    row["stages"][stage] = {"status": "BUILD_FAILURE"}
                    continue
                current = dict(case, seed=workload, expected_stdout=str(case["checksum"]))
                if stage == "counted":
                    current["expected_stdout"] += f" {case['expected_operations']}"
                counter = None
                try:
                    if stage == "instrumented":
                        result, counter = run_profile(pipeline, binaries[stage], data, n, nodes)
                        if counter["status"] != "CLEAN_COMPLETION":
                            row["stages"][stage] = {"status": counter["status"], "total_ticks": counter["total_ticks"]}
                            continue
                    else:
                        result = execute(binaries[stage], data)
                    verify_oracle(result, current, stage)
                except ProfileFailure as error:
                    row["stages"][stage] = error.details
                    continue
                row["stages"][stage] = {"status": "CLEAN_COMPLETION", "stdout": result.stdout.decode()}
                if stage == "counted":
                    row["operations"] = int(result.stdout.split()[1])
                if counter is not None:
                    profiled_nodes = counter["nodes"]
                    row["hits"], row["work"] = (profiled_nodes[target][key] for key in ("cnt", "work"))
                    row["total_ticks"] = counter["total_ticks"]
                    row["node_counters"] = profiled_nodes
            collected[workload].append(row)
            if all(s["status"] == "CLEAN_COMPLETION" for s in row["stages"].values()):
                complete[workload].append(profiled_nodes)
    identity = {"normalized_sha256": digest(normalized.encode()), "target_node_id": target,
                "canonical_node_ids": [n["id"] for n in nodes], "build_failures": failures}
    results = {name: summarize(pipeline, nodes, target, rows, complete[name]) for name, rows in collected.items()}
    return identity, results


def summarize(pipeline, nodes, target, rows, counters):
    result = {"rows": rows}
    if len(counters) != len(SIZES) or any(
        row["hits"] <= 0 or row["work"] <= 0 or row["operations"] <= 0 for row in rows
    ):
        return dict(result, status="INCOMPLETE")
    log_sizes = [log(n) for n in SIZES]
    log_counts = {channel: [log(r[channel]) for r in rows] for channel in ("hits", "work", "operations")}
    fits = {channel: linear_regression(log_sizes, values).slope for channel, values in log_counts.items()}
    result["slopes"] = {channel: {"alpha": fits[channel],
                                 "r_squared": correlation(log_sizes, values)**2 if len(set(values)) > 1 else 1.0}
                        for channel, values in log_counts.items()}
    result["signed_slope_error"] = {channel: fits[channel] - fits["operations"]
                                    for channel in ("hits", "work")}
    result["absolute_error_gain"] = (abs(result["signed_slope_error"]["hits"])
                                    - abs(result["signed_slope_error"]["work"]))
    result["oracle_gap_qualifies"] = fits["operations"] - fits["hits"] >= GAP
    result["proxy_gap_qualifies"] = fits["work"] - fits["hits"] >= GAP
    result["work_per_operation"] = [r["work"] / r["operations"] for r in rows]
    result["hits_per_operation"] = [r["hits"] / r["operations"] for r in rows]
    result["hit_count_matches_calls"] = all(r["hits"] == r["n"] for r in rows)
    full_fits = {
        node["id"]: {channel: pipeline.fit_dual_family_scaling(SIZES, [r[node["id"]][key] for r in counters])
                     for channel, key in (("fit_hits", "cnt"), ("fit_work", "work"))} for node in nodes
    }
    hit_fits = {nid: dict(fit, fit_work=fit["fit_hits"]) for nid, fit in full_fits.items()}
    result["selectors"] = {}
    for channel, fit in (("work", full_fits), ("hits", hit_fits)):
        tiers = pipeline.evaluate_four_slicing_tiers(nodes, fit)
        result["selectors"][channel] = {"symptom": tiers["primary_symptom"],
                                          "target_qualifier": tiers["work_qualifiers"].get(target)}
    return dict(result, status="COMPLETE")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--pipeline", type=Path, required=True)
    mode = cli.add_mutually_exclusive_group(required=True)
    mode.add_argument("--seal", action="store_true")
    mode.add_argument("--lock", type=Path)
    cli.add_argument("--lock-sha256")
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    if sys.platform != "linux" or args.output.exists() or bool(args.lock) != bool(args.lock_sha256):
        cli.error("Use Linux, a fresh output path and an independent lock digest when running")
    pipeline = load_pipeline(args.pipeline)
    sealed = encoded(design(pipeline))
    if args.seal:
        output = sealed
    else:
        supplied = args.lock.read_bytes()
        if digest(supplied) != args.lock_sha256 or supplied != sealed:
            raise ValueError("Study lock, inputs, code or execution environment differ")
        by_level = {}
        lock = json.loads(supplied)
        for optimization in OPTIMIZATIONS:
            by_level[optimization] = {}
            for op in SOURCES:
                identity, results = collect(pipeline, [cell for cell in lock["cells"] if cell["operation"] == op],
                                            optimization)
                by_level[optimization][op] = {"site": identity, "workloads": results}
                print(f"{optimization} {op}: {sum(v['status'] == 'COMPLETE' for v in results.values())} complete workloads",
                      flush=True)
        output = encoded({"schema": "eapg-weighted-panel-results-v1", "lock_sha256": args.lock_sha256,
                          "builds": by_level})
    with args.output.open("xb") as stream:
        stream.write(output)
    print(f"{digest(output)}  {args.output}")


if __name__ == "__main__":
    main()
