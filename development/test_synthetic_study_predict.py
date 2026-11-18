"""Test the blind operator with authored packets and an inert pipeline module."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from score_synthetic import SEEDS, validate_prediction
from synthetic_arms import ARM_IDS
from synthetic_frame import canonical
from synthetic_study_predict import BASELINE, ROOT, SCHEMA, predict_study, prediction_revision
from synthetic_trace import SCHEMA as TRACE_SCHEMA


PIPELINE_CODE = b"# Authored pipeline. This packet never needs a fit.\n"
PIPELINE_SHA = sha256(PIPELINE_CODE).hexdigest()
NORMALIZED = "// caf\N{LATIN SMALL LETTER E WITH ACUTE}\nint main() {}"
NORMALIZED_SHA = sha256(NORMALIZED.encode()).hexdigest()
PROJECTION = {"schema": TRACE_SCHEMA, "normalized_source": NORMALIZED, "normalized_source_sha256": NORMALIZED_SHA,
              "nodes": [{"id": "N1", "role": "STATE_UPD", "parent": "MAIN_SCOPE", "source_preview": "n += 1;"}],
              "seeds": {str(seed): {"status": "insufficient_clean_rows", "runs": [
                  {"n": 8, "status": "CLEAN_COMPLETION", "nodes": {"N1": {"cnt": 4, "work": 4}}}
              ]} for seed in SEEDS}}
PACKET = {"schema": SCHEMA, "draw_sha256": "a" * 64, "labels_sha256": "b" * 64,
          "pipeline_sha256": PIPELINE_SHA, "cases": [{"case_id": "opaque-01", "projection": PROJECTION},
                                                    {"case_id": "opaque-02", "projection": None}]}


class SyntheticStudyPredictTests(unittest.TestCase):
    def setUp(self):
        self.pipeline = SimpleNamespace(source_sha256=PIPELINE_SHA)
        self.pin = prediction_revision()

    def test_ledger_uses_ordered_cases_seeds_and_opaque_links(self):
        report = predict_study(self.pipeline, PACKET, self.pin)
        self.assertEqual(set(report), {"schema", "draw_sha256", "labels_sha256", "runner_sha256", "pipeline_sha256",
                                       "baseline_sha256", "arm_ids", "predictions"})
        self.assertEqual(report["schema"], "eapg-synthetic-predictions-v1")
        self.assertEqual(report["draw_sha256"], PACKET["draw_sha256"])
        self.assertEqual(report["labels_sha256"], PACKET["labels_sha256"])
        self.assertEqual(report["runner_sha256"], self.pin)
        self.assertEqual(report["baseline_sha256"], sha256((ROOT / BASELINE).read_bytes()).hexdigest())
        rows = report["predictions"]
        self.assertEqual([(row["case_id"], row["seed"]) for row in rows], [
            (case["case_id"], seed) for case in PACKET["cases"] for seed in SEEDS
        ])
        for row in rows:
            unavailable = row["case_id"] == "opaque-02"
            label = {"disposition": "quarantined" if unavailable else "confirmed_positive",
                     "normalized_source_sha256": None if unavailable else NORMALIZED_SHA,
                     "canonical_node_ids": [] if unavailable else ["N1"]}
            status = "unavailable" if unavailable else "insufficient_clean_rows"
            validate_prediction(row, label, ARM_IDS)
            self.assertEqual(row["profile_status"], status)
            self.assertTrue(all(arm == {"alert": None, "symptom_id": None, "candidates": [], "ranking": [],
                                        "status": status} for arm in row["arms"].values()))

    def test_rejects_invalid_pins_and_private_fields(self):
        with self.assertRaisesRegex(ValueError, "runner digest mismatch"):
            predict_study(self.pipeline, PACKET, "0" * 64)
        with self.assertRaisesRegex(ValueError, "pipeline pin mismatch"):
            predict_study(SimpleNamespace(source_sha256="1" * 64), PACKET, self.pin)
        for reason, alter in (
            ("Wrong blind packet schema", lambda pkt: pkt.update(schema="eapg-synthetic-labels-v1")),
            ("ledger link", lambda pkt: pkt.update(labels_sha256="missing")),
            ("fields in blind packet", lambda pkt: pkt.update(protocol_sha256="c" * 64)),
            ("fields in blind case", lambda pkt: pkt["cases"][0].update(expected_counts=[3])),
            ("Invalid blind case ID", lambda pkt: pkt["cases"][1].update(case_id="../label.json")),
            ("Duplicate blind case ID", lambda pkt: pkt["cases"][1].update(case_id="opaque-01")),
            ("projection schema", lambda pkt: pkt["cases"][0]["projection"].update(oracle_stdout="private")),
            ("node binding names", lambda pkt: pkt["cases"][0]["projection"]["nodes"][0].update(uses=[{"label": 1}])),
        ):
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                altered = deepcopy(PACKET)
                alter(altered)
                predict_study(self.pipeline, altered, self.pin)
        altered = deepcopy(PACKET)
        altered["cases"][0]["projection"]["seeds"]["42"] = {"status": "oracle_unverified", "runs": []}
        with self.assertRaisesRegex(ValueError, "Private oracle disposition"):
            predict_study(self.pipeline, altered, self.pin)

    def test_cli_rejects_unpinned_noncanonical_and_mismatched_inputs(self):
        script = Path(__file__).with_name("synthetic_study_predict.py")
        python = [sys.executable, "-B", str(script)]
        revision = subprocess.run([*python, "--print-revision"], check=True, capture_output=True, text=True)
        self.assertEqual(revision.stdout.strip(), self.pin)
        with TemporaryDirectory(dir=ROOT) as folder:
            directory = Path(folder)
            pipeline, packet, output = (directory / name for name in ("pipeline.py", "packet.json", "predictions.json"))
            pipeline.write_bytes(PIPELINE_CODE)
            raw = canonical(PACKET)
            packet.write_bytes(raw)
            args = [*python, "--packet", str(packet), "--packet-sha256", sha256(raw).hexdigest(),
                    "--pipeline", str(pipeline), "--pipeline-sha256", PIPELINE_SHA,
                    "--runner-sha256", self.pin, "--output", str(output)]

            def rejected(option, value, message):
                mutated = args.copy()
                mutated[mutated.index(option) + 1] = value
                result = subprocess.run(mutated, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertFalse(output.exists())

            rejected("--runner-sha256", "0" * 64, "Prediction runner digest mismatch")
            rejected("--packet-sha256", "0" * 64, "Ledger digest mismatch")
            rejected("--pipeline-sha256", "0" * 64, "Blind packet pipeline pin mismatch")
            changed = raw + b"\n"
            packet.write_bytes(changed)
            rejected("--packet-sha256", sha256(changed).hexdigest(), "Noncanonical JSON")
            packet.write_bytes(raw)
            pipeline.write_bytes(b"raise AssertionError('unpinned pipeline was executed')\n")
            rejected("--pipeline", str(pipeline), "Pinned module hash mismatch")
            pipeline.write_bytes(PIPELINE_CODE)

            outcome = subprocess.run(args, check=True, capture_output=True, text=True)
            result = output.read_bytes()
            self.assertEqual(result, canonical(json.loads(result)))
            self.assertEqual(outcome.stdout.split()[0], sha256(result).hexdigest())
            self.assertEqual(result, canonical(predict_study(self.pipeline, PACKET, self.pin)))
            again = subprocess.run(args, capture_output=True, text=True)
            self.assertIn("Prediction output already exists", again.stderr)
            self.assertEqual(output.read_bytes(), result)


if __name__ == "__main__":
    unittest.main()
