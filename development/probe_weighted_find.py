"""Compare a container-size work proxy with independently counted std::find comparisons."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

from gate1_sandbox import execute
from run_phase2_development import compile_stage, load_pipeline, profile_side, provenance, rank_by_seed, verify_oracle


SOURCE = """#include <algorithm>
#include <cstdio>
#include <vector>
int main() {
    int n, position;
    if (std::scanf("%d%d", &n, &position) != 2 || position < 0 || position >= n) return 1;
    std::vector<int> data(n, 0);
    data[position] = 1;
    long long checksum = 0;
    for (int i = 0; i < n; ++i) {
        const auto it = std::find(data.begin(), data.end(), 1);
        checksum += it - data.begin();
    }
    std::printf("%lld\\n", checksum);
}
"""
COUNTING_DEFINITION = """struct Needle {};
static unsigned long long comparisons = 0;
bool operator==(int value, Needle) {
    ++comparisons;
    return value == 1;
}
"""
SIZES = (8, 16, 32, 64, 128, 256)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--pipeline", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    if sys.platform != "linux" or args.output.exists():
        cli.error("Use the Linux fixture environment and a fresh output path")
    candidate = load_pipeline(args.pipeline)
    counter_source = SOURCE.replace("int main()", COUNTING_DEFINITION + "int main()")
    counter_source = counter_source.replace("data.end(), 1)", "data.end(), Needle{})")
    counter_source = counter_source.replace('std::printf("%lld\\n", checksum);',
                                            'std::printf("%lld %llu\\n", checksum, comparisons);')
    inputs = [{"seed": seed, "n": n, "stdin": f"{n} {p}\n", "expected_stdout": f"{n * p}\n",
               "position": p} for seed in (0, 1) for n in SIZES for p in [0 if seed == 0 else n - 1]]
    profile = profile_side(candidate, SOURCE, inputs)
    node, = (node for node in profile["nodes"]
             if "std::find(" in node["source_preview"] and "data.size()" in node["weight_expr"])
    node_id = node["id"]
    counted = compile_stage("independent comparison count", counter_source)
    by_seed = rank_by_seed(candidate, profile)
    rows = {}
    for case in inputs:
        seed, n, position = str(case["seed"]), case["n"], case["position"]
        run, = (run for run in profile["runs"][seed] if run["n"] == n)
        actual = n * (position + 1)
        result = execute(counted, case["stdin"].encode())
        verify_oracle(result, dict(case, expected_stdout=f"{n * position} {actual}\n"), "independent count")
        observed = int(result.stdout.split()[1])
        expected = {"cnt": n, "work": n * n}
        if run["status"] != "CLEAN_COMPLETION" or run["nodes"][node_id] != expected:
            raise ValueError(f"Unexpected find counts at size {n} with position {position}")
        rows.setdefault(seed, []).append({"n": n, "position": position, **expected, "comparisons": observed})
    record = {
        "schema": "eapg-authored-find-proxy-v1",
        "script_sha256": sha256(Path(__file__).read_bytes()).hexdigest(), "provenance": provenance(candidate),
        "node": node_id, "sizes": SIZES, "workloads": {},
    }
    for seed, name in (("0", "first_match"), ("1", "last_match")):
        fits = profile["fits"][seed][node_id]
        measured = candidate.fit_dual_family_scaling(SIZES, [row["comparisons"] for row in rows[seed]])
        expected_alpha = 1.0 if seed == "0" else 2.0
        if (fits["fit_hits"]["alpha"], fits["fit_work"]["alpha"], measured["alpha"]) != (1.0, 2.0, expected_alpha):
            raise ValueError(f"Unexpected find exponents for {name}")
        record["workloads"][name] = {"rows": rows[seed], "hits": fits["fit_hits"], "projected_work": fits["fit_work"],
                                     "comparisons": measured, "symptom_id": by_seed[seed]["primary_symptom"]}
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(record, output, indent=2, allow_nan=False)
        output.write("\n")
    print(f"Verified {len(inputs)} independent comparison counts for {node_id}.")


if __name__ == "__main__":
    main()
