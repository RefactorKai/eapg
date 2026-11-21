"""WP-S1 receipt checks. Run with python -B development/test_specificity_sweeps.py."""

from copy import deepcopy
import importlib.util
import json
import unittest

import specificity_sweeps as s1


@unittest.skipIf(importlib.util.find_spec("tree_sitter") is None, "tree_sitter is not installed")
class SpecificitySweepsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pipeline = s1.load_pipeline()
        cls.profiles = json.loads(s1.PROFILES.read_text(encoding="utf-8"))
        cls.receipt = json.loads(s1.RECEIPT.read_text(encoding="utf-8"))

    def test_committed_receipt_and_plot_reproduce(self):
        self.assertEqual(s1.main(["--check"]), 0)

    def test_nominal_counts_have_denominators(self):
        seed42 = self.receipt["part_a"]["seed_table"]["42"]
        self.assertEqual({k: (v["k"], v["n"]) for k, v in seed42.items() if k.startswith(("positive", "sham", "appr"))},
                         {"positive": (20, 20), "sham_quadratic": (5, 5), "sham_linear": (0, 5),
                          "sham_all": (5, 10), "appropriate_superlinear": (10, 10)})
        paired = self.receipt["paired"]
        self.assertEqual((paired["nominal"]["alerts"]["k"], paired["nominal"]["alerts"]["n"]), (4, 13))
        self.assertEqual(paired["nominal_with_drop_largest"]["cases"], ["p00256", "p02346", "p03048"])
        self.assertTrue(paired["sensitivity"]["sqlpp11"]["alerts_at_slope_0_ratio_1_50"])
        self.assertFalse(paired["sensitivity"]["sqlpp11"]["alerts_at_slope_0_ratio_1_55"])

    def test_nominal_patched_evaluator_matches_prospective_pipeline(self):
        patched = s1.tier_evaluator(self.pipeline, s1.NOMINAL_GAP, s1.NOMINAL_GAP)
        for case, seeds in s1.part_a_fits(self.pipeline, self.profiles)[:8]:
            nodes = case["projection"]["nodes"]
            self.assertEqual(patched(nodes, seeds[42]), self.pipeline.evaluate_four_slicing_tiers(nodes, seeds[42]))

    def test_tampered_profile_fails_binding(self):
        profiles = deepcopy(self.profiles)
        alerted = {r["case_id"] for r in json.loads(s1.COMMITTED.read_text(encoding="utf-8"))
                   ["part_a_prospective_scalar"]["active_slot_details"] if r["work_scoped_alert"]}
        case, = (c for c in profiles["cases"] if c["slot"] == "same_growth_sham" and c["case_id"] in alerted
                 and c["family"] == "F02_stride_jump")
        for row in case["projection"]["seeds"]["42"]["runs"]:
            for counts in row["nodes"].values():
                counts["work"] = counts["cnt"] = 1
        with self.assertRaises(ValueError):
            s1.bind_part_a(self.pipeline, profiles, s1.part_a_fits(self.pipeline, profiles))

    def test_tampered_paired_alert_fails(self):
        ledger = json.loads(s1.LEDGER.read_text(encoding="utf-8"))
        row, = (r for r in ledger["rows"] if r["case_id"] == "p03999")
        row["all_stream_alert"] = False
        with self.assertRaises(ValueError):
            s1.paired(ledger)


if __name__ == "__main__":
    unittest.main()
