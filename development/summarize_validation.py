"""Verify and summarize the registered development replay without source previews."""

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path


DATA = Path(__file__).resolve().parents[1] / "artifacts/phase2_data"


def summarize(raw):
    report = json.loads(raw)
    workload = (DATA / "development_workload.json").read_bytes()
    if report["workload_sha256"] != sha256(workload).hexdigest():
        raise ValueError("Registered workload digest mismatch")
    prior = json.loads((DATA / "development_counters.json").read_bytes())
    expected = {}
    for case in json.loads(workload)["inputs"]:
        n, k, *values = map(int, case["stdin"].split())
        if k != 1 or n != len(values):
            raise ValueError("Unexpected registered input shape")
        expected[str(case["seed"]), n] = f"{n - max(Counter(values).values())}\n"

    stage_counts = Counter()
    for side in ("slow", "fast"):
        result = report[side]
        if "failure" in result:
            raise ValueError(f"Development run failed on the {side} side: {result['failure']['status']}")
        observed = set()
        for seed, rows in result["runs"].items():
            for row in rows:
                key = seed, row["n"]
                if (key in observed or row["status"] != "CLEAN_COMPLETION" or row["returncode"] != 0
                        or row["stdout"].split() != expected[key].split()
                        or row["total_ticks"] != sum(node["work"] for node in row["nodes"].values())):
                    raise ValueError(f"Invalid profiling record for {side} seed {seed}, N={row['n']}")
                observed.add(key)
                stage_counts["instrumented_byte_exact"] += row["stdout"] == expected[key]
        if observed != set(expected):
            raise ValueError(f"Incomplete development ladder for {side}")
        stage_counts["instrumented_oracle_matches"] += len(observed)
        stage_counts["original_oracle_matches"] += result["plain_oracle_checks"]
        stage_counts["sanitizer_oracle_matches"] += result["sanitizer_oracle_checks"]

    slow = report["slow"]
    all_runs = [row for rows in slow["runs"].values() for row in rows]
    matches = [node["id"] for node in slow["nodes"] if node["role"] == "LOOP" and all(
        row["nodes"][node["id"]]["cnt"] == (row["n"] // 4 - 1) * (row["n"] // 2 + 2) + 1 for row in all_runs)]
    if len(matches) != 1:
        raise ValueError(f"Expected a unique loop matching the independent count formula, got {matches}")
    reference = matches[0]
    seeds = {}
    for seed, slicing in report["slices_by_seed"].items():
        old = prior["slices_by_seed"][seed]
        fit = slow["fits"][seed][reference]["fit_work"]
        candidates = slicing["c_pruned"]
        seeds[seed] = {"frozen_symptom": old["primary_symptom"], "candidate_symptom": slicing["primary_symptom"],
                       "work_alpha": fit["alpha"], "work_r2": fit["r2_poly"],
                       "reference_retained": reference in candidates, "candidates": candidates,
                       "node_count": slicing["v_total"], "ranked_candidates": slicing["ranked_candidates"],
                       "work_qualifiers": slicing["work_qualifiers"]}
    if seeds.keys() != prior["slices_by_seed"].keys():
        raise ValueError("Registered seed results are incomplete")
    return {"scope": "single previously registered PIE validation case, development only",
            "private_run_sha256": sha256(raw).hexdigest(), "workload_sha256": report["workload_sha256"],
            "provenance": report["provenance"], "stage_counts": stage_counts,
            "traversal_node": reference, "analytical_traversal_checks": len(all_runs), "seeds": seeds}


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("report", type=Path)
    cli.add_argument("--repeat", type=Path, help="require a byte-identical independent rerun")
    args = cli.parse_args()
    raw = args.report.read_bytes()
    if args.repeat is not None and raw != args.repeat.read_bytes():
        raise ValueError("Registered development rerun differs from the original")
    print(json.dumps({**summarize(raw), "byte_identical_runs": 1 + (args.repeat is not None)},
                     indent=2, sort_keys=True))
