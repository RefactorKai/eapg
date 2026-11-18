"""Authored ledger and scoring tests. Run with python -B development/test_score_synthetic.py."""

from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from score_synthetic import ARMS, SEEDS, read_pinned, score


HASH = "a" * 64
NODES = ["N1", "N2", "N3"]


def arm(alert, symptom=None, candidates=(), ranking=(), state=None):
    return {"alert": alert, "symptom_id": symptom, "candidates": list(candidates), "ranking": list(ranking),
            "status": state or ("ranked" if ranking else "no_symptom")}


def payload(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def fixture():
    draw = {"schema": "eapg-synthetic-draw-v1", "protocol_sha256": HASH, "frame_sha256": HASH,
            "draw_seed": 17, "cases": []}
    labels = {"schema": "eapg-synthetic-labels-v1", "source_manifest_sha256": HASH, "quarantine_sha256": HASH, "cases": []}
    predictions = {"schema": "eapg-synthetic-predictions-v1", "runner_sha256": HASH, "pipeline_sha256": HASH,
                   "baseline_sha256": HASH, "arm_ids": list(ARMS), "predictions": []}

    def add(pid, family, disposition, slot, accepted=(), *, left=NODES[:2], right=NODES[:2], profile="complete",
            selector="N1", fit_unavailable=False, left_failure=None):
        draw["cases"].append({"case_id": pid, "intended_slot": slot, "source_sha256": HASH, "workload_sha256": HASH})
        confirmed_positive = disposition == "confirmed_positive"
        labels["cases"].append({"case_id": pid, "family_id": family, "disposition": disposition,
                                "normalized_source_sha256": HASH, "canonical_node_ids": list(NODES),
                                "accepted_node_ids": list(accepted), "operation_evidence_sha256": HASH,
                                "reference_status": ("resolved" if accepted else "unresolved") if confirmed_positive else None,
                                "reference_reason": "ambiguous source origins" if confirmed_positive and not accepted else None})
        for seed in SEEDS:
            if profile != "complete":
                results = {name: arm(None, state=profile) for name in ARMS}
            elif fit_unavailable:
                results = {name: arm(None, state="no_eligible_fit") for name in ARMS}
            elif not selector:
                results = {name: arm(False) for name in ARMS}
                results["hit_growth"] = arm(None, state="no_eligible_fit")
            else:
                seed_left = left if pid != "win" or seed != 43 else right
                results = {
                    "work_scoped": arm(True, selector, seed_left, seed_left if not left_failure else (), left_failure),
                    "work_conventional": arm(True, selector, right, right),
                    "hits_scoped": arm(False), "hits_conventional": arm(False),
                    "work_symptom": arm(True, selector, [selector], [selector]),
                    "work_scoped_symbolic": arm(True, selector, seed_left, seed_left),
                    "hit_growth": arm(None, candidates=NODES, ranking=NODES),
                }
            predictions["predictions"].append({"case_id": pid, "seed": seed,
                                              "normalized_source_sha256": HASH if profile == "complete" else None,
                                              "profile_status": profile, "arms": results})

    add("win", "g1", "confirmed_positive", "positive_off_site", ["N2"], left=["N2", "N1"])
    add("unresolved_distinct", "g1", "confirmed_positive", "positive_at_site", left=["N2", "N1"])
    add("unresolved_tied", "g1", "confirmed_positive", "positive_at_site")
    add("profile_failed", "g1", "confirmed_positive", "positive_off_site", ["N2"], profile="normalization_failure")
    add("loss", "g2", "confirmed_positive", "positive_at_site", ["N1"], left=["N2", "N1"])
    add("sham_alert", "g2", "confirmed_sham", "same_growth_sham")
    add("sham_unavailable", "g3", "confirmed_sham", "same_growth_sham", fit_unavailable=True)
    add("appropriate", "g3", "confirmed_appropriate", "appropriate_superlinear", selector=None)
    add("failed_positive", "g2", "growth_failure", "positive_off_site", left=["N2", "N1"], left_failure="ranking_failure")
    add("qa", None, "quarantined", "positive_at_site", profile="not_run")
    add("swap_pos", "swap", "confirmed_positive", "comparator_swap_positive", ["N1"])
    add("swap_sham", "swap", "confirmed_sham", "comparator_swap_sham")
    draw["allocation"] = dict(Counter(row["intended_slot"] for row in draw["cases"]))
    draw_sha = sha256(payload(draw)).hexdigest()
    labels["draw_sha256"] = predictions["draw_sha256"] = draw_sha
    labels_sha = predictions["labels_sha256"] = sha256(payload(labels)).hexdigest()
    return draw, labels, predictions, {"draw_sha256": draw_sha, "labels_sha256": labels_sha}


class SyntheticScoring(unittest.TestCase):
    def test_estimands_flow_and_controls(self):
        draw, labels, predictions, pins = fixture()
        report = score(draw, labels, predictions, **pins)
        primary_seed = report["by_seed"]["42"]
        primary = primary_seed["primary"]
        self.assertEqual((primary["cases"], primary["families"]), (5, 2))
        self.assertEqual(primary["paired"]["case_weighted_delta_pp"], 0.0)
        self.assertEqual(primary["paired"]["family_weighted_delta_pp"], -37.5)
        self.assertEqual(primary["paired"]["family_bootstrap_95pct_delta_pp"], [-100.0, 25.0])
        self.assertEqual(primary["paired"]["leave_one_family_out_range_delta_pp"], [-100.0, 25.0])
        self.assertEqual([entry["delta_pp"] for entry in primary["paired"]["leave_one_family_out_delta_pp"]], [-100.0, 25.0])
        self.assertEqual(primary["paired"]["discordant_cases"], {"work_scoped": 1, "work_conventional": 1})
        self.assertEqual(primary_seed["reference_bounds"]["family_weighted_delta_pp"], [-50.0, -25.0])
        self.assertEqual(primary_seed["symptom_disagreement"]["paired"]["family_weighted_delta_pp"], 100.0)
        self.assertEqual(primary_seed["author_off_site"]["cases"], 2)
        self.assertEqual(primary_seed["intention_to_test"]["cases"], 7)
        self.assertEqual(primary_seed["intention_to_test"]["arms"]["work_scoped"]["top1"]["count"], 1)
        self.assertEqual(primary_seed["verification_flow"]["quarantined"], {"cases": 1, "families": 0, "unknown_family_cases": 1})
        self.assertEqual(primary_seed["comparator_swap"]["verified_pairs"], 1)
        self.assertEqual(primary_seed["multi_candidate"]["cases"], 4)
        self.assertEqual(primary_seed["multi_candidate_reference_retained"]["uniform_expected_top1"]["rate"], 0.5)
        sham = primary_seed["alerts"]["work_scoped"]["confirmed_sham"]
        self.assertEqual((sham["alerts_over_all"]["rate"], sham["alerts_upper_bound"]["rate"], sham["abstentions"]),
                         (0.5, 1.0, 1))
        appropriate = primary_seed["alerts"]["work_scoped"]["confirmed_appropriate"]
        self.assertEqual((appropriate["alerts_over_all"]["rate"], appropriate["coverage"]["rate"]), (0.0, 1.0))
        self.assertEqual(report["by_seed"]["43"]["primary"]["paired"]["family_weighted_delta_pp"], -50.0)
        self.assertFalse(report["primary_sized"] or report["positive_primary_evidence"] or report["away_from_symptom_evidence"])

    def test_rejects_ledger_and_arm_mismatches(self):
        def pred_case(data, pid):
            return next(row for row in data["predictions"] if row["case_id"] == pid and row["seed"] == 42)

        def ref_case(data, pid):
            return next(row for row in data["cases"] if row["case_id"] == pid)

        draw, labels, pred, pins = fixture()
        for message, mutate in (
            ("cover the draw and seeds", lambda d, l, p: p["predictions"].pop()),
            ("Duplicate predictions", lambda d, l, p: p["predictions"].append(p["predictions"][0])),
            ("Allocation does not match", lambda d, l, p: d["allocation"].update(positive_at_site=1)),
            ("Invalid draw seed or allocation", lambda d, l, p: d["allocation"].update(positive_at_site=True)),
            ("Unexpected seed", lambda d, l, p: p["predictions"][0].update(seed=45)),
            ("Labels digest mismatch", lambda d, l, p: p.update(labels_sha256="b" * 64)),
            ("cover the draw exactly", lambda d, l, p: l["cases"].pop()),
            ("Canonical source mismatch", lambda d, l, p: p["predictions"][0].update(normalized_source_sha256="b" * 64)),
            ("accepted IDs", lambda d, l, p: l["cases"][0].update(accepted_node_ids=["N99"])),
            ("conflicts with draw", lambda d, l, p: l["cases"][0].update(disposition="confirmed_sham")),
            ("part of an origin family", lambda d, l, p: ref_case(l, "qa").update(family_id="g1")),
            ("Unexpected or missing fields", lambda d, l, p: p["predictions"][0].update(accepted_node_ids=["N2"])),
            ("Unexpected or missing fields", lambda d, l, p: pred_case(p, "win")["arms"]["work_scoped"].update(label="N2")),
            ("Shared alert or symptom", lambda d, l, p: pred_case(p, "win")["arms"].update(
                work_conventional=arm(None, state="no_eligible_fit"))),
            ("Shared alert or symptom", lambda d, l, p: pred_case(p, "win")["arms"].update(
                hits_conventional=arm(True, "N1", ["N1"], ["N1"]))),
            ("Invalid work-symptom baseline", lambda d, l, p: pred_case(p, "win")["arms"].update(
                work_symptom=arm(True, "N1", ["N2"], ["N2"]))),
            ("Invalid rank disposition", lambda d, l, p: pred_case(p, "win")["arms"]["work_scoped"].update(ranking=["N1"])),
            ("Comparator-swap source mismatch", lambda d, l, p: ref_case(d, "swap_sham").update(source_sha256="b" * 64)),
            ("Comparator-swap workload mismatch", lambda d, l, p: ref_case(d, "swap_sham").update(workload_sha256="b" * 64)),
            ("Comparator-swap predictions disagree", lambda d, l, p: pred_case(p, "swap_sham")["arms"].update(
                hit_growth=arm(None, candidates=NODES, ranking=NODES[::-1]))),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                edited = deepcopy((draw, labels, pred))
                mutate(*edited)
                score(*edited, **pins)

    def test_cli_checks_all_three_pins_and_duplicate_json_keys(self):
        draw, labels, predictions, _ = fixture()
        with TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp:
            args = [sys.executable, "-B", str(Path(__file__).with_name("score_synthetic.py"))]
            for name, doc in (("draw", draw), ("labels", labels), ("predictions", predictions)):
                path = Path(temp, name + ".json")
                path.write_bytes(payload(doc))
                args.extend(("--" + name, str(path), "--" + name + "-sha256", sha256(path.read_bytes()).hexdigest()))
            result = subprocess.run(args, check=True, capture_output=True)
            self.assertEqual(json.loads(result.stdout)["primary_seed"], 42)
            for name in ("draw", "labels", "predictions"):
                altered = list(args)
                altered[args.index("--" + name + "-sha256") + 1] = "b" * 64
                result = subprocess.run(altered, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"Ledger digest mismatch: {name}.json".encode(), result.stderr)
            duplicate = Path(temp, "duplicate.json")
            duplicate.write_bytes(b'{"x":1,"x":2}')
            with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
                read_pinned(duplicate, sha256(duplicate.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
