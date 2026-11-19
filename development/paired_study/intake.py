"""Reproduce the metadata-only development draws for the paired C++ desk study."""

import argparse
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re


DRAW_SEED = "eapg-paired-development-2026-11-18-v1"
DRAW_SIZE = 12
PIE_VALIDATION_SHA256 = "6608a303c5c6ab61e7936599f3aa8cbde67bc36007e1a9739d7868665c531dab"
CPPPERF_REVISION = "a7cba4f6ced9535ab652f1589f1e31bf324edfe6"
CPPPERF_INVENTORY_SHA256 = "dd889ce52aaef291f1be5a13c6e85230d1dfb5dfc40cd21d2d6508732df20512"
CPPPERF_PREFIX = "data/dataset/"
CPPPERF_PATH = re.compile(r"([A-Za-z0-9.-]+)_([A-Za-z0-9.-]+)_([0-9a-f]{40})\.json")


def canonical_json(value):
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")


def stable_key(corpus, level, identifier):
    return sha256(canonical_json([DRAW_SEED, corpus, level, identifier])).hexdigest(), identifier


def draw(corpus, rows, *, group_count, case_count):
    groups = defaultdict(list)
    identifiers = set()
    for group_id, case_id, row in rows:
        if (group_id, case_id) in identifiers:
            raise ValueError(f"{corpus}: duplicate case {group_id}/{case_id}")
        identifiers.add((group_id, case_id))
        groups[group_id].append((case_id, row))
    if len(groups) != group_count or len(identifiers) != case_count:
        raise ValueError(f"{corpus}: unexpected inventory size")
    selected = sorted(groups, key=lambda key: stable_key(corpus, "group", key))[:DRAW_SIZE]
    return [
        min(groups[group_id], key=lambda item: stable_key(corpus, "case", f"{group_id}/{item[0]}"))[1]
        for group_id in selected
    ]


def pie_draw(path):
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != PIE_VALIDATION_SHA256:
        raise ValueError("expected the pinned PIE validation file")
    rows = []
    for line in raw.splitlines():
        record = json.loads(line)
        problem, slow, fast = (record[key] for key in ("problem_id", "src_id", "tgt_id"))
        if not re.fullmatch(r"p[0-9]{5}", problem) or any(
            not re.fullmatch(r"s[0-9]{9}", value) for value in (slow, fast)
        ):
            raise ValueError("unexpected PIE case identifier")
        rows.append((problem, f"{slow}::{fast}", {
            "problem_id": problem, "target_submission": slow, "reference_submission": fast,
        }))
    return {
        "input_sha256": PIE_VALIDATION_SHA256, "groups": 77, "cases": 2544,
        "draw": draw("pie-validation", rows, group_count=77, case_count=2544),
    }


def cppperf_draw(path):
    tree = json.loads(path.read_bytes())
    if tree.get("sha") != CPPPERF_REVISION or tree.get("truncated") is not False:
        raise ValueError("expected the complete pinned CppPerf GitHub tree")
    rows = []
    paths = {}
    for entry in tree["tree"]:
        if not entry["path"].startswith(CPPPERF_PREFIX):
            continue
        match = CPPPERF_PATH.fullmatch(entry["path"].removeprefix(CPPPERF_PREFIX))
        if entry["type"] != "blob" or not match or not re.fullmatch(r"[0-9a-f]{40}", entry["sha"]):
            raise ValueError("unexpected CppPerf inventory entry")
        owner, name, commit = match.groups()
        project = f"{owner}/{name}"
        if entry["path"] in paths:
            raise ValueError("duplicate CppPerf inventory path")
        paths[entry["path"]] = entry["sha"]
        rows.append((project.casefold(), commit, {
            "project": project, "reference_commit": commit,
            "metadata_path": entry["path"], "metadata_blob": entry["sha"],
        }))
    inventory_sha256 = sha256(canonical_json(paths)).hexdigest()
    if inventory_sha256 != CPPPERF_INVENTORY_SHA256:
        raise ValueError("CppPerf inventory checksum mismatch")
    return {
        "revision": CPPPERF_REVISION,
        "inventory_sha256": inventory_sha256,
        "groups": 42, "cases": 347,
        "draw": draw("cppperf-db", rows, group_count=42, case_count=347),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pie-validation", type=Path)
    parser.add_argument("--cppperf-tree", type=Path)
    args = parser.parse_args()
    if args.pie_validation is None and args.cppperf_tree is None:
        parser.error("choose at least one development inventory")
    result = {"schema": "paired-development-draw-v1", "seed": DRAW_SEED, "per_corpus": DRAW_SIZE}
    try:
        if args.pie_validation is not None:
            result["pie_validation"] = pie_draw(args.pie_validation)
        if args.cppperf_tree is not None:
            result["cppperf"] = cppperf_draw(args.cppperf_tree)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
