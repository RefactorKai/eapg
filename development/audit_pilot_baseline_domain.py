"""Audit the frozen synthetic pilot against the conventional slicer's static domain."""

import argparse
from collections import Counter
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path

from backward_slice import ControlFlow, UnsupportedProgram
from probe_gate2_pilot import PILOT_SHA, PIPELINE_SHA, RELEASE


PASS_ZERO = ("Frozen Pass 0 removes include lines before preprocessing and prepends the original lines afterward. "
             "These sources have no other preprocessor syntax that could remove the extra function definitions.")
TIERS = ("c_naive_work", "c_inter_only", "c_unpruned", "c_pruned")


def classify(parser, row):
    root = parser.parse(row["slow_code"].encode("utf-8")).root_node
    if root.has_error:
        raise ValueError(f"Cannot audit the raw syntax of {row['pair_id']}")
    headers = {node.child_by_field_name("path").text.decode() for node in root.named_children
               if node.type == "preproc_include"}
    functions = sum(node.type == "function_definition" for node in root.named_children)
    pending, directives = [root], set()
    while pending:
        node = pending.pop()
        if node.type.startswith("preproc_") and node.type != "preproc_include":
            directives.add(node.type)
        pending.extend(node.named_children)

    try:
        ControlFlow().build(root)
    except UnsupportedProgram as error:
        raw_cfg_rejection = str(error)
    else:
        raw_cfg_rejection = None
    unsupported_headers = sorted(headers - {"<cstdio>"})
    exclusions = []
    if unsupported_headers:
        exclusions.append("unsupported_headers_preserved_by_pass_zero")
    if functions > 1 and not directives:
        exclusions.append("multiple_top_level_functions")
    return {"pair_id": row["pair_id"], "unsupported_headers": unsupported_headers,
            "top_level_functions": functions, "other_preprocessor_syntax": sorted(directives),
            "raw_cfg_rejection": raw_cfg_rejection, "static_exclusions": exclusions,
            "eligible": not exclusions and raw_cfg_rejection is None}


def audit(parser):
    pilot = (RELEASE / "artifacts/scope_isolated_pilot/pilot100_results.json").read_bytes()
    pipeline = (RELEASE / "pipeline.py").read_bytes()
    if (sha256(pilot).hexdigest(), sha256(pipeline).hexdigest()) != (PILOT_SHA, PIPELINE_SHA):
        raise ValueError("Frozen pilot or pipeline hash mismatch")
    rows = json.loads(pilot)
    revision = {(row["pilot_revision"], row["scope_protocol"]) for row in rows}
    if revision != {("validated-input-pilot-v2", "main_scope")} or len({row["pair_id"] for row in rows}) != 100:
        raise ValueError("Unexpected frozen pilot cohort or revision")

    cases = [classify(parser, row) for row in rows]
    exclusions = Counter(reason for case in cases for reason in case["static_exclusions"])
    if len(cases) != 100 or exclusions != {"unsupported_headers_preserved_by_pass_zero": 100,
                                           "multiple_top_level_functions": 100}:
        raise ValueError("The two independent domain exclusions did not replay")
    if any(case["raw_cfg_rejection"] is None for case in cases):
        raise ValueError("The raw CFG parser accepted a case outside the expected domain")

    if not all(all(row["slicing"]["primary_symptom"] in row["slicing"][tier] for tier in TIERS) for row in rows):
        raise ValueError("The archived internal tiers do not all share the work symptom")
    off_symptom = [row for row in rows if row["gt_node"] != row["slicing"]["primary_symptom"]]
    tiers = {tier: {"all": sum(row["gt_node"] in row["slicing"][tier] for row in rows),
                    "off_symptom": sum(row["gt_node"] in row["slicing"][tier] for row in off_symptom)} for tier in TIERS}
    if len(off_symptom) != 18 or list(tiers.values()) != [
        {"all": 82, "off_symptom": 0}, {"all": 93, "off_symptom": 11},
        {"all": 100, "off_symptom": 18}, {"all": 100, "off_symptom": 18},
    ]:
        raise ValueError("Frozen internal tier counts differ from the archived results")

    revision_name, scope = next(iter(revision))
    return {"pilot_revision": revision_name, "scope_protocol": scope, "pilot_sha256": PILOT_SHA,
            "pipeline_sha256": PIPELINE_SHA,
            "comparator_sha256": sha256(Path(__file__).with_name("backward_slice.py").read_bytes()).hexdigest(),
            "parsers": {name: version(name) for name in ("tree-sitter", "tree-sitter-cpp")},
            "pass_zero": PASS_ZERO, "eligible": sum(case["eligible"] for case in cases),
            "exclusions": dict(exclusions), "top_level_functions": dict(Counter(c["top_level_functions"] for c in cases)),
            "off_symptom": len(off_symptom), "internal_tier_reference_retention": tiers, "cases": cases}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--json", action="store_true", help="Emit all 100 case classifications as JSON")
    args = cli.parse_args()
    try:
        from tree_sitter import Language, Parser
        import tree_sitter_cpp
    except ImportError:
        cli.error("Install the pinned parser dependencies from requirements-ast.txt")
    report = audit(Parser(Language(tree_sitter_cpp.language())))
    if args.json:
        print(json.dumps(report, indent=2))
        return

    cases = report["cases"]
    print(f"Frozen pilot {report['pilot_revision']} / {report['scope_protocol']}")
    print(f"Conventional baseline domain eligibility {report['eligible']}/{len(cases)}")
    print("All 100 have unsupported headers and multiple top-level functions.")
    distribution = ", ".join(f"{count} programs with {n}" for n, count in sorted(report["top_level_functions"].items()))
    print(f"Top-level functions: {distribution}.")
    print("The actual CFG parser rejected all 100 raw programs.")
    print(report["pass_zero"])
    print(f"Historical internal tiers at the same work symptom (all {len(cases)} / off symptom {report['off_symptom']})")
    for tier, counts in report["internal_tier_reference_retention"].items():
        print(f"  {tier:<13} {counts['all']:>3} / {counts['off_symptom']:>2}")


if __name__ == "__main__":
    main()
