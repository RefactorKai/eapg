"""Authored execution receipts only. Run with python -B development/test_synthetic_oracle.py."""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from synthetic_oracle import COUNT_MARKER, SEEDS, SIDES, verify_case


POSITIVE = {"original_order": [1, 0], "edited_order": [2, 0], "band": "strong"}
SOURCES = dict(original="same original source", edited="edited source", restored="same original source")
COUNTERS = {side: f"count {side}" for side in SIDES}


def fixture(after=lambda n: n * n, before=lambda n: n):
    return [{"seed": seed, "n": n, "stdin": f"{seed}:{n}\n", "expected_stdout": f"résultat {seed}\n",
             "expected_counts": dict(original=before(n), edited=after(n), restored=before(n))}
            for seed in SEEDS for n in (32, 64, 128, 256, 512, 1024)]


class SyntheticOracleTests(unittest.TestCase):
    def run_case(self, grid=None, *, slot="positive_off_site", growth=POSITIVE, sources=SOURCES, change=None):
        grid = grid if grid is not None else fixture()
        rows = {row["stdin"]: row for row in grid}

        def fake_compile(stage, source, *flags):
            side, build, _ = stage.split()
            self.assertEqual(source, (COUNTERS if build == "counting" else sources)[side])
            self.assertEqual(bool(flags), build == "sanitizer")
            return f"{side} {build}".encode()

        def fake_execute(binary, data):
            side, stage = binary.decode().split()
            row = rows[data.decode()]
            result = SimpleNamespace(returncode=0, stdout=row["expected_stdout"].encode(), stderr=b"",
                                     timed_out=False, events={})
            if stage == "counting":
                result.stdout += COUNT_MARKER + f"{row['expected_counts'][side]}\n".encode()
            if change:
                change(side, stage, row, result)
            return result

        with patch("synthetic_oracle.compile_stage", side_effect=fake_compile) as compile_mock, \
                patch("synthetic_oracle.execute", side_effect=fake_execute):
            report = verify_case(slot, sources, COUNTERS, grid, growth)
        if report["runs"]:
            self.assertEqual(compile_mock.call_count, 9)
            self.assertEqual(len(report["runs"]), 9 * 18)
        else:
            compile_mock.assert_not_called()
        return report

    def test_strong_positive_requires_all_seeds(self):
        good = self.run_case()
        self.assertEqual(good["disposition"], "confirmed_positive")
        self.assertEqual(good["failures"], [])
        for seed, outcome in good["per_seed"].items():
            with self.subTest(seed=seed):
                self.assertAlmostEqual(outcome["slope"], 1.0)
                self.assertEqual(outcome["largest_size_ratio"], 1024)

        grid = fixture()
        for row in grid:
            if row["seed"] == 44:
                row["expected_counts"]["edited"] = 2 * row["n"]
        failed = self.run_case(grid)
        self.assertEqual(failed["disposition"], "growth_failure")
        self.assertEqual(failed["failures"], [{"disposition": "growth_failure", "reason":
                                              "registered_growth_criterion_failed", "seed": 44}])

    def test_both_near_threshold_bands_and_controls(self):
        for band, slope in (("near_below", 0.63), ("near_above", 0.76)):
            counts = fixture(after=lambda n: round(n ** (1 + slope)))
            good = self.run_case(counts, growth=dict(POSITIVE, band=band))
            self.assertEqual(good["disposition"], "confirmed_positive")
            self.assertAlmostEqual(good["per_seed"]["42"]["slope"], slope, places=3)
        sham = self.run_case(fixture(after=lambda n: 3 * n), slot="same_growth_sham",
                             growth={"original_order": [1, 0], "edited_order": [1, 0], "band": "same"})
        self.assertEqual(sham["disposition"], "confirmed_sham")
        counts = fixture(before=lambda n: n * n)
        growth = {"original_order": [2, 0], "edited_order": [2, 0], "band": "appropriate"}
        sources = dict(SOURCES, edited=SOURCES["original"])
        control = self.run_case(counts, slot="appropriate_superlinear", growth=growth, sources=sources)
        self.assertEqual(control["disposition"], "confirmed_appropriate")
        counts[0]["expected_counts"]["edited"] += 1
        invalid = self.run_case(counts, slot="appropriate_superlinear", growth=growth, sources=sources)
        self.assertEqual(invalid["disposition"], "operation_failure")
        self.assertIn("unchanged_source_count_mismatch", {failure["reason"] for failure in invalid["failures"]})

    def test_reports_output_transport_and_restoration_failures(self):
        def corrupt(side, stage, row, result):
            if row["n"] == 32 and row["seed"] == 42:
                if (side, stage) == ("edited", "plain"):
                    result.stdout += b"\n"
                elif (side, stage) == ("edited", "counting"):
                    result.stdout = row["expected_stdout"].encode() + COUNT_MARKER + b"0\n"
                elif (side, stage) == ("restored", "counting"):
                    result.stdout = row["expected_stdout"].encode() + COUNT_MARKER + b"33\n"

        report = self.run_case(change=corrupt)
        self.assertEqual(report["disposition"], "output_failure")
        self.assertEqual({row["reason"] for row in report["failures"]}, {
            "stdout_mismatch", "invalid_count_trailer", "count_formula_mismatch", "restored_count_mismatch",
        })
        self.assertIsNone(report["per_seed"]["42"]["growth_check_passed"])

    def test_rejects_invalid_grid_counts_and_inverse_before_compiling(self):
        grid = fixture()
        grid[-1]["seed"] = 43
        self.assertEqual(self.run_case(grid)["disposition"], "invalid_input")
        grid = fixture()
        grid[0]["expected_counts"]["restored"] = True
        self.assertEqual(self.run_case(grid)["disposition"], "operation_failure")
        self.assertEqual(self.run_case(sources=dict(SOURCES, restored="different"))["disposition"], "invalid_source")

    def test_sanitizer_and_resources_are_explicit(self):
        def fail(side, stage, row, result):
            if side == "edited" and row["n"] == 32 and row["seed"] == 42:
                if stage == "sanitizer":
                    result.returncode = 1
                    result.stderr = b"runtime error: signed integer overflow"
                elif stage == "plain":
                    result.timed_out = True

        report = self.run_case(change=fail)
        self.assertEqual(report["disposition"], "resource_failure")
        self.assertEqual({row["disposition"] for row in report["failures"]}, {"sanitizer_failure", "resource_failure"})


if __name__ == "__main__":
    unittest.main()
