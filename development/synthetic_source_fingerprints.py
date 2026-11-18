"""Generate or verify synthetic provenance fingerprints from pinned UTF-8 sources."""

import argparse
from hashlib import sha256
from pathlib import Path

from build_reference_packet import custody
from run_phase2_development import ProfileFailure, load_module, normalize
from score_synthetic import digest, exact_keys, identifier, require
from synthetic_frame import canonical, commitment, read_canonical
from synthetic_oracle import utf8
from synthetic_quarantine import PROVENANCE


INVENTORY_SCHEMA = "eapg-synthetic-source-inventory-v1"
REPORT_SCHEMA = "eapg-synthetic-source-fingerprints-v1"
IDENTIFIER_TYPES = custody.ID_NODES | {"statement_identifier"}


def fingerprints_for_source(pipeline, source):
    raw = sha256(source.encode("utf-8")).hexdigest()
    try:
        normalized, _ = normalize(pipeline, source)
    except ProfileFailure as error:
        unavailable = {"unavailable_reason": f"normalization_{error.details['status'].lower()}"}
        return {"raw_sha256": raw, "normalized_sha256": unavailable, "template_sha256": unavailable}
    except RuntimeError as error:
        if str(error) != "Normalized source contains a tree-sitter error":
            raise
        unavailable = {"unavailable_reason": "normalization_parse_error"}
        return {"raw_sha256": raw, "normalized_sha256": unavailable, "template_sha256": unavailable}
    normalized_sha256 = sha256(normalized.encode("utf-8")).hexdigest()
    root = pipeline.parser.parse(normalized.encode("utf-8")).root_node
    template = ({"unavailable_reason": "template_parse_error"} if root.has_error
                else template_digest(root))
    return {"raw_sha256": raw, "normalized_sha256": normalized_sha256, "template_sha256": template}


def template_digest(root):
    # A C++ identifier that happens to be named "count" is still a renamable binding.
    serial, stack = [], [root]
    while stack:
        node = stack.pop()
        if node is None:
            serial.append(None)
        elif node.type == "comment":
            continue
        elif node.type == "number_literal" or node.type in IDENTIFIER_TYPES:
            serial.append([node.type, "abstract"])
        elif not node.child_count:
            serial.append([node.type, node.text.decode("utf-8")])
        else:
            serial.append([node.type])
            stack.append(None)
            stack.extend(reversed(node.children))
    return commitment(serial)


def build_report(pipeline, inventory):
    exact_keys(inventory, "schema rows", "source inventory")
    require(inventory["schema"] == INVENTORY_SCHEMA and isinstance(inventory["rows"], list)
            and inventory["rows"], "Expected a nonempty source inventory")
    inputs = {}
    for row in inventory["rows"]:
        exact_keys(row, "row_id sources", "source inventory row")
        row_id, sources = row["row_id"], row["sources"]
        require(identifier(row_id) and row_id not in inputs, "Invalid or duplicate source inventory row ID")
        require(isinstance(sources, dict) and sources and all(
            identifier(version) and utf8(source) and bool(source) for version, source in sources.items()
        ), f"Expected versioned UTF-8 source bytes for {row_id}")
        inputs[row_id] = sources
    # Original and restored versions often share exact bytes within and across rows.
    by_source = {source: fingerprints_for_source(pipeline, source)
                 for source in dict.fromkeys(source for versions in inputs.values() for source in versions.values())}
    rows = [{"row_id": row_id, "sources": {version: by_source[source] for version, source in versions.items()}}
            for row_id, versions in inputs.items()]
    return {"schema": REPORT_SCHEMA, "pipeline_sha256": pipeline.source_sha256,
            "fingerprinter_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
            "source_inventory_sha256": commitment(inventory), "rows": rows}


def verify_attestations(report, provenance):
    require(isinstance(provenance, dict) and provenance.get("schema") == PROVENANCE
            and isinstance(provenance.get("rows"), list), "Wrong provenance manifest")
    reproduced = {row["row_id"]: row["sources"] for row in report["rows"]}
    attested = {}
    for row in provenance["rows"]:
        require(isinstance(row, dict) and {"row_id", "sources", "unknown_provenance_reason"} <= row.keys(),
                "Incomplete provenance row")
        row_id = row["row_id"]
        require(identifier(row_id) and row_id not in attested, "Invalid or duplicate provenance row ID")
        sources = reproduced.get(row_id)
        require(sources is not None and sources == row["sources"], f"Attested source fingerprints do not replay for {row_id}")
        attested[row_id] = sources
        require(not any(isinstance(value, dict) for version in sources.values() for value in version.values())
                or identifier(row["unknown_provenance_reason"]), f"Missing static fingerprint must keep provenance unknown for {row_id}")
    require(reproduced.keys() == attested.keys(), "Source inventory does not cover all attested provenance rows")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--inventory", required=True, type=Path)
    cli.add_argument("--inventory-sha256", required=True)
    cli.add_argument("--pipeline", required=True, type=Path)
    cli.add_argument("--pipeline-sha256", required=True)
    cli.add_argument("--provenance", type=Path)
    cli.add_argument("--provenance-sha256")
    cli.add_argument("--output", required=True, type=Path)
    args = cli.parse_args()
    try:
        require(not args.output.exists() and args.output.parent.is_dir(), "Require a new fingerprint output path")
        require(digest(args.pipeline_sha256), "Expected a pinned pipeline digest")
        require((args.provenance is None) == (args.provenance_sha256 is None), "Provide both provenance path and pin")
        inventory = read_canonical(args.inventory, args.inventory_sha256)
        provenance = read_canonical(args.provenance, args.provenance_sha256) if args.provenance is not None else None
        pipeline = load_module("synthetic_fingerprint_pipeline", args.pipeline, args.pipeline_sha256)
        report = build_report(pipeline, inventory)
        if provenance is not None:
            verify_attestations(report, provenance)
            report["verified_provenance_sha256"] = args.provenance_sha256
        with args.output.open("xb") as stream:
            stream.write(canonical(report))
        print(f"{commitment(report)}  {args.output.name}")
    except (OSError, ValueError, RuntimeError) as error:
        cli.error(str(error))


if __name__ == "__main__":
    main()
