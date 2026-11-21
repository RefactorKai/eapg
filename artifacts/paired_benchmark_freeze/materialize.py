"""Reconstruct the local PIE validation subset; never compile or run the sources."""

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PIE_SHA256 = "6608a303c5c6ab61e7936599f3aa8cbde67bc36007e1a9739d7868665c531dab"
SCHEMA = "eapg.paired-benchmark-freeze.v1"
EXCLUDED_EVALUATION_GROUPS = ["p03497"]
SIDES = {"slow": "src", "fast": "tgt"}


def digest(data):
    return sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def record_id(record):
    return "/".join(record[key] for key in ("problem_id", "src_id", "tgt_id"))


def pair_payload(record):
    pair = {"id": record_id(record)}
    for side, key in SIDES.items():
        pair[side] = {
            "submission_id": record[f"{key}_id"],
            "code": record[f"{key}_code"],
            "pie_aggregate_runtime": record[f"{key}_agg_runtime"],
        }
        if record[f"{key}_status"] != "Accepted":
            raise ValueError(f"PIE did not mark both submissions accepted: {pair['id']}")
    if not 0 < pair["fast"]["pie_aggregate_runtime"] < pair["slow"]["pie_aggregate_runtime"]:
        raise ValueError(f"PIE runtimes do not support the slow/fast labels: {pair['id']}")
    return pair


def validation_records(path):
    raw = path.read_bytes()
    if digest(raw) != PIE_SHA256:
        raise ValueError("input must be the exact public PIE validation file")
    entries = [json.loads(line) for line in raw.splitlines()]
    records = {record_id(row): row for row in entries}
    if len(records) != len(entries) or len(records) != 2544:
        raise ValueError("unexpected validation inventory")
    return records


def materialize(manifest, validation):
    if (manifest["schema"] != SCHEMA or manifest["held_out_used"] is not False
            or manifest["excluded_evaluation_groups"] != EXCLUDED_EVALUATION_GROUPS
            or manifest["sources"]["pie-validation"]["release_sha256"] != PIE_SHA256):
        raise ValueError("unexpected manifest provenance")
    records = validation_records(validation)
    counts, judges = Counter(), Counter()
    ids, problems, fingerprints = set(), set(), set()
    output = []
    for row in manifest["pairs"]:
        pair_id = row["id"]
        if (pair_id in ids or row["source"] != "pie-validation"
                or row["problem_id"] in EXCLUDED_EVALUATION_GROUPS
                or row["language"] != "C++" or row["license"] != "CDLA-Permissive-2.0"
                or row["url"] != manifest["sources"]["pie-validation"]["url"]):
            raise ValueError(f"wrong or duplicate pair metadata: {pair_id}")
        ids.add(pair_id)
        problems.add(row["problem_id"])
        release = records[pair_id]
        if release["problem_id"] != row["problem_id"]:
            raise ValueError(f"problem ID differs from release: {pair_id}")
        pair = pair_payload(release)
        code_identities = []
        for side in SIDES:
            code = pair[side]["code"].encode("utf-8")
            if (row[side]["submission_id"] != pair[side]["submission_id"]
                    or row[side]["sha256"] != digest(code)):
                raise ValueError(f"{side} source differs from the manifest: {pair_id}")
            code_identities.append(digest(code.replace(b"\r\n", b"\n").replace(b"\r", b"\n").strip()))
        identity = tuple(sorted(code_identities))
        if identity[0] == identity[1] or identity in fingerprints:
            raise ValueError(f"duplicate source pair: {pair_id}")
        fingerprints.add(identity)
        payload = canonical(pair)
        if digest(payload) != row["sha256"]:
            raise ValueError(f"pair payload differs from the manifest: {pair_id}")
        output.append(payload + b"\n")
        counts[row["source"]] += 1
        judges[row["origin_judge"]] += 1
    dataset = b"".join(output)
    if (counts != manifest["counts_by_source"] or judges != manifest["counts_by_original_judge"]
            or len(ids) != manifest["pair_count"] or not 500 <= len(ids) <= 1000
            or len(problems) != manifest["problem_count"]
            or digest(dataset) != manifest["payload_sha256"]):
        raise ValueError("frozen population or payload digest differs from the manifest")
    return dataset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pie-validation", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=ROOT / "manifest.json")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path)
    mode.add_argument("--verify", type=Path)
    args = parser.parse_args()
    try:
        raw = args.manifest.read_bytes()
        manifest = json.loads(raw)
        payload = materialize(manifest, args.pie_validation)
        if args.verify:
            if args.verify.read_bytes() != payload:
                raise ValueError("local payload differs from the version in the manifest")
        else:
            with args.output.open("xb") as output:
                output.write(payload)
        print(f"{manifest['counts_by_source']} | manifest SHA-256: {digest(raw)} | payload SHA-256: {digest(payload)}")
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
