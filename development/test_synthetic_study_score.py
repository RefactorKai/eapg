"""Test the registered scoring boundary on the historical scorer's authored fixture."""

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from score_synthetic import score
from synthetic_frame import canonical, commitment
from synthetic_study_score import LEDGERS, score_study, scoring_revision
from test_score_synthetic import fixture


class SyntheticStudyScoreTests(unittest.TestCase):
    def setUp(self):
        draw, labels, predictions, links = fixture()
        self.documents = (draw, labels, predictions)
        self.links = links
        self.pins = {**links, "predictions_sha256": commitment(predictions), "scorer_sha256": scoring_revision(),
                     **{key: predictions[key] for key in ("runner_sha256", "pipeline_sha256", "baseline_sha256")}}

    def test_registered_wrapper_preserves_paired_estimates(self):
        result = score_study(*self.documents, **self.pins)
        self.assertEqual(result, score(*self.documents, **self.links))
        self.assertEqual(result["by_seed"]["42"]["primary"]["paired"]["family_weighted_delta_pp"], -37.5)

    def test_independent_pins_fail_before_estimation(self):
        for key, message in (
            ("scorer_sha256", "Scorer bundle digest mismatch"),
            ("runner_sha256", "Prediction runner digest mismatch"),
            ("pipeline_sha256", "Prediction pipeline digest mismatch"),
            ("baseline_sha256", "Prediction baseline digest mismatch"),
            ("draw_sha256", "Draw ledger digest mismatch"),
            ("labels_sha256", "Labels ledger digest mismatch"),
            ("predictions_sha256", "Predictions ledger digest mismatch"),
        ):
            with self.subTest(pin=key), patch("synthetic_study_score.score") as estimator:
                with self.assertRaisesRegex(ValueError, message):
                    score_study(*self.documents, **dict(self.pins, **{key: "0" * 64}))
                estimator.assert_not_called()
        with patch("synthetic_study_score.score") as estimator:
            with self.assertRaisesRegex(ValueError, "Wrong predictions ledger schema"):
                score_study(self.documents[0], self.documents[1], self.documents[1], **self.pins)
            estimator.assert_not_called()

    def test_cli_verifies_raw_canonical_inputs_and_writes_a_fresh_report(self):
        script = Path(__file__).with_name("synthetic_study_score.py")
        python = [sys.executable, "-B", str(script)]
        printed = subprocess.run([*python, "--print-revision"], capture_output=True, check=True, text=True)
        self.assertEqual(printed.stdout.strip(), self.pins["scorer_sha256"])
        with TemporaryDirectory(dir=script.resolve().parents[1]) as folder:
            directory = Path(folder)
            output = directory / "score.json"
            args = [*python, "--output", str(output)]
            for name, document in zip(LEDGERS, self.documents):
                path = directory / f"{name}.json"
                path.write_bytes(canonical(document))
                args.extend([f"--{name}", str(path)])
            for name, pin in self.pins.items():
                args.extend(["--" + name.replace("_", "-"), pin])

            def reject(option, value, message):
                changed = args.copy()
                changed[changed.index(option) + 1] = value
                run = subprocess.run(changed, capture_output=True, text=True)
                self.assertNotEqual(run.returncode, 0)
                self.assertIn(message, run.stderr)
                self.assertFalse(output.exists())

            reject("--scorer-sha256", "0" * 64, "Scorer bundle digest mismatch")
            reject("--baseline-sha256", "0" * 64, "Prediction baseline digest mismatch")
            reject("--draw", str(directory / "labels.json"), "Ledger digest mismatch")
            path = directory / "labels.json"
            noncanonical = path.read_bytes() + b"\n"
            path.write_bytes(noncanonical)
            reject("--labels-sha256", sha256(noncanonical).hexdigest(), "Noncanonical JSON")
            path.write_bytes(canonical(self.documents[1]))

            result = subprocess.run(args, capture_output=True, check=True, text=True)
            raw = output.read_bytes()
            self.assertEqual(raw, canonical(json.loads(raw)))
            self.assertEqual(raw, canonical(score(*self.documents, **self.links)))
            self.assertEqual(result.stdout.split()[0], sha256(raw).hexdigest())
            again = subprocess.run(args, capture_output=True, text=True)
            self.assertIn("Score output already exists", again.stderr)
            self.assertEqual(output.read_bytes(), raw)


if __name__ == "__main__":
    unittest.main()
