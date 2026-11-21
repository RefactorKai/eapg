"""Unit tests for the pilot Table I re-execution receipt and its comparison rules."""

from copy import deepcopy
import json
import unittest

import reexec_pilot as reexec


class ReexecPilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gen = reexec.load_frozen_pipeline()
        cls.published = reexec.load_published()
        cls.receipt = json.loads(reexec.RECEIPT.read_text(encoding="utf-8"))

    def test_committed_receipt_recomputes_from_raw_counters(self):
        self.assertEqual(reexec.check_receipt_static(self.gen, self.receipt, self.published),
                         sum(r["v_slow"] + r["v_fast"] for r in self.published))

    def test_embedded_sources_match_generator(self):
        corpus = reexec.embedded_corpus(self.gen, self.published)
        self.assertEqual([c["slow_code"] for c in corpus], [r["slow_code"] for r in self.published])
        self.assertTrue(all(callable(c["input_gen"]) for c in corpus))

    def test_identical_records_have_no_mismatch_or_flip(self):
        result = reexec.compare_records(self.published, deepcopy(self.published))
        self.assertEqual((result["mismatches"], result["decision_flips"]), ([], []))
        self.assertEqual(result["decisions_compared"], 18 * len(self.published))

    def test_slice_change_is_a_mismatch_and_a_flip(self):
        fresh = deepcopy(self.published)
        fresh[0]["slicing"]["c_pruned"] = []
        result = reexec.compare_records(self.published, fresh)
        self.assertEqual(result["mismatches"], [f"{fresh[0]['pair_id']}:slicing.c_pruned"])
        self.assertIn(f"{fresh[0]['pair_id']}:c_pruned.retains_reference", result["decision_flips"])

    def test_r2_drift_across_gate_flips_node_decision(self):
        pairs = {"PAIR_001": deepcopy(self.receipt["pairs"]["PAIR_001"])}
        fresh = deepcopy(pairs)
        node = next(iter(fresh["PAIR_001"]["slow"]["nodes"].values()))
        node["fit_work"]["r2_exp"] = 0.0 if node["fit_work"]["r2_exp"] >= reexec.EXP_R2_GATE else 1.0
        result = reexec.compare_counters(pairs, fresh)
        self.assertEqual(len(result["mismatches"]), 1)
        self.assertTrue(any(f.endswith("fit_work.r2_exp_gate") for f in result["decision_flips"]))

    def test_tampered_counter_fails_static_check(self):
        receipt = deepcopy(self.receipt)
        node = next(iter(receipt["pairs"]["PAIR_001"]["slow"]["nodes"].values()))
        node["work"][-1] += 1
        with self.assertRaises(AssertionError):
            reexec.check_receipt_static(self.gen, receipt, self.published)


if __name__ == "__main__":
    unittest.main()
