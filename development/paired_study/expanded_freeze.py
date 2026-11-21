"""Hash a pinned scrape draw and emit a metadata-only expanded manifest."""

import argparse
import base64
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

from .expanded_draw import (
    ARCHIVE, FREEZE, INITIAL_MANIFEST_SHA256, PROTOCOL_SHA256, read_aliases, read_problem_metadata,
)
from .expanded_intake import (
    ARCHIVED_LEDGER_SHA256, CODENET, CODE_NET_URL, CONTEST, GITHUB, PIE_PINS, PIE_TRAIN, PIE_VALIDATION,
    archive_metadata, audit, canonical, contest_candidate, digest, fingerprints, index_pie_sources,
)
from .expanded_repositories import archive_paths, checked_path


CODENET_SHA256 = "7e96620307f874269a62cc0225f2a5a13d2de2b3c368cf61319c87ec276620fb"


def pinned_json(path, pin):
    raw = path.read_bytes()
    if digest(raw) != pin:
        raise ValueError(f"{path.name} does not match its pin")
    return json.loads(raw)


def describe_sources(row, sides, seen):
    """Use file-level hashes for overlap; bind path and bytes for each side."""
    row = dict(row)
    source_keys, fingerprints_ = [], []
    for side, files in zip(("slow", "fast"), sides):
        file_rows = []
        for path, data in sorted(files.items()):
            fingerprint = fingerprints(data)
            fingerprints_.append(fingerprint)
            file_rows.append({"path": path, "sha256": digest(data), **fingerprint})
        if not file_rows:
            continue
        side_hash = digest(canonical([[entry["path"], entry["sha256"]] for entry in file_rows]))
        row[side] = {"id": row[f"{side}_id"], "files": file_rows,
                     "sha256": file_rows[0]["sha256"] if row["frame"] == CONTEST else side_hash}
        source_keys.append(digest(canonical(sorted(x["normalized_source"] for x in file_rows))))
    row["fingerprints"] = fingerprints_
    row["raw_source_hashes"] = [digest(data) for files in sides for data in files.values()]
    if not all(sides) or row.get("unavailable") or row.get("incomplete_source"):
        row["intake_stop"] = "intake_unretrievable"
    else:
        pair_key = tuple(sorted(source_keys))
        if pair_key[0] == pair_key[1] or pair_key in seen:
            row["intake_stop"] = "intake_duplicate"
        seen.add(pair_key)
        row["sha256"] = digest(canonical([row["slow"]["sha256"], row["fast"]["sha256"]]))
    return row


def expected_pie_ids(rows):
    return {(row["problem_id"], row[f"{side}_id"])
            for row in rows for side in ("slow", "fast")}


def read_side(path):
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def lookup_sources(row, args, pie_sources):
    if row["corpus"] in PIE_PINS:
        corpus = pie_sources[row["corpus"]]
        return [{row[f"{side}_id"] + ".cpp": corpus[(row["problem_id"], row[f"{side}_id"])]}
                for side in ("slow", "fast")]
    if row["corpus"] == CODENET:
        base = args.codenet_source / row["problem_id"] / "C++"
        paths = [base / (row[f"{side}_id"] + ".cpp") for side in ("slow", "fast")]
        return [{path.name: raw} if (raw := read_side(path)) else {} for path in paths]
    if row["corpus"] == GITHUB:
        return repository_sides(row, args.github_source)
    raise ValueError(f"unexpected source corpus {row['corpus']}")


def repository_sides(row, source_dir):
    result = []
    for side in ("slow", "fast"):
        base = source_dir / row["repo"] / row[f"{side}_id"]
        candidates = {path: read_side(base / checked_path(path)) for path in row.get(f"{side}_paths", [])}
        result.append({path: raw for path, raw in candidates.items() if raw is not None})
    return result


def bind_repository(row, doc):
    fetched = doc["rows"][row["id"]]
    if any(fetched[k] != row[k] for k in ("repo", "slow_id", "fast_id")):
        raise ValueError("fetched repository sources differ from the draw")
    root = doc["identities"][row["repo"]].get("root")
    details = {k: fetched[k] for k in ("slow_paths", "fast_paths", "license_evidence") if k in fetched}
    details["license"] = fetched.get("license") if fetched.get("license_evidence") else None
    details["incomplete_source"] = bool(fetched.get("missing_files"))
    if not root or root != row["cluster"].removeprefix("repository/"):
        details["unavailable"] = "repository_root_mismatch"
    elif all(k in fetched for k in ("slow_paths", "fast_paths")) and not (
            fetched["slow_paths"] and fetched["fast_paths"]):
        details["unavailable"] = "no_changed_cpp_source_on_one_or_both_sides"
    elif not details["license"] or fetched.get("unavailable"):
        details["unavailable"] = "pinned_provenance_unverified"
    return {**row, **details}


def archive_fingerprints(archived, args, pie_sources, evidence):
    expected = archive_paths(ARCHIVE, args.cppperf_archive)
    if expected.keys() != evidence["rows"].keys():
        raise ValueError("fetched CppPerf source list differs from pinned archive")
    counts = Counter()
    for row in archived:
        if row["frame"] == CONTEST:
            sides = lookup_sources(row, args, pie_sources)
            row.update(describe_sources(row, sides, set()))
            counts["contest_pairs"] += 1
            continue
        key = f"{row['repo'].casefold()}/{row['fast_id']}"
        pins = expected[key]
        if any(evidence["rows"][key].get(k) != v for k, v in pins.items()):
            raise ValueError("fetched CppPerf row differs from pinned paths")
        sides = repository_sides(pins, args.github_source)
        root = evidence["identities"][row["repo"]].get("root")
        if root:
            row["cluster"] = "repository/" + root
        previously_pinned = set(row["raw_source_hashes"])
        described = describe_sources(row, sides, set())
        counts["repository_pairs"] += 1
        counts["repository_files_expected"] += len(pins["slow_paths"]) + len(pins["fast_paths"])
        counts["repository_files_retrieved"] += sum(map(len, sides))
        if (root and all(set(side) == set(pins[side_name + "_paths"])
                         for side, side_name in zip(sides, ("slow", "fast"))) and
                previously_pinned.issubset(described["raw_source_hashes"])):
            counts["repository_pairs_verified"] += 1
        row["fingerprints"] = described["fingerprints"]
        row["raw_source_hashes"] = sorted(previously_pinned | set(described["raw_source_hashes"]))
    counts["repository_pairs_verified"] += 0
    return dict(counts)


def freeze(args, payload):
    initial = pinned_json(FREEZE / "manifest.json", INITIAL_MANIFEST_SHA256)
    draw = pinned_json(args.draw, args.draw_sha256)
    if (draw["protocol_sha256"] != PROTOCOL_SHA256 or
            draw["initial_manifest_sha256"] != INITIAL_MANIFEST_SHA256 or len(draw["rows"]) > 500):
        raise ValueError("draw is not bound to this protocol and original cohort")
    judges, judge_sha = read_problem_metadata(args.codenet_metadata)
    if judge_sha != draw["judge_metadata_sha256"]:
        raise ValueError("judge metadata differs from the draw")
    aliases, alias_sha = read_aliases(args.problem_aliases, judges)
    rule = (FREEZE / "EXPANSION_INTAKE_RULE.md").read_bytes()
    if alias_sha != draw["alias_sha256"] or digest(rule) != draw["intake_rule_sha256"]:
        raise ValueError("aliases or intake rule differ from the draw")
    archive_evidence = args.archive_source_manifest.read_bytes()
    expanded_evidence = args.expanded_source_manifest.read_bytes()
    repository_evidence = json.loads(expanded_evidence)
    archived = archive_metadata(ARCHIVE, judges, aliases)
    original = [contest_candidate(PIE_VALIDATION, judges, r["problem_id"], r["slow"]["submission_id"],
                                  r["fast"]["submission_id"]) for r in initial["pairs"]]
    rows = original + draw["rows"]
    pie_sources = {
        PIE_VALIDATION: index_pie_sources(
            args.pie / PIE_PINS[PIE_VALIDATION][0], PIE_VALIDATION,
            expected_pie_ids(original + [r for r in archived if r["frame"] == CONTEST])),
        PIE_TRAIN: index_pie_sources(args.pie / PIE_PINS[PIE_TRAIN][0], PIE_TRAIN,
                                     expected_pie_ids([r for r in rows if r["corpus"] == PIE_TRAIN])),
    }
    coverage = archive_fingerprints(archived, args, pie_sources, json.loads(archive_evidence))
    archive_fingerprint_sha256 = digest(canonical([
        {k: row[k] for k in ("cluster", "id", "fingerprints", "raw_source_hashes")} for row in archived
    ]))
    archive_complete = (coverage["contest_pairs"] == 77 and
                        coverage["repository_pairs_verified"] == coverage["repository_pairs"] == 70)
    seen = set()
    described_rows = []
    checksum = sha256()
    payload_count = 0
    for row in rows:
        row = dict(row, language="C++")
        if row["frame"] == CONTEST:
            row["aliases"] = aliases.get(row["problem_id"], [])
            row["license"] = "CDLA-Permissive-2.0"
            if row["corpus"] in PIE_PINS:
                _, ri, pin = PIE_PINS[row["corpus"]]
                row.update(source="PIE", url=f"https://drive.google.com/file/d/{ri}/view",
                           release_id=ri, release_sha256=pin)
            else:
                row.update(source="IBM Project CodeNet", url=CODE_NET_URL, release_id="1.0.0",
                           release_sha256=CODENET_SHA256)
        else:
            row = bind_repository(row, repository_evidence)
        source_sides = lookup_sources(row, args, pie_sources)
        described = describe_sources(row, source_sides, seen)
        described_rows.append(described)
        if "sha256" in described and row.get("license"):
            item = {"id": row["corpus"] + ":" + row["id"], "pair_sha256": described["sha256"]}
            for side, files in zip(("slow", "fast"), source_sides):
                item[side] = {path: base64.b64encode(raw).decode("ascii") for path, raw in files.items()}
            line = canonical(item) + b"\n"
            payload.write(line)
            checksum.update(line)
            payload_count += 1
    overlap = audit(described_rows, archived)
    quarantined = set(overlap["quarantined_pairs"])
    pairs = []
    for row in described_rows:
        label = row["corpus"] + ":" + row["id"]
        pairs.append({k: v for k, v in row.items() if k not in ("fingerprints", "raw_source_hashes")} |
                     {"cluster_id": overlap["cluster_by_pair"][label], "quarantined": label in quarantined})
    return {
        "schema": "eapg.paired-benchmark-expansion-manifest.v1",
        "protocol_sha256": PROTOCOL_SHA256,
        "initial_manifest_sha256": INITIAL_MANIFEST_SHA256,
        "archived_ledger_sha256": ARCHIVED_LEDGER_SHA256,
        "draw_sha256": args.draw_sha256,
        "held_out_used": False,
        "run_outcomes_inspected": False,
        "intake_rule": rule.decode("utf-8"),
        "intake_rule_sha256": draw["intake_rule_sha256"],
        "repository_snapshot_sha256": draw["repository_snapshot_sha256"],
        "candidate_counts": draw["candidate_counts"],
        "pair_count": len(rows),
        "counts_by_source": dict(Counter(row["corpus"] for row in rows)),
        "intake_stops": dict(Counter(row["intake_stop"] for row in pairs if "intake_stop" in row)),
        "archive_fingerprint_coverage": coverage,
        "archive_fingerprint_inventory_sha256": archive_fingerprint_sha256,
        "archive_source_evidence_sha256": digest(archive_evidence),
        "repository_source_evidence_sha256": digest(expanded_evidence),
        "payload": {"sha256": checksum.hexdigest(), "pairs": payload_count, "format": "jsonl-base64"},
        "status": "scrape_frozen" if archive_complete else "provisional_incomplete_archive_template_coverage",
        "overlap": overlap,
        "pairs": pairs,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("draw", "pie", "codenet-metadata", "codenet-source", "github-source",
                 "problem-aliases", "cppperf-archive", "archive-source-manifest", "expanded-source-manifest",
                 "payload", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--draw-sha256", required=True)
    args = parser.parse_args()
    try:
        with args.payload.open("xb") as payload:
            args.payload.chmod(0o600)
            doc = freeze(args, payload)
        data = canonical(doc) + b"\n"
        with args.output.open("xb") as output:
            output.write(data)
    except (OSError, KeyError, ValueError) as error:
        parser.error(str(error))
    print(f"{doc['pair_count']} pairs | {doc['status']} | SHA-256: {digest(data)}")


if __name__ == "__main__":
    main()
