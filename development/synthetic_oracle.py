"""Check custodian-supplied output and whole-workload counts before prediction.

Each source map has original, edited, and restored C++ text. The committed UTF-8
grid supplies seed, n, stdin, expected_stdout, and positive integer expected_counts
for those three variants. A separate counting build appends one decimal record to
its ordinary stdout: ``\nEAPG-OPERATIONS-v1 <count>\n``.

The caller seals the grid, sources, operation inventory, and independent analytic
reviews. This check observes their executable predictions. It never runs a formula
as host code or uses a benchmark profiler to confirm a label.
"""

from base64 import b64encode
from hashlib import sha256
import json
from math import isfinite, log
import re
from statistics import linear_regression
from time import perf_counter_ns

from gate1_sandbox import MAX_SCALE, execute
from run_phase2_development import SANITIZER_FLAGS, ProfileFailure, compile_stage, process_status
from score_synthetic import EXPECTED, SEEDS


SIDES = ("original", "edited", "restored")
COUNT_MARKER = b"\nEAPG-OPERATIONS-v1 "
RESOURCE_STATUSES = {"TIMEOUT_TLE", "MEMORY_LIMIT_MLE", "TASK_LIMIT", "OUTPUT_LIMIT"}
REQUIRED_GRID_FIELDS = {"seed", "n", "stdin", "expected_stdout", "expected_counts"}
FAILURE_PRIORITY = ("resource_failure", "compile_failure", "semantic_failure", "sanitizer_failure",
                    "output_failure", "operation_failure", "growth_failure")


def text_map(values):
    return type(values) is dict and set(values) == set(SIDES) and all(
        type(value) is str and value and utf8(value) for value in values.values()
    )


def utf8(value):
    if type(value) is not str:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def valid_grid(grid):
    if type(grid) is not list or len(grid) != len(SEEDS) * 6:
        return False
    if any(type(row) is not dict or set(row) != REQUIRED_GRID_FIELDS
           or type(row["seed"]) is not int or type(row["n"]) is not int
           or not 0 < row["n"] <= MAX_SCALE or not utf8(row["stdin"]) or not utf8(row["expected_stdout"])
           for row in grid):
        return False
    initial = grid[0]["n"]
    return [(row["seed"], row["n"]) for row in grid] == [
        (seed, initial * 2**index) for seed in SEEDS for index in range(6)
    ]


def valid_analytic_evidence(growth, expected):
    if type(growth) is not dict or set(growth) != {"original_order", "edited_order", "band"}:
        return False
    original, edited, band = (growth[key] for key in ("original_order", "edited_order", "band"))
    if any(type(order) is not list or len(order) != 2 or any(
        type(power) not in (float, int) or not 0 <= power or (type(power) is float and not isfinite(power))
        for power in order
    ) for order in (original, edited)):
        return False
    if expected == "confirmed_positive":
        return edited > original and band in ("strong", "near_below", "near_above")
    if expected == "confirmed_sham":
        return edited == original and band == "same"
    return edited == original and edited > [1, 0] and band == "appropriate"


def execution_evidence(result, stage, row, side, elapsed):
    process = process_status(result)
    evidence = {"seed": row["seed"], "n": row["n"], "side": side, "stage": stage,
                "launcher_elapsed_ns": elapsed, "process_status": process, "returncode": result.returncode,
                "timed_out": result.timed_out, "events": result.events,
                "stdout_b64": b64encode(result.stdout).decode("ascii"),
                "stderr_b64": b64encode(result.stderr).decode("ascii")}
    failure = None
    if stage == "counting":
        evidence.update(expected_count=row["expected_counts"][side], observed_count=None)
    if process in RESOURCE_STATUSES:
        failure = "resource_failure", process
    elif stage == "sanitizer" and (process != "CLEAN_COMPLETION" or b"runtime error:" in result.stderr):
        failure = "sanitizer_failure", "sanitizer_execution"
    elif process != "CLEAN_COMPLETION":
        failure = ("operation_failure" if stage == "counting" else "semantic_failure"), process
    else:
        output = result.stdout
        if stage == "counting":
            output, marker, decimal = output.rpartition(COUNT_MARKER)
            try:
                if not marker or not re.fullmatch(rb"[1-9][0-9]*\n", decimal):
                    raise ValueError("Expected one positive decimal count trailer")
                evidence["observed_count"] = int(decimal)
            except ValueError:
                failure = "operation_failure", "invalid_count_trailer"
        if failure is None:
            if output != row["expected_stdout"].encode("utf-8"):
                failure = "output_failure", "stdout_mismatch"
            elif stage == "counting" and evidence["observed_count"] != evidence["expected_count"]:
                failure = "operation_failure", "count_formula_mismatch"
    evidence["verification_status"] = failure[1] if failure else "passed"
    return evidence, failure


def growth_evidence(rows, counts, band):
    n_values = [row["n"] for row in rows]
    original = [counts[n]["original"] for n in n_values]
    edited = [counts[n]["edited"] for n in n_values]
    changes = [log(after) - log(before) for before, after in zip(original, edited)]
    slope = linear_regression([log(n) for n in n_values], changes).slope
    large_ratio = 2 * edited[-1] >= 3 * original[-1]
    pass_screen = {
        "strong": slope >= 0.70 and large_ratio,
        "near_below": 0.55 <= slope < 0.70 and large_ratio,
        "near_above": 0.70 <= slope <= 0.85 and large_ratio,
        "same": abs(slope) <= 0.10,
        "appropriate": edited == original,
    }[band]
    try:
        ratio = edited[-1] / original[-1]
    except OverflowError:
        ratio = None
    return {"slope": slope, "largest_size_ratio": ratio, "largest_size_counts": [original[-1], edited[-1]],
            "growth_check_passed": pass_screen}


def verify_case(intended_slot, sources, counting_sources, grid, growth):
    """Run the registered oracle checks and return an evidence report for one slot.

    The grid is in seed-major, ascending-size order. Growth orders are compared
    lexically as [polynomial exponent, log exponent]. Launcher failures that make
    the isolation receipt unavailable propagate to the study runner.
    """
    expected = EXPECTED[intended_slot]
    report = {"schema": "eapg-synthetic-operation-evidence-v1", "intended_slot": intended_slot,
              "builds": [], "runs": [], "per_seed": {}, "failures": []}

    def record(disposition, reason, **context):
        report["failures"].append({"disposition": disposition, "reason": reason, **context})

    if not text_map(sources) or sources["original"] != sources["restored"] or (
        (sources["original"] == sources["edited"]) != (expected == "confirmed_appropriate")
    ):
        record("invalid_source", "invalid_original_edited_restored_sources")
    if not text_map(counting_sources):
        record("operation_failure", "invalid_counting_sources")
    if not valid_grid(grid):
        record("invalid_input", "invalid_seed_and_size_grid")
    elif any(type(counts := row["expected_counts"]) is not dict or set(counts) != set(SIDES) or any(
        type(value) is not int or value <= 0 for value in counts.values()
    ) for row in grid):
        record("operation_failure", "invalid_formula_counts")
    if not valid_analytic_evidence(growth, expected):
        record("growth_failure", "invalid_analytic_growth_or_band")
    if report["failures"]:
        report["disposition"] = report["failures"][0]["disposition"]
        return report

    report["source_sha256"] = {side: sha256(sources[side].encode()).hexdigest() for side in SIDES}
    report["counting_source_sha256"] = {side: sha256(counting_sources[side].encode()).hexdigest() for side in SIDES}
    report["grid_sha256"] = sha256(json.dumps(grid, ensure_ascii=False, sort_keys=True,
                                                 separators=(",", ":")).encode()).hexdigest()
    report["growth"] = growth
    observed = {(row["seed"], row["n"]): {} for row in grid}
    for side in SIDES:
        for stage, source, flags in (("plain", sources[side], ()),
                                     ("sanitizer", sources[side], SANITIZER_FLAGS),
                                     ("counting", counting_sources[side], ())):
            try:
                binary = compile_stage(f"{side} {stage} build", source, *flags)
            except ProfileFailure as error:
                report["builds"].append({"side": side, "stage": stage, **error.details})
                status = error.details["status"]
                record("resource_failure" if status in RESOURCE_STATUSES else "compile_failure",
                       status, side=side, stage=stage)
                continue
            report["builds"].append({"side": side, "stage": stage, "status": "CLEAN_COMPLETION",
                                     "executable_sha256": sha256(binary).hexdigest()})
            for row in grid:
                start = perf_counter_ns()
                result = execute(binary, row["stdin"].encode("utf-8"))
                evidence, failure = execution_evidence(result, stage, row, side, perf_counter_ns() - start)
                report["runs"].append(evidence)
                key = row["seed"], row["n"]
                if stage == "counting" and evidence["observed_count"] is not None:
                    observed[key][side] = evidence["observed_count"]
                if failure:
                    record(*failure, side=side, stage=stage, seed=key[0], n=key[1])

    for (seed, n), counts in observed.items():
        if {"original", "restored"} <= counts.keys() and counts["original"] != counts["restored"]:
            record("operation_failure", "restored_count_mismatch", seed=seed, n=n)
        if expected == "confirmed_appropriate" and {"original", "edited"} <= counts.keys():
            if counts["original"] != counts["edited"]:
                record("operation_failure", "unchanged_source_count_mismatch", seed=seed, n=n)
    for seed in SEEDS:
        rows = [row for row in grid if row["seed"] == seed]
        counts = {row["n"]: observed[seed, row["n"]] for row in rows}
        if any(values.keys() != set(SIDES) for values in counts.values()):
            report["per_seed"][str(seed)] = {"growth_check_passed": None, "reason": "incomplete_counts"}
            continue
        outcome = growth_evidence(rows, counts, growth["band"])
        report["per_seed"][str(seed)] = outcome
        if not outcome["growth_check_passed"]:
            record("growth_failure", "registered_growth_criterion_failed", seed=seed)
    failed = {failure["disposition"] for failure in report["failures"]}
    report["disposition"] = next((failure for failure in FAILURE_PRIORITY if failure in failed), expected)
    return report
