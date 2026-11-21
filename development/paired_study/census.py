"""Extend the archived paired-study intake to the pinned Path B census."""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from hashlib import sha1, sha256
import json
from pathlib import Path
import re
from zipfile import BadZipFile, ZipFile

from . import intake


LEGACY_DRAW_SHA256 = "76196f0a83422f44df6f990c8412352c8a647b03cc3dbd362ba6dbbd42e9c5a1"
SEALED_PIE_NAMES = {"pie_test.jsonl", "pie_merged_testcases.tar.gz", "pie_test_static_manifest.json"}


def case_key(corpus: str, item: tuple[str, str, dict]) -> tuple[str, str]:
    return intake.stable_key(corpus, "case", f"{item[0]}/{item[1]}")


def draw_all(corpus: str, rows: list[tuple[str, str, dict]], *, group_count: int, case_count: int) -> list[dict]:
    original = intake.draw(corpus, rows, group_count=group_count, case_count=case_count)
    winners = {}
    for group, _, row in sorted(rows, key=lambda item: case_key(corpus, item)):
        winners.setdefault(group, row)
    order = sorted(winners, key=lambda group: intake.stable_key(corpus, "group", group))
    extended = [winners[group] for group in order]
    if intake.canonical_json(extended[:intake.DRAW_SIZE]) != intake.canonical_json(original):
        raise ValueError(f"{corpus}: extension changed the legacy draw")
    return extended


def pie_records(path: Path) -> Iterator[dict]:
    if path.name.casefold() in SEALED_PIE_NAMES or path.resolve().name.casefold() in SEALED_PIE_NAMES:
        raise ValueError("sealed PIE evaluation data cannot be used for the census")
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != intake.PIE_VALIDATION_SHA256:
        raise ValueError("expected the pinned PIE validation file")
    for line in raw.splitlines():
        yield json.loads(line)


def pie_census(path: Path) -> dict:
    rows = []
    for record in pie_records(path):
        problem, slow, fast = (record[key] for key in ("problem_id", "src_id", "tgt_id"))
        rows.append((problem, f"{slow}::{fast}", {
            "problem_id": problem, "target_submission": slow, "reference_submission": fast,
        }))
    return {"input_sha256": intake.PIE_VALIDATION_SHA256, "groups": 77, "cases": 2544,
            "draw": draw_all("pie-validation", rows, group_count=77, case_count=2544)}


def cppperf_inventory(path: Path) -> list[tuple[str, str, dict]]:
    tree = json.loads(path.read_bytes())
    if tree.get("sha") != intake.CPPPERF_REVISION or tree.get("truncated") is not False:
        raise ValueError("expected the complete pinned CppPerf GitHub tree")
    paths, rows = {}, []
    for entry in tree["tree"]:
        name = entry["path"]
        if not name.startswith(intake.CPPPERF_PREFIX):
            continue
        match = intake.CPPPERF_PATH.fullmatch(name.removeprefix(intake.CPPPERF_PREFIX))
        if entry["type"] != "blob" or not match or name in paths:
            raise ValueError(f"unexpected CppPerf inventory entry: {name}")
        owner, repo, commit = match.groups()
        project = f"{owner}/{repo}"
        paths[name] = entry["sha"]
        rows.append((project.casefold(), commit, {"project": project, "reference_commit": commit,
                                                "metadata_path": name, "metadata_blob": entry["sha"]}))
    if sha256(intake.canonical_json(paths)).hexdigest() != intake.CPPPERF_INVENTORY_SHA256:
        raise ValueError("CppPerf inventory checksum mismatch")
    return rows


def cppperf_metadata(archive: ZipFile, row: dict) -> dict:
    path = row["metadata_path"]
    raw = archive.read(f"CppPerf-{intake.CPPPERF_REVISION}/{path}")
    if sha1(f"blob {len(raw)}\0".encode("ascii") + raw).hexdigest() != row["metadata_blob"]:
        raise ValueError(f"CppPerf Git blob mismatch for {path}")
    record = json.loads(raw)
    old = record["commit_info"]["old_sha"]
    count = record["tests"]["significant_improvements"]
    if (record["metadata"]["repository_name"].casefold() != row["project"].casefold()
            or record["commit_info"]["new_sha"] != row["reference_commit"]
            or not re.fullmatch(r"[0-9a-f]{40}", old) or type(count) is not int or count < 0):
        raise ValueError(f"unexpected CppPerf metadata for {path}")
    return record


def census_draw(pie_path: Path, tree_path: Path, archive_path: Path) -> dict:
    pie = pie_census(pie_path)
    inventory = cppperf_inventory(tree_path)
    cpp = {"revision": intake.CPPPERF_REVISION, "inventory_sha256": intake.CPPPERF_INVENTORY_SHA256,
           "groups": 42, "cases": 347, "draw": draw_all("cppperf-db", inventory, group_count=42, case_count=347)}
    prefix = {"pie_validation": {**pie, "draw": pie["draw"][:intake.DRAW_SIZE]},
              "cppperf": {**cpp, "draw": cpp["draw"][:intake.DRAW_SIZE]}}
    prefix_sha256 = sha256(intake.canonical_json(prefix)).hexdigest()
    if prefix_sha256 != LEGACY_DRAW_SHA256:
        raise ValueError("census prefix differs from the registered 24-slot draw")

    census_slots = {row["metadata_path"]: slot for slot, row in enumerate(cpp["draw"], 1)}
    stratum = []
    with ZipFile(archive_path) as archive:
        for _, _, row in sorted(inventory, key=lambda item: case_key("cppperf-db", item)):
            metadata = cppperf_metadata(archive, row)
            count = metadata["tests"]["significant_improvements"]
            if count > 0:
                stratum.append({**row, "target_commit": metadata["commit_info"]["old_sha"],
                                "significant_improvements": count, "stratum_slot": len(stratum) + 1,
                                "census_slot": census_slots.get(row["metadata_path"])})
    additional = sum(row["census_slot"] is None for row in stratum)
    return {
        "schema": "paired-development-census-v1", "seed": intake.DRAW_SEED, "held_out_used": False,
        "legacy_draw_sha256": prefix_sha256, "legacy_slots": 2 * intake.DRAW_SIZE,
        "pie_validation": pie, "cppperf": cpp,
        "cppperf_significant_stratum": {"patches": stratum, "additional_slots": additional},
        "total_slots": len(pie["draw"]) + len(cpp["draw"]) + additional,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pie-validation", type=Path, required=True)
    parser.add_argument("--cppperf-tree", type=Path, required=True)
    parser.add_argument("--cppperf-archive", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = census_draw(args.pie_validation, args.cppperf_tree, args.cppperf_archive)
    except (OSError, ValueError, KeyError, TypeError, BadZipFile) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
