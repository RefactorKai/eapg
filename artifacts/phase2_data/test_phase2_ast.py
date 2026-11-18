"""Authored Gate 2 regressions. Run against the release or a trusted --pipeline PATH."""

import argparse
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from tree_sitter import Query, QueryCursor


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "development"))
from build_candidate import build_candidate


PROSPECTIVE_SHA = "2c95df0e5676e8b19464457adfb34cdf85a8a10cc0dca8b70557a1d587ced383"
PROGRESS = """
void solve(int r, int limit, int cutoff) {
    while (r < limit) {
        r = r + 1;
        limit = cutoff;
    }
}
"""


class Phase2AstTests(unittest.TestCase):
    pipeline_path = None
    _tempdir = None

    @classmethod
    def setUpClass(cls):
        path = cls.pipeline_path
        if path is None:
            cls._tempdir = TemporaryDirectory(prefix="eapg-ast-test-")
            path = Path(cls._tempdir.name) / "prospective.py"
            digest = build_candidate(path, prospective=True)
            if digest != PROSPECTIVE_SHA:
                raise RuntimeError(f"Unexpected prospective candidate SHA-256: {digest}")
        spec = spec_from_file_location("gate2_candidate", path)
        cls.pipeline = module_from_spec(spec)
        spec.loader.exec_module(cls.pipeline)

    @classmethod
    def tearDownClass(cls):
        if cls._tempdir is not None:
            cls._tempdir.cleanup()
            cls._tempdir = None

    def inspect(self, source):
        expanded, aliases = self.pipeline.preprocess_pass_zero(source)
        normalized = self.pipeline.normalize_synthetic_braces(expanded)
        self.assertTrue(self.pipeline.verify_cpp_syntax(normalized), "normalized C++17 syntax")
        nodes = self.pipeline.extract_macro_nodes(normalized, aliases)
        instrumented = self.pipeline.instrument_cpp_source(normalized, nodes)
        self.assertTrue(self.pipeline.verify_cpp_syntax(instrumented), "instrumented C++17 syntax")
        return nodes, instrumented

    def node(self, nodes, preview):
        matches = [node for node in nodes if node["source_preview"] == preview]
        self.assertEqual(len(matches), 1, preview)
        return matches[0]

    def capture(self, source, pattern):
        tree = self.pipeline.parser.parse(source.encode())
        query = Query(self.pipeline.CPP_LANGUAGE, pattern)
        return QueryCursor(query).captures(tree.root_node).get("match", [])

    def calls(self, source):
        return self.capture(source, "(call_expression function: (_)) @match")

    def counters(self, calls, nodes, targets):
        indices = {str(nodes.index(node)).encode() for node in targets}
        return [
            call for call in calls
            if call.child_by_field_name("function").text.lower().startswith(b"__eapg_tick")
            and call.child_by_field_name("arguments").named_children[0].text in indices
        ]

    def test_plain_assignment_preserves_rhs_self_use(self):
        nodes, _ = self.inspect(PROGRESS)
        step = self.node(nodes, "r = r + 1;")
        self.assertEqual(set(step["defs"]), {"r"})
        self.assertEqual(set(step["uses"]), {"r"})
        self.assertTrue(step["is_unidirectional_step"])
        self.assertFalse(step["is_state_reset"])

    def test_monotonic_pruning_keeps_the_guard_reset(self):
        nodes, _ = self.inspect(PROGRESS)
        loop = self.node(nodes, "while (r < limit)")
        step = self.node(nodes, "r = r + 1;")
        reset = self.node(nodes, "limit = cutoff;")
        fits = {}
        for node in nodes:
            fit = {"growth": "POLY", "alpha": 0.0 if node["role"] == "FUNCTION_ENTRY" else 2.0}
            fits[node["id"]] = {"fit_work": fit, "fit_hits": fit}
        result = self.pipeline.analyze_eapg_slicing(nodes, fits)
        self.assertEqual(result["primary_symptom"], loop["id"])
        self.assertIn(reset["id"], result["c_slice"])
        self.assertNotIn(step["id"], result["c_slice"])

    def test_linear_stl_calls(self):
        nodes, _ = self.inspect("""
#include <algorithm>
#include <vector>
using namespace std;
void solve(vector<int>& v, int needle) {
    auto it = find(v.begin(), v.end(), needle);
    auto occurrences = count(v.begin(), v.end(), needle);
    std::reverse(v.begin(), v.end());
}
""")
        for call in (
            "find(v.begin(), v.end(), needle)",
            "count(v.begin(), v.end(), needle)",
            "std::reverse(v.begin(), v.end())",
        ):
            with self.subTest(call=call):
                weighted = [node for node in nodes if call in node["source_preview"]
                            and "v.size()" in node["weight_expr"]]
                self.assertEqual(len(weighted), 1, "expected one size-weighted node")

    def test_linear_call_uses_the_visible_container_declaration(self):
        nodes, _ = self.inspect("""
#include <algorithm>
#include <vector>
struct Range {
    int* begin();
    int* end();
};
std::vector<int> v;
void local_shadow() {
    std::reverse(v.begin(), v.end());
    Range v;
    std::reverse(v.begin(), v.end());
}
void parameter_shadow(std::vector<int>& v) {
    std::reverse(v.begin(), v.end());
    {
        Range v;
        std::reverse(v.begin(), v.end());
    }
    std::reverse(v.begin(), v.end());
}
void unrelated(int v) {}
""")
        weights = [node["weight_expr"] for node in nodes
                   if node["source_preview"] == "std::reverse(v.begin(), v.end());"]
        size = "(unsigned long long)(v.size())"
        self.assertEqual(weights, [size, "1ULL", size, "1ULL", size])

    def test_unrecognized_member_receiver_keeps_unit_work(self):
        nodes, _ = self.inspect("""
#include <string>
struct Range { int find(int); };
void solve(Range known_type, std::string& text) {
    auto deduced = Range{};
    known_type.find(1);
    deduced.find(2);
    text.find('x');
}
""")
        self.assertEqual(self.node(nodes, "known_type.find(1);")["weight_expr"], "1ULL")
        self.assertEqual(self.node(nodes, "deduced.find(2);")["weight_expr"], "1ULL")
        self.assertEqual(self.node(nodes, "text.find('x');")["weight_expr"], "(unsigned long long)(text.size())")

    def test_member_weight_requires_one_ast_call(self):
        nodes, _ = self.inspect("""
#include <cstdio>
#include <string>
void solve(std::string& v) {
    std::puts("v.find(");
    v.find('x');
    auto both = v.find('x') + v.find('y');
}
""")
        self.assertEqual(self.node(nodes, 'std::puts("v.find(");')["weight_expr"], "1ULL")
        self.assertEqual(self.node(nodes, "v.find('x');")["weight_expr"], "(unsigned long long)(v.size())")
        self.assertEqual(self.node(nodes, "auto both = v.find('x') + v.find('y');")["weight_expr"], "1ULL")

    def test_linear_calls_in_conditions(self):
        for statement, keyword, algorithm in (
            ("if (std::find(v.begin(), v.end(), needle) != v.end()) --needle;", "if", "find"),
            ("while (remaining-- > 0 && std::count(v.begin(), v.end(), needle) != 0) --needle;",
             "while", "count"),
        ):
            with self.subTest(condition=keyword):
                nodes, instrumented = self.inspect(f"""
#include <algorithm>
#include <vector>
void solve(std::vector<int>& v, int needle, int remaining) {{
    {statement}
}}
""")
                weighted = [node for node in nodes if "v.size()" in node["weight_expr"]]
                self.assertEqual(len(weighted), 1, f"std::{algorithm} must have a linear work node")
                calls = self.calls(instrumented)
                callee = f"std::{algorithm}".encode()
                sites = [call for call in calls if call.child_by_field_name("function").text == callee]
                counters = self.counters(calls, nodes, weighted)
                self.assertEqual(len(sites), 1)
                self.assertEqual(len(counters), 1)
                site, tick = sites[0], counters[0]
                self.assertLess(tick.end_byte, site.start_byte)
                if keyword == "while":
                    # The RHS executes only if the left operand is true, including on a
                    # failed final condition. A tick in the loop body misses that evaluation.
                    right_operands = self.capture(
                        instrumented, '(binary_expression operator: "&&" right: (_) @match)'
                    )
                    self.assertTrue(any(rhs.start_byte <= tick.start_byte < site.end_byte <= rhs.end_byte
                                        for rhs in right_operands), "tick must respect short-circuiting")

    def test_assigned_recursion_ticks_before_call(self):
        nodes, instrumented = self.inspect("""
int descend(int n) {
    if (n < 2) return 1;
    int left = descend(n - 1);
    left = descend(n - 2);
    return left;
}
""")
        calls = self.calls(instrumented)
        for expression in ("descend(n - 1)", "descend(n - 2)"):
            with self.subTest(call=expression):
                targets = [node for node in nodes if expression in node["source_preview"]]
                self.assertTrue(any("left" in node["defs"] for node in targets))
                sites = [call for call in calls if call.text == expression.encode()]
                self.assertEqual(len(sites), 1)
                ticks = self.counters(calls, nodes, targets)
                self.assertTrue(any(tick.end_byte < sites[0].start_byte for tick in ticks),
                                "expected a tick before the recursive call")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(add_help=False)
    cli.add_argument("--pipeline", type=Path, default=None)
    options, unittest_args = cli.parse_known_args()
    if options.pipeline is not None:
        Phase2AstTests.pipeline_path = options.pipeline.resolve()
    unittest.main(argv=[sys.argv[0], *unittest_args])
