"""Replay the sealed Path B desk judgments without executing source code."""

from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path, PurePosixPath
from random import Random
import sys


REPO = Path(__file__).resolve().parents[2]
LEDGER_SHA = "e9b5b65c26727538b887047fd16b863850619783e111957a95dcec2ed2c05345"
SEED = 20261120
BOOTSTRAPS = 10_000
EXPECTED_BATCHES = {"batch-12.json", "batch-13-reconciled.json", "batch-14.json"}
COARSE = {
    "EXCLUDED": ("excluded", "desk_exclusion", "reject", "rejected_scope", "reject_architecture",
                 "excluded_architecture", "excluded_alignment", "rejected_correctness_alignment",
                 "reject_unsupported_dependency"),
    "BLOCKED": ("blocked", "block", "blocked_missing_prerequisite"),
    "DIAGNOSTIC": ("same_order_control", "scoped_growth_candidate", "scoped_growth",
                   "eligible_scoped_growth", "decreasing_ratio_diagnostic"),
}
DESK_REASONS = {
    "source": ("concurrency_or_cache_layout", "source_derived_oracle_failure",
               "source_derived_undefined_behavior", "isa_or_arch_locked", "graphics_driver_or_host_api",
               "forced_avx", "source_derived_numeric_oracle_failure", "forced_x86_native"),
    "contract": ("no_common_calibrated_work", "fixed_contract", "no_common_restoring_event",
                 "alignment_boundary", "insufficient_workload_ladder", "no_isolated_restoration",
                 "no_executable_work_delta", "no_matching_work_delta", "unverified_assertion_configuration",
                 "unverified_cache_cutoff_alignment", "unverified_calibrated_cache_work"),
    "route": ("missing_pinned_dependency", "unsupported_dependencies", "missing_pinned_dependency_and_calibration"),
}
HISTORICAL_PREFIXES = {
    "source": ("AArch64-only ExtractOffset branch", "AVX3 specialization", "Both exact files force AVX2",
               "Changed behavior depends on cache placement", "Source-derived cursor witness",
               "Source-derived repeated packed segments", "The border change requires a graphics context"),
    "contract": ("A fixed scalar contract supplies no size ladder",
                 "Reference difference-array updates eliminate the target", "The contract specifies one scalar pair",
                 "The contract supplies five inputs", "The libdwarf allocation/lifetime policy",
                 "The string has exactly three characters"),
}
EXCLUSIONS = {"desk_excluded", "historical_desk_excluded"}
FRAMES = {"pie-validation": "PIE", "cppperf-census": "CppPerf", "cppperf-significant-stratum": "SigOnly"}
ALLOCATION = {
    "source": ((18, 5), (20, 5), (10, 2)),
    "contract": ((33, 8), (10, 2), (2, 1)),
    "route": ((0, 0), (0, 0), (2, 1)),
}
DISPOSITIONS = ("SOURCE_WITNESS", "CONTRACT_GAP", "ROUTE_CONDITIONAL", "ELIGIBLE", "INSUFFICIENT_EVIDENCE")
RUBRIC = {
    "decision_order": ["SOURCE_WITNESS", "ROUTE_CONDITIONAL", "CONTRACT_GAP"],
    "rule": "Use the first independently supported disposition. Give exact source spans or name a missing prerequisite. "
            "A speculative source witness does not take precedence. Record material secondary reasons separately.",
    "route": "A and B are the target and reference respectively. The portable C++17 route uses one isolated "
             "translation unit, the pinned dependencies and ordinary toolchain headers. It requires legal workloads, "
             "an independent output oracle, one comparable countable operation and one isolatable intervention. "
             "Do not compile, execute, use project-native builds or substitute a different event for a changed path.",
    "labels": {
        "SOURCE_WITNESS": "Concrete wrong output or undefined behavior, locked ISA, graphics/host API, "
                          "concurrency/cache behavior or a changed event bypassed by the portable route.",
        "ROUTE_CONDITIONAL": "A named absent pinned dependency or demonstrated single-TU support gap. "
                             "Use missing_pinned_dependency_and_calibration when both are missing.",
        "CONTRACT_GAP": "Specific missing legal ladder, common calibrated event, alignment or isolated restoration. "
                        "Includes missing calibration or configuration when a dependency failure is unestablished.",
        "ELIGIBLE": "A legal ladder, a credible independent oracle design, a common calibrated event and an "
                    "isolatable edit. Use same_order_control, decreasing_ratio_diagnostic or scoped_growth_candidate.",
        "INSUFFICIENT_EVIDENCE": "Genuine insufficiency after considering the other labels. Name the missing evidence.",
    },
    "existing_reason_codes": DESK_REASONS,
    "evidence_scope": "Only supplied source snapshots and summarized task or API contracts. The supplied project "
                      "snapshots contain the changed files. Standard toolchain headers are available. An include "
                      "absent from the packet alone does not establish an unbuildable project; name a required "
                      "dependency on the changed path if it prevents the isolated route.",
}


def load(path, expected):
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != expected:
        raise ValueError(f"SHA-256 mismatch for {path.name}")
    data = json.loads(raw)
    if data.get("held_out_used") is not False:
        raise ValueError(f"Missing quarantine flag in {path.name}")
    return data


def load_ledger(path):
    ledger = load(path, LEDGER_SHA)
    ranks = [row["intake_rank"] for row in ledger["rows"]]
    if (ledger["schema"] != "eapg.path-b.ledger.v2"
            or not all(type(rank) is int for rank in ranks)
            or sorted(ranks) != list(range(1, 148))):
        raise ValueError("Expected exactly one ledger row for each Path B rank 1–147")
    return ledger


def desk_bucket(row):
    reason = row["phase_a"]["reason"]
    if row["final_disposition"] == "historical_desk_excluded":
        matches = [bucket for bucket, prefixes in HISTORICAL_PREFIXES.items()
                   for prefix in prefixes if reason.startswith(prefix)]
    else:
        matches = [bucket for bucket, reasons in DESK_REASONS.items() if reason in reasons]
    if len(matches) != 1:
        raise ValueError(f"Unknown or ambiguous desk reason at rank {row['intake_rank']}: {reason!r}")
    return matches[0]


def sample_plan(ledger, draft_path):
    """Freeze the rank draw separately from the subsequent source-packet checks."""
    if sys.version_info[:3] != (3, 14, 2):
        raise ValueError("Rank draw requires the recorded Python 3.14.2")
    draft = load(draft_path, ledger["draft_sha256"])
    expected = {row["intake_rank"]: row for row in draft["rows"]}
    rows = {row["intake_rank"]: row for row in ledger["rows"]}
    if len(draft["rows"]) != 147 or set(expected) != set(rows):
        raise ValueError("Draft and final rank coverage disagree")
    pools = {(bucket, frame): [] for bucket in ALLOCATION for frame in FRAMES.values()}
    for rank, row in sorted(rows.items()):
        for key in ("corpus", "target", "reference", "pins", "census_slot", "stratum_slot"):
            if row[key] != expected[rank][key]:
                raise ValueError(f"Draft and final {key} disagree at rank {rank}")
        if row["final_disposition"] in EXCLUSIONS:
            pools[desk_bucket(row), FRAMES[row["corpus"]]].append(rank)
    cells, ranks = [], []
    for bucket, quotas in ALLOCATION.items():
        for frame, (pool_size, quota) in zip(FRAMES.values(), quotas, strict=True):
            pool = pools[bucket, frame]
            if len(pool) != pool_size:
                raise ValueError(f"Expected {pool_size} {bucket}/{frame} exclusions, found {len(pool)}")
            selected = Random(SEED).sample(sorted(pool), quota)
            cells.append({"bucket": bucket, "frame": frame, "pool_size": pool_size,
                          "quota": quota, "ordered_sample": selected})
            ranks.extend(selected)
    if len(ranks) != 24 or len(set(ranks)) != 24 or any(type(rank) is not int for rank in ranks):
        raise ValueError("Expected 24 unique integer rank selections")
    existing_ranks = {rank for rank, row in rows.items() if row["phase_a"].get("independent_verdicts")}
    return {
        "schema": "eapg.path-b.desk-agreement.draw.v1", "held_out_used": False,
        "ledger_sha256": LEDGER_SHA, "draft_sha256": ledger["draft_sha256"],
        "seed": SEED, "python": "3.14.2", "eligible_slots": sum(map(len, pools.values())),
        "cells": cells, "selected_ranks": sorted(ranks),
        "overlap_with_existing": sorted(existing_ranks.intersection(ranks)),
        "selected_pins": {rank: {key: rows[rank][key] for key in ("pins", "census_slot", "stratum_slot")}
                          for rank in sorted(ranks)},
    }


def evidence_path(root, name):
    path = root / name
    if Path(name).name != name or path.resolve().parent != root.resolve():
        raise ValueError(f"Invalid audit evidence path {name!r}")
    return path


def sealed_votes(ledger, custody):
    """Join vote strings and reconciliations to the three sealed responses per batch."""
    batches = {}
    provenance = {}
    panel = {}
    rank_by_stratum = {row["stratum_slot"]: row["intake_rank"] for row in ledger["rows"]
                       if row["stratum_slot"] is not None}
    if set(rank_by_stratum) != set(range(1, 35)):
        raise ValueError("Expected all 34 stratum slots for the archival rank lookup")
    for row in sorted(ledger["rows"], key=lambda row: row["intake_rank"]):
        phase = row["phase_a"]
        votes = phase.get("independent_verdicts", [])
        if votes == []:
            continue
        rank = row["intake_rank"]
        name = row["evidence"]["file"]
        expected = ledger["batch_receipts"].get(name)
        if (len(votes) != 3 or not phase.get("reconciliation") or name not in EXPECTED_BATCHES
                or row["evidence"]["sha256"] != expected):
            raise ValueError(f"Invalid retrospective evidence at rank {rank}")
        if name not in batches:
            batch = load(evidence_path(custody, name), expected)
            for key in ("intake_sha256", "prescreen_sha256"):
                if batch[key] != ledger[key]:
                    raise ValueError(f"Wrong input identity in {name}")
            auditors = {}
            signatures = []
            for seal in batch["audits"]:
                audit = load(evidence_path(custody, seal["file"]), seal["sha256"])
                identity = audit["audit_id"]
                if (identity in auditors or audit.get("cxx_executed") is not False
                        or audit["source_index_sha256"] != batch["source_index_sha256"]):
                    raise ValueError(f"Wrong blind audit identity in {name}")
                by_rank = {rank_by_stratum[vote["slot"]]: vote for vote in audit["rows"]}
                if len(by_rank) != 8 or len(audit["rows"]) != 8:
                    raise ValueError(f"Invalid ballot coverage in {seal['file']}")
                auditors[identity] = by_rank
                signatures.append({"audit_id": identity, "file": seal["file"], "sha256": seal["sha256"]})
            by_rank = {rank_by_stratum[record["stratum_slot"]]: record for record in batch["rows"]}
            if (len(auditors) != 3 or len(by_rank) != 8 or len(batch["rows"]) != 8
                    or any(set(audit) != set(by_rank) for audit in auditors.values())):
                raise ValueError(f"Invalid auditor or row count in {name}")
            batches[name] = (by_rank, list(auditors.values()))
            provenance[name] = {"sha256": expected, "audits": signatures}
        batch_rows, auditors = batches[name]
        observed = [{key: audit[rank][key] for key in ("status", "reason", "stage")} for audit in auditors]
        if batch_rows[rank] != phase or votes != observed:
            raise ValueError(f"Reconciled row or independent votes differ at rank {rank}")
        panel[rank] = {
            "project": row["pins"]["project"],
            "batch": name,
            "final_disposition": row["final_disposition"],
            "reconciliation": phase["reconciliation"],
            "votes": votes,
        }
    if list(panel) != list(range(124, 148)) or set(batches) != EXPECTED_BATCHES:
        raise ValueError("Expected all 24 sealed retrospective ranks (124–147)")
    return panel, provenance


def agreement(vectors):
    n = len(vectors)
    if not n or any(len(vector) != 3 for vector in vectors):
        raise ValueError("Fleiss agreement requires a nonempty panel of three-vote vectors")
    rows = [Counter(vector) for vector in vectors]
    marginals = Counter(label for vector in vectors for label in vector)
    unanimous = sum(len(row) == 1 for row in rows)
    matching = sum(count * (count - 1) // 2 for row in rows for count in row.values())
    votes = 3 * n
    expected_numerator = sum(count ** 2 for count in marginals.values())
    expected_denominator = votes ** 2
    return {
        "n": n, "unanimous": unanimous, "unanimous_percentage": 100 * unanimous / n,
        "matching_pairs": matching, "total_pairs": votes, "p_bar": matching / votes,
        "p_e": expected_numerator / expected_denominator, "marginals": dict(marginals),
        "kappa": ((matching * votes - expected_numerator) / (expected_denominator - expected_numerator)
                  if expected_numerator < expected_denominator else None),
    }


def percentile(sorted_values, probability):
    index = (len(sorted_values) - 1) * probability
    lower = int(index)
    upper = min(lower + 1, len(sorted_values) - 1)
    return sorted_values[lower] + (index - lower) * (sorted_values[upper] - sorted_values[lower])


def intervals(draws, taxonomies):
    statistics = ("unanimous_percentage", "p_bar", "kappa")
    values = {name: {statistic: [] for statistic in statistics} for name in taxonomies}
    count = 0
    for ranks in draws:
        count += 1
        for name, vectors in taxonomies.items():
            result = agreement([vectors[rank] for rank in ranks])
            for statistic in statistics:
                if result[statistic] is not None:
                    values[name][statistic].append(result[statistic])
    result = {}
    for name, estimates in values.items():
        result[name] = {}
        for statistic, sample in estimates.items():
            stable = len(sample) * 100 >= count * 95
            sample.sort()
            result[name][statistic] = {
                "undefined_replicates": count - len(sample),
                "status": "descriptive" if stable else "unstable",
                "interval_95": [percentile(sample, p) for p in (.025, .975)] if stable else None,
            }
    return result


def cluster_draws(panel):
    projects = {}
    for rank, row in sorted(panel.items()):
        projects.setdefault(row["project"], []).append(rank)
    clusters = list(projects.values())
    random = Random(SEED)
    for _ in range(BOOTSTRAPS):
        yield [rank for _ in clusters for rank in random.choice(clusters)]


def existing(ledger, custody):
    panel, provenance = sealed_votes(ledger, custody)
    mapping = {status: family for family, statuses in COARSE.items() for status in statuses}
    raw = {rank: [vote["status"] for vote in row["votes"]] for rank, row in panel.items()}
    coarse = {rank: [mapping[status] for status in votes] for rank, votes in raw.items()}
    taxonomies = {"raw": raw, "coarse": coarse}
    results = {name: agreement(list(votes.values())) for name, votes in taxonomies.items()}
    if (results["raw"]["unanimous"], results["raw"]["matching_pairs"],
            results["coarse"]["unanimous"], results["coarse"]["matching_pairs"],
            results["coarse"]["marginals"]) != (
                1, 14, 18, 59, {"EXCLUDED": 37, "BLOCKED": 24, "DIAGNOSTIC": 11}):
        raise ValueError("Retrospective vote totals differ from the registered replay assertions")
    if (round(results["raw"]["kappa"], 4), round(results["coarse"]["kappa"], 4)) != (.0878, .6998):
        raise ValueError("Retrospective kappa differs from the registered replay assertions")
    for name, estimates in intervals(cluster_draws(panel), taxonomies).items():
        results[name]["bootstrap"] = estimates
        results[name]["disagreeing_ranks"] = [rank for rank, votes in taxonomies[name].items()
                                              if len(set(votes)) > 1]
    groups = Counter(row["phase_a"].get("reviewer_group") for row in ledger["rows"])
    if groups != {1: 40, 2: 35, 3: 48, None: 24}:
        raise ValueError("Reviewer allocation counts differ from the registered replay assertions")
    return {
        "schema": "eapg.path-b.desk-agreement.existing.v1", "held_out_used": False,
        "ledger_sha256": LEDGER_SHA, "primary_taxonomy": "coarse", "results": results,
        "bootstrap": {"seed": SEED, "draws": BOOTSTRAPS, "unit": "project cluster",
                      "projects": len({row["project"] for row in panel.values()})},
        "reviewer_group_coverage": {str(key): value for key, value in groups.items()},
        "auditor_provenance": "Independent blind desk-audit agent responses recorded by the lab coordinator",
        "final_dispositions": dict(Counter(row["final_disposition"] for row in panel.values())),
        "panel": panel, "batch_seals": provenance,
    }


def canonical(data):
    return (json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
            + "\n").encode()


def write_receipt(path, data):
    return seal_bytes(path, canonical(data))


def seal_bytes(path, raw):
    try:
        with path.open("xb") as handle:
            handle.write(raw)
    except FileExistsError:
        if path.read_bytes() != raw:
            raise ValueError(f"Refusing to overwrite a different receipt at {path}")
    return sha256(raw).hexdigest()


def source_path(root, name):
    parts = PurePosixPath(name)
    path = root.joinpath(*parts.parts)
    if (parts.is_absolute() or name != parts.as_posix() or ".." in parts.parts or "\\" in name
            or ":" in name or not path.resolve().is_relative_to(root.resolve())):
        raise ValueError(f"Invalid source storage path {name!r}")
    if {"pie_test.jsonl", "pie_merged_testcases.tar.gz", "pie_test_static_manifest.json"}.intersection(
            part.casefold() for part in path.resolve().parts):
        raise ValueError("Quarantined path in source index")
    return path


def prepare_packets(ledger, draw, source_index, index_path, contracts, packet_dir):
    ranks = draw["selected_ranks"]
    if source_index["ledger_sha256"] != LEDGER_SHA or contracts["ledger_sha256"] != LEDGER_SHA:
        raise ValueError("Packet input ledger mismatch")
    if set(contracts["contracts"]) != set(map(str, ranks)):
        raise ValueError("Contracts must cover every selected rank exactly once")
    packet_dir.mkdir(parents=True, exist_ok=True)
    rubric_digest = write_receipt(packet_dir / "rubric.json", RUBRIC)
    mapping = {}
    for number, rank in enumerate(ranks, 1):
        packet = f"P{number:03}"
        files = [file for file in source_index["files"] if file["intake_rank"] == rank]
        paths = sorted({file["path"] for file in files})
        by_side = {(file["side"], file["path"]): file for file in files}
        if not paths or set(by_side) != {(side, path) for side in ("target", "reference") for path in paths}:
            raise ValueError(f"Incomplete source inventory at rank {rank}")
        if len(by_side) != len(files):
            raise ValueError(f"Duplicate source entry at rank {rank}")
        row = ledger["rows"][rank - 1]
        pins = row["phase_a"].get("sources_sha256", {})
        items = []
        for path_number, path in enumerate(paths, 1):
            label = f"F{path_number:03}{PurePosixPath(path).suffix}"
            for side, blind, change in (("target", "A", "old_sha256"), ("reference", "B", "new_sha256")):
                file = by_side[side, path]
                expected = (pins.get(side) if row["corpus"] == "pie-validation" else pins.get(path, {}).get(change))
                if file["status"] == "absent" and expected is None:
                    items.append({"side": blind, "file": label, "state": "absent"})
                    continue
                if file["status"] != "verified" or (expected and expected != file["sha256"]):
                    raise ValueError(f"Unverified source at rank {rank}, {side} {path}")
                raw = source_path(index_path.parent, file["storage"]).read_bytes()
                if sha256(raw).hexdigest() != file["sha256"]:
                    raise ValueError(f"Source bytes changed at rank {rank}, {side} {path}")
                destination = packet_dir / packet / blind / label
                destination.parent.mkdir(parents=True, exist_ok=True)
                seal_bytes(destination, raw)
                items.append({"side": blind, "file": label, "state": "supplied", "sha256": file["sha256"]})
        contract = contracts["contracts"][str(rank)]
        descriptor = {"packet_id": packet, "contract": contract["summary"], "files": items,
                      "rubric_sha256": rubric_digest}
        mapping[packet] = {"rank": rank, "sha256": write_receipt(packet_dir / packet / "packet.json", descriptor)}
    orders = {}
    for reviewer, seed in zip("abc", (20261121, 20261122, 20261123), strict=True):
        order = Random(seed).sample(list(mapping), 24)
        batches = [order[start:start + 8] for start in range(0, 24, 8)]
        orders[reviewer] = {"batches": batches, "sha256": write_receipt(packet_dir / f"order-{reviewer}.json", batches)}
    if len({tuple(r for batch in value["batches"] for r in batch) for value in orders.values()}) != 3:
        raise ValueError("Auditor permutations must differ")
    return {"schema": "eapg.path-b.desk-agreement.packets.v1", "held_out_used": False,
            "ledger_sha256": LEDGER_SHA, "rubric_sha256": rubric_digest, "packet_map": mapping, "orders": orders}


def score(ledger, draw, packets, verdicts):
    ranks = draw["selected_ranks"]
    packet_map = {key: value["rank"] for key, value in packets["packet_map"].items()}
    if sorted(packet_map.values()) != ranks or set(verdicts) != set("abc"):
        raise ValueError("The three verdicts must cover the same sealed rank set")
    panel = {rank: [] for rank in ranks}
    identities = set()
    for reviewer in "abc":
        ballot = verdicts[reviewer]
        if (ballot["auditor_id"] in identities or ballot["reviewer"] != reviewer or not ballot["auditor_id"]
                or ballot.get("prior_decisions_seen") is not False or ballot.get("cxx_executed") is not False
                or ballot["rubric_sha256"] != packets["rubric_sha256"]):
            raise ValueError(f"Invalid independence or scope attestation from reviewer {reviewer}")
        identities.add(ballot["auditor_id"])
        expected = packets["orders"][reviewer]["batches"]
        if [[vote["packet_id"] for vote in batch] for batch in ballot["batches"]] != expected:
            raise ValueError(f"Missing or misordered packets from reviewer {reviewer}")
        for batch in ballot["batches"]:
            for vote in batch:
                packet = vote["packet_id"]
                if (vote["status"] not in DISPOSITIONS or not isinstance(vote["reason_code"], str)
                        or not vote["reason_code"].strip() or not isinstance(vote["rationale"], str)
                        or not vote["rationale"].strip() or not vote["evidence"]
                        or vote["packet_sha256"] != packets["packet_map"][packet]["sha256"]):
                    raise ValueError(f"Invalid verdict from {reviewer} for {packet}")
                panel[packet_map[packet]].append(vote)
    vectors = {rank: [vote["status"] for vote in votes] for rank, votes in panel.items()}
    result = agreement(list(vectors.values()))
    result["marginals"] = dict.fromkeys(DISPOSITIONS, 0) | result["marginals"]
    cells = [sorted(cell["ordered_sample"]) for cell in draw["cells"] if cell["quota"]]
    rng = Random(SEED)
    draws = ([rng.choice(cell) for cell in cells for _ in cell] for _ in range(BOOTSTRAPS))
    result["bootstrap"] = intervals(draws, {"fresh": vectors})["fresh"]
    result["disagreeing_ranks"] = [rank for rank, vote in vectors.items() if len(set(vote)) > 1]
    pairs = {}
    for a, b in combinations(range(3), 2):
        left, right = (Counter(votes[i] for votes in vectors.values()) for i in (a, b))
        same = sum(votes[a] == votes[b] for votes in vectors.values())
        chance = sum(left[label] * right[label] for label in DISPOSITIONS)
        pairs["abc"[a] + "abc"[b]] = {"match": same, "n": len(ranks), "match_percentage": 100 * same / len(ranks),
                                     "kappa": ((same * len(ranks) - chance) / (len(ranks) ** 2 - chance)
                                               if chance != len(ranks) ** 2 else None)}
    original_labels = {"source": "SOURCE_WITNESS", "contract": "CONTRACT_GAP", "route": "ROUTE_CONDITIONAL"}
    confusion = {label: dict.fromkeys(DISPOSITIONS, 0) for label in original_labels.values()}
    for rank, votes in vectors.items():
        original = original_labels[desk_bucket(ledger["rows"][rank - 1])]
        for vote in votes:
            confusion[original][vote] += 1
    return {"schema": "eapg.path-b.desk-agreement.reaudit.v1", "held_out_used": False,
            "ledger_sha256": LEDGER_SHA, "results": {"five_label": result}, "auditor_pairs": pairs,
            "auditor_provenance": "Three isolated outcome-blind AI desk auditors",
            "versus_original": {"exact_agreements": sum(row[label] for label, row in confusion.items()),
                                "vote_count": len(ranks) * 3, "confusion": confusion},
            "overlap_with_existing": draw["overlap_with_existing"], "panel": panel,
            "vote_matrix": {rank: dict.fromkeys(DISPOSITIONS, 0) | dict(Counter(votes))
                            for rank, votes in vectors.items()},
            "bootstrap": {"seed": SEED, "draws": BOOTSTRAPS, "unit": "whole vote vectors within allocation cells",
                          "qualification": "Conditional on the sampled strata including singleton cells. "
                                           "Repeated projects may induce dependence."}}


def public_summary(receipt, receipt_sha):
    public = {key: value for key, value in receipt.items() if key not in {"panel", "batch_seals", "vote_matrix"}}
    if receipt["schema"] == "eapg.path-b.desk-agreement.reaudit.v1":
        row = receipt["results"]["five_label"]
        projected = {key: value for key, value in row.items() if key != "disagreeing_ranks"}
        projected["disagreements"] = len(row["disagreeing_ranks"])
        public["results"] = {"five_label": projected}
    public["custody_receipt_sha256"] = receipt_sha
    return public


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest="command", required=True)
    replay = commands.add_parser("existing", help="Replay the 24 sealed historical judgments")
    replay.add_argument("--ledger", type=Path, required=True)
    replay.add_argument("--output", type=Path, required=True)
    replay.add_argument("--public-output", type=Path)
    replay.add_argument("--custody", type=Path, default=REPO / ".codex/private/lab/path-b-census/phase-a")
    sample = commands.add_parser("sample", help="Prepare the sealed rank draw and blind packets")
    scorer = commands.add_parser("score", help="Score a complete set of previously sealed ballots")
    for command in (sample, scorer):
        command.add_argument("--ledger", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--draw", type=Path, required=True)
        command.add_argument("--draw-sha256", required=True)
    sample.add_argument("--draft", type=Path, default=REPO / ".codex/private/lab/path-b-census/phase-a/ledger-v2-a4-draft.json")
    sample.add_argument("--source-index", type=Path, required=True)
    sample.add_argument("--source-index-sha256", required=True)
    sample.add_argument("--contracts", type=Path, required=True)
    sample.add_argument("--contracts-sha256", required=True)
    sample.add_argument("--packet-dir", type=Path, required=True)
    scorer.add_argument("--sample-manifest", type=Path, required=True)
    scorer.add_argument("--sample-sha256", required=True)
    scorer.add_argument("--verdict", type=Path, action="append", required=True)
    scorer.add_argument("--seals", type=Path, required=True)
    scorer.add_argument("--seals-sha256", required=True)
    scorer.add_argument("--public-output", type=Path)
    args = cli.parse_args()
    try:
        ledger = load_ledger(args.ledger)
        if args.command == "existing":
            receipt = existing(ledger, args.custody)
        elif args.command == "sample":
            draw = load(args.draw, args.draw_sha256)
            if json.loads(canonical(sample_plan(ledger, args.draft))) != draw:
                raise ValueError("Sealed draw does not reproduce")
            source_index = load(args.source_index, args.source_index_sha256)
            contracts = load(args.contracts, args.contracts_sha256)
            receipt = prepare_packets(ledger, draw, source_index, args.source_index, contracts, args.packet_dir)
            receipt.update(draw_sha256=args.draw_sha256, source_index_sha256=args.source_index_sha256,
                           contract_sha256=args.contracts_sha256)
            load_ledger(args.ledger)
            print(f"Sealed 24 packets ({write_receipt(args.output, receipt)})")
            return
        else:
            draw = load(args.draw, args.draw_sha256)
            packets = load(args.sample_manifest, args.sample_sha256)
            seals = load(args.seals, args.seals_sha256)
            if (packets["draw_sha256"] != args.draw_sha256 or seals["packet_manifest_sha256"] != args.sample_sha256
                    or len(args.verdict) != 3 or set(seals["verdict_sha256"]) != set("abc")):
                raise ValueError("Sealed score input identity mismatch")
            verdicts = {reviewer: load(path, seals["verdict_sha256"][reviewer])
                        for reviewer, path in zip("abc", args.verdict, strict=True)}
            receipt = score(ledger, draw, packets, verdicts)
            receipt.update(draw_sha256=args.draw_sha256, packet_manifest_sha256=args.sample_sha256,
                           verdict_seals_sha256=args.seals_sha256)
        receipt_sha = write_receipt(args.output, receipt)
        if args.public_output:
            write_receipt(args.public_output, public_summary(receipt, receipt_sha))
    except (OSError, ValueError, KeyError, TypeError) as error:
        cli.exit(1, f"desk agreement: {error}\n")
    print(f"Agreement receipt SHA-256 {receipt_sha}")
    for name, result in receipt["results"].items():
        kappa = f"{result['kappa']:.6f}" if result["kappa"] is not None else "undefined"
        print(f"{name}: unanimous {result['unanimous']}/{result['n']}, "
              f"P_bar={result['matching_pairs']}/{result['total_pairs']}, kappa={kappa}")


if __name__ == "__main__":
    main()
