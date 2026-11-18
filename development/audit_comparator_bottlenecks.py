"""Count first CFG blockers on frozen pilot and pinned UOJ C++-family sources.

The header-omission screen hides only root-level literal include nodes from
ControlFlow. All other nodes, source spans and raw parse errors are unchanged.
This is a source-only diagnostic before preprocessing or brace normalization.
It does not test compile success, canonical criteria, growth, or references.
"""

import argparse
from collections import defaultdict
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.request import urlopen

from audit_uoj_source_availability import RELEASE as UOJ_FILES, REVISION, counts, read_pairs
from backward_slice import ControlFlow, UnsupportedProgram
from probe_gate2_pilot import PILOT_SHA, RELEASE


def without_literal_headers(root):
    def literal_header(node):
        path = node.child_by_field_name("path") if node.type == "preproc_include" else None
        return path is not None and path.type in {"system_lib_string", "string_literal"}

    return SimpleNamespace(has_error=root.has_error,
                           named_children=[node for node in root.named_children if not literal_header(node)])


def first_blocker(root):
    cfg = ControlFlow()
    try:
        cfg.build(root)
        cfg.dependencies()
    except UnsupportedProgram as error:
        reason = str(error)
        if reason.startswith("Unsupported "):
            return reason.removeprefix("Unsupported ").split(" on normalized line ", 1)[0]
        return {"Normalized source has a C++ parse error": "raw_parse_error",
                "Expected one int main() definition": "not_one_function_definition",
                "The CFG has no reachable exit": "no_reachable_cfg_exit"}.get(reason, reason)
    return None


def summarize(cases):
    def histogram(index):
        buckets = defaultdict(list)
        for case in cases:
            if case[index] is not None:
                buckets[case[index]].append(case)
        return {reason: counts(rows) for reason, rows in buckets.items()}

    return {"published": counts(cases), "raw_cfg_pass": counts([case for case in cases if case[2] is None]),
            "header_omission_cfg_pass": counts([case for case in cases if case[3] is None]),
            "header_only_rescued": counts([case for case in cases if case[2] is not None and case[3] is None]),
            "raw_first_blocker": histogram(2), "header_omission_first_blocker": histogram(3)}


def screen(parser, rows, source_field):
    result = []
    for row in rows:
        root = parser.parse(row[source_field].encode("utf-8")).root_node
        result.append((row["problem_id"], row.get("language"), first_blocker(root),
                       first_blocker(without_literal_headers(root))))
    return result


def uoj_rows(track, path):
    if path is not None:
        return read_pairs(path.read_bytes(), track)
    name, _ = UOJ_FILES[track]
    url = f"https://raw.githubusercontent.com/hehezhou/UOJ-Bench/{REVISION}/dataset/{name}"
    with urlopen(url, timeout=30) as response:
        return read_pairs(response.read(), track)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--download", action="store_true", help="Read the pinned official UOJ files in memory")
    for track, (name, _) in UOJ_FILES.items():
        cli.add_argument(f"--{track}", type=Path, help=f"Local copy of pinned {name}")
    args = cli.parse_args()
    if args.download and (args.easy or args.hard) or not args.download and not (args.easy and args.hard):
        cli.error("Specify --download or both --easy and --hard")
    try:
        from tree_sitter import Language, Parser
        import tree_sitter_cpp
    except ImportError:
        cli.error("Install the pinned parser dependencies from requirements-ast.txt")

    parser = Parser(Language(tree_sitter_cpp.language()))
    try:
        raw = (RELEASE / "artifacts/scope_isolated_pilot/pilot100_results.json").read_bytes()
        if sha256(raw).hexdigest() != PILOT_SHA:
            raise ValueError("Frozen pilot hash mismatch")
        pilot = screen(parser, json.loads(raw), "slow_code")
        cohorts = {track: screen(parser, (row for row in uoj_rows(track, getattr(args, track))
                                          if row["language"].startswith("C++")), "wrong_code") for track in UOJ_FILES}
    except (OSError, ValueError) as error:
        cli.error(str(error))
    pooled = cohorts["easy"] + cohorts["hard"]
    cohorts.update(pooled=pooled, explicit_cpp17=[row for row in pooled if row[1] == "C++17"])
    print(json.dumps({"pilot_sha256": PILOT_SHA, "uoj_revision": REVISION,
                      "uoj_files_sha256": {name: digest for name, digest in UOJ_FILES.values()},
                      "comparator_sha256": sha256(Path(__file__).with_name("backward_slice.py").read_bytes()).hexdigest(),
                      "parsers": {name: version(name) for name in ("tree-sitter", "tree-sitter-cpp")},
                      "pilot_slow": summarize(pilot), "uoj_cpp_evaluated": {k: summarize(v) for k, v in cohorts.items()}},
                     indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
