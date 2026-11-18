"""Check paired-arm ranking and profile eligibility without running C++."""

from hashlib import sha256
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backward_slice import UnsupportedProgram
from synthetic_arms import ARM_IDS, predict_seed


class SyntheticArmsTests(unittest.TestCase):
    def setUp(self):
        self.source = "int main() {}"
        self.fit = {"growth": "POLY", "alpha": 2.0, "r2_poly": 1.0}
        self.profile = {
            "normalized_sha256": sha256(self.source.encode()).hexdigest(),
            "nodes": [{"id": "N1"}, {"id": "N2"}],
            "fits": {"42": {nid: {"fit_hits": self.fit.copy(), "fit_work": self.fit.copy()}
                            for nid in ("N1", "N2")}},
            "runs": {"42": [{"n": n, "status": "CLEAN_COMPLETION",
                             "nodes": {"N1": {"cnt": n, "work": n * n}, "N2": {"cnt": 0, "work": 0}}}
                            for n in (8, 16, 32, 64)]},
        }
        self.rank_modes = []

        def select(_nodes, fits):
            self.assertEqual(fits["N2"]["fit_work"]["growth"], "UNAVAILABLE")
            return {"primary_symptom": "N1", "c_pruned": ["N1"], "delta_alphas": {}}

        def rank(record, *, use_loop_def_use, macro_nodes):
            self.assertIs(macro_nodes, self.profile["nodes"])
            self.rank_modes.append(use_loop_def_use)
            return record["slicing"]["c_pruned"][::-1]

        self.pipeline = SimpleNamespace(evaluate_four_slicing_tiers=select,
                                        format_eapg_skeleton=lambda *_: "fixture",
                                        rank_candidates_by_role_priority=rank)

    def arms(self):
        return predict_seed(self.pipeline, self.source, self.profile, 42)["arms"]

    def test_same_symptom_uses_shared_ordering_and_canonical_candidates(self):
        with patch("synthetic_arms.backward_slice", return_value=["N2", "N1"]) as baseline:
            arms = self.arms()
        baseline.assert_called_once()
        self.assertEqual(set(arms), set(ARM_IDS))
        self.assertEqual(self.rank_modes, [False, False, True, False, False])
        self.assertEqual(arms["work_scoped"]["symptom_id"], arms["work_conventional"]["symptom_id"])
        self.assertEqual(arms["work_conventional"]["candidates"], ["N1", "N2"])
        self.assertEqual(arms["work_conventional"]["ranking"], ["N2", "N1"])
        self.assertEqual(arms["hit_growth"]["ranking"], ["N1"])

    def test_unsupported_baseline_preserves_the_observed_alert(self):
        with patch("synthetic_arms.backward_slice", side_effect=UnsupportedProgram("fixture")):
            arms = self.arms()
        self.assertEqual(arms["work_conventional"], {"alert": True, "symptom_id": "N1",
                         "candidates": [], "ranking": [], "status": "unsupported_baseline"})
        self.assertEqual(arms["work_scoped"]["status"], "ranked")

    def test_unavailable_fits_are_not_negative_alerts(self):
        for seed_fit in self.profile["fits"]["42"].values():
            for fit in seed_fit.values():
                fit["r2_poly"] = 0.84
        arms = self.arms()
        self.assertTrue(all(arm["status"] == "no_eligible_fit" and arm["alert"] is None for arm in arms.values()))

    def test_wrong_source_and_censored_grid_fail_before_ranking(self):
        with self.assertRaisesRegex(ValueError, "same normalized source"):
            predict_seed(self.pipeline, self.source + " ", self.profile, 42)
        self.profile["runs"]["42"][-1]["status"] = "CAP_BREACHED"
        with self.assertRaisesRegex(ValueError, "four distinct"):
            self.arms()


if __name__ == "__main__":
    unittest.main()
