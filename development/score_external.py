"""Score separately sealed reference and prediction ledgers without source code."""

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re

from replay_pilot_contrast import contrast


STATUSES = {"confirmed_positive", "verified_negative", "constant_factor", "indeterminate",
            "compile_failure", "oracle_failure", "insufficient_scales", "unsupported",
            "resource_failure", "sanitizer_failure"}
METHODS = ("symbolic", "abstract")
DIGEST = re.compile(r"[0-9a-f]{64}")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def index_rows(rows):
    index = {row["pair_id"]: row for row in rows}
    require(len(index) == len(rows) and all(type(pid) is str and pid for pid in index), "Invalid pair IDs")
    return index


def count_rate(count, n):
    return {"count": count, "total": n, "rate": count / n if n else None}


def grouped_rate(rows, hit):
    groups = defaultdict(list)
    for row in rows:
        groups[row["group_id"]].append(hit(row))
    return {**count_rate(sum(map(sum, groups.values())), len(rows)),
            "group_macro_rate": sum(sum(group) / len(group) for group in groups.values()) / len(groups)
            if groups else None}


def cohort(rows):
    differences = defaultdict(list)
    emitted = [row for row in rows if row["slice"]]
    result = {"pairs": len(rows), "groups": len({r["group_id"] for r in rows}),
              "symptom_coverage": count_rate(sum(row["symptom_id"] is not None for row in rows), len(rows)),
              "slice_coverage": count_rate(len(emitted), len(rows)),
              "slice_recall": grouped_rate(rows, lambda row: bool(set(row["labels"]) & set(row["slice"]))),
              "singleton_slices": sum(len(r["slice"]) == 1 for r in rows),
              "mean_reduction_emitted_slices": sum(1 - len(row["slice"]) / row["node_count"] for row in emitted)
              / len(emitted) if emitted else None}
    for method in METHODS:
        result[method] = {"coverage": grouped_rate(rows, lambda row: bool(row[method]))}
        for k in (1, 2):
            result[method][f"top{k}"] = grouped_rate(rows, lambda row: bool(set(row[method][:k]) & set(row["labels"])))
    for row in rows:
        neural, symbolic = (int(bool(set(row[method][:1]) & set(row["labels"]))) for method in reversed(METHODS))
        differences[row["group_id"]].append(neural - symbolic)
    result["top1_contrast_abstract_minus_symbolic"] = contrast([differences[key] for key in sorted(differences)]) \
        if rows else None
    return result


def score(study, predictions, study_sha):
    require(study["schema"] == "eapg-external-study-ledger-v1", "Wrong study ledger schema")
    require(predictions["schema"] == "eapg-external-predictions-v1", "Wrong predictions schema")
    require(predictions["study_sha256"] == study_sha, "Predictions are bound to a different study ledger")
    for key in ("protocol_sha256", "pipeline_sha256", "quarantine_sha256"):
        require(DIGEST.fullmatch(study[key]) and predictions[key] == study[key], f"Mismatched {key}")
    require(DIGEST.fullmatch(predictions["adapter_sha256"]), "A pinned adapter digest is required")
    refs = index_rows(study["pairs"])
    output = index_rows(predictions["pairs"])
    drawn = study["drawn_pair_ids"]
    require(drawn and len(drawn) == len(refs) and set(drawn) == refs.keys() == output.keys(), "Draw ledger is incomplete")
    positives, negatives, all_rows = [], [], []
    for pid in sorted(refs):
        ref, pred = refs[pid], output[pid]
        status, group = ref["screening_status"], ref["group_id"]
        nodes, labels = ref["canonical_node_ids"], ref["accepted_node_ids"]
        normalized_sha = ref["normalized_source_sha256"]
        candidates, symptom = pred["slice"], pred["symptom_id"]
        require(status in STATUSES and type(group) is str and group, f"Invalid screening row for {pid}")
        require(nodes == [f"N{i}" for i in range(1, len(nodes) + 1)], f"Invalid canonical IDs for {pid}")
        require((not nodes and normalized_sha is None or isinstance(normalized_sha, str)
                 and DIGEST.fullmatch(normalized_sha)) and pred["normalized_source_sha256"] == normalized_sha,
                f"Mismatched canonical source for {pid}")
        require(len(labels) == len(set(labels)) and set(labels) <= set(nodes), f"Invalid reference nodes for {pid}")
        require(len(candidates) == len(set(candidates)) and set(candidates) <= set(nodes)
                and (symptom in nodes or (symptom is None and not candidates)), f"Invalid slice for {pid}")
        prompt = pred["prompt_tokens"]
        require(prompt is None or (type(prompt) is int and prompt > 0), f"Invalid prompt length for {pid}")
        eligible = len(nodes) <= 26 and prompt is not None and prompt + 1 <= 512
        for method in METHODS:
            rank = pred[method]
            require(not rank or (len(rank) == len(set(rank)) == min(2, len(candidates))
                                 and set(rank) <= set(candidates)), f"Invalid {method} ranking for {pid}")
        require(eligible or not pred["abstract"], f"Ineligible neural output for {pid}")
        row = {"group_id": group, "labels": labels, "eligible": eligible, "node_count": len(nodes),
               **{key: pred[key] for key in ("slice", "symptom_id", *METHODS)}}
        all_rows.append((status, row))
        if status == "confirmed_positive":
            require(DIGEST.fullmatch(ref["reference_manifest_sha256"])
                    and ref["reference_status"] == ("resolved" if labels else "unresolved"),
                    f"Missing sealed human reference disposition for {pid}")
            positives.append(row)
        else:
            require(not labels, f"Nonpositive row has a reference label for {pid}")
            if status == "verified_negative":
                negatives.append(row)
    adjudicated = [row for row in positives if row["labels"]]
    eligible = [row for row in adjudicated if row["eligible"]]
    primary = cohort(adjudicated)
    paired = primary["top1_contrast_abstract_minus_symbolic"]
    status_counts = Counter(status for status, _ in all_rows)
    flow = {status: {"pairs": status_counts[status],
                     "groups": len({row["group_id"] for outcome, row in all_rows if outcome == status})}
            for status in sorted(status_counts)}
    return {"drawn_pairs": len(drawn), "drawn_groups": len({row["group_id"] for _, row in all_rows}), "screening_flow": flow,
            "verified_negative_alerts": count_rate(sum(row["symptom_id"] is not None for row in negatives), len(negatives)),
            "D_pos": primary, "D_elig": cohort(eligible),
            "D_rank": cohort([row for row in eligible if len(row["slice"]) >= 2]),
            "confirmed_positive_lower_bound": {method: count_rate(primary[method]["top1"]["count"], len(positives))
                                               for method in METHODS},
            "positive_transfer_evidence": bool(paired and primary["groups"] >= 20
                                               and paired["group_bootstrap_95pct_delta_pp"][0] > 0)}


def read_pinned(path, expected):
    raw = path.read_bytes()
    require(sha256(raw).hexdigest() == expected, f"Ledger digest mismatch: {path.name}")
    return json.loads(raw)


def self_check():
    h = "a" * 64
    pins = dict.fromkeys(("protocol_sha256", "pipeline_sha256", "quarantine_sha256"), h)
    rows = [dict(pair_id=str(i), group_id=f"g{i}", canonical_node_ids=["N1", "N2"],
                 normalized_source_sha256=h,
                 accepted_node_ids=(["N1"] if i in (0, 1) else []),
                 screening_status=("verified_negative" if i == 3 else "confirmed_positive"),
                 reference_status=("resolved" if i < 2 else "unresolved"), reference_manifest_sha256=h)
            for i in range(4)]
    ranks = [dict(pair_id=str(i), prompt_tokens=(512 if i == 1 else 511), symptom_id="N2",
                  normalized_source_sha256=h,
                  slice=["N2", "N1"], symbolic=["N2", "N1"], abstract=(["N1", "N2"] if i != 1 else []))
             for i in range(4)]
    study = dict(schema="eapg-external-study-ledger-v1", drawn_pair_ids=list("0123"), pairs=rows, **pins)
    pred = dict(schema="eapg-external-predictions-v1", study_sha256=h, adapter_sha256=h, pairs=ranks, **pins)
    result = score(study, pred, h)
    assert [result[name]["pairs"] for name in ("D_pos", "D_elig", "D_rank")] == [2, 1, 1]
    assert result["D_pos"]["abstract"]["top1"] == {**count_rate(1, 2), "group_macro_rate": 0.5}
    assert result["confirmed_positive_lower_bound"]["abstract"] == count_rate(1, 3)
    assert result["verified_negative_alerts"] == count_rate(1, 1) and not result["positive_transfer_evidence"]
    wrong_source = [{**ranks[0], "normalized_source_sha256": "b" * 64}, *ranks[1:]]
    for invalid in ({**pred, "pairs": ranks[:-1]}, {**pred, "study_sha256": "b" * 64},
                    {**pred, "pairs": wrong_source}):
        try:
            score(study, invalid, h)
        except ValueError:
            continue
        raise AssertionError("Invalid ledger was accepted")
    print("Authored scoring cohorts, abstention, negatives, lower bound, and ledger binding passed.")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--self-check", action="store_true")
    cli.add_argument("--study", type=Path)
    cli.add_argument("--study-sha256")
    cli.add_argument("--predictions", type=Path)
    cli.add_argument("--predictions-sha256")
    args = cli.parse_args()
    if args.self_check:
        self_check()
    elif all((args.study, args.study_sha256, args.predictions, args.predictions_sha256)):
        study = read_pinned(args.study, args.study_sha256)
        predictions = read_pinned(args.predictions, args.predictions_sha256)
        print(json.dumps(score(study, predictions, args.study_sha256), indent=2, sort_keys=True))
    else:
        cli.error("Use --self-check or supply both ledgers and their independently recorded SHA-256 digests")
