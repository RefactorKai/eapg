"""Test whether changing only the reference comparator can reverse a growth label."""

import argparse
from hashlib import sha256
from math import log
from pathlib import Path
from statistics import linear_regression

from gate1_sandbox import execute
from probe_synthetic_comparison import SEEDS, SIZES, digest, encoded
from probe_synthetic_intervention import AFTER, BEFORE, FAST, triangular
from run_phase2_development import (SANITIZER_FLAGS, compile_stage, load_pipeline,
                                    normalize, profile_side, provenance, verify_oracle)
from synthetic_arms import predict_seed


SAME_ORDER = "cursor = 1;"

# Count scalar initialization/updates, condition evaluations, and input/output items.
# Six setup units cover input, both guards, and initialization of cursor, total and i.
COUNTING_BUILD = r'''#include <cstdio>
int main() {
    int n;
    if (std::scanf("%d", &n) != 1 || n < 1) return 1;
    volatile int cursor{};
    long long total = 0, work = 6;
    for (int i = 1; ++work, i <= n; ++work, ++i) {
        ++work;
        RESET_STATEMENT
        while (++work, cursor < i) {
            ++work;
            ++cursor;
        }
        ++work;
        total += cursor;
    }
    ++work;
    std::printf("%lld %lld\n", total, work);
}
'''


def check_counts(variants, grid):
    counts = {}
    for name, (source, reset, increments) in variants.items():
        if source.count(reset) != 1 or source.replace(reset, BEFORE) != FAST:
            raise ValueError(f"{name}: expected one reversible reset edit")
        counting = compile_stage("independent counting build", COUNTING_BUILD.replace("RESET_STATEMENT", reset))
        plain = compile_stage("comparator plain build", source)
        sanitized = compile_stage("comparator UBSan build", source, *SANITIZER_FLAGS)
        observed = []
        for case in grid:
            n = case["n"]
            data = case["stdin"].encode()
            verify_oracle(execute(plain, data), case, "comparator plain")
            verify_oracle(execute(sanitized, data), case, "sanitizer")
            # Each successful cursor test gives one update. Each outer trip adds five other units.
            expected = 8 + 5 * n + 2 * increments(n)
            counted = dict(case, expected_stdout=f"{triangular(n)} {expected}\n")
            result = execute(counting, data)
            verify_oracle(result, counted, "independent operation count")
            observed.append(int(result.stdout.split()[1]))
        counts[name] = observed
    return counts


def run(pipeline, output):
    source = FAST.replace(BEFORE, AFTER)
    variants = {
        "evaluated": (source, AFTER, triangular),
        "linear_comparator": (FAST, BEFORE, lambda n: n),
        "quadratic_comparator": (FAST.replace(BEFORE, SAME_ORDER), SAME_ORDER, lambda n: triangular(n) - n),
    }
    grid = [{"n": n, "seed": seed, "stdin": f"{n}\n", "expected_stdout": f"{triangular(n)}\n"}
            for seed in SEEDS for n in SIZES]
    counts = check_counts(variants, grid)
    comparisons = {}
    for name in ("linear_comparator", "quadratic_comparator"):
        per_seed = {}
        for seed_index, seed in enumerate(SEEDS):
            start = seed_index * len(SIZES)
            rows = slice(start, start + len(SIZES))
            ratios = [edited / original for edited, original in zip(counts["evaluated"][rows], counts[name][rows], strict=True)]
            slope = linear_regression([log(n) for n in SIZES], [log(ratio) for ratio in ratios]).slope
            if name == "linear_comparator" and slope >= 0.70 and ratios[-1] >= 1.50:
                disposition = "confirmed_positive"
            elif name == "quadratic_comparator" and abs(slope) <= 0.10:
                disposition = "confirmed_sham"
            else:
                raise ValueError(f"{name} did not meet the expected growth criterion at seed {seed}")
            per_seed[str(seed)] = {"slope": slope, "largest_ratio": ratios[-1], "disposition": disposition}
        comparisons[name] = per_seed

    normalized, _ = normalize(pipeline, source)
    profile = profile_side(pipeline, source, grid)
    if any(row["status"] != "CLEAN_COMPLETION" for runs in profile["runs"].values() for row in runs):
        raise ValueError("Expected clean profiles on every authored input")

    # Both calls receive only evaluated-side inputs, independent of the comparator or its label.
    predictions = {name: [predict_seed(pipeline, normalized, profile, seed) for seed in SEEDS]
                   for name in comparisons}
    positive, sham = predictions.values()
    if positive != sham or not all(row["arms"]["work_scoped"]["alert"] is True for row in positive):
        raise ValueError("Expected identical arm predictions and an alert under both comparators")

    code = (Path(__file__), Path(__file__).with_name("synthetic_arms.py"), Path(__file__).with_name("backward_slice.py"))
    report = {"schema": "eapg-authored-comparator-swap-v1", "provenance": provenance(pipeline),
              "code_sha256": {path.name: sha256(path.read_bytes()).hexdigest() for path in code},
              "source_sha256": {name: digest(text) for name, (text, _, _) in variants.items()},
              "counting_template_sha256": digest(COUNTING_BUILD), "workload_sha256": sha256(encoded(grid)).hexdigest(),
              "grid": grid, "operation_counts": counts, "comparisons": comparisons,
              "evaluated_profiles": profile["runs"], "predictions": predictions}
    with output.open("xb") as stream:
        raw = encoded(report)
        stream.write(raw)
    print(f"{sha256(raw).hexdigest()}  {output.name}")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--pipeline", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    if args.output.exists() or not args.output.parent.is_dir():
        cli.error("Specify a new report file in an existing directory")
    run(load_pipeline(args.pipeline), args.output)


if __name__ == "__main__":
    main()
