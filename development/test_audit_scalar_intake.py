"""Unit tests for the development-only 10-group OEIS scalar intake feasibility audit."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

import audit_scalar_intake as intake
from run_phase2_development import load_module


ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = Path(__file__).resolve().parent / "scalar_intake_feasibility.json"


@unittest.skipUnless(shutil.which("g++") is not None, "g++ is required for C++17 syntax and preprocessing checks")
class ScalarIntakeAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if intake.PROSPECTIVE_DEFAULT.exists():
            cls.pipeline = load_module("test_scalar_intake_pipeline", intake.PROSPECTIVE_DEFAULT, intake.PROSPECTIVE_SHA)
        else:
            with TemporaryDirectory(prefix="eapg-prospective-") as tmp:
                prospective = Path(tmp) / "prospective.py"
                subprocess.run(
                    [sys.executable, "-B", str(ROOT / "development/build_candidate.py"), "--prospective", str(prospective)],
                    cwd=str(ROOT), check=True, stdout=subprocess.DEVNULL,
                )
                cls.pipeline = load_module("test_scalar_intake_pipeline", prospective, intake.PROSPECTIVE_SHA)
        intake.attach_trusted_cpp_runner(cls.pipeline)
        cls.results = []
        for spec in intake.build_oeis_candidates():
            if "force_rejection" in spec:
                status, reason = spec["force_rejection"]
                res = {"status": status, "reason": reason, "slot": spec["slot"],
                       "mechanism_family": spec["mechanism_family"]}
            else:
                res = intake.check_slot(cls.pipeline, spec)
            cls.results.append({"oeis_id": spec["oeis_id"], "oeis_group": spec["oeis_group"],
                                "description": spec["description"], **res})
        cls.by_id = {row["oeis_id"]: row for row in cls.results}

    def test_funnel_counts_and_report_consistency(self):
        eligible = [row for row in self.results if row["status"] == "eligible_static_and_analytic"]
        funnel = {
            "oeis_groups_covered": len({row["oeis_group"] for row in self.results}),
            "proposed_specs": len(self.results),
            "semantic_or_single_stmt_rejected": sum(
                row["status"] in ("semantic_mismatch_rejected", "intervention_rejected") for row in self.results
            ),
            "domain_or_mapping_rejected": sum(
                row["status"] in ("syntax_error", "normalized_syntax_error", "parse_error",
                                  "unsupported_comparator", "node_limit_exceeded", "unresolved_reference")
                for row in self.results
            ),
            "growth_band_failed": sum(row["status"] == "growth_band_failed" for row in self.results),
            "eligible_static_and_analytic": len(eligible),
            "eligible_distinct_oeis_groups": len({row["oeis_group"] for row in eligible}),
            "eligible_distinct_mechanisms": len({row["mechanism_family"] for row in eligible}),
            "scoped_top1_on_eligible": sum(row["analytic_arms"]["work_scoped"]["top1_hit"] for row in eligible),
            "conventional_top1_on_eligible": sum(row["analytic_arms"]["work_conventional"]["top1_hit"] for row in eligible),
            "scoped_retained_on_eligible": sum(row["analytic_arms"]["work_scoped"]["retained"] for row in eligible),
            "conventional_retained_on_eligible": sum(row["analytic_arms"]["work_conventional"]["retained"] for row in eligible),
        }
        expected = {
            "oeis_groups_covered": 10,
            "proposed_specs": 11,
            "semantic_or_single_stmt_rejected": 4,
            "domain_or_mapping_rejected": 0,
            "growth_band_failed": 2,
            "eligible_static_and_analytic": 5,
            "eligible_distinct_oeis_groups": 5,
            "eligible_distinct_mechanisms": 4,
            "scoped_top1_on_eligible": 3,
            "conventional_top1_on_eligible": 0,
            "scoped_retained_on_eligible": 4,
            "conventional_retained_on_eligible": 5,
        }
        self.assertEqual(funnel, expected)
        saved = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(saved["schema"], "eapg-dev-scalar-intake-feasibility-v2")
        self.assertEqual(saved["funnel"], funnel)
        self.assertEqual(saved["candidates"], self.results)

    def test_slope_floor_rejects_theoretical_half_gap_examples(self):
        for oeis_id in ("A006218_quotient", "A002088"):
            row = self.by_id[oeis_id]
            self.assertEqual(row["status"], "growth_band_failed", msg=oeis_id)
            self.assertFalse(row["band_pass"])
            self.assertLess(row["analytic_slope"], 0.55)

    def test_a400004_exposes_two_scope_retention_boundary(self):
        row = self.by_id["A400004"]
        self.assertEqual(row["status"], "eligible_static_and_analytic")
        self.assertEqual(row["reference_node"], "N7")
        self.assertGreaterEqual(row["analytic_slope"], 0.55)
        self.assertFalse(row["analytic_arms"]["work_scoped"]["retained"])
        self.assertEqual(row["analytic_arms"]["work_scoped"]["candidates"], ["N9"])
        self.assertTrue(row["analytic_arms"]["work_conventional"]["retained"])
        self.assertFalse(row["analytic_arms"]["work_conventional"]["top1_hit"])

    def test_distinct_templates_can_share_monotone_cursor_reset_mechanism(self):
        disk = self.by_id["A000328"]
        wythoff = self.by_id["A000201"]
        self.assertEqual(disk["mechanism_family"], "monotone_cursor_reset")
        self.assertEqual(wythoff["mechanism_family"], "monotone_cursor_reset")
        self.assertNotEqual(disk["template_sha256"]["original"], wythoff["template_sha256"]["original"])
        self.assertNotEqual(disk["template_sha256"]["edited"], wythoff["template_sha256"]["edited"])
        self.assertTrue(disk["analytic_arms"]["work_scoped"]["top1_hit"])
        self.assertTrue(wythoff["analytic_arms"]["work_scoped"]["top1_hit"])


if __name__ == "__main__":
    unittest.main()
