"""Pin a scrape draw from offline metadata; source files are not opened."""

import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path

from .expanded_intake import (
    PIE_TRAIN, PIE_VALIDATION, alias_clusters, archive_metadata, canonical,
    codenet_candidates, digest, extend, pinned_pie_rows, read_pie_train,
)
from .expanded_repositories import repository_candidates


ROOT = Path(__file__).resolve().parents[2]
FREEZE = ROOT / "artifacts/paired_benchmark_freeze"
ARCHIVE = ROOT / "artifacts/paired_development/ledger.json"
PROTOCOL_SHA256 = "8a9692457cdba6d9b2860717b8bc254dae47dc48eebe7baacabb17a82007953e"
INITIAL_MANIFEST_SHA256 = "72428cdb00e89b7d01d9a74e20837452df24d5c5a9ee8dbc8e52150655295d10"


def read_problem_metadata(directory):
    raw = (directory / "problem_list.csv").read_bytes()
    judges = {row["id"]: row["dataset"] for row in csv.DictReader(raw.decode("utf-8").splitlines())}
    return judges, digest(raw)


def read_aliases(path, judges):
    raw = path.read_bytes()
    aliases = defaultdict(list)
    for line in raw.decode("ascii").splitlines():
        members = line.split(",")
        if len(members) < 2 or not all(name in judges for name in members):
            raise ValueError("unexpected CodeNet problem alias group")
        label = "codenet-identical/" + min(members)
        for member in members:
            aliases[member].append(label)
    if not aliases:
        raise ValueError("expected explicit IBM problem aliases")
    return aliases, digest(raw)


def draw(input_dir, codenet_dir, aliases_path, repositories):
    judges, judge_sha = read_problem_metadata(codenet_dir)
    aliases, alias_sha = read_aliases(aliases_path, judges)
    representatives = alias_clusters(judges, aliases)
    train, allowed, submitted = read_pie_train(input_dir / "pie_train.jsonl", judges)
    for row in pinned_pie_rows(input_dir / "pie_val.jsonl", PIE_VALIDATION):
        submitted.update((row["src_id"], row["tgt_id"]))
        if row["problem_id"] in allowed:
            raise ValueError("public PIE splits are not problem-disjoint")
    net = []
    for problem in sorted(allowed):
        with (codenet_dir / f"{problem}.csv").open(newline="", encoding="utf-8") as metadata:
            net.extend(codenet_candidates(problem, metadata, judges=judges,
                                          train_problems=allowed, published_submissions=submitted))
    old = archive_metadata(ARCHIVE, judges, aliases)
    original = (FREEZE / "manifest.json").read_bytes()
    if digest(original) != INITIAL_MANIFEST_SHA256:
        raise ValueError("expected the initially frozen validation manifest")
    snapshot = repository_candidates(repositories)
    repository_rows = snapshot["rows"]
    return {
        "schema": "eapg.paired-benchmark-expansion-draw.v1",
        "protocol_sha256": PROTOCOL_SHA256,
        "initial_manifest_sha256": INITIAL_MANIFEST_SHA256,
        "intake_rule_sha256": digest((FREEZE / "EXPANSION_INTAKE_RULE.md").read_bytes()),
        "judge_metadata_sha256": judge_sha,
        "alias_sha256": alias_sha,
        "repository_snapshot_sha256": snapshot["snapshot_sha256"],
        "candidate_counts": {PIE_TRAIN: len(train), "codenet": len(net), "repository": len(repository_rows)},
        "rows": extend(train, net, repository_rows, aliases=representatives,
                       old_clusters={r["cluster"] for r in old}),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pie", type=Path, required=True)
    parser.add_argument("--codenet-metadata", type=Path, required=True)
    parser.add_argument("--problem-aliases", type=Path, required=True)
    parser.add_argument("--repository-metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        document = draw(args.pie, args.codenet_metadata, args.problem_aliases, args.repository_metadata)
        data = canonical(document) + b"\n"
        with args.output.open("xb") as stream:
            stream.write(data)
    except (OSError, KeyError, ValueError) as error:
        parser.error(str(error))
    print(f"{len(document['rows'])} draw rows | SHA-256: {digest(data)}")


if __name__ == "__main__":
    main()
