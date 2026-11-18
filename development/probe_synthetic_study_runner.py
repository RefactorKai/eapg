"""Exercise the three separate study CLIs on an authored roster in Ubuntu WSL."""

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

from probe_comparator_swap import COUNTING_BUILD, SAME_ORDER
from probe_synthetic_intervention import AFTER, BEFORE, FAST, HIGH_GROWTH, triangular
from score_synthetic import EXPECTED, SEEDS, require
from synthetic_frame import canonical, commitment
from test_synthetic_study_custodian import fixture


HERE = Path(__file__).resolve().parent
PROTOCOL = b"Authored development fixture for the integrated synthetic runner\n"
CURSOR_SHAM = "cursor = i - (1);"
AT_SITE_ORIGINAL = FAST.replace("cursor = i - 1;\n        while (cursor < i) {\n            ++cursor;",
                                "for (int j = 0; j < 1; ++j) {\n            cursor = i;")


def edited_program(slot):
    if slot == "positive_at_site":
        return AT_SITE_ORIGINAL, "j < 1", "j < n", 1, 2, "strong"
    if slot == "same_growth_sham":
        return FAST, BEFORE, CURSOR_SHAM, 1, 1, "same"
    if slot == "comparator_swap_sham":
        return FAST.replace(BEFORE, SAME_ORDER), SAME_ORDER, AFTER, 2, 2, "same"
    return FAST, BEFORE, AFTER, 1, 2, "strong"


def counted_for(source):
    """Count outer/inner tests, increments, and scalar updates for for-loop fixtures."""
    if "++total;" in source:
        fixed, total = 5, "volatile long long total = 0;"
        body = "++total;"
        output = r'std::printf("%lld\n", static_cast<long long>(total));'
        outer = "for (int i = 0; i < n; ++i)"
        counted_outer = "for (int i = 0; ++work, i < n; ++work, ++i)"
        inner = "for (int j = 0; j < n; ++j)"
        counted_inner = "for (int j = 0, counted_init = (++work, 0); ++work, j < n; ++work, ++j)"
    else:
        fixed, total = 6, "long long total = 0;"
        body = "cursor = i;"
        output = r'std::printf("%lld\n", total);'
        outer = "for (int i = 1; i <= n; ++i)"
        counted_outer = "for (int i = 1; ++work, i <= n; ++work, ++i)"
        bound = "n" if "j < n" in source else "1"
        inner = f"for (int j = 0; j < {bound}; ++j)"
        counted_inner = f"for (int j = 0, counted_init = (++work, 0); ++work, j < {bound}; ++work, ++j)"
    replacements = ((total, total + f"\n    long long work = {fixed};"), (outer, counted_outer), (inner, counted_inner),
                    (body, f"++work; {body}"),
                    (output, r'++work; std::printf("%lld\n\nEAPG-OPERATIONS-v1 %lld\n", static_cast<long long>(total), work);'))
    for before, after in replacements:
        require(source.count(before) == 1, f"Authored counting build has an ambiguous anchor: {before}")
        source = source.replace(before, after)
    return source.replace("total += cursor;", "++work; total += cursor;")


def registration(family, slot, plan):
    if slot == "appropriate_superlinear":
        original = edited = HIGH_GROWTH
        edit, before, after, band = None, 2, 2, "appropriate"
        counted = counted_for(original)
        counted_edited = counted
    else:
        original, removed, inserted, before, after, band = edited_program(slot)
        require(original.count(removed) == 1, "Authored edit has an ambiguous anchor")
        start = original.encode("utf-8").index(removed.encode("utf-8"))
        edited = original.replace(removed, inserted)
        edit = {"start_byte": start, "removed": removed, "inserted": inserted}
        if slot == "positive_off_site":
            statement = b"while (cursor < i)"
            offset = edited.encode("utf-8").index(statement)
            plan["intended_statement_span"] = [offset, offset + len(statement)]
        if slot == "positive_at_site":
            counted, counted_edited = counted_for(original), counted_for(edited)
        else:
            template = COUNTING_BUILD.replace(r'"%lld %lld\n"', r'"%lld\n\nEAPG-OPERATIONS-v1 %lld\n"')
            counted = template.replace("RESET_STATEMENT", removed)
            counted_edited = template.replace("RESET_STATEMENT", inserted)
    return {"sources": {"original": original, "edited": edited, "restored": original},
            "counting_sources": {"original": counted, "edited": counted_edited, "restored": counted},
            "growth": {"original_order": [before, 0], "edited_order": [after, 0], "band": band},
            "edit": edit, "equivalent_edited_intervals": [],
            "operation_inventory_sha256": commitment(["authored operation inventory", slot])}


def grid(family, slot, registration):
    rows = []
    for seed in SEEDS:
        for j in range(6):
            n = family["workload"]["n0"] << j
            value = triangular(n)
            if slot == "appropriate_superlinear":
                value = n * n
                original = edited = 7 + 4 * n + 3 * n * n
            elif slot == "positive_at_site":
                original, edited = 8 + 8 * n, 8 + 5 * n + 3 * n * n
            else:
                a = triangular(n) - n if slot == "comparator_swap_sham" else n
                b = n if slot == "same_growth_sham" else triangular(n)
                original, edited = 8 + 5 * n + 2 * a, 8 + 5 * n + 2 * b
            rows.append({"seed": seed, "n": n, "stdin": f"{n}\n", "expected_stdout": f"{value}\n",
                         "expected_counts": {"original": original, "edited": edited, "restored": original}})
    return rows


def command(script, *args, cwd):
    result = subprocess.run([sys.executable, "-B", str(HERE / script), *map(str, args)],
                            cwd=cwd, capture_output=True, text=True, timeout=360)
    if result.returncode:
        raise RuntimeError(f"{script} stopped with status {result.returncode}\n{result.stderr}")
    return result.stdout


def pinned_arg(name, path):
    return [f"--{name}", path, f"--{name}-sha256", sha256(path.read_bytes()).hexdigest()]


def run(pipeline, pipeline_sha, root):
    root.mkdir()
    inputs, eligible = fixture(sha256(PROTOCOL).hexdigest(), eligible_registration=registration, eligible_grid=grid)
    private, operator = root / "custodian", root / "operator"
    private.mkdir(mode=0o700)
    operator.mkdir()
    protocol = private / "protocol.md"
    protocol.write_bytes(PROTOCOL)
    custodian_args = pinned_arg("protocol", protocol)
    names = ("frame", "inputs", "draw", "provenance", "quarantine", "sources")
    for name, value in zip(names, inputs[1:], strict=True):
        path = private / f"{name}.json"
        path.write_bytes(canonical(value))
        custodian_args.extend(pinned_arg(name, path))
    candidate = ["--pipeline", pipeline, "--pipeline-sha256", pipeline_sha]
    custodian = "synthetic_study_custodian.py"
    predictor = "synthetic_study_predict.py"
    scorer = "synthetic_study_score.py"
    result = private / "study"
    runtime_pin = command(custodian, "--print-runtime", *candidate, cwd=private).strip()
    custodian_pin = command(custodian, "--print-revision", cwd=private).strip()
    prediction_pin = command(predictor, "--print-revision", cwd=operator).strip()
    scorer_pin = command(scorer, "--print-revision", cwd=root).strip()
    baseline_pin = sha256((HERE / "backward_slice.py").read_bytes()).hexdigest()
    command(custodian, *custodian_args, *candidate, "--runner-sha256", custodian_pin,
            "--runtime-sha256", runtime_pin, "--output", result, cwd=private)
    packet, predictions = operator / "blind.json", operator / "predictions.json"
    packet.write_bytes((result / "blind.json").read_bytes())
    command(predictor, *pinned_arg("packet", packet), *candidate, "--runner-sha256", prediction_pin,
            "--output", predictions, cwd=operator)
    score_path = root / "score.json"
    command(scorer, *pinned_arg("draw", private / "draw.json"), *pinned_arg("labels", result / "labels.json"),
            *pinned_arg("predictions", predictions), "--scorer-sha256", scorer_pin, "--runner-sha256", prediction_pin,
            "--pipeline-sha256", pipeline_sha, "--baseline-sha256", baseline_pin, "--output", score_path, cwd=root)
    score = json.loads(score_path.read_bytes())
    labels = {row["case_id"]: row for row in json.loads((result / "labels.json").read_bytes())["cases"]}
    evidence = json.loads((result / "evidence.json").read_bytes())["cases"]
    predicted = json.loads(predictions.read_bytes())["predictions"]
    require(all(labels[case_id]["disposition"] == EXPECTED[slot] for slot, case_id in eligible.items()),
            "Unexpected fixture dispositions: " + repr({slot: labels[cid]["disposition"] for slot, cid in eligible.items()}))
    require(all(labels[eligible[slot]]["reference_status"] == "resolved"
                for slot in ("positive_off_site", "positive_at_site", "comparator_swap_positive")),
            "Expected each authored positive to resolve to a canonical node")
    outcomes = Counter(row["disposition"] for row in labels.values())
    require(len(labels) == 322 and outcomes["quarantined"] == 316 and len(predicted) == 966, "Incomplete draw coverage")
    require(all(report["primary"]["families"] == report["comparator_swap"]["verified_pairs"] == 1
                for report in score["by_seed"].values()) and not score["primary_sized"],
            "Expected one under-sized authored family and one verified swap")
    builds = sum(len(row["operation"]["builds"]) for row in evidence if row["operation"] is not None)
    oracle_runs = sum(len(row["operation"]["runs"]) for row in evidence if row["operation"] is not None)
    profiles = sum(len(row["trace"].get("runs", [])) for row in evidence if row["trace"] is not None)
    require((builds, oracle_runs, profiles) == (54, 972, 90), "Wrong number of independently verified fixture invocations")
    stages = {f"{row['case_id']}.{stage}.json": canonical(row[field]) for row in evidence
              for stage, field in (("operation", "operation"), ("reference", "reference"), ("profile", "trace"))
              if row[field] is not None}
    require({path.name: path.read_bytes() for path in (result / "stages").iterdir()} == stages,
            "Incomplete or mismatched intermediate custody receipts")
    summary = {"status": "authored_smoke_passed", "labels": len(labels), "predictions": len(predicted),
               "dispositions": dict(outcomes), "verified_swap_pairs_per_seed": 1, "primary_sized": False,
               "oracle_builds": builds, "oracle_runs": oracle_runs, "profile_runs": profiles,
               "stage_receipts": len(stages)}
    print(json.dumps(summary, sort_keys=True))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--pipeline", type=Path, required=True)
    cli.add_argument("--pipeline-sha256", required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    run(args.pipeline.resolve(), args.pipeline_sha256, args.output.resolve())


if __name__ == "__main__":
    main()
