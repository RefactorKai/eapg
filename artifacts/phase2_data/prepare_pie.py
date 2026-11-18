"""Seal the preregistered draw from the official PIE test release."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys
import tarfile
from tempfile import TemporaryDirectory


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "phase1_correction"))
from phase2_custody_and_probes import json_bytes, sha, write_manifest


TEST_SHA = "e0b1ef26a22c0c60022acd469cffffac91fd55304a8161b333ae5aa51005d10b"
TEST_URL = "https://drive.google.com/file/d/1cpgez6RNH42M8c6fCyAWgbFTxdASBlA0/view"
VAL_SHA = "6608a303c5c6ab61e7936599f3aa8cbde67bc36007e1a9739d7868665c531dab"
TESTCASES_SHA = "02f21225ba963ec9de89b3a5e42f2e9647d8333b717a02cf5bd8b4d088b8309c"


def make_frame(data):
    if sha(data) != TEST_SHA:
        raise ValueError("Official test release SHA-256 mismatch")
    rows = [json.loads(line) for line in data.splitlines() if line.strip()]
    if (len(rows), len({row["problem_id"] for row in rows})) != (978, 41):
        raise ValueError("Expected 978 pairs across all 41 official test problems")
    pairs = []
    for row in rows:
        problem, slow, fast = row["problem_id"], row["src_id"], row["tgt_id"]
        if row["language"] != "cpp" or (slow, fast) != (row["submission_id_v0"], row["submission_id_v1"]):
            raise ValueError(f"Unexpected language or submission IDs for {problem}")
        if not row["tests"] or not all(str(test).isdecimal() for test in row["tests"]):
            raise ValueError(f"Missing or invalid test indices for {problem}")
        pairs.append({
            "split": "test", "pair_id": f"{problem}:{slow}:{fast}", "problem_id": problem,
            "slow_sub_id": slow, "fast_sub_id": fast, "slow_code": row["src_code"],
            "fast_code": row["tgt_code"], "test_indices": [int(test) for test in row["tests"]],
        })
    return {
        "release": f"LearningOpt PIE test.jsonl ({TEST_URL}, SHA-256 {TEST_SHA})",
        "usage_terms": "Research copy from the official PIE release. Source: https://github.com/LearningOpt/pie#dataset . Confirm dataset-specific terms before redistribution.",
        "pairs": pairs,
    }


def verify_data():
    frame = make_frame((HERE / "pie_test.jsonl").read_bytes())
    validation = (HERE / "pie_val.jsonl").read_bytes()
    if sha(validation) != VAL_SHA:
        raise ValueError("Official validation release SHA-256 mismatch")
    val_rows = [json.loads(line) for line in validation.splitlines() if line.strip()]
    val_problems = {row["problem_id"] for row in val_rows}
    test_problems = {row["problem_id"] for row in frame["pairs"]}
    if (len(val_rows), len(val_problems)) != (2544, 77) or test_problems & val_problems:
        raise ValueError("Unexpected validation frame or overlapping problem IDs")
    sealed = json.loads((HERE / "pie_test_static_manifest.json").read_text(encoding="utf-8"))
    manifest = sealed["manifest"]
    if sha(json_bytes(manifest)) != sealed["manifest_sha256"] or sha(json_bytes(frame)) != manifest["frame_sha256"]:
        raise ValueError("Static draw does not match the verified test release")
    pairs = manifest["pairs"]
    expected = Counter((pair["problem_id"], index) for pair in pairs for index in pair["test_indices"])
    archive_path = HERE / "pie_merged_testcases.tar.gz"
    if sha(archive_path.read_bytes()) != TESTCASES_SHA:
        raise ValueError("Merged correctness archive SHA-256 mismatch")
    pattern = re.compile(r"merged_test_cases/(p\d+)/(input|output)\.(\d+)\.txt")
    seen = Counter()
    with tarfile.open(archive_path, "r|gz", stream=True) as archive:
        for member in archive:
            match = pattern.fullmatch(member.name)
            if member.isfile() and match and (match[1], int(match[3])) in expected:
                seen[match[1], int(match[3]), match[2]] += 1
    missing = [(p, i, kind) for p, i in expected for kind in ("input", "output") if seen[p, i, kind] != 1]
    if missing:
        raise ValueError(f"Missing or repeated test-case entries: {missing[:8]} ({len(missing)} total)")
    print(f"Verified {len(pairs)} drawn pairs across {len(test_problems)} test problems, "
          f"{sum(expected.values())} test references and {len(expected)} unique input/output pairs.")
    print(f"Validation: {len(val_rows)} pairs, {len(val_problems)} problems, zero test problem overlap.")
    print(f"Provisional static groups: {len(manifest['quarantine']['test_groups'])}")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--verify", action="store_true", help="Verify downloaded releases, sealed draw, and test archive coverage")
    if cli.parse_args().verify:
        verify_data()
        return
    source = HERE / "pie_test.jsonl"
    destination = HERE / "pie_test_static_manifest.json"
    frame = json_bytes(make_frame(source.read_bytes()))
    with TemporaryDirectory(prefix="pie-frame-", dir=HERE) as scratch:
        path = Path(scratch) / "frame.json"
        path.write_bytes(frame)
        write_manifest(path, sha(frame), destination)
    print(f"Sealed provisional static draw in {destination}")


if __name__ == "__main__":
    main()
