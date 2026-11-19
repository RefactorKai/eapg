import unittest

from development.paired_study import panel


class AuthoredPanelTests(unittest.TestCase):
    def test_carry_restart_and_restoration(self):
        case = panel.CASES[0]
        dense = list(range(1, 9))
        self.assertEqual(panel.independent_counts(case.reference, 8, dense), (dense, 8, 0))
        self.assertEqual(panel.independent_counts(case.target, 8, dense), (dense, 36, 0))
        self.assertEqual(panel.independent_counts({"key": panel.CLAMP}, 8, dense), (dense, 8, 0))
        self.assertEqual(panel.independent_counts({"seed": "0"}, 8, dense), (dense, 36, 0))

    def test_nonmonotone_requires_valid_restart(self):
        nonmonotone = [4, 1, 3, 2]
        with self.assertRaisesRegex(ValueError, "rank invariant"):
            panel.independent_counts({}, 4, nonmonotone)
        self.assertEqual(panel.independent_counts({"seed": "0"}, 4, nonmonotone),
                         (nonmonotone, 10, 0))

    def test_finite_range_controls_match_registered_expectations(self):
        for case in panel.CASES:
            with self.subTest(case.id):
                grid = panel.workloads(case.nonmonotone)
                counts = {}
                for name, opts in (("target", case.target), ("reference", case.reference)):
                    counts[name] = {key: sum(panel.independent_counts(opts, key[1], queries)[1:])
                                    for key, queries in grid.items()}
                pairs = {key: (counts["target"][key], counts["reference"][key]) for key in grid}
                actual = all(row["positive"] for row in panel.screen(pairs).values())
                self.assertEqual(actual, case.positive)

    def test_source_spans_and_killed_definition(self):
        template = panel.TEMPLATE.read_text(encoding="utf-8")
        case = panel.CASES[2]
        units, span_map = panel.changed_units(template, case)
        self.assertEqual(list(units), ["killed", "seed"])
        baseline, _ = panel.source_and_spans(template, case.reference)
        self.assertEqual(span_map["reference_source_sha256"], panel.digest(baseline))
        raw = (2, 0, 3, 8, 0, 0, 0, 0, 3, 0)
        example = panel.graph(raw, case.target, units, 8, 2, 3)
        by_id = {n["id"]: n for n in example["nodes"]}
        self.assertEqual(by_id["rank-loop"]["parents"], ["entry"])
        self.assertEqual(by_id["copy-2"]["parents"], ["copy-1"])
        self.assertEqual(by_id["copy-1"]["parents"], ["seed"])
        self.assertEqual(by_id["seed"]["parents"], [])
        self.assertEqual(by_id["seed"]["unit"], units["seed"])
        self.assertEqual(by_id["killed-write"]["unit"], units["killed"])
        self.assertNotIn("killed-write", {p for n in example["nodes"] for p in n["parents"]})

    def test_trace_parser_rejects_tampering(self):
        grid = {("dense", 2): [1, 2]}
        options = {"seed": "0", "extra": "2"}
        expected = {("dense", 2): ([1, 2], 3, 4)}
        wire = b"0 0 1 0 0 0 0 0 1 2\n1 0 2 1 0 0 0 0 2 2\nTRACE 3 4\n"
        row = panel.parse_trace(wire, options, {}, grid, expected)["dense", 2]
        self.assertEqual(row["work"], 7)
        self.assertEqual(row["episodes"][1]["other_events"][0]["count"], 2)
        for invalid in (wire.replace(b"TRACE 3 4", b"TRACE 3 5"),
                        wire.replace(b"1 0 2 1", b"1 0 2 0"), wire + b"EXTRA\n"):
            with self.assertRaises(ValueError):
                panel.parse_trace(invalid, options, {}, grid, expected)


if __name__ == "__main__":
    unittest.main()
