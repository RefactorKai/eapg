"""Pins the fresh bit-exact re-execution of the 100-pair pilot used as the WP-A1 baseline."""

from hashlib import sha256
import json
from pathlib import Path
from statistics import mean
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMPARISON = ROOT / "development/fresh_pilot100_comparison.json"
COMPARISON_SHA256 = "6b28f042c3d35e80e6b8cf8044caa7c86bd6218c8c64209488370ff4badda57d"
PILOT = ROOT / "artifacts/scope_isolated_pilot/pilot100_results.json"
TIERS = ("c_naive_hits", "c_naive_work", "c_inter_only", "c_unpruned", "c_pruned")


class FreshPilotComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = COMPARISON.read_bytes()
        cls.comparison = json.loads(cls.raw)
        cls.published = json.loads(PILOT.read_text(encoding="utf-8"))

    def test_pinned_digest(self):
        self.assertEqual(sha256(self.raw).hexdigest(), COMPARISON_SHA256)

    def test_ran_on_frozen_pipeline(self):
        manifest = dict(line.split("  ", 1)[::-1] for line in (ROOT / "SHA256SUMS").read_text().splitlines() if line)
        self.assertEqual(self.comparison["pipeline_sha256"], manifest["pipeline.py"])

    def test_bit_exact_against_published(self):
        pairs = self.comparison["pairs"]
        self.assertEqual(pairs, len(self.published))
        self.assertTrue(all(count == pairs for count in self.comparison["discrete"].values()))
        for field, stats in self.comparison["numeric"].items():
            self.assertEqual(stats["exact"], stats.get("compared", pairs), field)
            self.assertEqual((stats["max_abs_diff"], stats["median_abs_diff"]), (0.0, 0.0), field)
        self.assertEqual(self.comparison["mismatches"], [])
        self.assertFalse(any(self.comparison["decision_flips"].values()))

    def test_table_i_matches_published_records(self):
        for tier in TIERS:
            sets = [r["slicing"][tier] for r in self.published]
            expected = {
                "coverage": sum(map(bool, sets)),
                "retained": sum(r["gt_node"] in s for r, s in zip(self.published, sets, strict=True)),
                "mean_size": mean(map(len, sets)),
                "mean_reduction_pct": 100 * mean(1 - len(s) / r["v_slow"] for r, s in zip(self.published, sets, strict=True)),
            }
            row = self.comparison["table_i"][tier]
            self.assertEqual(row.keys(), expected.keys(), tier)
            for key, value in expected.items():
                self.assertAlmostEqual(row[key], value, places=9, msg=f"{tier}.{key}")


if __name__ == "__main__":
    unittest.main()
