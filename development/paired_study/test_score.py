from copy import deepcopy
from hashlib import sha256
import unittest
from unittest.mock import Mock, patch

from development.paired_study import score


DIGEST = "a" * 64


def fixture():
    registration = {
        "schema": score.REGISTRATION_SCHEMA, "phase": "development",
        "population": "authored", "seed": 42, "arms": ["rewind", "impact"],
        "candidate": "rewind", "comparator": "impact", "gates": None,
        "pins": dict.fromkeys(score.PINS, DIGEST), "cases": [],
    }
    evaluation = {
        "schema": score.EVALUATION_SCHEMA, "registration_sha256": DIGEST, "cases": [],
    }
    predictions = {
        "schema": score.PREDICTIONS_SCHEMA, "registration_sha256": DIGEST, "cases": [],
    }
    rows = [
        ("p1", "g1", "confirmed_positive", [["x"]]),
        ("p2", "g1", "confirmed_positive", [["x"], ["y"]]),
        ("p3", "g2", "confirmed_positive", [["x"]]),
        ("joint", "g3", "confirmed_positive", [["x", "y"]]),
        ("unresolved", "g4", "confirmed_positive", []),
        ("negative", "g5", "verified_negative", []),
        ("pruned", "g6", "insufficient_scales", []),
    ]
    for case, group, status, labels in rows:
        shared = {"id": case, "span_map_sha256": DIGEST}
        registration["cases"].append({**shared, "group": group, "units": ["x", "y", "z"]})
        evaluation["cases"].append({
            **shared, "status": status, "mechanism": "cursor", "location": "off_symptom",
            "timing": "not_measured", "acceptable_sets": labels, "receipt_sha256": DIGEST,
        })
        rewinds = {"alert": True, "status": "ranked", "candidates": ["x", "y"],
                   "ranking": [["x"], ["y"]]}
        impact = {"alert": True, "status": "tie", "candidates": ["x", "y"],
                  "ranking": [["x", "y"]]}
        if case == "p3":
            rewinds = {"alert": True, "status": "unsupported", "candidates": [], "ranking": []}
        if case == "negative":
            rewinds = {"alert": False, "status": "no_alert", "candidates": [], "ranking": []}
        predictions["cases"].append({**shared, "arms": {"rewind": rewinds, "impact": impact}})
    return registration, evaluation, predictions


class PairedStudyScoreTests(unittest.TestCase):
    def test_draw_pin_binds_inventory(self):
        registration, _, _ = fixture()
        registration["pins"]["draw"] = sha256(score.json_bytes(registration["cases"])).hexdigest()
        score.validate_committed_draw(registration)
        registration["cases"][0]["units"].reverse()
        with self.assertRaisesRegex(ValueError, "committed draw"):
            score.validate_committed_draw(registration)

    def test_exact_power_and_interval_edges(self):
        for n, expected in [(35, .433), (60, .727), (71, .805), (80, .855)]:
            self.assertAlmostEqual(score.exact_power(n, .27, .07), expected, places=3)
        self.assertAlmostEqual(score.exact_power(6, .6, .4), .6 ** 6 + .4 ** 6)
        self.assertEqual(score.exact_mcnemar(5, 0), .0625)
        self.assertEqual(score.exact_mcnemar(0, 0), 1)
        self.assertAlmostEqual(score.binomial_upper(0, 29), .098145, places=5)
        self.assertAlmostEqual(score.binomial_upper(0, 10), .258866, places=5)
        self.assertIsNone(score.binomial_upper(0, 0))
        self.assertEqual(score.matched_score_interval(10, 0, 0)[1], 1)
        lo, hi = score.matched_score_interval(0, 0, 10)
        self.assertAlmostEqual(lo, -hi)
        self.assertLess(lo, -.25)
        lo, hi = score.matched_score_interval(26, 9, 45)
        reflected = score.matched_score_interval(9, 26, 45)
        self.assertAlmostEqual(lo, -reflected[1])
        self.assertAlmostEqual(hi, -reflected[0])

    def test_full_draw_groups_ties_abstentions_and_sets(self):
        result = score.score(*fixture(), DIGEST)
        self.assertEqual(result["flow"]["drawn_pairs"], 7)
        self.assertEqual(result["primary"]["table"], {"wins": 1, "losses": 0, "both": 0, "neither": 1})
        self.assertEqual(result["primary"]["inference"], "descriptive")
        self.assertEqual(result["arms"]["rewind"]["top1"]["count"], 2)
        self.assertEqual(result["arms"]["rewind"]["top1"]["total"], 3)
        self.assertEqual(result["arms"]["rewind"]["unresolved_top1_bounds"], [.5, .75])
        self.assertEqual(result["arms"]["impact"]["top1"]["count"], 0)
        self.assertEqual(result["arms"]["impact"]["top2"]["count"], 3)
        self.assertEqual(result["arms"]["impact"]["joint_top2"]["count"], 1)
        self.assertEqual(result["arms"]["impact"]["negative_representative_alerts"]["count"], 1)
        self.assertEqual(result["arms"]["rewind"]["negative_representative_alerts"]["count"], 0)

    def test_reference_selection_does_not_depend_on_order_or_predictions(self):
        registration, evaluation, predictions = fixture()
        first = score.select(registration, evaluation, DIGEST)
        for ledger in (registration, evaluation, predictions):
            ledger["cases"].reverse()
        second = score.select(registration, evaluation, DIGEST)
        self.assertEqual(first["primary"], second["primary"])
        self.assertEqual(first["negative"], second["negative"])
        self.assertNotEqual(first["evaluation_sha256"], second["evaluation_sha256"])
        result = score.score(registration, evaluation, predictions, DIGEST)
        self.assertEqual(result["selection_sha256"], sha256(score.json_bytes(second)).hexdigest())

    def test_invalid_ledgers_fail_closed(self):
        original = fixture()
        for test, edit in (
            ("missing row", lambda r, e, p: p["cases"].pop()),
            ("foreign map", lambda r, e, p: p["cases"][0].update(span_map_sha256="b" * 64)),
            ("duplicate unit", lambda r, e, p: p["cases"][0]["arms"]["rewind"]["ranking"].append(["x"])),
            ("review leak in prediction", lambda r, e, p: p["cases"][0].update(acceptable_sets=[["x"]])),
            ("false first rank", lambda r, e, p: p["cases"][0]["arms"]["rewind"].update(status="tie")),
            ("negative label", lambda r, e, p: e["cases"][5].update(acceptable_sets=[["x"]])),
            ("contradictory oracle sets", lambda r, e, p: e["cases"][0].update(acceptable_sets=[["x"], ["x", "y"]])),
            ("unregistered confirmatory", lambda r, e, p: r.update(phase="confirmatory")),
        ):
            with self.subTest(test), self.assertRaises(ValueError):
                ledgers = deepcopy(original)
                edit(*ledgers)
                score.score(*ledgers, DIGEST)

    def test_read_pinned_rejects_wrong_bytes_and_duplicate_keys(self):
        raw = b'{"cases": [], "cases": []}'
        path = Mock()
        path.name = "ledger.json"
        path.read_bytes.return_value = raw
        with self.assertRaisesRegex(ValueError, "digest"):
            score.read_pinned(path, DIGEST)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            score.read_pinned(path, sha256(raw).hexdigest())
        raw = b'{"cases": []}'
        path.read_bytes.return_value = raw
        self.assertEqual(score.read_pinned(path, sha256(raw).hexdigest()), {"cases": []})

    def test_confirmatory_requires_prospective_power_and_detached_selection(self):
        registration, evaluation, predictions = fixture()
        for i in range(10):
            case = f"independent-{i}"
            registration["cases"].append({**registration["cases"][0], "id": case, "group": f"independent-{i}"})
            evaluation["cases"].append(deepcopy({**evaluation["cases"][0], "id": case}))
            predictions["cases"].append(deepcopy({**predictions["cases"][0], "id": case}))
        registration["phase"] = "confirmatory"
        registration["pins"].update(dict.fromkeys(score.CONFIRMATORY_PINS, DIGEST))
        registration["gates"] = {
            "min_primary_groups": 10, "target_power": .8, "win_probability": .9, "loss_probability": .01,
            "max_false_alert_rate": .1, "practical_margin": .2,
        }
        selection = score.select(registration, evaluation, DIGEST)
        with self.assertRaisesRegex(ValueError, "selection commitment"):
            score.score(registration, evaluation, predictions, DIGEST)
        result = score.score(registration, evaluation, predictions, DIGEST,
                             sha256(score.json_bytes(selection)).hexdigest())
        self.assertEqual(result["primary"]["groups"], 12)
        self.assertTrue(result["primary"]["decision"]["superiority_supported"])
        self.assertFalse(result["primary"]["decision"]["false_alert_target_supported"])
        registration["gates"].update(win_probability=.27, loss_probability=.07)
        with self.assertRaisesRegex(ValueError, "declared paired-test power"):
            score.select(registration, evaluation, DIGEST)

    def test_score_cli_does_not_open_predictions_when_split_receipt_is_missing(self):
        registration, _, _ = fixture()
        registration["phase"] = "confirmatory"
        registration["pins"].update(dict.fromkeys(score.CONFIRMATORY_PINS, DIGEST))
        registration["gates"] = {
            "min_primary_groups": 6, "target_power": .7, "win_probability": .99, "loss_probability": .01,
            "max_false_alert_rate": .1, "practical_margin": .2,
        }
        arguments = ["score", "score"]
        for name in ("registration", "evaluation", "predictions"):
            arguments.extend([f"--{name}", f"{name}.json", f"--{name}-sha256", DIGEST])
        with patch.object(score.sys, "argv", arguments), patch.object(score.sys, "stderr"), \
                patch.object(score, "read_pinned", return_value=registration) as read:
            with self.assertRaises(SystemExit):
                score.main()
            self.assertEqual(read.call_count, 1)
            self.assertEqual(read.call_args.args[0].name, "registration.json")


if __name__ == "__main__":
    unittest.main()
