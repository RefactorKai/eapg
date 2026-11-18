"""Authored CFG, dependence, and canonical projection fixtures."""

import argparse
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

from tree_sitter import Language, Parser
import tree_sitter_cpp

from backward_slice import UnsupportedProgram, backward_slice


PIPELINE = SimpleNamespace(parser=Parser(Language(tree_sitter_cpp.language())))


class BackwardSliceTests(unittest.TestCase):
    pipeline = PIPELINE

    def slice(self, source, spans, criterion=-1):
        raw = source.encode("utf-8")
        nodes = []
        for index, snippet in enumerate(spans):
            token = snippet.encode("utf-8")
            self.assertEqual(raw.count(token), 1, snippet)
            start = raw.index(token)
            nodes.append({"id": f"N{index + 1}", "normalized_span": [start, start + len(token)]})
        result = backward_slice(self.pipeline, source, nodes, nodes[criterion]["id"])
        return [spans[int(node_id[1:]) - 1] for node_id in result]

    def test_overwrites_and_shadowing_kill_stale_definitions(self):
        source = """int main() {
    // π tests UTF-8 byte offsets after a non-ASCII comment.
    int stale = 7;
    int value = stale;
    value = 2;
    {
        int value = 3;
        ++value;
    }
    return value;
}"""
        spans = ["return value;", "int stale = 7;", "int value = stale;", "value = 2;",
                 "int value = 3;", "++value;"]
        self.assertEqual(self.slice(source, spans, criterion=0), ["return value;", "value = 2;"])

    def test_branch_and_unmapped_definition_flow_transitively(self):
        conditional = "if (flag) {\n        x = hidden;\n    } else {\n        x = 4;\n    }"
        source = f"""int main() {{
    int basis = 1;
    int flag = 1;
    int hidden = basis;
    int x = 0;
    {conditional}
    return x;
}}"""
        spans = ["int basis = 1;", "int flag = 1;", "int x = 0;", conditional,
                 "x = hidden;", "x = 4;", "return x;"]
        self.assertEqual(self.slice(source, spans), ["int basis = 1;", "int flag = 1;", conditional,
                                                    "x = hidden;", "x = 4;", "return x;"])

    def test_for_update_uses_loop_carried_definition(self):
        loop = "for (; x < cap; x += step) {\n        step = x + 1;\n    }"
        source = f"""int main() {{
    int x = 0;
    int cap = 3;
    int step = 9;
    {loop}
    return x;
}}"""
        spans = ["int x = 0;", "int cap = 3;", "int step = 9;", loop, "step = x + 1;", "return x;"]
        self.assertEqual(self.slice(source, spans), [spans[i] for i in (0, 1, 3, 4, 5)])

    def test_while_loop_control_survives_break_and_continue(self):
        guard = "if (i >= bound) { break; }"
        branch = "if (i == 1) { continue; }"
        loop = f"while (i < 4) {{ ++i; {guard} {branch} ++total; }}"
        source = f"""int main() {{
    int i = 0;
    int bound = 3;
    int total = 0;
    {loop}
    return total;
}}"""
        spans = ["int i = 0;", "int bound = 3;", "int total = 0;", loop,
                 "++i;", guard, branch, "++total;", "return total;"]
        self.assertEqual(self.slice(source, spans), spans)

    def test_do_body_definition_reaches_exit_even_before_first_condition(self):
        loop = "do { x = 7; } while (flag);"
        source = f"""int main() {{
    int x = 0;
    int flag = 0;
    {loop}
    return x;
}}"""
        spans = ["int x = 0;", "int flag = 0;", loop, "x = 7;", "return x;"]
        result = self.slice(source, spans)
        self.assertIn("x = 7;", result)
        self.assertNotIn("int x = 0;", result)

    def test_scan_may_write_and_guard_can_control_later_execution(self):
        scan = 'std::scanf("%d", &n);'
        guard = "if (n < 1 || n > 10) { return 1; }"
        output = 'std::printf("%lld\\n", static_cast<long long>(n));'
        source = f"""#include <cstdio>
int main() {{
    int n = 2;
    {scan}
    {guard}
    {output}
}}"""
        spans = ["int n = 2;", scan, guard, output]
        self.assertEqual(self.slice(source, spans), spans)

    def test_unsupported_syntax_and_effects_fail_closed(self):
        for body in (
            "int x = 0; int *ptr = &x; ++*ptr;",
            "int x = 0; int &alias = x;",
            "int x[2] = {}; x[0] = 1;",
            "int x = 0; static int y = 0;",
            "int x = 0; std::scanf(\"%n\", &x);",
            "int x = 0; std::printf(\"%lld\", x);",
            "int x = 0; std::puts(\"x\");",
            "int x = 0; auto f = []{}; f();",
            "int x = 0; if (++x > 0) { x = 2; }",
            "if constexpr (true) { return 1; }",
            "int x = 0; for (;;) { break; }",
        ):
            with self.subTest(body=body), self.assertRaises(UnsupportedProgram):
                self.slice(f"int main() {{ {body} return 0; }}", ["return 0;"])
        with self.assertRaises(UnsupportedProgram):
            self.slice("void helper() {} int main() { helper(); return 0; }", ["return 0;"])

    def test_criterion_must_own_a_reachable_operation(self):
        source = "int main() { return 0; int dead = 1; }"
        with self.assertRaises(UnsupportedProgram):
            self.slice(source, ["return 0;", "int dead = 1;"])
        self.assertEqual(backward_slice(self.pipeline, source, [], None), [])

    def test_pipeline_projects_the_three_authored_programs(self):
        if self.pipeline is PIPELINE:
            self.skipTest("supply --pipeline to test canonical extraction")
        from probe_synthetic_intervention import AFTER, BEFORE, FAST, HIGH_GROWTH

        for source, criterion, expected in (
            (FAST.replace(BEFORE, AFTER), "N5", ["N1", "N3", "N4", "N5", "N6"]),
            (FAST, "N5", ["N1", "N3", "N4", "N5", "N6"]),
            (HIGH_GROWTH, "N4", ["N1", "N3", "N4"]),
        ):
            with self.subTest(criterion=criterion):
                expanded, aliases = self.pipeline.preprocess_pass_zero(source)
                normalized = self.pipeline.normalize_synthetic_braces(expanded)
                self.assertTrue(self.pipeline.verify_cpp_syntax(normalized))
                nodes = self.pipeline.extract_macro_nodes(normalized, aliases)
                self.assertEqual(backward_slice(self.pipeline, normalized, nodes, criterion), expected)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(add_help=False)
    cli.add_argument("--pipeline", type=Path)
    options, unittest_args = cli.parse_known_args()
    if options.pipeline:
        from run_phase2_development import load_pipeline

        BackwardSliceTests.pipeline = load_pipeline(options.pipeline.resolve())
    unittest.main(argv=[sys.argv[0], *unittest_args])
