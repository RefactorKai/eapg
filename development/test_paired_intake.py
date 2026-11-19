"""Verify the development draw and its input safeguards without dataset files."""

import json
from pathlib import Path
import unittest
from unittest.mock import Mock

from paired_study import intake


class DevelopmentDrawTest(unittest.TestCase):
    def test_draw_uses_one_case_per_group_and_ignores_input_order(self):
        rows = [(f"group-{i}", f"case-{j}", (i, j)) for i in range(15) for j in range(3)]
        first = intake.draw("desk-test", rows, group_count=15, case_count=45)
        second = intake.draw("desk-test", reversed(rows), group_count=15, case_count=45)
        self.assertEqual(first, second)
        self.assertEqual(len({group for group, _ in first}), 12)

    def test_duplicate_and_incomplete_inventories_are_rejected(self):
        rows = [("p1", "pair", None), ("p1", "pair", None)]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            intake.draw("desk-test", rows, group_count=1, case_count=2)
        with self.assertRaisesRegex(ValueError, "inventory size"):
            intake.draw("desk-test", rows[:1], group_count=2, case_count=1)

    def test_unpinned_inputs_are_rejected(self):
        path = Mock(spec=Path)
        path.read_bytes.return_value = json.dumps({
            "sha": intake.CPPPERF_REVISION, "truncated": True,
        }).encode("utf-8")
        with self.assertRaisesRegex(ValueError, "pinned PIE validation"):
            intake.pie_draw(path)
        with self.assertRaisesRegex(ValueError, "complete pinned CppPerf"):
            intake.cppperf_draw(path)
        path.read_bytes.return_value = json.dumps({
            "sha": intake.CPPPERF_REVISION, "truncated": False, "tree": [],
        }).encode("utf-8")
        with self.assertRaisesRegex(ValueError, "checksum"):
            intake.cppperf_draw(path)


if __name__ == "__main__":
    unittest.main()
