"""Check whether the scoped slice drops an authored transitive growth edit."""

import argparse
from pathlib import Path

from probe_synthetic_comparison import SEEDS, SIZES, encoded
from probe_synthetic_intervention import triangular
from reference_adjudication import require, sha
from run_phase2_development import load_module, normalize, profile_side, provenance
from synthetic_arms import predict_seed
from synthetic_intervention import resolve_intervention
from synthetic_oracle import verify_case


ORIGINAL = r'''#include <cstdio>
int main() {
    int n;
    if (std::scanf("%d", &n) != 1 || n < 1) return 1;
    int origin = 0;
    int staged = 0;
    volatile int cursor = 0;
    long long total = 0;
    for (int i = 1; i <= n; ++i) {
        origin = i - 1;
        staged = 2 * origin;
        cursor = staged;
        while (cursor < 2 * i)
            ++cursor;
        total += cursor / 2;
    }
    std::printf("%lld\n", total);
}
'''

# Count input/output items, original conditions, and scalar updates as unit operations.
# Eight units cover valid input, two guards, and initialization of five variables.
COUNTING = r'''#include <cstdio>
int main() {
    int n;
    if (std::scanf("%d", &n) != 1 || n < 1) return 1;
    int origin = 0;
    int staged = 0;
    volatile int cursor = 0;
    long long total = 0, operations = 8;
    for (int i = 1; ++operations, i <= n; ++operations, ++i) {
        ++operations;
        origin = i - 1;
        ++operations;
        staged = 2 * origin;
        ++operations;
        cursor = staged;
        while (++operations, cursor < 2 * i) {
            ++operations;
            ++cursor;
        }
        ++operations;
        total += cursor / 2;
    }
    ++operations;
    std::printf("%lld\n\nEAPG-OPERATIONS-v1 %lld\n", total, operations);
}
'''


def run(pipeline):
    before, after = "i - 1", "0"
    sources = {"original": ORIGINAL, "edited": ORIGINAL.replace(before, after), "restored": ORIGINAL}
    counting = {"original": COUNTING, "edited": COUNTING.replace(before, after), "restored": COUNTING}
    source_hashes = {name: sha(source) for name, source in sources.items()}
    start = ORIGINAL.encode().index(before.encode())
    record = {"schema": "eapg-synthetic-intervention-v1", **sources, "source_sha256": source_hashes,
              "edit": {"start_byte": start, "removed": before, "inserted": after}, "equivalent_edited_intervals": []}

    # Seven units per outer trip, two per cursor increment, ten fixed units.
    # Starting at twice (i-1) needs two advances per trip. Starting at zero needs 2*i.
    grid = [{"n": n, "seed": seed, "stdin": f"{n}\n", "expected_stdout": f"{triangular(n)}\n",
             "expected_counts": {"original": 10 + 11 * n, "restored": 10 + 11 * n,
                                 "edited": 10 + 7 * n + 2 * n * (n + 1)}} for seed in SEEDS for n in SIZES]
    growth = {"original_order": [1, 0], "edited_order": [2, 0], "band": "strong"}
    counted = verify_case("positive_off_site", sources, counting, grid, growth)
    require(counted["disposition"] == "confirmed_positive", f"Independent operation verification failed: {counted}")
    reference = resolve_intervention(pipeline, record)
    require(reference["reference_status"] == "resolved", f"Expected a unique authored edit: {reference}")
    edit, = reference["accepted_node_ids"]

    normalized, _ = normalize(pipeline, sources["edited"])
    profile = profile_side(pipeline, sources["edited"], grid)
    require(reference["normalized_source_sha256"] == profile["normalized_sha256"], "Reference and profile digest mismatch")
    require([row["node_id"] for row in reference["canonical_nodes"]] == [node["id"] for node in profile["nodes"]],
            "Reference and profile have different node IDs")
    require(all(row["status"] == "CLEAN_COMPLETION" for rows in profile["runs"].values() for row in rows),
            "Expected every authored profile to complete")

    predictions = [predict_seed(pipeline, normalized, profile, seed) for seed in SEEDS]
    for row in predictions:
        arms = row["arms"]
        scoped, conventional = arms["work_scoped"], arms["work_conventional"]
        require(scoped["alert"] and scoped["symptom_id"] == conventional["symptom_id"], "Expected one common work symptom")
        require(edit not in scoped["candidates"] and edit in conventional["candidates"],
                "Expected only the conventional slice to follow the transitive dependency")
    files = ("probe_transitive_edit.py", "synthetic_arms.py", "synthetic_intervention.py",
             "synthetic_oracle.py", "backward_slice.py")
    return {"schema": "eapg-authored-transitive-edit-v1", "provenance": provenance(pipeline),
            "software_sha256": {name: sha(Path(__file__).with_name(name).read_bytes()) for name in files},
            "inputs": grid, "counted": counted, "reference": reference, "evaluated_profiles": profile["runs"],
            "predictions": predictions}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--pipeline", required=True, type=Path)
    cli.add_argument("--pipeline-sha256", required=True)
    cli.add_argument("--out", required=True, type=Path)
    args = cli.parse_args()
    if args.out.exists() or not args.out.parent.is_dir():
        cli.error("Choose a fresh output in an existing directory")
    pipeline = load_module("transitive_edit_pipeline", args.pipeline, args.pipeline_sha256)
    raw = encoded(run(pipeline))
    with args.out.open("xb") as stream:
        stream.write(raw)
    print(f"{sha(raw)}  {args.out.name}")


if __name__ == "__main__":
    main()
