"""Check authored Gate 2 counter placement using the Phase 2 isolation runner."""

import argparse
import json
from pathlib import Path

from gate1_sandbox import compile_cpp, execute
from run_phase2_development import historical, load_pipeline, normalize, profile_case, validate_counter


def verify_condition_work(pipeline):
    _, nodes, _, record = profile_case(pipeline, """
#include <algorithm>
#include <vector>
using namespace std;
int main() {
    vector<int> v(8, 1);
    auto found = find(v.begin(), v.end(), 1);
    auto occurrences = count(v.begin(), v.end(), 1);
    std::reverse(v.begin(), v.end());
    int needle = 2;
    int remaining = 2;
    if (std::find(v.begin(), v.end(), needle - 1) != v.end()) --needle;
    while (remaining-- > 0 && std::count(v.begin(), v.end(), needle) != 0) --needle;
    remaining = 0;
    while (remaining-- > 0 && std::count(v.begin(), v.end(), needle) != 0) --needle;
    return needle;
}
""", b"", 1)
    measured = [record["nodes"][node["id"]] for node in nodes if "v.size()" in node["weight_expr"]]
    expected = [{"cnt": hits, "work": 8 * hits} for hits in (1, 1, 1, 1, 2, 0)]
    if record["status"] != "CLEAN_COMPLETION" or measured != expected:
        raise RuntimeError(f"Unexpected STL call counters {measured}, expected {expected}")
    return measured


def verify_recursive_cap(pipeline):
    normalized, aliases = normalize(pipeline, """
int descend(int n) {
    if (n == 0) return n;
    int a = descend(n - 1);
    return a;
}
int main() { descend(10000); }
""")
    nodes = pipeline.extract_macro_nodes(normalized, aliases)
    instrumented = historical.instrument(pipeline, normalized, nodes)
    init = "\n__eapg_init();\n"
    if instrumented.count(init) != 1:
        raise RuntimeError("Expected exactly one generated main initializer")
    instrumented = instrumented.replace(init, init + "__eapg_cap = 4;\n")
    result = execute(compile_cpp(instrumented.encode()), counter_scale=1)
    record = validate_counter(result, nodes, 4)
    expected = {"cnt": 1, "work": 1}
    entry, = [node["id"] for node in nodes if node.get("name") == "descend"]
    assignment, = [node["id"] for node in nodes if node["source_preview"] == "int a = descend(n - 1);"]
    entry_count, assignment_count = (record["nodes"][node_id] for node_id in (entry, assignment))
    if (record["status"] != "CAP_BREACHED" or record["total_ticks"] != 4
            or entry_count != expected or assignment_count != expected):
        raise RuntimeError(f"Expected a cap before recursive descent, got {record}")
    return {"status": record["status"], "total_ticks": record["total_ticks"],
            "entry": entry_count, "assigned_call": assignment_count}


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--pipeline", type=Path, required=True)
    candidate = load_pipeline(cli.parse_args().pipeline)
    print(json.dumps({"stl_calls": verify_condition_work(candidate),
                      "recursive_cap": verify_recursive_cap(candidate)}, indent=2))
