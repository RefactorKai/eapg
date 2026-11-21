"""Detect C++ equality expressions used directly as bitwise operands."""

from __future__ import annotations

import argparse
from base64 import b64decode
from collections import Counter, defaultdict
from hashlib import sha1, sha256
from importlib.metadata import version
import json
from pathlib import Path, PurePosixPath
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlparse
from urllib.request import Request, urlopen
from zipfile import ZipFile

REPO = Path(__file__).resolve().parents[2]
ARTIFACT = Path("artifacts/paired_development")
CUSTODY = Path(".codex/private/lab/path-b-census")
HISTORICAL_SHA = "3d12f67f151c5daf4363575c8476f0bdb4ae487c6960aadd7b8d14d7720fffcd"
INDEX_SCHEMA = "eapg.path-b.precedence-source-index.v1"
RECEIPT_SCHEMA = "eapg.path-b.precedence-sweep.v1"
ARCHIVE_PINS = (
    ".codex/private/lab/full-a2/source-pins.json",
    ".codex/private/lab/a4-a5-2026-11-19/source-pins.json",
)
ORACLE_PATH = ".codex/private/lab/full-a3/p03788/diagnostic/evaluation.json"
HALF_PREPARED = Path(".codex/private/lab/full-a3/p03788/prepared")
HALF_REFERENT_SHA = "20c0a11f17cd2658873b4d7314f72490beb14add1740760621e8f5dd3a587721"
CPP_SUFFIXES = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".ipp", ".inl", ".inc"}
BITWISE = {"^", "&", "|"}
EQUALITY = {"==", "!="}
PARSER_VERSIONS = {"tree-sitter": "0.26.0", "tree-sitter-cpp": "0.23.4"}


def pinned_parser():
    from tree_sitter import Language, Parser
    import tree_sitter_cpp

    installed = {package: version(package) for package in PARSER_VERSIONS}
    if installed != PARSER_VERSIONS:
        raise ValueError(f"Expected pinned tree-sitter versions, found {installed}")
    return Parser(Language(tree_sitter_cpp.language()))


def span(node, source):
    start = node.start_byte
    # The pinned Windows binding can crash reading start_point on missing nodes.
    return {"start_byte": start, "end_byte": node.end_byte, "line": source.count(b"\n", 0, start) + 1}


def operator(node, source):
    token = node.child_by_field_name("operator")
    return source[token.start_byte:token.end_byte].decode("ascii") if token is not None else None


def scan_source(parser, source):
    """Scan original bytes, excluding wrapped operands and unreliable AST regions."""
    tree = parser.parse(source)
    root = tree.root_node
    pending = [(root, False)]
    findings, limitations = [], []
    while pending:
        node, in_error = pending.pop()
        if node.is_error or node.is_missing:
            limitations.append({"reason": "missing_node" if node.is_missing else "error_node", **span(node, source)})
            in_error = True
        if node.type == "preproc_arg":
            limitations.append({"reason": "opaque_preprocessor_body", **span(node, source)})
            continue
        pending.extend((child, in_error) for child in reversed(node.children))
        if in_error or node.has_error or node.type != "binary_expression":
            continue
        bitwise = operator(node, source)
        if bitwise not in BITWISE:
            continue
        operands = []
        for side in ("left", "right"):
            child = node.child_by_field_name(side)
            if child is not None and child.type == "binary_expression":
                comparison = operator(child, source)
                if comparison in EQUALITY:
                    operands.append({"side": side, "operator": comparison, **span(child, source)})
        if operands:
            findings.append({"operator": bitwise, "ast_type": node.type, "operands": operands, **span(node, source)})
    return {"parse_status": "partial" if root.has_error else "parsed",
            "findings": findings, "coverage_limits": limitations}


def checked_json(path, expected):
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != expected:
        raise ValueError(f"Pinned JSON differs: {path.name}")
    return json.loads(raw)


def git_blob(raw):
    return sha1(f"blob {len(raw)}\0".encode("ascii") + raw).hexdigest()


def checked_relpath(value):
    path = PurePosixPath(value)
    if (path.is_absolute() or path.as_posix() != value or not path.parts or ".." in path.parts
            or ":" in value or "\\" in value
            or any(part.casefold() in {"pie_test.jsonl", "pie_merged_testcases.tar.gz",
                                       "pie_test_static_manifest.json"} for part in path.parts)):
        raise ValueError(f"Invalid relative source path: {value!r}")
    return path


def historical_index():
    return checked_json(REPO / ARTIFACT / "historical-manifest.json", HISTORICAL_SHA)["local_evidence"]


def historic_pins(historical):
    pins = {}
    for name in ARCHIVE_PINS:
        for item in checked_json(REPO / name, historical[name]):
            if isinstance(item, dict):
                key = (item["project"].casefold(), item["commit"], item["path"])
                candidates = [REPO / Path(name).parent / checked_relpath(item["file"])]
                claim = (item["sha256"], item["blob"], candidates, name)
            else:
                url, digest, error = item
                if error or not digest:
                    continue
                owner, project, commit, path = unquote(urlparse(url).path).lstrip("/").split("/", 3)
                key = (f"{owner}/{project}".casefold(), commit, path)
                candidates = [REPO / Path(name).parent / f"{owner}_{project}" / side / checked_relpath(path)
                              for side in ("old_sha", "new_sha")]
                claim = (digest, None, candidates, name)
            if key in pins and claim[:2] != pins[key][:2]:
                raise ValueError(f"Conflicting archived SHA pins for {key}")
            pins[key] = claim
    return pins


def fetch_exact_source(project, commit, path):
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", project) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Invalid pinned GitHub identity")
    api = f"https://api.github.com/repos/{project}/contents/{quote(path)}?ref={commit}"
    request = Request(api, headers={"Accept": "application/vnd.github+json", "User-Agent": "EAPG-static-audit"})
    with urlopen(request, timeout=20) as response:
        if urlparse(response.geturl()).hostname != "api.github.com":
            raise ValueError("GitHub source pin redirected outside the API")
        info = json.load(response)
    if info["type"] != "file" or info["path"] != path or info["encoding"] != "base64":
        raise ValueError("Unexpected GitHub source response")
    raw = b64decode("".join(info["content"].splitlines()), validate=True)
    if len(raw) != info["size"] or git_blob(raw) != info["sha"]:
        raise ValueError("Retrieved bytes differ from the upstream Git blob")
    return raw, {"api": api, "git_blob": info["sha"], "size": info["size"]}


def stash(storage, raw):
    digest = sha256(raw).hexdigest()
    path = storage / digest
    if path.resolve() != storage.resolve() / digest:
        raise ValueError("Content-addressed source may not resolve outside its file")
    try:
        with path.open("xb") as handle:
            handle.write(raw)
    except FileExistsError:
        if path.read_bytes() != raw:
            raise ValueError(f"Content-addressed source differs: {digest}")
    return {"status": "verified", "sha256": digest, "size": len(raw), "storage": f"blobs/{digest}"}


def build_index(ledger, ledger_sha, source_index, recover):
    from development.paired_study.census import cppperf_metadata, pie_records
    from development.paired_study.intake import CPPPERF_REVISION, PIE_VALIDATION_SHA256
    from development.paired_study.path_b_cases import VALIDATION

    destination = source_index.parent
    if not destination.resolve().is_relative_to((REPO / CUSTODY).resolve()):
        raise ValueError("Store complete source bytes under repository Path B custody")
    destination.mkdir(parents=True, exist_ok=True)
    storage = destination / "blobs"
    storage.mkdir(exist_ok=True)
    if storage.is_symlink():
        raise ValueError("Source storage must remain inside sweep custody")
    historical = historical_index()
    archive_pins = historic_pins(historical)
    source_pairs = {}
    pie_rows = {(row["case_id"], row["target"], row["reference"])
                for row in ledger["rows"] if row["corpus"] == "pie-validation"}
    for record in pie_records(VALIDATION):
        key = record["problem_id"], record["src_id"], record["tgt_id"]
        if key in pie_rows:
            if key in source_pairs:
                raise ValueError(f"Duplicate pinned PIE pair: {key}")
            source_pairs[key] = record["src_code"].encode(), record["tgt_code"].encode()

    files = []
    workspace_inputs = REPO.parent / ".codex/private/path-b-census"
    with ZipFile(workspace_inputs / "cppperf-metadata.zip") as archive:
        for row in ledger["rows"]:
            rank = row["intake_rank"]
            sources = row["phase_a"].get("sources_sha256") or {}
            if row["corpus"] == "pie-validation":
                pair = source_pairs.get((row["case_id"], row["target"], row["reference"]), (None, None))
                for side, raw in zip(("target", "reference"), pair, strict=True):
                    item = {"intake_rank": rank, "side": side, "path": "submission.cpp",
                            "blob_identity": row[side], "authority": "pinned_pie_validation"}
                    expected = sources.get(side)
                    if raw is None:
                        item.update(status="missing", reason="pair absent from pinned PIE validation")
                    elif expected and sha256(raw).hexdigest() != expected:
                        item.update(status="missing", reason="source SHA-256 differs from the desk pin")
                    else:
                        item.update(stash(storage, raw))
                    files.append(item)
                continue

            pins = row["pins"]
            project = pins["project"]
            meta = cppperf_metadata(archive, pins)["commit_info"]
            if (meta["old_sha"], meta["new_sha"]) != (row["target"], row["reference"]):
                raise ValueError(f"Source commit pins differ at rank {rank}")
            for changed in sorted(meta["files_changed"], key=lambda f: f["filename"]):
                new_path = checked_relpath(changed["filename"])
                old_path = checked_relpath(changed.get("previous_filename", changed["filename"]))
                if not {new_path.suffix.casefold(), old_path.suffix.casefold()} & CPP_SUFFIXES:
                    continue
                if changed["status"] not in {"modified", "added", "removed", "renamed"}:
                    raise ValueError(f"Unrecognized file status at rank {rank}")
                plans = (("target", "old_sha256", "added", old_path),
                         ("reference", "new_sha256", "removed", new_path))
                for side, sha_key, absent_status, relpath in plans:
                    name = relpath.as_posix()
                    item = {"intake_rank": rank, "side": side, "path": name, "commit": row[side],
                            "metadata_blob": pins["metadata_blob"], "blob_identity": None}
                    if changed["status"] == absent_status:
                        item.update(status="absent", reason=f"pinned patch marks file {absent_status}")
                    else:
                        resolve_cppperf(item, sources.get(name, {}).get(sha_key), project, archive_pins,
                                        storage, recover)
                    files.append(item)
    if {item["intake_rank"] for item in files} != set(range(1, 148)):
        raise ValueError("Pinned source plan does not cover every ledger rank")
    return {"schema": INDEX_SCHEMA, "held_out_used": False, "ledger_sha256": ledger_sha,
            "pie_validation_sha256": PIE_VALIDATION_SHA256, "cppperf_revision": CPPPERF_REVISION,
            "historical_manifest_sha256": HISTORICAL_SHA,
            "historical_pin_receipts": {name: historical[name] for name in ARCHIVE_PINS}, "files": files}


def resolve_cppperf(item, expected, project, archive_pins, storage, recover):
    commit, name = item["commit"], item["path"]
    claim = archive_pins.get((project.casefold(), commit, name))
    candidates = []
    expected_blob = None
    if claim:
        archived, expected_blob, candidates, origin = claim
        if expected and archived != expected:
            raise ValueError(f"Archived and ledger source pins disagree at rank {item['intake_rank']}")
        expected = archived
    else:
        origin = "path_b_ledger"
    if expected:
        candidates = [storage / expected, REPO / CUSTODY / "cppperf-blobs" / expected, *candidates]
    for path in candidates:
        if path.is_file():
            raw = path.read_bytes()
            if sha256(raw).hexdigest() == expected and (expected_blob is None or git_blob(raw) == expected_blob):
                item.update(stash(storage, raw), blob_identity=git_blob(raw), authority=origin)
                return
    if recover:
        try:
            raw, proof = fetch_exact_source(project, commit, name)
        except (HTTPError, URLError, TimeoutError) as error:
            item.update(status="missing", reason=f"pinned upstream fetch failed: {getattr(error, 'code', type(error).__name__)}")
            return
        if ((expected and sha256(raw).hexdigest() != expected)
                or (expected_blob and proof["git_blob"] != expected_blob)):
            item.update(status="missing", reason="upstream recovery differs from an earlier authenticated source pin")
            return
        item.update(stash(storage, raw), blob_identity=proof["git_blob"],
                    authority="upstream_exact_commit_contents", upstream_pin=proof)
        return
    item.update(status="missing", reason="no verified cached bytes" if expected else "no authenticated historical file pin")


def read_source(directory, record):
    digest = record["sha256"]
    path = directory / checked_relpath(record["storage"])
    if (not re.fullmatch(r"[0-9a-f]{64}", digest) or record["storage"] != f"blobs/{digest}"
            or path.resolve() != directory.resolve() / "blobs" / digest):
        raise ValueError("Source storage path differs from its confined digest location")
    raw = path.read_bytes()
    if len(raw) != record["size"] or sha256(raw).hexdigest() != digest:
        raise ValueError(f"Stored bytes differ from pinned source at rank {record['intake_rank']}")
    if "commit" in record and git_blob(raw) != record["blob_identity"]:
        raise ValueError(f"Stored Git blob differs at rank {record['intake_rank']}")
    return raw


def summarize(files, ranks):
    selected = [file for file in files if file["intake_rank"] in ranks]
    by_rank = defaultdict(list)
    for file in selected:
        by_rank[file["intake_rank"]].append(file)
    fully_accessible = {rank for rank, parts in by_rank.items()
                        if all(p["status"] in {"absent", "verified"} for p in parts)}
    fully_scanned = {rank for rank in fully_accessible
                     if all(p["status"] == "absent" or p["parse_status"] == "parsed" for p in by_rank[rank])}
    hit_ranks = {p["intake_rank"] for p in selected if p.get("finding_keys")}
    parse_counts = Counter(p.get("parse_status", p["status"]) for p in selected)
    return {
        "eligible_slots": len(ranks),
        "accessible_slots": len({p["intake_rank"] for p in selected if p["status"] == "verified"}),
        "fully_accessible_slots": len(fully_accessible),
        "fully_scanned_slots": len(fully_scanned),
        "hit_slots_fully_scanned": len(hit_ranks & fully_scanned),
        "hit_slots_partial_scan": sorted(hit_ranks - fully_scanned),
        "eligible_file_sides": sum(p["status"] != "absent" for p in selected),
        "legitimate_absent_sides": parse_counts["absent"],
        "accessible_file_sides": parse_counts["parsed"] + parse_counts["partial"],
        "parsed_file_sides": parse_counts["parsed"],
        "partial_parse_file_sides": parse_counts["partial"],
        "missing_file_sides": parse_counts["missing"],
        "file_sides_with_opaque_macros": sum(
            any(limit["reason"] == "opaque_preprocessor_body" for limit in p.get("coverage_limits", []))
            for p in selected
        ),
        "unique_source_blobs": len({p["sha256"] for p in selected if p["status"] == "verified"}),
        "unique_expressions": len({key for p in selected for key in p.get("finding_keys", [])}),
    }


def half_reflector(parser, findings, files):
    from tree_sitter import Query, QueryCursor

    source, = [p for p in files if (p["intake_rank"], p["side"], p["blob_identity"]) == (5, "reference", "s831559970")]
    if source["sha256"] != HALF_REFERENT_SHA:
        raise ValueError("Half Reflector reference differs from its diagnostic pin")
    hits = {findings[key]["line"]: findings[key] for key in source["finding_keys"]}
    if set(hits) != {17, 57} or any(h["operator"] != "^" for h in hits.values()):
        raise ValueError("Expected both Half Reflector reference forms")
    if ([(o["side"], o["operator"]) for o in hits[17]["operands"]] != [("right", "==")]
            or [(o["side"], o["operator"]) for o in hits[57]["operands"]] != [("left", "=="), ("right", "==")]):
        raise ValueError("Half Reflector AST grouping differs from the registered forms")
    historical = historical_index()
    evaluation = checked_json(REPO / ORACLE_PATH, historical[ORACLE_PATH])
    relevant = {(result["witness"], result["variant"]): result for result in evaluation["evaluations"]
                if result["mode"] == "plain"}
    results = {variant: relevant["minimal_odd_case", variant]
               for variant in ("target", "reference", "restored", "sham")}
    if (evaluation["case"] != "p03788"
            or results["reference"]["source_sha256"] != source["sha256"]
            or any(r["args"] != ["AAB", 7] or r["oracle_stdout"] != "BBA"
                   or r["observed_stdout"] != ("ABA" if variant == "reference" else "BBA")
                   or r["oracle_pass"] is not (variant != "reference") for variant, r in results.items())
            or relevant["predeclared_ladder", "reference"]["oracle_pass"] is not False):
        raise ValueError("Independent Half Reflector oracle receipt and witness disagree")
    prepared = (HALF_PREPARED / "manifest.json").as_posix()
    recorded = checked_json(REPO / prepared, historical[prepared])
    if evaluation["prepared_sha256"] != historical[prepared] or recorded["case"] != evaluation["case"]:
        raise ValueError("Half Reflector preparation differs from the oracle receipt")
    cutoffs = {"target": "500000", "restored": "2*n", "sham": "250000+250000"}
    query = Query(parser.language, '(binary_expression left: (identifier) @counter operator: "==" right: (_) @cutoff)')
    for variant, cutoff in cutoffs.items():
        raw = (REPO / HALF_PREPARED / f"{variant}.cpp").read_bytes()
        expected = results[variant]["source_sha256"]
        tree = parser.parse(raw)
        expressions = [match["cutoff"][0].text.translate(None, b" \t\r\n")
                       for _, match in QueryCursor(query).matches(tree.root_node)
                       if match["counter"][0].text == b"cnt"]
        if (sha256(raw).hexdigest() != expected or recorded["sources"][variant] != expected
                or expressions != [cutoff.encode()]):
            raise ValueError(f"Half Reflector cutoff provenance differs for {variant}")
    hits[17].update(classification="intentional",
                    rationale="The simulation XORs the inversion flag with the stored-symbol equality.")
    hits[57].update(classification="witness-backed defect",
                    rationale="The odd-length reconstruction returns the wrong output on the pinned witness. "
                    "Making the same grouping explicit leaves the branch decision unchanged.")
    return {"intake_rank": 5, "reference_submission": "s831559970", "case": "p03788",
            "source_sha256": source["sha256"], "oracle_receipt_sha256": historical[ORACLE_PATH],
            "prepared_manifest_sha256": historical[prepared], "registered_cutoffs": cutoffs,
            "fixture": "3 7\nAAB\n", "oracle_output": "BBA",
            "outputs": {variant: r["observed_stdout"] for variant, r in results.items()},
            "ladder_reference_oracle_pass": False}


def scan_index(ledger, index, directory, reviews=None):
    parser = pinned_parser()
    rows = {row["intake_rank"]: row for row in ledger["rows"]}
    files, scans, findings = [], {}, {}
    keys, placements = set(), defaultdict(set)
    for source in index["files"]:
        rank, side, path = (source[k] for k in ("intake_rank", "side", "path"))
        row = rows[rank]
        key = rank, side, path
        if type(rank) is not int or key in keys or side not in {"target", "reference"}:
            raise ValueError(f"Duplicate or unsupported file side: {key}")
        keys.add(key)
        checked_relpath(path)
        if row["corpus"] == "pie-validation":
            if source["blob_identity"] != row[side] or path != "submission.cpp":
                raise ValueError(f"PIE submission differs at rank {rank}")
        elif source["commit"] != row[side] or source["metadata_blob"] != row["pins"]["metadata_blob"]:
            raise ValueError(f"CppPerf pin differs at rank {rank}")
        found = {**source, "finding_keys": []}
        files.append(found)
        if source["status"] in {"absent", "missing"}:
            continue
        if source["status"] != "verified":
            raise ValueError(f"Invalid source status at rank {rank}")
        raw = read_source(directory, source)
        digest = source["sha256"]
        if digest not in scans:
            scans[digest] = scan_source(parser, raw)
        scan = scans[digest]
        found.update(parse_status=scan["parse_status"], coverage_limits=scan["coverage_limits"])
        for hit in scan["findings"]:
            start, end = hit["start_byte"], hit["end_byte"]
            hit_key = f"{digest}:{start}:{end}"
            expression = sha256(raw[start:end]).hexdigest()
            entry = findings.setdefault(hit_key, {**hit, "source_sha256": digest, "locations": [],
                                                  "expression_sha256": expression})
            entry["locations"].append({"intake_rank": rank, "side": side, "path": path,
                                       "blob_identity": source["blob_identity"], "parse_status": scan["parse_status"]})
            found["finding_keys"].append(hit_key)
            placements[rank, path, expression].add(side)
    if {(rank, side) for rank, side, _ in keys} != {(r, side) for r in rows for side in ("target", "reference")}:
        raise ValueError("Source index omits one or more ledger rank sides")
    witness = half_reflector(parser, findings, files)
    unreviewed = {key for key, result in findings.items() if "classification" not in result}
    if reviews is not None:
        if set(reviews) != unreviewed:
            raise ValueError("Context reviews must cover every remaining finding exactly once")
        for key, review in reviews.items():
            if (set(review) != {"classification", "rationale"}
                    or review["classification"] not in {"intentional", "ambiguous"} or not review["rationale"]):
                raise ValueError("Only a checked independent witness can establish an additional defect")
            findings[key].update(review)
    for key, hit in findings.items():
        counts = Counter((loc["intake_rank"], loc["path"]) for loc in hit["locations"])
        hit["shared_across_ranks"] = len({loc["intake_rank"] for loc in hit["locations"]}) > 1
        for loc in hit["locations"]:
            rank, path = loc["intake_rank"], loc["path"]
            loc["unchanged_file_hit"] = counts[rank, path] > 1
            loc["same_expression_on_both_sides"] = len(placements[rank, path, hit["expression_sha256"]]) > 1

    pie = {rank for rank, row in rows.items() if row["corpus"] == "pie-validation"}
    groups = {
        "distinct": set(rows), "pie_validation": pie, "cppperf_distinct": set(rows) - pie,
        "cppperf_census": {rank for rank, row in rows.items()
                          if row["corpus"] == "cppperf-census"},
        "combined_census": {rank for rank, row in rows.items() if row["census_slot"] is not None},
        "cppperf_significant_test": {rank for rank, row in rows.items() if row["stratum_slot"] is not None},
    }
    return {"schema": RECEIPT_SCHEMA, "held_out_used": False, "parser_versions": PARSER_VERSIONS,
            "coverage_scope": "Fully scanned slots have a reliable AST for every present eligible file side. "
                              "Opaque macro body tokens are outside the AST search scope.",
            "summary": {name: summarize(files, ranks) for name, ranks in groups.items()},
            "files": files, "findings": findings, "witness": witness,
            "review_complete": reviews is not None or not unreviewed}


def public_projection(full, custody_sha):
    if not full["review_complete"]:
        raise ValueError("Complete the contextual review before releasing sweep results")
    return {
        "schema": full["schema"], "held_out_used": False,
        "custody_receipt_sha256": custody_sha, "inputs": full["inputs"],
        "coverage_scope": full["coverage_scope"],
        "parser_versions": full["parser_versions"], "summary": full["summary"], "witness": full["witness"],
        "finding_locators": {
            key: {name: hit[name] for name in ("source_sha256", "start_byte", "end_byte", "line",
                                               "operator", "operands", "classification", "locations")}
            for key, hit in full["findings"].items()
        },
        "missing_sources": [{key: row[key] for key in ("intake_rank", "side", "path", "reason")}
                            for row in full["files"] if row["status"] == "missing"],
    }


def main():
    sys.path.insert(0, str(REPO))
    from artifacts.paired_development.desk_agreement import load_ledger, write_receipt, LEDGER_SHA

    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--ledger", type=Path, required=True)
    cli.add_argument("--source-index", type=Path, required=True)
    cli.add_argument("--source-index-sha256")
    cli.add_argument("--output", type=Path)
    cli.add_argument("--public-output", type=Path)
    cli.add_argument("--reviews", type=Path)
    cli.add_argument("--reviews-sha256")
    cli.add_argument("--index-only", action="store_true")
    cli.add_argument("--recover-historical", action="store_true")
    args = cli.parse_args()
    ledger = load_ledger(args.ledger)
    if args.index_only:
        index = build_index(ledger, LEDGER_SHA, args.source_index, args.recover_historical)
        print("Source index SHA-256", write_receipt(args.source_index, index))
        return
    if (args.recover_historical or not args.output or not args.source_index_sha256
            or bool(args.reviews) != bool(args.reviews_sha256)):
        cli.error("For a sweep, supply --source-index-sha256 and --output; a review requires its digest")
    if not args.output.resolve().is_relative_to((REPO / CUSTODY).resolve()):
        cli.error("Write the full sweep receipt under repository Path B custody")
    index = checked_json(args.source_index, args.source_index_sha256)
    if (index["schema"] != INDEX_SCHEMA or index["held_out_used"] is not False
            or index["ledger_sha256"] != LEDGER_SHA):
        raise ValueError("Source index schema, quarantine flag or ledger pin differs")
    reviews = checked_json(args.reviews, args.reviews_sha256) if args.reviews else None
    if reviews is not None and (reviews["held_out_used"] is not False
                                or reviews["source_index_sha256"] != args.source_index_sha256):
        raise ValueError("Context review does not belong to this quarantined source index")
    result = scan_index(ledger, index, args.source_index.parent, reviews["reviews"] if reviews else None)
    result["inputs"] = {"ledger_sha256": LEDGER_SHA, "source_index_sha256": args.source_index_sha256,
                        "reviews_sha256": args.reviews_sha256}
    receipt_sha = write_receipt(args.output, result)
    if args.public_output:
        write_receipt(args.public_output, public_projection(result, receipt_sha))
    print("Sweep receipt SHA-256", receipt_sha)
    print(json.dumps(result["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
