"""Gate 2 selector and ranker fixtures using authored code and synthetic fits."""

import argparse
import importlib.util
import inspect
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "development"))
from build_candidate import build_candidate


PROSPECTIVE_SHA = "2c95df0e5676e8b19464457adfb34cdf85a8a10cc0dca8b70557a1d587ced383"
SCALES = [4, 8, 16, 32]


class Phase2Selection(unittest.TestCase):
    pipeline_path = None
    _tempdir = None

    @classmethod
    def setUpClass(cls):
        path = cls.pipeline_path
        if path is None:
            cls._tempdir = TemporaryDirectory(prefix="eapg-select-test-")
            path = Path(cls._tempdir.name) / "prospective.py"
            digest = build_candidate(path, prospective=True)
            if digest != PROSPECTIVE_SHA:
                raise RuntimeError(f"Unexpected prospective candidate SHA-256: {digest}")
        spec = importlib.util.spec_from_file_location("gate2_pipeline", path)
        cls.pipeline = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.pipeline
        spec.loader.exec_module(cls.pipeline)

    @classmethod
    def tearDownClass(cls):
        if cls._tempdir is not None:
            cls._tempdir.cleanup()
            cls._tempdir = None

    def nodes(self, source):
        expanded, aliases = self.pipeline.preprocess_pass_zero(source)
        normalized = self.pipeline.normalize_synthetic_braces(expanded)
        self.assertFalse(self.pipeline.parser.parse(normalized.encode()).root_node.has_error)
        return self.pipeline.extract_macro_nodes(normalized, aliases)

    def fits(self, nodes, counts, hits=None):
        result = {}
        for node in nodes:
            nid = node["id"]
            series = counts.get(nid, [1] * len(SCALES))
            work_fit = self.pipeline.fit_dual_family_scaling(SCALES, series)
            hit_fit = self.pipeline.fit_dual_family_scaling(SCALES, hits[nid]) if hits and nid in hits else work_fit
            result[nid] = {"fit_hits": hit_fit, "fit_work": work_fit}
        return result

    def assert_symptom(self, nodes, counts, expected, *, hits=None):
        result = self.pipeline.evaluate_four_slicing_tiers(nodes, self.fits(nodes, counts, hits))
        self.assertEqual(result["primary_symptom"], expected)
        self.assertEqual(result["c_naive_work"], [expected] if expected else [])
        if expected:
            self.assertIn(expected, result["c_pruned"])
        else:
            self.assertEqual(result["c_pruned"], [])
        return result

    def rank(self, source, nodes, fits, slicing):
        details = self.pipeline.analyze_eapg_slicing(nodes, fits)
        details.update(primary_symptom=slicing["primary_symptom"], c_slice=slicing["c_pruned"],
                       r_search=1 - len(slicing["c_pruned"]) / len(nodes))
        record = {"slow_code": source, "pilot_revision": self.pipeline.PILOT_REVISION,
                  "skeleton": self.pipeline.format_eapg_skeleton(nodes, fits, details),
                  "slicing": slicing}
        rank = self.pipeline.rank_candidates_by_role_priority
        if "macro_nodes" in inspect.signature(rank).parameters:
            return rank(record, use_loop_def_use=True, macro_nodes=nodes)
        return rank(record, use_loop_def_use=True)

    def test_nested_work_jump_selects_inner_loop(self):
        nodes = self.nodes("""int main(int n, char**) {
            if (n > 0) {
                for (int i = 0; i < n; ++i) {
                    for (int j = 0; j < n; ++j) {}
                }
            }
        }""")
        self.assertEqual([(node["role"], node["parent"]) for node in nodes],
                         [("BRANCH", "MAIN_SCOPE"), ("LOOP", "N1"), ("LOOP", "N2")])
        self.assert_symptom(nodes, {"N2": SCALES, "N3": [n**2 for n in SCALES]}, "N3")

    def test_main_scope_quadratic_loop_after_linear_loop(self):
        nodes = self.nodes("""int main(int n, char**) {
            for (int i = 0; i < n; ++i) {}
            for (long long j = 0; j < 1LL * n * n; ++j) {}
        }""")
        self.assertEqual([node["parent"] for node in nodes], ["MAIN_SCOPE", "MAIN_SCOPE"])
        self.assert_symptom(nodes, {"N1": SCALES, "N2": [n**2 for n in SCALES]}, "N2")

    def test_proposed_maximum_work_rule_prefers_cubic_to_earlier_quadratic(self):
        nodes = self.nodes("""int main(int n, char**) {
            if (n > 0) {
                for (long long i = 0; i < 1LL * n * n; ++i) {}
                for (long long j = 0; j < 1LL * n * n * n; ++j) {}
            }
        }""")
        self.assert_symptom(nodes, {"N2": [n**2 for n in SCALES], "N3": [n**3 for n in SCALES]}, "N3")

    def test_root_call_with_hidden_linear_work_remains_eligible(self):
        nodes = self.nodes("""#include <algorithm>
        #include <vector>
        int main(int n, char**) {
            std::vector<int> data(n);
            std::reverse(data.begin(), data.end());
        }""")
        call, = [node for node in nodes if node["source_preview"].startswith("std::reverse")]
        self.assertEqual((call["role"], call["parent"]), ("CALL", "MAIN_SCOPE"))
        nid = call["id"]
        result = self.assert_symptom(nodes, {nid: SCALES}, nid, hits={nid: [1] * len(SCALES)})
        self.assertEqual(result["c_naive_hits"], [])

    def test_ordinary_linear_loops_are_controls(self):
        loop = "for (int i = 0; i < n; ++i) {}"
        for body in (loop, f"if (n > 0) {{ {loop} }}"):
            with self.subTest(body=body):
                nodes = self.nodes(f"int main(int n, char**) {{ {body} }}")
                linear, = [node["id"] for node in nodes if node["role"] == "LOOP"]
                self.assert_symptom(nodes, {linear: SCALES}, None)

    def test_exponential_recursion_selects_function_entry(self):
        nodes = self.nodes("""int visit(int n) {
            if (n <= 0) return 0;
            return visit(n - 1) + visit(n - 1);
        }
        int main(int n, char**) { return visit(n); }""")
        self.assertEqual([(node["role"], node["parent"]) for node in nodes[:3]],
                         [("FUNCTION_ENTRY", None), ("BRANCH", "N1"), ("CALL", "N1")])
        counts = {"N1": [2**(n + 1) - 1 for n in SCALES],
                  "N2": [2**(n + 1) - 1 for n in SCALES],
                  "N3": [2**n - 1 for n in SCALES]}
        fits = self.fits(nodes, counts)
        for nid in counts:
            self.assertEqual(fits[nid]["fit_work"]["growth"], "EXP")
        self.assertEqual(self.assert_symptom(nodes, counts, "N1")["c_naive_hits"], ["N1"])

    def test_function_work_jump_requires_one_direct_call_site(self):
        for body, has_caller in (
            ('return std::puts("solve(");', False),
            ('solve(n); return std::puts("solve(");', True),
            ("return ::solve(n);", True),
            ("solve(n); return solve(n - 1);", False),
            ("return solve(n) + solve(n - 1);", False),
            ("auto solve = [](int x) { return x; }; return solve(n);", False),
            ("return helpers::solve(n);", False),
            ("int (*solve)(int) = &helpers::solve; return solve(n);", False),
            ("auto invoke = &solve; return invoke(n);", False),
        ):
            with self.subTest(body=body):
                nodes = self.nodes(f"""#include <cstdio>
                namespace helpers {{ int solve(int); }}
                int solve(int n) {{
                    if (n > 0) return solve(n - 1);
                    return n;
                }}
                int main(int n, char**) {{ {body} }}
                """)
                function, = [node for node in nodes if node["role"] == "FUNCTION_ENTRY"]
                nid = function["id"]
                quadratic = [n**2 for n in SCALES]
                counts = {nid: quadratic}
                if has_caller:
                    counts.update({node["id"]: quadratic for node in nodes
                                   if node["source_preview"].startswith('return std::puts')})
                expected = nid if has_caller else None
                result = self.assert_symptom(nodes, counts, expected)
                self.assertEqual(result["c_naive_hits"], [nid] if has_caller else [])
                details = self.pipeline.analyze_eapg_slicing(nodes, self.fits(nodes, counts))
                self.assertEqual(details["primary_symptom"], expected)

    def test_ranker_uses_expanded_node_ids(self):
        source = """#define SET_OFFSET(x) int x = 0; x += 0
        int main(int n, char**) {
            for (int i = 0; i < n; ++i) {
                SET_OFFSET(start);
                for (int j = start; j < n; ++j) {}
            }
        }"""
        nodes = self.nodes(source)
        self.assertEqual([node["source_preview"] for node in nodes[1:3]],
                         ["int start = 0;", "start += 0;"])
        raw = self.pipeline.extract_macro_nodes(self.pipeline.normalize_synthetic_braces(source), {})
        self.assertNotIn("N4", {node["id"] for node in raw})
        fits = self.fits(nodes, {"N1": SCALES, "N2": SCALES, "N3": SCALES,
                                 "N4": [n**2 for n in SCALES]})
        slicing = self.pipeline.evaluate_four_slicing_tiers(nodes, fits)
        self.assertEqual(slicing["c_pruned"], ["N2", "N3", "N4"])
        try:
            ranked = self.rank(source, nodes, fits, slicing)
        except KeyError as error:
            self.fail(f"Ranker could not resolve expanded node ID {error}")
        self.assertCountEqual(ranked, slicing["c_pruned"])
        self.assertIn(ranked[0], {"N2", "N3"})

    def test_single_write_initializer_alias_stays_below_loop(self):
        source = """int main(int n, char**) {
            const int offset = 0;
            for (int i = 0; i < n; ++i) {
                int start = offset;
                for (int j = start; j < n; ++j) {}
            }
        }"""
        nodes = self.nodes(source)
        self.assertEqual(nodes[2]["source_preview"], "int start = offset;")
        fits = self.fits(nodes, {"N2": SCALES, "N3": SCALES, "N4": [n**2 for n in SCALES]})
        slicing = self.pipeline.evaluate_four_slicing_tiers(nodes, fits)
        self.assertEqual(slicing["c_pruned"], ["N3", "N4"])
        self.assertEqual(self.rank(source, nodes, fits, slicing), ["N4", "N3"])

    def test_single_write_actual_loop_bounds_stay_first(self):
        cases = {
            "PAIR_033": ("N12", "N13", "N14", "radius_lim"),
            "PAIR_034": ("N12", "N13", "N14", "radius_lim"),
            "PAIR_035": ("N11", "N12", "N13", "band_end"),
            "PAIR_036": ("N11", "N12", "N13", "band_end"),
        }
        pairs = {pair["pair_id"]: pair for pair in self.pipeline.generate_pilot_100_corpus()}
        for pair_id, (start, bound, inner, name) in cases.items():
            with self.subTest(pair_id=pair_id):
                source = pairs[pair_id]["slow_code"]
                nodes = self.nodes(source)
                by_id = {node["id"]: node for node in nodes}
                self.assertEqual(by_id[bound]["source_preview"], f"int {name} = n;")
                self.assertEqual([node["id"] for node in nodes if name in node["defs"]], [bound])
                counts = {node["id"]: SCALES for node in nodes
                          if node["role"] == "LOOP" or node["parent"] in by_id
                          and by_id[node["parent"]]["role"] == "LOOP"}
                counts[inner] = [n**2 for n in SCALES]
                counts.update({node["id"]: counts[inner] for node in nodes if node["parent"] == inner})
                fits = self.fits(nodes, counts)
                slicing = self.pipeline.evaluate_four_slicing_tiers(nodes, fits)
                self.assertEqual(slicing["primary_symptom"], inner)
                self.assertEqual(slicing["c_pruned"], [start, bound, inner])
                ranked = self.rank(source, nodes, fits, slicing)
                self.assertCountEqual(ranked, slicing["c_pruned"])
                self.assertEqual(ranked[0], bound)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--pipeline", type=Path, default=None)
    options = cli.parse_args()
    if options.pipeline is not None:
        Phase2Selection.pipeline_path = options.pipeline.resolve()
    unittest.main(argv=[sys.argv[0]], verbosity=2)
