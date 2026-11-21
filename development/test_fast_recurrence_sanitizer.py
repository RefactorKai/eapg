"""Check the committed UBSan receipt for the 25 corrected fast recurrences."""

import hashlib
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import check_fast_recurrence_sanitizer as sanitizer  # noqa: E402


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FastRecurrenceSanitizerTests(unittest.TestCase):
    def setUp(self):
        self.receipt = json.loads(sanitizer.RESULTS.read_text("utf-8"))

    def test_receipt_binds_current_inputs(self):
        self.assertEqual(self.receipt["script_sha256"], digest(HERE / "check_fast_recurrence_sanitizer.py"))
        self.assertEqual(self.receipt["scaling_results_sha256"], digest(sanitizer.SCALING_RESULTS))
        self.assertEqual(self.receipt["pipeline_sha256"], digest(sanitizer.ROOT / "pipeline.py"))
        self.assertEqual(tuple(self.receipt["compiler_flags"]), sanitizer.FLAGS)

    def test_corrected_programs_clean_and_frozen_programs_trap_at_92(self):
        records = self.receipt["records"]
        scaling = json.loads(sanitizer.SCALING_RESULTS.read_text("utf-8"))["records"]
        self.assertEqual([r["pair_id"] for r in records], [r["pair_id"] for r in scaling])
        self.assertEqual(sorted(r["mechanism"] for r in records), ["A2.1"] * 13 + ["B.3"] * 12)
        self.assertIn("92", {str(n) for n in self.receipt["sizes"]})
        for record in records:
            for n, entry in record["sizes"].items():
                for build in ("corrected", "instrumented"):
                    self.assertEqual((entry[build]["exit_code"], entry[build]["finding"]), (0, None),
                                     (record["pair_id"], build, n))
            self.assertIsNone(record["sizes"]["91"]["frozen"]["finding"], record["pair_id"])
            self.assertIn("signed integer overflow", record["sizes"]["92"]["frozen"]["finding"], record["pair_id"])

    @unittest.skipUnless(shutil.which("g++"), "g++ is required for the live sanitizer check")
    def test_live_sanitizer_run_at_92(self):
        scaling = json.loads(sanitizer.SCALING_RESULTS.read_text("utf-8"))["records"]
        generated = {r["pair_id"]: r for r in sanitizer.generate_pilot_100_corpus()}
        for mechanism in ("A2.1", "B.3"):
            record = next(r for r in scaling if r["mechanism"] == mechanism)
            with self.subTest(pair_id=record["pair_id"]), TemporaryDirectory() as workdir:
                binary = Path(workdir) / "corrected"
                sanitizer.compile_source(record["corrected_fast_code"], binary)
                result, finding = sanitizer.run(binary, 92, generated[record["pair_id"]]["input_gen"])
                self.assertEqual((result.returncode, finding, result.stderr), (0, None, ""))
                committed = next(r for r in self.receipt["records"] if r["pair_id"] == record["pair_id"])
                self.assertEqual(result.stdout.strip(), committed["sizes"]["92"]["corrected"]["stdout"])


if __name__ == "__main__":
    unittest.main()
