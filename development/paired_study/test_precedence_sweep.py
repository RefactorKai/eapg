from pathlib import Path
from runpy import run_path

import pytest


pytest.importorskip("tree_sitter")
pytest.importorskip("tree_sitter_cpp")

SWEEP = run_path(str(Path(__file__).resolve().parents[2] / "artifacts/paired_development/precedence_sweep.py"))


def scan(source):
    return SWEEP["scan_source"](SWEEP["pinned_parser"](), source)


def test_groups_only_direct_equality_operands_in_original_bytes():
    source = b'''// a == b ^ c != d
auto text = "a == b ^ c != d";
int f() {
    return (a == b /* comment */ ^ c != d)
        + (a == b & (c != d)) + ((a == b) | c == d)
        + ((a == b) ^ (c == d)) + (a == b && c != d) + (a == b || c != d)
        + (a == b xor c != d);
}
'''
    result = scan(source)
    assert result["parse_status"] == "parsed"
    assert [[hit["operator"], [(op["side"], op["operator"]) for op in hit["operands"]]]
            for hit in result["findings"]] == [
        ["^", [("left", "=="), ("right", "!=")]],
        ["&", [("left", "==")]],
        ["|", [("right", "==")]],
    ]
    hit = result["findings"][0]
    assert hit["line"] == 4
    assert source[hit["start_byte"]:hit["end_byte"]] == b"a == b /* comment */ ^ c != d"


def test_marks_macro_and_parse_gaps_while_retaining_clean_regions():
    result = scan(b"#define F(x) (x == 1 ^ 2)\nint f(){return a==b & c==d;}\nvoid f(")
    assert result["parse_status"] == "partial"
    assert {item["reason"] for item in result["coverage_limits"]} == {"opaque_preprocessor_body", "error_node"}
    assert [hit["line"] for hit in result["findings"]] == [2]


def test_missing_node_span_uses_byte_positions():
    result = scan(b"int f() {\nreturn 0\n}")
    assert result["coverage_limits"] == [
        {"reason": "missing_node", "start_byte": 18, "end_byte": 18, "line": 2}
    ]


def test_slot_denominator_separates_partial_parses_from_absence():
    files = [
        {"intake_rank": 1, "status": "verified", "sha256": "a", "parse_status": "parsed", "finding_keys": ["x"]},
        {"intake_rank": 1, "status": "absent"},
        {"intake_rank": 2, "status": "verified", "sha256": "b", "parse_status": "partial", "finding_keys": ["y"]},
        {"intake_rank": 2, "status": "missing"},
    ]
    result = SWEEP["summarize"](files, {1, 2})
    assert (result["eligible_slots"], result["accessible_slots"], result["fully_accessible_slots"]) == (2, 2, 1)
    assert (result["fully_scanned_slots"], result["hit_slots_fully_scanned"], result["hit_slots_partial_scan"]) == (1, 1, [2])
    assert (result["eligible_file_sides"], result["legitimate_absent_sides"], result["missing_file_sides"]) == (3, 1, 1)
