"""Audit full-frame exposure links with custodian-supplied source fingerprints.

Both splits must use the same fingerprint revision. IDs and aliases must
already be canonicalized and qualified by their data source. This program reads
metadata only. The custodian supplies and attests the complete inventories.
"""

import argparse
from collections import defaultdict
from hashlib import sha256
from pathlib import Path
import sys

from .score import digest, fields, identifier, identifiers, index_rows, json_bytes, read_pinned, require


METADATA_SCHEMA = "eapg.paired.split-metadata.v1"
AUDIT_SCHEMA = "eapg.paired.split-audit.v1"
AUDIT_FIELDS = {
    "schema", "development_sha256", "prospective_sha256", "fingerprint_revision_sha256",
    "development_count", "prospective_count", "prospective_components", "prospective_group_count",
    "drawn_groups", "groups_sha256",
}


def inventory(document, split):
    fields(document, {"schema", "split", "drawn_ids", "fingerprint_revision_sha256", "rows"}, f"{split} metadata")
    require(document["schema"] == METADATA_SCHEMA and document["split"] == split
            and digest(document["fingerprint_revision_sha256"]), f"Invalid {split} split metadata")
    rows = index_rows(document["rows"], {"id", "group", "projects", "problems", "submission_ids", "sources"}, split)
    require(rows, f"Empty {split} inventory")
    drawn = identifiers(document["drawn_ids"], f"{split} draw IDs")
    require((bool(drawn) and drawn <= rows.keys()) if split == "prospective" else not drawn,
            f"Invalid draw for {split}")
    keys_by_id = {}
    for case, row in rows.items():
        require(identifier(row["group"]), f"Invalid claimed group for {case}")
        keys = {
            (kind, key)
            for kind in ("projects", "problems", "submission_ids")
            for key in identifiers(row[kind], f"{case} {kind}")
        }
        require((row["projects"] or row["problems"]) and row["submission_ids"], f"Incomplete origin for {case}")
        fields(row["sources"], {"target", "reference"}, f"{case} source versions")
        for side, source in row["sources"].items():
            fields(source, {"source_sha256", "template_sha256"}, f"{case} {side} fingerprints")
            require(all(map(digest, source.values())), f"Invalid {case} {side} fingerprint")
            keys.update(source.items())
        keys_by_id[case] = keys
    return rows, drawn, keys_by_id


def components(keys_by_id):
    parents = {case: case for case in keys_by_id}
    previous = {}

    def root(case):
        while parents[case] != case:
            parents[case] = parents[parents[case]]
            case = parents[case]
        return case

    for case, keys in sorted(keys_by_id.items()):
        for key in sorted(keys):
            left, right = root(case), root(previous.setdefault(key, case))
            parents[max(left, right)] = min(left, right)
    groups = defaultdict(list)
    for case in sorted(keys_by_id):
        groups[root(case)].append(case)
    return list(groups.values())


def audit(development, prospective, development_sha256, prospective_sha256, expected_group_count):
    require(digest(development_sha256) and digest(prospective_sha256), "Missing input byte commitments")
    require(type(expected_group_count) is int and expected_group_count > 0, "Invalid planned group count")
    dev, _, dev_keys = inventory(development, "development")
    frame, drawn, frame_keys = inventory(prospective, "prospective")
    revision = development["fingerprint_revision_sha256"]
    require(prospective["fingerprint_revision_sha256"] == revision, "Fingerprint revision mismatch")
    overlap = sorted(dev.keys() & frame.keys())
    require(not overlap, "Cross-split duplicate case IDs: " + ", ".join(overlap))
    prospect_components = []
    labels_seen = set()
    for members in components(dev_keys | frame_keys):
        dev_links = [case for case in members if case in dev]
        frame_links = [case for case in members if case in frame]
        require(not (dev_links and frame_links), "Cross-split linked case IDs: " + ", ".join(members))
        if frame_links:
            claimed = {frame[case]["group"] for case in frame_links}
            require(len(claimed) == 1, "Claimed group splits a component: " + ", ".join(members))
            label = next(iter(claimed))
            require(label not in labels_seen, "Claimed group spans disconnected components: " + ", ".join(members))
            labels_seen.add(label)
            prospect_components.append(members)
    drawn_groups = {case: frame[case]["group"] for case in sorted(drawn)}
    group_count = len(set(drawn_groups.values()))
    require(group_count == expected_group_count,
            f"Audited drawn group count {group_count} does not match planned group count {expected_group_count}")
    return {
        "schema": AUDIT_SCHEMA,
        "development_sha256": development_sha256,
        "prospective_sha256": prospective_sha256,
        "fingerprint_revision_sha256": revision,
        "development_count": len(dev),
        "prospective_count": len(frame),
        "prospective_components": prospect_components,
        "prospective_group_count": group_count,
        "drawn_groups": drawn_groups,
        "groups_sha256": sha256(json_bytes(drawn_groups)).hexdigest(),
    }


def check_registration(receipt, registration):
    """Bind the exact registered draw and group labels to the pinned audit output."""
    fields(receipt, AUDIT_FIELDS, "split audit")
    require(receipt["schema"] == AUDIT_SCHEMA and all(digest(receipt[k]) for k in (
        "development_sha256", "prospective_sha256", "fingerprint_revision_sha256", "groups_sha256",
    )), "Invalid split audit identity")
    drawn = receipt["drawn_groups"]
    require(type(drawn) is dict and drawn and all(identifier(k) and identifier(v) for k, v in drawn.items()),
            "Invalid audited draw")
    require(sha256(json_bytes(drawn)).hexdigest() == receipt["groups_sha256"] == registration["pins"]["groups"],
            "Wrong group digest in split audit or registration")
    require(receipt["prospective_group_count"] == len(set(drawn.values())), "Wrong group count in split audit")
    registered = {row["id"]: row["group"] for row in registration["cases"]}
    require(len(registered) == len(registration["cases"]) and registered == drawn,
            "Registered draw differs from the audited draw")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for split in ("development", "prospective"):
        parser.add_argument(f"--{split}", type=Path, required=True)
        parser.add_argument(f"--{split}-sha256", required=True)
    parser.add_argument("--expected-group-count", type=int, required=True)
    args = parser.parse_args()
    try:
        development = read_pinned(args.development, args.development_sha256)
        prospective = read_pinned(args.prospective, args.prospective_sha256)
        manifest = audit(development, prospective, args.development_sha256, args.prospective_sha256,
                         args.expected_group_count)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    sys.stdout.buffer.write(json_bytes(manifest))


if __name__ == "__main__":
    main()
