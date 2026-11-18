"""Join and score three independently pinned, source-free synthetic study ledgers."""

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re

from replay_pilot_contrast import contrast
from score_external import count_rate, require


SEEDS = (42, 43, 44)
PRIMARY = ("work_scoped", "work_conventional")
ARMS = (*PRIMARY, "hits_scoped", "hits_conventional", "hit_growth", "work_symptom", "work_scoped_symbolic")
POSITIVE_SLOTS = {"positive_off_site", "positive_at_site"}
EXPECTED = dict.fromkeys((*POSITIVE_SLOTS, "comparator_swap_positive"), "confirmed_positive") | {
    "same_growth_sham": "confirmed_sham", "comparator_swap_sham": "confirmed_sham",
    "appropriate_superlinear": "confirmed_appropriate",
}
CONFIRMED = set(EXPECTED.values())
DISPOSITIONS = CONFIRMED | {
    "quarantined", "invalid_source", "invalid_input", "semantic_failure", "output_failure",
    "sanitizer_failure", "compile_failure", "operation_failure", "growth_failure", "resource_failure",
}
DIGEST = re.compile(r"[0-9a-f]{64}")
STATUS = re.compile(r"[a-z][a-z0-9_]*")


def exact_keys(row, keys, context):
    require(isinstance(row, dict) and row.keys() == set(keys.split()), f"Unexpected or missing fields in {context}")


def identifier(value):
    return isinstance(value, str) and bool(value) and value.strip() == value


def digest(value):
    return isinstance(value, str) and bool(DIGEST.fullmatch(value))


def status(value):
    return isinstance(value, str) and bool(STATUS.fullmatch(value))


def unique_strings(value):
    return isinstance(value, list) and all(identifier(item) for item in value) and len(value) == len(set(value))


def index(rows, fields, context, *, seeded=False):
    require(isinstance(rows, list), f"Expected a row list in {context}")
    result = {}
    for row in rows:
        exact_keys(row, fields, context)
        pid = row["case_id"]
        require(identifier(pid), f"Invalid case ID in {context}")
        key = pid
        if seeded:
            seed = row["seed"]
            require(type(seed) is int and seed in SEEDS, f"Unexpected seed for {pid}")
            key = (pid, seed)
        require(key not in result, f"Duplicate {context} row {key}")
        result[key] = row
    return result


def validate_label(design, label):
    pid = design["case_id"]
    slot, disposition = design["intended_slot"], label["disposition"]
    require(isinstance(slot, str) and slot in EXPECTED, f"Invalid intended slot for {pid}")
    require(digest(design["source_sha256"]) and digest(design["workload_sha256"]), f"Invalid draw digests for {pid}")
    require(isinstance(disposition, str) and disposition in DISPOSITIONS, f"Invalid disposition for {pid}")
    require(disposition not in CONFIRMED or disposition == EXPECTED[slot], f"Disposition conflicts with draw for {pid}")
    family = label["family_id"]
    require(identifier(family) or (family is None and disposition == "quarantined"), f"Invalid family for {pid}")
    nodes, accepted = label["canonical_node_ids"], label["accepted_node_ids"]
    normalized, operations = label["normalized_source_sha256"], label["operation_evidence_sha256"]
    require(isinstance(nodes, list) and nodes == [f"N{i}" for i in range(1, len(nodes) + 1)],
            f"Invalid canonical IDs for {pid}")
    require(digest(normalized) or (not nodes and normalized is None), f"Invalid canonical source digest for {pid}")
    require(unique_strings(accepted) and set(accepted) <= set(nodes), f"Invalid accepted IDs for {pid}")
    require(digest(operations) or (operations is None and disposition not in CONFIRMED),
            f"Missing operation evidence for {pid}")
    ref, reason = label["reference_status"], label["reference_reason"]
    if disposition == "confirmed_positive":
        require((accepted and ref == "resolved" and reason is None)
                or (not accepted and ref == "unresolved" and identifier(reason)), f"Invalid reference for {pid}")
    else:
        require(not accepted and ref is None and reason is None, f"Unexpected reference for {pid}")


def validate_prediction(pred, label, arms):
    context = f"{pred['case_id']} seed {pred['seed']}"
    normalized = pred["normalized_source_sha256"]
    profile = pred["profile_status"]
    require(status(profile), f"Missing profile disposition for {context}")
    require(normalized is None or (digest(normalized) and normalized == label["normalized_source_sha256"]),
            f"Canonical source mismatch for {context}")
    require(profile != "complete" or normalized is not None, f"Unbound complete profile for {context}")
    require(label["disposition"] != "quarantined" or profile != "complete", f"Quarantined profile for {context}")
    result = pred["arms"]
    require(isinstance(result, dict) and result.keys() == set(arms), f"Missing or unexpected arms for {context}")
    nodes = set(label["canonical_node_ids"])
    for arm, out in result.items():
        exact_keys(out, "alert symptom_id candidates ranking status", f"{context} {arm}")
        candidates, ranking = out["candidates"], out["ranking"]
        alert, symptom, state = out["alert"], out["symptom_id"], out["status"]
        require(unique_strings(candidates) and unique_strings(ranking) and set(candidates) <= nodes,
                f"Invalid candidate or ranking IDs for {context} {arm}")
        require(status(state) and (state == "ranked") == bool(ranking)
                and (not ranking or set(ranking) == set(candidates)), f"Invalid rank disposition for {context} {arm}")
        require(alert is None or type(alert) is bool, f"Invalid alert state for {context} {arm}")
        require(symptom is None or (identifier(symptom) and symptom in nodes), f"Invalid symptom for {context} {arm}")
        if profile != "complete":
            require(alert is None and symptom is None and not candidates, f"Prediction without profile for {context} {arm}")
        elif arm == "hit_growth":
            require(alert is None and symptom is None, f"Unexpected alert for {context} {arm}")
        else:
            require((alert is True) == (symptom is not None) and (alert is True or not candidates),
                    f"Alert and symptom disagree for {context} {arm}")
            require((alert is False) == (state == "no_symptom"), f"Missing no-symptom disposition for {context} {arm}")
            require((alert is None) == (state == "no_eligible_fit"), f"Missing fit disposition for {context} {arm}")
        require(state != "empty_slice" or (symptom is not None and not candidates), f"Invalid empty slice for {context} {arm}")
        if arm.endswith("_conventional") and candidates:
            require(symptom in candidates, f"Conventional slice omitted its criterion for {context} {arm}")

    for scoped, other in (PRIMARY, ("hits_scoped", "hits_conventional"),
                          ("work_scoped", "work_scoped_symbolic"), ("work_scoped", "work_symptom")):
        if scoped in result and other in result:
            require(all(result[scoped][key] == result[other][key] for key in ("alert", "symptom_id")),
                    f"Shared alert or symptom disagrees for {context} {other}")
    if "work_scoped_symbolic" in result:
        require(result["work_scoped"]["candidates"] == result["work_scoped_symbolic"]["candidates"],
                f"Shared scoped slice disagrees for {context}")
    if "work_symptom" in result:
        out = result["work_symptom"]
        expected = [out["symptom_id"]] if out["symptom_id"] is not None else []
        require(out["ranking"] == out["candidates"] == expected, f"Invalid work-symptom baseline for {context}")


def join(draw, labels, predictions, draw_sha256, labels_sha256):
    specs = (
        (draw, "draw", "protocol_sha256 frame_sha256 draw_seed allocation cases"),
        (labels, "labels", "draw_sha256 source_manifest_sha256 quarantine_sha256 cases"),
        (predictions, "predictions", "draw_sha256 labels_sha256 runner_sha256 pipeline_sha256 baseline_sha256 arm_ids predictions"),
    )
    for value, name, fields in specs:
        exact_keys(value, "schema " + fields, f"{name} ledger")
        require(value["schema"] == f"eapg-synthetic-{name}-v1", f"Wrong {name} ledger schema")
        require(all(digest(item) for key, item in value.items() if key.endswith("_sha256")), f"Invalid {name} digest")
    allocation = draw["allocation"]
    require(type(draw["draw_seed"]) is int and isinstance(allocation, dict) and allocation
            and all(slot in EXPECTED and type(count) is int and count > 0 for slot, count in allocation.items()),
            "Invalid draw seed or allocation")
    require(labels["draw_sha256"] == predictions["draw_sha256"] == draw_sha256, "Draw digest mismatch")
    require(predictions["labels_sha256"] == labels_sha256, "Labels digest mismatch")
    arms = predictions["arm_ids"]
    require(unique_strings(arms) and set(PRIMARY) <= set(arms) <= set(ARMS), "Invalid registered arms")
    require(("hits_scoped" in arms) == ("hits_conventional" in arms), "Incomplete hits factorial arms")
    design = index(draw["cases"], "case_id intended_slot source_sha256 workload_sha256", "draw")
    refs = index(labels["cases"], "case_id family_id disposition normalized_source_sha256 canonical_node_ids "
                 "accepted_node_ids reference_status reference_reason operation_evidence_sha256", "labels")
    output = index(predictions["predictions"], "case_id seed normalized_source_sha256 profile_status arms",
                   "predictions", seeded=True)
    require(design and design.keys() == refs.keys(), "Labels do not cover the draw exactly")
    require(output.keys() == {(pid, seed) for pid in design for seed in SEEDS}, "Predictions do not cover the draw and seeds exactly")
    quarantined = set()
    eligible = set()
    for pid, slot in design.items():
        ref = refs[pid]
        validate_label(slot, ref)
        if ref["disposition"] == "quarantined":
            quarantined.add(ref["family_id"])
        else:
            eligible.add(ref["family_id"])
        for seed in SEEDS:
            validate_prediction(output[pid, seed], ref, arms)
    require(allocation == Counter(row["intended_slot"] for row in design.values()), "Allocation does not match draw counts")
    require(not quarantined & eligible, "Only part of an origin family was quarantined")
    return {seed: [{**design[pid], **refs[pid], **output[pid, seed],
                    "mapped_source_sha256": refs[pid]["normalized_source_sha256"],
                    # Unknown quarantined origins get distinct units only in intention-to-test summaries.
                    "family": (refs[pid]["family_id"] or "", pid if refs[pid]["family_id"] is None else "")}
                   for pid in design] for seed in SEEDS}


def families(rows, measurement):
    groups = defaultdict(list)
    for row in rows:
        groups[row["family"]].append(measurement(row))
    return groups


def family_means(groups):
    return [sum(group) / len(group) for group in groups.values()]


def mean(values):
    return sum(values) / len(values) if values else None


def grouped_rate(rows, measurement):
    groups = families(rows, measurement)
    return {**count_rate(sum(map(sum, groups.values())), len(rows)), "family_macro_rate": mean(family_means(groups))}


def top(row, arm):
    return next(iter(row["arms"][arm]["ranking"]), None)


def hit(row, arm):
    return top(row, arm) in row["accepted_node_ids"]


def counts(rows):
    return {"cases": len(rows), "families": len({row["family_id"] for row in rows if row["family_id"] is not None}),
            "unknown_family_cases": sum(row["family_id"] is None for row in rows)}


def paired(rows, left, right):
    groups = families(rows, lambda row: int(hit(row, left)) - int(hit(row, right)))
    if not groups:
        return None
    result = contrast([groups[key] for key in sorted(groups)])
    low, high = result["group_bootstrap_95pct_delta_pp"]
    group_means = {key: sum(group) / len(group) for key, group in groups.items()}
    total = sum(group_means.values())
    return {
        "left": left, "right": right,
        "case_weighted_delta_pp": result["pair_weighted_delta_pp"],
        "family_weighted_delta_pp": result["group_weighted_delta_pp"],
        "family_bootstrap_95pct_delta_pp": [low, high], "interval_width_pp": high - low,
        "leave_one_family_out_range_delta_pp": result["leave_one_group_out_delta_pp"],
        "leave_one_family_out_delta_pp": [
            {"family_id": family or None, "unknown_family_case_id": unknown_case or None,
             "delta_pp": 100 * (total - group_means[family, unknown_case]) / (len(groups) - 1)}
            for family, unknown_case in sorted(groups) if len(groups) > 1
        ],
        "discordant_cases": {left: result["discordant_pairs"]["neural_only"], right: result["discordant_pairs"]["symbolic_only"]},
        "family_macro_discordance": mean(family_means(families(rows, lambda row: hit(row, left) != hit(row, right)))),
    }


def localization(rows, arms):
    result = {**counts(rows), "arms": {}}
    for arm in arms:
        emitted = [row for row in rows if row["arms"][arm]["candidates"]]
        retained = lambda row: bool(set(row["accepted_node_ids"]) & set(row["arms"][arm]["candidates"]))
        result["arms"][arm] = {
            "top1": grouped_rate(rows, lambda row: hit(row, arm)),
            "retention": grouped_rate(rows, retained), "retention_emitted": grouped_rate(emitted, retained),
            "prediction_coverage": grouped_rate(rows, lambda row: top(row, arm) is not None),
            "candidates": dict(sorted(Counter(len(row["arms"][arm]["candidates"]) for row in rows).items())),
            "mean_reduction_emitted": mean([1 - len(row["arms"][arm]["candidates"]) / len(row["canonical_node_ids"])
                                            for row in emitted]),
            "statuses": dict(sorted(Counter(row["arms"][arm]["status"] for row in rows).items())),
        }
    result["paired"] = paired(rows, *PRIMARY) if all(arm in arms for arm in PRIMARY) else None
    return result


def bounds(rows):
    def unresolved_delta(row, side):
        left, right = (top(row, arm) for arm in PRIMARY)
        if row["reference_status"] == "unresolved" and left != right:
            return int(left is not None) if side == 1 else -int(right is not None)
        return int(hit(row, PRIMARY[0])) - int(hit(row, PRIMARY[1]))

    estimates = [mean(family_means(families(rows, lambda row: unresolved_delta(row, side)))) for side in (-1, 1)]
    return {
        "arms": {arm: {"lower": grouped_rate(rows, lambda row: hit(row, arm)),
                       "upper": grouped_rate(rows, lambda row: hit(row, arm) or
                                             (row["reference_status"] == "unresolved" and top(row, arm) is not None))}
                 for arm in PRIMARY},
        "family_weighted_delta_pp": [value * 100 for value in estimates] if rows else None,
    }


def alert_summary(rows, arm):
    return {**counts(rows),
            "alerts_over_all": grouped_rate(rows, lambda row: row["arms"][arm]["alert"] is True),
            "alerts_upper_bound": grouped_rate(rows, lambda row: row["arms"][arm]["alert"] is not False),
            "coverage": grouped_rate(rows, lambda row: row["arms"][arm]["alert"] is not None),
            "abstentions": sum(row["arms"][arm]["alert"] is None for row in rows)}


def multi_candidate(rows, arms, *, retained_only):
    matched = []
    for row in rows:
        candidates = row["arms"]["work_scoped"]["candidates"]
        accepted = set(row["accepted_node_ids"])
        overlap = len(accepted.intersection(candidates))
        if len(candidates) >= 2 and (overlap or not retained_only):
            matched.append((row, candidates[0] in accepted, overlap / len(candidates)))
    cases = [row for row, _, _ in matched]
    first = {row["case_id"]: correct for row, correct, _ in matched}
    uniform = {row["case_id"]: probability for row, _, probability in matched}
    return {**localization(cases, [arm for arm in ("work_scoped", "work_scoped_symbolic") if arm in arms]),
            "raw_first_top1": grouped_rate(cases, lambda row: first[row["case_id"]]),
            "uniform_expected_top1": grouped_rate(cases, lambda row: uniform[row["case_id"]])}


def comparator_swap(rows):
    groups = defaultdict(list)
    for row in rows:
        if row["intended_slot"].startswith("comparator_swap_"):
            groups[row["family"]].append(row)
    exercised = 0
    for pair in groups.values():
        if all(row["disposition"] == "quarantined" for row in pair):
            continue
        require(len(pair) == 2 and {row["intended_slot"] for row in pair} == {"comparator_swap_positive", "comparator_swap_sham"},
                "Invalid comparator-swap allocation in final family")
        confirmed = [row for row in pair if row["disposition"] in CONFIRMED]
        if len(confirmed) == 2:
            left, right = confirmed
            require(left["workload_sha256"] == right["workload_sha256"], "Comparator-swap workload mismatch")
            require(left["source_sha256"] == right["source_sha256"]
                    and left["mapped_source_sha256"] == right["mapped_source_sha256"], "Comparator-swap source mismatch")
            if left["mapped_source_sha256"] is not None:
                require(left["profile_status"] == right["profile_status"] and left["arms"] == right["arms"],
                        "Comparator-swap predictions disagree on identical evaluated inputs")
                exercised += left["profile_status"] == "complete"
    drawn = [row for group in groups.values() for row in group]
    return {**counts(drawn), "verified_pairs": exercised, "dispositions": dict(Counter(row["disposition"] for row in drawn))}


def summarize(rows, arms):
    intended = [row for row in rows if row["intended_slot"] in POSITIVE_SLOTS]
    positives = [row for row in intended if row["disposition"] == "confirmed_positive"]
    resolved = [row for row in positives if row["reference_status"] == "resolved"]
    off_symptom = [row for row in resolved if row["arms"]["work_scoped"]["alert"] is True
                   and row["arms"]["work_scoped"]["symptom_id"] not in row["accepted_node_ids"]]
    complete = [row for row in positives if all(top(row, arm) is not None for arm in PRIMARY)]
    primary = localization(positives, arms)
    disagreement = localization(off_symptom, arms)
    flow = {outcome: counts([row for row in rows if row["disposition"] == outcome])
            for outcome in sorted({row["disposition"] for row in rows})}
    controls = {kind: [row for row in rows if row["intended_slot"] == slot and row["disposition"] == kind]
                for kind, slot in (("confirmed_sham", "same_growth_sham"), ("confirmed_appropriate", "appropriate_superlinear"))}
    selectors = [arm for arm in ("work_scoped", "hits_scoped") if arm in arms]
    return {
        "draw": counts(rows), "provenance_eligible": counts([row for row in rows if row["disposition"] != "quarantined"]),
        "verification_flow": flow,
        "verification_by_slot": {slot: dict(sorted(Counter(row["disposition"] for row in rows
                                                          if row["intended_slot"] == slot).items()))
                                 for slot in sorted({row["intended_slot"] for row in rows})},
        "profile_statuses": dict(sorted(Counter(row["profile_status"] for row in rows).items())),
        "primary": primary, "resolved": localization(resolved, arms), "complete_case": localization(complete, arms),
        "symptom_disagreement": disagreement, "reference_bounds": bounds(positives),
        "author_off_site": localization([row for row in positives if row["intended_slot"] == "positive_off_site"], arms),
        "intention_to_test": {**localization(intended, arms), "weighting_for_unknown_family_cases": "one unit per case"},
        "multi_candidate": multi_candidate(positives, arms, retained_only=False),
        "multi_candidate_reference_retained": multi_candidate(positives, arms, retained_only=True),
        "alerts": {arm: {"confirmed_positive": alert_summary(positives, arm),
                         **{kind: alert_summary(cohort, arm) for kind, cohort in controls.items()}}
                   for arm in selectors},
        "work_minus_hits": {scope: paired(positives, f"work_{scope}", f"hits_{scope}")
                            for scope in ("scoped", "conventional")} if "hits_scoped" in arms else {},
        "comparator_swap": comparator_swap(rows),
    }


def score(draw, labels, predictions, *, draw_sha256, labels_sha256):
    by_seed = join(draw, labels, predictions, draw_sha256, labels_sha256)
    reports = {str(seed): summarize(rows, predictions["arm_ids"]) for seed, rows in by_seed.items()}
    primary = reports["42"]["primary"]
    off_symptom = reports["42"]["symptom_disagreement"]
    positive = primary["families"] >= 60 and primary["paired"]["family_bootstrap_95pct_delta_pp"][0] > 0
    away = positive and off_symptom["families"] >= 30 and off_symptom["paired"]["family_bootstrap_95pct_delta_pp"][0] > 0
    return {"primary_seed": 42, "arm_ids": predictions["arm_ids"], "by_seed": reports,
            "primary_sized": primary["families"] >= 60, "positive_primary_evidence": positive,
            "away_from_symptom_evidence": away}


def reject_duplicate_keys(pairs):
    result = dict(pairs)
    require(len(result) == len(pairs), "Duplicate JSON key in sealed ledger")
    return result


def read_pinned(path, expected):
    raw = path.read_bytes()
    require(digest(expected) and sha256(raw).hexdigest() == expected, f"Ledger digest mismatch: {path.name}")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_keys)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("draw", "labels", "predictions"):
        cli.add_argument(f"--{name}", required=True, type=Path)
        cli.add_argument(f"--{name}-sha256", required=True)
    args = cli.parse_args()
    try:
        draw = read_pinned(args.draw, args.draw_sha256)
        labels = read_pinned(args.labels, args.labels_sha256)
        predictions = read_pinned(args.predictions, args.predictions_sha256)
        result = score(draw, labels, predictions, draw_sha256=args.draw_sha256, labels_sha256=args.labels_sha256)
    except (OSError, ValueError) as error:
        cli.error(str(error))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
