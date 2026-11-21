"""Check that a full census extends the original draw on a shuffled frame."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from . import census, intake


def test_census_extends_legacy_draw():
    rows = [(f"group-{group}", f"case-{case}", {"group": group, "case": case})
            for group in range(15) for case in range(3)]
    legacy = intake.draw("desk-test", rows, group_count=15, case_count=45)
    extended = census.draw_all("desk-test", list(reversed(rows)), group_count=15, case_count=45)
    assert intake.canonical_json(extended[:12]) == intake.canonical_json(legacy)
    assert len({row["group"] for row in extended}) == 15


def test_census_rejects_sealed_path_before_opening():
    path = Mock(spec=Path, name="pie-test-path")
    path.name = "pie_test.jsonl"
    with pytest.raises(ValueError, match="sealed PIE"):
        next(census.pie_records(path))
    path.read_bytes.assert_not_called()
