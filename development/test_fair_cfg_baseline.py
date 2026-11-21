"""Regression tests for frozen-slice fair CFG policies."""

from fractions import Fraction
from itertools import permutations
import json
import unittest

import fair_cfg_baseline as fair


class FairCFGBaselineTests(unittest.TestCase):
    def fixture(self):
        return {"cands": ["N1", "N3", "N5", "N7"],
                "rank": ["N7", "N1", "N3", "N5"],
                "scoped_cands": ["N3", "N5"], "scoped_rank": ["N3", "N5"],
                "symptom": "N5", "accepted": ["N3", "N7"]}

    def test_policy_orders(self):
        row = self.fixture()
        expected = (["N7", "N1", "N3", "N5"], ["N5", "N7", "N1", "N3"],
                    ["N7", "N1", "N3", "N5"], ["N3", "N1", "N5", "N7"],
                    ["N5", "N3", "N7", "N1"], ["N3", "N7", "N1"], ["N3", "N5"])
        for policy, order in zip(fair.POLICIES, expected):
            with self.subTest(policy=policy):
                self.assertEqual(fair.ranking(row, policy), order)

    def test_uniform_matches_enumeration_with_multiple_accepted(self):
        row = self.fixture()
        scores = []
        for order in permutations(row["cands"]):
            scores.append(fair.case_metrics(dict(row, rank=list(order)), "reported CFG"))
        expected = tuple(sum(s[i] for s in scores) / len(scores) for i in range(4))
        self.assertEqual(fair.case_metrics(row, "uniform CFG"), expected)

    def test_empty_and_missing_reference(self):
        row = dict(self.fixture(), cands=[], rank=[], scoped_cands=[], scoped_rank=[])
        for policy in fair.POLICIES:
            self.assertEqual(fair.case_metrics(row, policy), (0, 0, 0, 0))
        for policy in fair.POLICIES:
            self.assertEqual(fair.case_metrics(dict(self.fixture(), accepted=["N99"]), policy), (0, 0, 0, 0))
        self.assertIsNone(fair.summarize([], "reported CFG")["top1"]["rate"])

    def test_uniform_singleton_and_all_accepted(self):
        for cands in (["N5"], ["N1", "N3", "N5", "N7"]):
            row = dict(self.fixture(), cands=cands, rank=cands, accepted=cands)
            self.assertEqual(fair.case_metrics(row, "uniform CFG"), (1, 1, 1, 1))

    def test_invalid_inputs(self):
        row = self.fixture()
        for invalid in (dict(row, cands=["N1", "N1"]), dict(row, rank=["N99"]),
                        dict(row, rank=["N1", "N1"])):
            with self.assertRaises(ValueError):
                fair.case_metrics(invalid, "reported CFG")
        with self.assertRaisesRegex(ValueError, "Missing symptom"):
            fair.ranking(dict(row, symptom=None), "nearest preceding CFG")
        with self.assertRaisesRegex(ValueError, "Unknown policy"):
            fair.ranking(row, "invalid")

    def test_exclusion_preserves_slice_retention(self):
        row = dict(self.fixture(), accepted=["N5"])
        self.assertEqual(fair.case_metrics(row, fair.POLICIES[5]), (1, 0, 0, 0))
        self.assertEqual(fair.case_metrics(row, "reported CFG"), (1, 0, 0, Fraction(1, 4)))

    def test_committed_outputs_and_coverage(self):
        receipt = fair.build_receipt()
        reconciliation = receipt["audit_anchor_reconciliation"]
        self.assertEqual(reconciliation["core"]["exact_count"], "1483/360")
        self.assertEqual(reconciliation["all_confirmed_positive"]["exact_count"], "1543/360")
        self.assertEqual(reconciliation["all_confirmed_positive"]["denominator"], 21)
        self.assertEqual(json.loads(fair.OUTPUT.read_text()), json.loads(json.dumps(receipt)))
        self.assertEqual(fair.TABLE.read_text(), fair.render_table(receipt))
        part_b = [r for r in receipt["results"] if r["cohort"] == "Part B"]
        self.assertEqual(sum(r["metrics"] is not None for r in part_b), 1)
        self.assertEqual(next(r["metrics"] for r in part_b if r["metrics"])["top1"]["count"], 6)


if __name__ == "__main__":
    unittest.main()
