"""Tag new Path B slots from pinned development inputs without invoking C++."""

from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
from zipfile import BadZipFile, ZipFile

from . import census, intake


INCLUDE = re.compile(r'^\s*#\s*include\s*(?:<([^>]+)>|"([^"]+)")')
INCLUDE_DIRECTIVE = re.compile(r"^\s*#\s*include\b")
IGNORED = re.compile(r'''/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\\n])*"|(?<!\d)'(?:\\.|[^'\\\n])*' ''', re.S | re.X)
MARKERS = {
    "gcc_target": re.compile(r"^\s*#\s*pragma\s+GCC\s+target\b|__attribute__\s*\(\(\s*target\s*\("),
    "isa": re.compile(r"\b(?:AVX\w*|SSE[234]?\w*|NEON|AArch64|_mm\w*|__builtin_ia32_\w+|"
                      r"__\w*(?:AVX|SSE|NEON)\w*|__aarch64__|immintrin|arm_neon|[expt]mmintrin)\b", re.I),
    "host_api": re.compile(r"\b(?:_WIN32|__linux__|__APPLE__|windows\.h|unistd\.h|sys/mman\.h|"
                           r"QueryPerformanceCounter|VirtualAlloc|mmap|sched_setaffinity)\b"),
    "graphics": re.compile(r"\b(?:OpenGL|Vulkan|GLFW|GL/\w+\.h|vulkan/\w+\.h|"
                           r"gl[A-Z]\w+|vk[A-Z]\w+|glfw[A-Z]\w+)\b"),
    "concurrency": re.compile(r"\b(?:atomic(?:_\w+)?|mutex|pthread_\w+|condition_variable|"
                              r"memory_order_\w+|std::(?:thread|jthread|async|scoped_lock|unique_lock|lock_guard))\b"),
    "cache_line": re.compile(r"\b(?:cache[_ ]?line\w*|hardware_destructive_interference_size)\b|"
                             r"\balignas\s*\(\s*(?:64|128)\s*\)", re.I),
}
DIRECT_DEPENDENCE = re.compile(
    r"\b(?:_mm(?:256|512)?_\w+|__builtin_ia32_\w+|gl[A-Z]\w+|vk[A-Z]\w+|glfw[A-Z]\w+)\s*\("
    r"|\b(?:pthread_create|pthread_mutex_\w+|std::(?:thread|jthread|async))\b"
)
LOOP = re.compile(r"\b(?:for|while)\s*\(|\b(?:for_each|transform|sort|accumulate)\s*\(")
CONTAINER = re.compile(r"\b(?:vector|deque|list|map|unordered_map|set|unordered_set|"
                       r"queue|stack|priority_queue|span)\s*<")
INPUT = re.compile(r"\b(?:cin\s*>>|(?:scanf|getchar(?:_unlocked)?|fgets|getline|fread)\s*\()")
TU_SUFFIXES = {".c", ".cc", ".cpp", ".cxx"}
GCC_HEADERS = {"bits/stdc++.h", "bits/extc++.h", "ext/pb_ds/assoc_container.hpp", "ext/pb_ds/tree_policy.hpp"}


def code_text(text: str, *, keep_literals: bool = False) -> str:
    # shortcut: lexical hints only, use a C++ parser for decisions that need full syntax.
    return IGNORED.sub(lambda match: match[0] if keep_literals and not match[0].startswith("/")
                       else re.sub(r"[^\n]", " ", match[0]), text)


def include_resolution(file: str, header: str, quoted: bool, paths: set[str]) -> str:
    relative = posixpath.normpath(posixpath.join(posixpath.dirname(file), header))
    if quoted and relative in paths:
        return "patch_relative"
    if any(posixpath.join(root, header) in paths for root in ("", "include", "src")):
        return "patch_search_root_candidate"
    if not quoted and header in GCC_HEADERS:
        return "gcc_toolchain_header"
    if quoted or "/" in header:
        return "outside_visible_files"
    return "system_search_unchecked"


def source_tags(text: str, file: str, paths: set[str], touched: set[int]) -> dict:
    uncommented = code_text(text, keep_literals=True).split("\n")
    code = code_text(text)
    markers: dict[str, list[int]] = {}
    for name, pattern in MARKERS.items():
        hits = [line for line, content in enumerate(uncommented, 1) if pattern.search(content)]
        if hits:
            markers[name] = hits
    hard_hits = []
    for line, (content, masked) in enumerate(zip(uncommented, code.split("\n")), 1):
        if line in touched and (MARKERS["gcc_target"].search(content) or DIRECT_DEPENDENCE.search(masked)):
            hard_hits.append(line)
    includes = []
    for line, content in enumerate(uncommented, 1):
        if match := INCLUDE.match(content):
            header = match[1] or match[2]
            includes.append({"line": line, "header": header,
                             "resolution": include_resolution(file, header, bool(match[2]), paths)})
        elif INCLUDE_DIRECTIVE.match(content):
            includes.append({"line": line, "resolution": "macro_or_continued_include"})
    return {"file": file, "markers": markers, "direct_dependence_lines": hard_hits,
            "includes": includes, "loop": bool(LOOP.search(code)),
            "container": bool(CONTAINER.search(code)), "input": bool(INPUT.search(code))}


def pie_tags(record: dict) -> dict:
    sides = {}
    for side, prefix in (("target", "src"), ("reference", "tgt")):
        text = record[f"{prefix}_code"]
        file = record[f"{prefix}_id"] + ".cpp"
        tags = source_tags(text, file, {file}, set(range(1, text.count("\n") + 2)))
        tags["source_sha256"] = sha256(text.encode("utf-8")).hexdigest()
        sides[side] = [tags]
    return case_tags(sides, full_sources=True)


def patch_view(patch: str, side: str) -> tuple[str, set[int]]:
    lines, touched = [], set()
    marker = "-" if side == "target" else "+"
    for line in patch.splitlines():
        if line.startswith("@@ "):
            lines.append("")
        elif line.startswith((" ", marker)):
            lines.append(line[1:])
            if line[0] == marker:
                touched.add(len(lines))
    return "\n".join(lines), touched


def cppperf_tags(metadata: dict) -> dict:
    commit = metadata["commit_info"]
    files = commit["files_changed"]
    sides = {}
    for side, absent in (("target", "added"), ("reference", "removed")):
        paths = {item["filename"] for item in files if item["status"] != absent}
        sides[side] = []
        for item in files:
            if item["status"] == absent or not item.get("patch"):
                continue
            text, touched = patch_view(item["patch"], side)
            sides[side].append(source_tags(text, item["filename"], paths, touched))
    return {**case_tags(sides, full_sources=False), "target_commit": commit["old_sha"],
            "significant_improvements": metadata["tests"]["significant_improvements"],
            "translation_units_touched": sum(PurePosixPath(x["filename"]).suffix in TU_SUFFIXES for x in files),
            "files_without_patch": [x["filename"] for x in files if not x.get("patch")]}


def case_tags(sides: dict, *, full_sources: bool) -> dict:
    files = [file for side in sides.values() for file in side]
    scaling = "loop_or_container" if any(f["loop"] or f["container"] for f in files) else "no_visible_scaling_clue"
    if full_sources and scaling == "no_visible_scaling_clue" and all(f["input"] for f in files):
        scaling = "apparently_fixed_arity_io"
    return {"recommendation": "obvious_fast_fail_candidate" if any(f["direct_dependence_lines"] for f in files)
            else "desk_audit_candidate", "scaling_clue": scaling, "sides": sides}


def summary(rows: list[dict]) -> dict:
    return {
        "slots": len(rows),
        "recommendations": dict(Counter(row["recommendation"] for row in rows)),
        "scaling_clues": dict(Counter(row["scaling_clue"] for row in rows)),
        "marker_cases": dict(Counter(marker for row in rows for marker in {
            marker for side in row["sides"].values() for file in side for marker in file["markers"]
        })),
        "multiple_translation_units_touched": sum(row.get("translation_units_touched", 0) > 1 for row in rows),
        "visible_include_cases": sum(any(file["includes"] for side in row["sides"].values()
                                         for file in side) for row in rows),
        "outside_visible_include_cases": sum(any(
            inc["resolution"] == "outside_visible_files" for side in row["sides"].values()
            for file in side for inc in file["includes"]
        ) for row in rows),
    }


def prescreen(pie_path: Path, tree_path: Path, archive_path: Path) -> dict:
    draw = census.census_draw(pie_path, tree_path, archive_path)
    pie_rows = draw["pie_validation"]["draw"][intake.DRAW_SIZE:]
    selected = {(row["problem_id"], row["target_submission"], row["reference_submission"]): index
                for index, row in enumerate(pie_rows)}
    pie_tags_by_index = {}
    for record in census.pie_records(pie_path):
        key = tuple(record[field] for field in ("problem_id", "src_id", "tgt_id"))
        if key in selected:
            pie_tags_by_index[selected[key]] = pie_tags(record)
    pie = [{**row, "census_slot": i + intake.DRAW_SIZE + 1, **pie_tags_by_index[i]}
           for i, row in enumerate(pie_rows)]
    cpp_rows = draw["cppperf"]["draw"][intake.DRAW_SIZE:]
    stratum = draw["cppperf_significant_stratum"]["patches"]
    extra_rows = [row for row in stratum if row["census_slot"] is None]
    with ZipFile(archive_path) as archive:
        cpp = [{**row, "census_slot": i, **cppperf_tags(census.cppperf_metadata(archive, row))}
               for i, row in enumerate(cpp_rows, intake.DRAW_SIZE + 1)]
        extra = [{**row, **cppperf_tags(census.cppperf_metadata(archive, row))} for row in extra_rows]
    groups = {"pie_validation": pie, "cppperf_census": cpp, "cppperf_significant_extra": extra}
    return {"schema": "eapg.path-b.prescreen.v1", "held_out_used": False,
            "intake_sha256": sha256(intake.canonical_json(draw)).hexdigest(),
            "summary": {**{key: summary(rows) for key, rows in groups.items()}, "all_new": summary(pie + cpp + extra)},
            "rows": groups}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pie-validation", type=Path, required=True)
    parser.add_argument("--cppperf-tree", type=Path, required=True)
    parser.add_argument("--cppperf-archive", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = prescreen(args.pie_validation, args.cppperf_tree, args.cppperf_archive)
    except (OSError, ValueError, KeyError, TypeError, BadZipFile) as error:
        parser.error(str(error))
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
