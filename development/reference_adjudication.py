"""Validate a blinded Phase 2 reference packet and seal one pair's adjudication.

The custodian pins the complete packet digest before distributing the specification,
submissions, and independent screening evidence. Withhold the Pass-2 map until the
two independent human raw-line reviews are recorded and hashed. All reviewers
must remain blind to candidate slices, prompts, and predictions. The validator
checks structure and identity bindings. The custodian must enforce access and
review free text for leakage. Mapping uses inclusive raw line ranges, so an
overlap is an option for human review, not evidence of token-level provenance.

Run without arguments for authored fixtures. Supply --packet, --packet-sha256,
and --reviews FIRST SECOND to inspect mappings. Supply --adjudication THIRD for
ambiguous or conflicting marks. --out seals a resolved or explicitly unresolved
result at a new path. Keep packets, initial reviews, adjudications, and digests
under custodian control. The third record binds the two review hashes printed in
the mapping preview, in the same order. An empty accepted_node_ids array with a
rationale records an unresolved reference. Match normalized source and pipeline
hashes at scoring.
"""

import argparse
import json
from pathlib import Path
import re
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "artifacts/phase1_correction"))
from phase2_custody_and_probes import json_bytes, local_pass2_map, sha


PACKET = "eapg-phase2-blinded-reference-packet-v1"
REVIEW = "eapg-phase2-raw-review-v1"
ADJUDICATION = "eapg-phase2-third-adjudication-v1"
MANIFEST = "eapg-phase2-sealed-reference-v1"
NODE_ROLES = ("FUNCTION_ENTRY", "LOOP", "BRANCH", "CALL", "STATE_UPD")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def fields(obj, names):
    require(type(obj) is dict and set(obj) == set(names.split()), f"Expected only fields: {names}")


def text(value):
    return type(value) is str and bool(value.strip())


def digest(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def span(value, minimum, *, half_open=False):
    return (type(value) is list and len(value) == 2 and all(type(n) is int for n in value)
            and minimum <= value[0] <= value[1] - int(half_open))


def validate_packet(packet, packet_sha256):
    fields(packet, "schema pair_id protocol_sha256 pipeline_sha256 problem_spec slow_code fast_code "
                   "slow_source_sha256 fast_source_sha256 independent_evidence pass2_map")
    require(packet["schema"] == PACKET and all(text(packet[k]) for k in
            ("pair_id", "problem_spec", "slow_code", "fast_code")), "Invalid packet version or text")
    require(digest(packet["protocol_sha256"]) and digest(packet["pipeline_sha256"]), "Missing revision hashes")
    for side in ("slow", "fast"):
        require(sha(packet[f"{side}_code"]) == packet[f"{side}_source_sha256"], f"{side} source SHA-256 mismatch")
    evidence = packet["independent_evidence"]
    fields(evidence, "record_sha256 summary")
    require(digest(evidence["record_sha256"]) and text(evidence["summary"]), "Missing independent evidence")
    mapping = packet["pass2_map"]
    fields(mapping, "normalized_source_sha256 line_alignment nodes")
    require(digest(mapping["normalized_source_sha256"]) and mapping["line_alignment"] in ("aligned", "unresolved"),
            "Invalid Pass-2 map metadata")
    raw_line_count = len(packet["slow_code"].splitlines())
    require(type(mapping["nodes"]) is list, "Pass-2 nodes must be a list")
    for number, row in enumerate(mapping["nodes"], 1):
        fields(row, "node_id role normalized_byte_span normalized_line_span pre_brace_byte_span "
                    "raw_source_lines macro_invocation_evidence has_synthetic_braces")
        require(row["node_id"] == f"N{number}" and row["role"] in NODE_ROLES
                and span(row["normalized_byte_span"], 0, half_open=True)
                and span(row["pre_brace_byte_span"], 0, half_open=True)
                and span(row["normalized_line_span"], 1), "Invalid canonical node ID, role, or span")
        lines, macros = row["raw_source_lines"], row["macro_invocation_evidence"]
        require(type(lines) is list and all(type(line) is int and 1 <= line <= raw_line_count for line in lines)
                and lines == sorted(set(lines)) and (mapping["line_alignment"] == "aligned" or not lines)
                and type(macros) is list and all(text(macro) for macro in macros)
                and type(row["has_synthetic_braces"]) is bool, "Invalid Pass-2 source provenance")
    require(digest(packet_sha256) and sha(json_bytes(packet)) == packet_sha256, "Pinned packet SHA-256 mismatch")
    return raw_line_count, mapping


def validate_review(review, packet_sha256, raw_line_count, nodes):
    fields(review, "schema reviewer_id packet_sha256 independent_and_blinded marks unresolved_reason")
    require(review["schema"] == REVIEW and text(review["reviewer_id"]) and review["independent_and_blinded"] is True
            and review["packet_sha256"] == packet_sha256, "Invalid or unbound raw reviewer record")
    marks = review["marks"]
    require(type(marks) is list and (review["unresolved_reason"] is None if marks else text(review["unresolved_reason"])),
            "Supply raw marks or an unresolved reason")
    options = []
    for mark in marks:
        fields(mark, "raw_line_span rationale")
        lines = mark["raw_line_span"]
        require(span(lines, 1) and lines[1] <= raw_line_count and text(mark["rationale"]), "Invalid raw reviewer mark")
        first, last = lines
        candidates = [node["node_id"] for node in nodes if any(first <= line <= last for line in node["raw_source_lines"])]
        options.append({"raw_line_span": lines, "mapping_options": candidates})
    return {"reviewer_id": review["reviewer_id"], "review_sha256": sha(json_bytes(review)), "raw_marks": options}


def adjudicate(packet, packet_sha256, reviews, third=None):
    raw_line_count, mapping = validate_packet(packet, packet_sha256)
    nodes = mapping["nodes"]
    require(len(reviews) == 2, "Require exactly two initial raw review records")
    initial = sorted((validate_review(review, packet_sha256, raw_line_count, nodes) for review in reviews),
                     key=lambda review: review["reviewer_id"])
    reviewer_ids = {review["reviewer_id"] for review in initial}
    require(len(reviewer_ids) == 2, "Initial reviewer IDs must be distinct")
    review_hashes = [review["review_sha256"] for review in initial]
    options = [[mark["mapping_options"] for mark in review["raw_marks"]] for review in initial]
    agreed = [{matches[0] for matches in marks if len(matches) == 1} for marks in options]
    consensus = all(options) and all(len(matches) == 1 for marks in options for matches in marks) and agreed[0] == agreed[1]

    accepted = agreed[0] if consensus else set()
    status = "resolved" if consensus else "needs_adjudication"
    if third is not None:
        fields(third, "schema reviewer_id packet_sha256 review_sha256s blinded accepted_node_ids rationale")
        require(third["schema"] == ADJUDICATION and text(third["reviewer_id"]) and third["reviewer_id"] not in reviewer_ids
                and third["blinded"] is True and third["packet_sha256"] == packet_sha256
                and third["review_sha256s"] == review_hashes and text(third["rationale"]),
                "Third adjudication must be blinded, independent of the first reviewers, and bound to both raw reviews")
        require(not consensus, "Unique reviewer consensus needs no third adjudication")
        chosen = third["accepted_node_ids"]
        allowed = {node_id for marks in options for matches in marks for node_id in matches}
        require(type(chosen) is list and all(text(node_id) and node_id in allowed for node_id in chosen)
                and len(chosen) == len(set(chosen)), "Adjudicated IDs must come from documented raw-span mapping options")
        accepted = set(chosen)
        status = "resolved" if accepted else "unresolved"

    ids = [node["node_id"] for node in nodes]
    return {"schema": MANIFEST, "pair_id": packet["pair_id"], "packet_sha256": packet_sha256,
            "protocol_sha256": packet["protocol_sha256"], "pipeline_sha256": packet["pipeline_sha256"],
            "normalized_source_sha256": mapping["normalized_source_sha256"], "canonical_node_ids": ids,
            "status": status, "accepted_node_ids": [nid for nid in ids if nid in accepted],
            "review_sha256s": review_hashes, "review_mappings": initial,
            "adjudication_sha256": None if third is None else sha(json_bytes(third))}


def read_json(path):
    def unique(pairs):
        obj = dict(pairs)
        require(len(obj) == len(pairs), "Duplicate JSON field")
        return obj

    return json.loads(path.read_bytes(), object_pairs_hook=unique)


def self_check():
    # Raw source from the pinned custody exporter's authored macro fixture.
    raw = """#include <iostream>
#define REP(i, n) for (int i = 0; i < (n); ++i)
int main() {
    int n = 10;
    int total = 0;
    REP(i, n)
        if (i > 0) total += i;
        else total -= i;
    return total;
}
"""
    fast = "int main() { return 45; }"
    packet = {"schema": PACKET, "pair_id": "authored-fixture", "protocol_sha256": sha("fixture-protocol"),
              "pipeline_sha256": sha((Path(__file__).resolve().parents[1] / "pipeline.py").read_bytes()),
              "problem_spec": "Authored fixture only", "slow_code": raw, "fast_code": fast,
              "slow_source_sha256": sha(raw), "fast_source_sha256": sha(fast),
              "independent_evidence": {"record_sha256": sha("fixture-evidence"), "summary": "Fixture only"},
              "pass2_map": local_pass2_map()}
    packet_sha = sha(json_bytes(packet))

    def review(person, line):
        return {"schema": REVIEW, "reviewer_id": person, "packet_sha256": packet_sha,
                "independent_and_blinded": True, "marks": [{"raw_line_span": [line, line], "rationale": "Fixture"}],
                "unresolved_reason": None}

    first, second = review("fixture-a", 6), review("fixture-b", 6)
    agreed = adjudicate(packet, packet_sha, [second, first])
    require(agreed["status"] == "resolved" and agreed["accepted_node_ids"] == ["N3"], "Consensus fixture failed")
    second = review("fixture-b", 7)
    pending = adjudicate(packet, packet_sha, [first, second])
    require(pending["status"] == "needs_adjudication" and not pending["accepted_node_ids"], "Ambiguous fixture failed")
    require(pending["review_mappings"][1]["raw_marks"] == [
        {"raw_line_span": [7, 7], "mapping_options": ["N3", "N4", "N5"]},
    ], "Expanded loop, branch, and update must remain visible as separate options")
    third = {"schema": ADJUDICATION, "reviewer_id": "fixture-c", "packet_sha256": packet_sha,
             "review_sha256s": pending["review_sha256s"], "blinded": True, "accepted_node_ids": ["N3"],
             "rationale": "Fixture adjudication chooses the expanded loop on the invocation line"}
    resolved = adjudicate(packet, packet_sha, [first, second], third)
    require(resolved["status"] == "resolved" and resolved["accepted_node_ids"] == ["N3"], "Adjudication fixture failed")
    unresolved = adjudicate(packet, packet_sha, [first, second], {**third, "accepted_node_ids": []})
    require(unresolved["status"] == "unresolved" and not unresolved["accepted_node_ids"], "Unresolved fixture failed")

    tainted = json.loads(json_bytes(packet))
    tainted["pass2_map"]["nodes"][0]["prediction_rank"] = 1
    for test in (lambda: adjudicate(tainted, sha(json_bytes(tainted)), [first, second]),
                 lambda: adjudicate(packet, packet_sha, [first, {**second, "candidate_slice": ["N3"]}]),
                 lambda: adjudicate(packet, packet_sha, [first, first]),
                 lambda: adjudicate(packet, packet_sha, [first, second], {**third, "reviewer_id": "fixture-a"}),
                 lambda: adjudicate(packet, packet_sha, [first, second], {**third, "accepted_node_ids": ["N1"]}),
                 lambda: adjudicate(packet, sha("wrong digest"), [first, second])):
        try:
            test()
        except ValueError:
            continue
        raise AssertionError("Invalid custody or reviewer input was accepted")
    print("Authored reference fixtures passed: macro mapping, consensus, adjudication, unresolved, and blinding checks.")


def main():
    cli = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    cli.add_argument("--packet", type=Path)
    cli.add_argument("--packet-sha256", help="Canonical packet digest pinned in the custodian's ledger")
    cli.add_argument("--reviews", type=Path, nargs=2, metavar=("FIRST", "SECOND"))
    cli.add_argument("--adjudication", type=Path)
    cli.add_argument("--out", type=Path)
    args = cli.parse_args()
    if not any(vars(args).values()):
        self_check()
        return
    if not all((args.packet, args.packet_sha256, args.reviews)):
        cli.error("--packet, --packet-sha256, and two --reviews are required together")
    try:
        manifest = adjudicate(read_json(args.packet), args.packet_sha256, [read_json(path) for path in args.reviews],
                              read_json(args.adjudication) if args.adjudication else None)
        if args.out:
            require(manifest["status"] != "needs_adjudication", "Unadjudicated disagreements cannot be sealed")
            with args.out.open("x", encoding="utf-8") as handle:
                json.dump({"manifest": manifest, "manifest_sha256": sha(json_bytes(manifest))}, handle, indent=2)
                handle.write("\n")
        else:
            print(json.dumps(manifest, indent=2))
    except (ValueError, OSError) as error:
        cli.error(str(error))


if __name__ == "__main__":
    main()
