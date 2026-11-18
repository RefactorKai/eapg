"""Verify the multi-agent prospective scalar study (Part A) and blinded
reference adjudication + live QLoRA external contract study (Part B).
"""

from hashlib import sha256
import json
from math import isclose
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "development"))
from synthetic_study_predict import prediction_revision
from synthetic_study_score import scoring_revision

try:
    from synthetic_study_custodian import custodian_revision
except ImportError:  # -S / no tree_sitter installed
    custodian_revision = None
RESULTS_PATH = ROOT / "development/prospective_multiagent_results.json"
EXPECTED_RESULTS_SHA256 = "2016611a8d142b0068b5e5c03ed9f685a0196c6159510b808ca2135c7928cf81"


def file_sha256(path):
    return sha256(path.read_bytes()).hexdigest()


class ProspectiveMultiagentStudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = RESULTS_PATH.read_bytes()
        assert sha256(raw).hexdigest() == EXPECTED_RESULTS_SHA256
        cls.report = json.loads(raw)

    def test_top_level_provenance_and_code_pins(self):
        r = self.report
        self.assertEqual(r["schema"], "eapg-prospective-multiagent-study-v1")
        self.assertEqual(
            r["execution_environment"]["gate1_probes"],
            {
                "probe_boundaries": "passed",
                "probe_private_scratch": "passed",
                "probe_resource_limits": "passed",
                "probe_cleanup": "passed",
            },
        )
        prov = r["subagent_provenance"]
        self.assertEqual(prov["part_a_verifier"]["role"], "Prospective Scalar Cohort Verifier")
        roles = [row["role"] for row in prov["part_b_reviewers"]]
        self.assertEqual(
            roles,
            [
                "Blinded Reference Reviewer A",
                "Blinded Reference Reviewer B",
                "Blinded Reference Adjudicator C",
            ],
        )

        pins = r["part_a_prospective_scalar"]["code_pins"]
        self.assertEqual(pins["custodian_sha256"], "e0c327f6ee57ff3575e0a8f5d56a2105e6e9293ee531003acb1ff90caa0d797e")
        if custodian_revision is not None:
            self.assertEqual(pins["custodian_sha256"], custodian_revision())
        self.assertEqual(pins["predictor_sha256"], prediction_revision())
        self.assertEqual(pins["scorer_sha256"], scoring_revision())
        self.assertEqual(pins["baseline_sha256"], file_sha256(ROOT / "development/backward_slice.py"))
        self.assertEqual(pins["pipeline_sha256"], "2c95df0e5676e8b19464457adfb34cdf85a8a10cc0dca8b70557a1d587ced383")

    def test_part_a_execution_and_score_invariants(self):
        pa = self.report["part_a_prospective_scalar"]
        self.assertTrue(pa["cross_os_part_a_exact_match"])
        self.assertEqual(
            pa["ledger_hashes"]["score"],
            "ce049b3262f536599d9c332c6a8558fd0073bd94df8f37692e901f25fab6f4b9",
        )
        self.assertEqual(pa["ledger_hashes"]["score"], pa["windows_cross_os_ledger_hashes"]["score"])
        self.assertEqual(
            pa["ledger_hashes"]["frame"],
            "79fe894baef6915f75b0cf0cb96c3f1ddacf1bafa32cbd22d24832e3913827ef",
        )
        self.assertEqual(pa["ledger_hashes"]["frame"], pa["windows_cross_os_ledger_hashes"]["frame"])
        self.assertEqual(
            pa["ledger_hashes"]["draw"],
            "e7b6d1e5b81cdac4b9372ca7eb770bcfac35b177c8d639a3b7f0c1431d71e180",
        )
        self.assertEqual(
            pa["ledger_hashes"]["quarantine"],
            "9b97ec6b53059c8e69ffb67e8ecd1eaafe1e574449e2297543bf0ecdb4fa46bb",
        )
        counts = pa["execution_counts"]
        self.assertEqual(
            counts,
            {
                "active_families": 10,
                "active_pilot_template_overlap": 0,
                "active_slots": 42,
                "domain_supported_slots": 322,
                "drawn_families": 80,
                "drawn_slots": 322,
                "oracle_builds": 378,
                "oracle_runs": 6804,
                "pilot_exposure_rows": 101,
                "placeholder_bridge_rows": 1,
                "profile_runs": 738,
                "quarantined_slots": 280,
                "real_exposure_collisions": 0,
                "stage_receipts": 105,
                "total_exposure_rows": 102,
            },
        )
        pqa = pa["prompt_quarantine_audit"]
        self.assertEqual(pqa["abstract_graph"], {"active_cases_checked": 21, "pilot_unique_prompts": 38, "token_sequence_collisions": 0})
        self.assertEqual(pqa["hotspot_raw"], {"active_cases_checked": 21, "pilot_unique_prompts": 80, "token_sequence_collisions": 0})

        by_seed = pa["score_summary"]["by_seed"]
        self.assertEqual(sorted(by_seed), ["42", "43", "44"])
        for seed in ("42", "43", "44"):
            s = by_seed[seed]
            self.assertEqual(s["primary"]["families"], 10)
            self.assertEqual(s["primary"]["cases"], 20)
            ws = s["primary"]["arms"]["work_scoped"]
            wc = s["primary"]["arms"]["work_conventional"]
            sym = s["primary"]["arms"]["work_scoped_symbolic"]
            self.assertEqual((ws["top1"]["count"], wc["top1"]["count"], sym["top1"]["count"]), (15, 0, 14))
            self.assertEqual((ws["retention"]["count"], wc["retention"]["count"]), (16, 20))
            self.assertTrue(isclose(ws["mean_reduction_emitted"], 0.8937750875715272, rel_tol=0, abs_tol=1e-12))
            self.assertTrue(isclose(wc["mean_reduction_emitted"], 0.6433676318951087, rel_tol=0, abs_tol=1e-12))
            self.assertEqual(s["primary"]["paired"]["family_weighted_delta_pp"], 75.0)
            self.assertEqual(s["primary"]["paired"]["family_bootstrap_95pct_delta_pp"], [60.0, 90.0])

            off = s["author_off_site"]
            self.assertEqual(off["arms"]["work_scoped"]["top1"]["count"], 6)
            self.assertEqual(off["arms"]["work_conventional"]["top1"]["count"], 0)
            self.assertEqual(off["arms"]["work_scoped_symbolic"]["top1"]["count"], 5)
            self.assertEqual(off["paired"]["family_bootstrap_95pct_delta_pp"], [30.0, 90.0])

            mc = s["multi_candidate"]
            self.assertEqual(mc["cases"], 9)
            self.assertEqual(mc["arms"]["work_scoped"]["top1"]["count"], 6)
            self.assertEqual(mc["arms"]["work_scoped_symbolic"]["top1"]["count"], 5)

            alerts = s["alerts"]["work_scoped"]
            self.assertEqual(alerts["confirmed_sham"]["alerts_over_all"]["count"], 5)
            self.assertEqual(alerts["confirmed_appropriate"]["alerts_over_all"]["count"], 10)
            self.assertEqual(s["comparator_swap"]["verified_pairs"], 1)

        rows = pa["active_slot_details"]
        self.assertEqual(len(rows), 42)
        pos_rows = [row for row in rows if row["disposition"] == "confirmed_positive"]
        self.assertEqual(len(pos_rows), 21)
        self.assertEqual(sum(1 for row in pos_rows if row["work_scoped_hit"]), 16)
        self.assertEqual(sum(1 for row in pos_rows if row["work_conv_hit"]), 0)

        gpu = pa["neural_live_slice_eval"]
        expected_gpu = {
            "base_abstract_graph_constrained": (12, 21, 7 / 12, None, 12, 0.6),
            "base_abstract_graph_unconstrained": (0, 21, 0.0, None, 0, 0.0),
            "qlora_abstract_graph_fold0_constrained": (11, 21, 8 / 15, "33dfb098f723365b98b98a396d23e0005c353963c26283f908b3367084527637", 11, 0.55),
            "qlora_abstract_graph_fold0_unconstrained": (2, 21, 0.1, "33dfb098f723365b98b98a396d23e0005c353963c26283f908b3367084527637", 2, 0.1),
            "qlora_hotspot_raw_fold0_constrained": (14, 21, 0.65, "78f27b5bb12d96d7b556e9ae882f3cedeb1a3d64b967986de43335fa2ae2e28e", 13, 0.65),
        }
        for key, (hits, cases, macro, asha, core_hits, core_macro) in expected_gpu.items():
            entry = gpu[key]
            self.assertEqual((entry["hits"], entry["cases"], entry["adapter_sha256"]), (hits, cases, asha))
            self.assertTrue(isclose(entry["family_macro_rate"], macro, rel_tol=0, abs_tol=1e-12))
            self.assertEqual((entry["core_20"]["hits"], entry["core_20"]["cases"]), (core_hits, 20))
            self.assertTrue(isclose(entry["core_20"]["family_macro_rate"], core_macro, rel_tol=0, abs_tol=1e-12))
            self.assertLessEqual(entry["peak_vram_gib"], 2.5)

    def test_part_b_blinded_adjudication_and_oof_contract(self):
        pb = self.report["part_b_blinded_adjudication"]
        self.assertTrue(pb["cross_os_stress_exact_match"])
        self.assertEqual(pb["fold0_adapter_sha256"], "33dfb098f723365b98b98a396d23e0005c353963c26283f908b3367084527637")
        self.assertEqual(sorted(pb["oof_adapter_hashes"]), [f"fold-{i}" for i in range(5)])

        f0_pos = pb["score_fold0"]["D_pos"]
        oof_pos = pb["score_strict_oof"]["D_pos"]
        unb_pos = pb["score_unbiased_symbolic"]["D_pos"]
        unb_rank = pb["score_unbiased_symbolic"]["D_rank"]
        self.assertEqual((oof_pos["pairs"], oof_pos["groups"], oof_pos["singleton_slices"]), (14, 11, 4))
        self.assertEqual(oof_pos["slice_recall"]["count"], 12)
        self.assertEqual(f0_pos["abstract"]["top1"]["count"], 12)
        self.assertEqual(oof_pos["abstract"]["top1"]["count"], 10)
        self.assertEqual(oof_pos["symbolic"]["top1"]["count"], 10)
        self.assertEqual(unb_pos["symbolic"]["top1"]["count"], 6)
        self.assertTrue(isclose(unb_pos["symbolic"]["top1"]["group_macro_rate"], 6 / 11, rel_tol=0, abs_tol=1e-12))
        self.assertEqual(unb_rank["symbolic"]["top1"]["count"], 4)
        self.assertTrue(isclose(unb_rank["symbolic"]["top1"]["group_macro_rate"], 4 / 7, rel_tol=0, abs_tol=1e-12))
        self.assertEqual(unb_pos["top1_contrast_abstract_minus_symbolic"]["discordant_pairs"], {"neural_only": 6, "symbolic_only": 2})
        self.assertEqual(oof_pos["top1_contrast_abstract_minus_symbolic"]["discordant_pairs"], {"neural_only": 2, "symbolic_only": 2})
        self.assertEqual(oof_pos["top1_contrast_abstract_minus_symbolic"]["group_weighted_delta_pp"], 0.0)
        self.assertEqual(pb["score_strict_oof"]["verified_negative_alerts"], {"count": 1, "rate": 0.5, "total": 2})

        details = pb["pair_details"]
        self.assertEqual(len(details), 16)
        self.assertEqual(sum(1 for d in details if d["screening_status"] == "confirmed_positive"), 14)
        self.assertEqual(sum(1 for d in details if d["screening_status"] == "verified_negative"), 2)
        for d in details:
            if d["prompt_tokens"] is not None:
                self.assertLessEqual(d["prompt_tokens"] + 1, 512)


if __name__ == "__main__":
    unittest.main()
