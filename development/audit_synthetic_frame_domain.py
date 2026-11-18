"""Check the complete proposed frame against the shared C++17 source domain."""

import argparse
from collections import Counter
from hashlib import sha256
from pathlib import Path

from backward_slice import ControlFlow, UnsupportedProgram
from gate1_sandbox import invoke
from run_phase2_development import ProfileFailure, load_module, normalize, provenance, verify_preprocessing
from score_synthetic import digest, exact_keys, identifier, require
from synthetic_frame import CORE_SLOTS, FRAME, SWAP_SLOTS, canonical, commitment, read_canonical, validate_slots
from synthetic_oracle import utf8
from synthetic_source_fingerprints import INVENTORY_SCHEMA


SCHEMA = "eapg-synthetic-frame-domain-v1"
SYNTAX_FLAGS = ("-std=c++17", "-fsyntax-only", "-x", "c++", "-")


def checked_sources(frame, inventory):
    """Bind all planned versions before any compiler invocation."""
    exact_keys(frame, "schema protocol_sha256 draw_seed sham_classes allocation families comparator_swap", "origin frame")
    require(frame["schema"] == FRAME, "Wrong origin frame")
    require(isinstance(frame["families"], list) and frame["families"], "Expected a nonempty origin frame")
    swap = frame["comparator_swap"]
    exact_keys(swap, "family_id slots", "comparator swap")
    family_ids, case_ids, planned = set(), set(), {}
    for family in frame["families"]:
        require(isinstance(family, dict) and {"family_id", "slots"} <= family.keys(), "Incomplete origin family")
        family_id = family["family_id"]
        require(identifier(family_id) and family_id not in family_ids, "Invalid or duplicate family ID")
        family_ids.add(family_id)
        slots = family["slots"]
        validate_slots(slots, CORE_SLOTS, case_ids)
        planned.update({plan["case_id"]: (family_id, slot, plan) for slot, plan in slots.items()})
    require(identifier(swap["family_id"]) and swap["family_id"] in family_ids,
            "Comparator swap must belong to the proposed frame")
    validate_slots(swap["slots"], SWAP_SLOTS, case_ids)
    planned.update({plan["case_id"]: (swap["family_id"], slot, plan) for slot, plan in swap["slots"].items()})

    exact_keys(inventory, "schema rows", "source inventory")
    require(inventory["schema"] == INVENTORY_SCHEMA and isinstance(inventory["rows"], list),
            "Wrong source inventory schema")
    checked = {}
    for row in inventory["rows"]:
        exact_keys(row, "row_id sources", "source inventory row")
        case_id, sources = row["row_id"], row["sources"]
        require(identifier(case_id) and case_id in planned and case_id not in checked,
                "Unexpected or duplicate source inventory case ID")
        _, _, plan = planned[case_id]
        exact_keys(sources, "original evaluated restored", f"source versions for {case_id}")
        require(all(utf8(source) and source for source in sources.values()), f"Invalid UTF-8 source for {case_id}")
        actual = {name: sha256(source.encode("utf-8")).hexdigest() for name, source in sources.items()}
        require(actual == plan["source_hashes"], f"Source bytes differ from the plan for {case_id}")
        checked[case_id] = sources
    require(checked.keys() == planned.keys(), "Source inventory must cover the complete frame and comparator swap")
    return planned, checked


def syntax_only(source):
    verify_preprocessing(invoke(["g++", *SYNTAX_FLAGS], data=source.encode("utf-8")), "frame syntax check")


def inspect_source(pipeline, source):
    try:
        syntax_only(source)
        normalized, aliases = normalize(pipeline, source)
        if normalized != source:
            syntax_only(normalized)
    except ProfileFailure as error:
        return {"status": "compiler_failure", "process_status": error.details["status"]}
    except RuntimeError as error:
        if str(error) != "Normalized source contains a tree-sitter error":
            raise
        return {"status": "normalization_parse_error"}

    raw = normalized.encode("utf-8")
    root = pipeline.parser.parse(raw).root_node
    cfg = ControlFlow()
    try:
        cfg.build(root)
        dependencies = cfg.dependencies()
    except UnsupportedProgram as error:
        return {"status": "unsupported_comparator", "reason": str(error)}
    reachable_spans = {cfg.operations[index].owner for index in dependencies}
    nodes = pipeline.extract_macro_nodes(normalized, aliases)
    roles = Counter(node["role"] for node in nodes)
    mapped = Counter(node["role"] for node in nodes if tuple(node["normalized_span"]) in reachable_spans)
    return {"status": "supported", "normalized_sha256": sha256(raw).hexdigest(),
            "canonical_roles": dict(roles), "reachable_cfg_owner_roles": dict(mapped)}


def audit_frame(pipeline, frame, inventory):
    planned, checked = checked_sources(frame, inventory)
    by_source = {source: inspect_source(pipeline, source) for source in dict.fromkeys(
        source for versions in checked.values() for source in versions.values()
    )}
    cases, families = [], {}
    for case_id, (family, slot, _) in planned.items():
        versions = {name: by_source[source] for name, source in checked[case_id].items()}
        supported = all(result["status"] == "supported" for result in versions.values())
        cases.append({"case_id": case_id, "family_id": family, "slot": slot,
                      "supported": supported, "sources": versions})
        if slot in CORE_SLOTS:
            families[family] = families.get(family, True) and supported
    return {"schema": SCHEMA, "frame_sha256": commitment(frame), "inventory_sha256": commitment(inventory),
            "pipeline_sha256": pipeline.source_sha256, "authored_cases": len(cases),
            "supported_cases": sum(case["supported"] for case in cases),
            "core_families": len(families), "supported_core_families": sum(families.values()),
            "cases": cases}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("frame", "inventory", "pipeline"):
        cli.add_argument(f"--{name}", required=True, type=Path)
        cli.add_argument(f"--{name}-sha256", required=True)
    cli.add_argument("--output", required=True, type=Path)
    args = cli.parse_args()
    try:
        require(not args.output.exists() and args.output.parent.is_dir(), "Choose a fresh report path")
        require(digest(args.pipeline_sha256), "Invalid pinned pipeline SHA-256")
        frame = read_canonical(args.frame, args.frame_sha256)
        inventory = read_canonical(args.inventory, args.inventory_sha256)
        pipeline = load_module("frame_domain_pipeline", args.pipeline, args.pipeline_sha256)
        report = audit_frame(pipeline, frame, inventory)
        files = ("audit_synthetic_frame_domain.py", "backward_slice.py")
        report["software_sha256"] = {name: sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                     for name in files}
        runtime = provenance(pipeline)
        runtime["flags"] = {"syntax": SYNTAX_FLAGS, "preprocessing": ["-E", "-P", "-x", "c++", "-"]}
        del runtime["sanitizer_flags"]
        report["runtime"] = runtime
        with args.output.open("xb") as stream:
            stream.write(canonical(report))
        print(f"{commitment(report)}  {args.output.name}")
    except (OSError, RuntimeError, ValueError) as error:
        cli.error(str(error))


if __name__ == "__main__":
    main()
