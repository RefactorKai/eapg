"""Exercise the prospective evidence flow on authored development fixtures in WSL."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

from build_reference_packet import build_packet
from run_phase2_development import load_pipeline, profile_side, provenance, rank_by_seed


FAST = """#include <cstdio>
int main() {
    int n;
    if (std::scanf("%d", &n) != 1 || n < 1) return 1;
    volatile int cursor{};
    long long total = 0;
    for (int i = 1; i <= n; ++i) {
        cursor = i - 1;
        while (cursor < i) {
            ++cursor;
        }
        total += cursor;
    }
    std::printf("%lld\\n", total);
}
"""
HIGH_GROWTH = """#include <cstdio>
int main() {
    int n;
    if (std::scanf("%d", &n) != 1 || n < 1) return 1;
    volatile long long total = 0;
    for (int i = 0; i < n; ++i) {
        for (int j = 0; j < n; ++j) {
            ++total;
        }
    }
    std::printf("%lld\\n", static_cast<long long>(total));
}
"""
SIZES = (16, 32, 64, 128)
BEFORE, AFTER = "cursor = i - 1;", "cursor = 0;"


def digest(text):
    return sha256(text.encode()).hexdigest()


def triangular(n):
    return n * (n + 1) // 2


def square(n):
    return n * n


def verify_counts(profile, statement, expected):
    node, = (node for node in profile["nodes"] if node["source_preview"] == statement)
    nid = node["id"]
    records = profile["runs"]["0"]
    observed = [row["nodes"][nid]["cnt"] for row in records]
    if any(row["status"] != "CLEAN_COMPLETION" for row in records) or observed != [expected(n) for n in SIZES]:
        raise ValueError(f"{statement} counter differs from the independent count oracle: {observed}")
    return {"node_id": nid, "counts": observed, "work_fit": profile["fits"]["0"][nid]["fit_work"]}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--pipeline", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    if sys.platform != "linux" or args.output.exists():
        cli.error("Run in Ubuntu WSL with a fresh output path")
    pipeline = load_pipeline(args.pipeline)
    if FAST.count(BEFORE) != 1:
        raise ValueError("The authored intervention must have a unique anchor")
    start = FAST.index(BEFORE)
    slow = FAST[:start] + AFTER + FAST[start + len(BEFORE):]
    if slow[:start] + BEFORE + slow[start + len(AFTER):] != FAST:
        raise ValueError("The authored inverse failed")
    reference_line = slow.count("\n", 0, start) + 1
    span = [len(slow[:start].encode()), len(slow[:start + len(AFTER)].encode())]

    oracle_record = {"sizes": SIZES, "expected_stdout": [triangular(n) for n in SIZES],
                     "slow_increments": [triangular(n) for n in SIZES], "inverse_increments": list(SIZES)}
    oracle_sha = digest(json.dumps(oracle_record, sort_keys=True))
    profiles, counts = {}, {}
    for name, source, oracle, statement, work in (
        ("intervention", slow, triangular, "++cursor;", triangular),
        ("inverse", FAST, triangular, "++cursor;", lambda n: n),
        ("appropriate_quadratic", HIGH_GROWTH, square, "++total;", square),
    ):
        inputs = [{"n": n, "seed": 0, "stdin": f"{n}\n", "expected_stdout": f"{oracle(n)}\n"} for n in SIZES]
        profile = profile_side(pipeline, source, inputs)
        counts[name] = verify_counts(profile, statement, work)
        profiles[name] = {key: profile[key] for key in ("nodes", "fits", "normalized_sha256")}

    profile = profiles["intervention"]
    packet = build_packet(pipeline, {
        "pair_id": "authored-cursor-reset", "problem_spec": "Sum integers from 1 through N",
        "slow_code": slow, "fast_code": FAST, "protocol_sha256": digest("authored intervention fixture v1"),
        "independent_evidence": {"record_sha256": oracle_sha,
                                 "summary": "Closed-form triangular output and cursor increments"},
        "profile": {"pipeline_sha256": pipeline.source_sha256,
                    "normalized_source_sha256": profile["normalized_sha256"],
                    "canonical_node_ids": [node["id"] for node in profile["nodes"]]},
    })
    reference, = (node["node_id"] for node in packet["pass2_map"]["nodes"]
                  if node["role"] == "STATE_UPD" and node["raw_source_lines"] == [reference_line])
    selectors = {name: rank_by_seed(pipeline, profile)["0"] for name, profile in profiles.items()}
    positive, inverse, control = (selectors[name] for name in profiles)
    slow_fit, fast_fit = (counts[name]["work_fit"] for name in ("intervention", "inverse"))
    if (slow_fit["growth"] != "POLY" or fast_fit["growth"] != "POLY"
            or slow_fit["alpha"] - fast_fit["alpha"] < 0.70):
        raise ValueError("The intervention did not clear the development work-growth contrast")
    if (positive["primary_symptom"] in (None, reference) or reference not in positive["c_pruned"]
            or inverse["primary_symptom"] is not None or control["primary_symptom"] is None):
        raise ValueError(f"Unexpected authored smoke outcome for reference {reference}: {selectors}")
    report = {"schema": "eapg-authored-intervention-smoke-v1", "sizes": SIZES, "provenance": provenance(pipeline),
              "probe_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
              "intervention": {"slow_sha256": digest(slow), "inverse_sha256": digest(FAST), "raw_span": span,
                               "raw_line": reference_line, "reference": reference},
              "oracle": oracle_record, "oracle_sha256": oracle_sha,
              "counts": counts, "selectors": selectors, "profiles": profiles}
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(f"Verified three authored profiles over {len(SIZES)} sizes each. "
          f"Intervention {reference}, symptom {positive['primary_symptom']}, ranking {positive['ranked_candidates']}.")


if __name__ == "__main__":
    main()
