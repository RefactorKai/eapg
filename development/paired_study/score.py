"""Join independently pinned ledgers for the paired repeated-work study."""

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from math import comb, exp, fsum, lgamma, log, log1p
from pathlib import Path
from random import Random
import re
from statistics import NormalDist
import sys


REGISTRATION_SCHEMA = "eapg.paired.registration.v1"
EVALUATION_SCHEMA = "eapg.paired.evaluation.v1"
PREDICTIONS_SCHEMA = "eapg.paired.predictions.v1"
PINS = {"protocol", "draw", "groups", "methods", "analysis"}
CONFIRMATORY_PINS = {
    "access", "staffing", "workloads", "toolchain", "review_protocol", "split_audit",
}
GATES = {
    "min_primary_groups", "target_power", "win_probability", "loss_probability",
    "max_false_alert_rate", "practical_margin",
}
POSITIVE = "confirmed_positive"
NEGATIVES = {"verified_negative", "constant_factor"}
EVAL_STATUSES = NEGATIVES | {
    POSITIVE, "indeterminate", "compile_failure", "oracle_failure", "insufficient_scales",
    "unsupported", "resource_failure", "sanitizer_failure", "unreviewed",
}
METHOD_STATUSES = {
    "ranked", "tie", "abstain", "unsupported", "insufficient", "no_alert", "measurement_failure",
}
LOCATIONS = {"at_symptom", "off_symptom", "mixed", "unknown"}
TIMING = {"confirmed", "unconfirmed", "indeterminate", "not_measured"}
ALPHA = 0.05
Z = NormalDist().inv_cdf(1 - ALPHA / 2)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def fields(value, expected, context):
    require(type(value) is dict and value.keys() == expected, f"Unexpected fields in {context}")


def identifier(value):
    return type(value) is str and bool(value.strip()) and value == value.strip()


def identifiers(value, context):
    require(type(value) is list and all(map(identifier, value)) and len(set(value)) == len(value),
            f"Expected unique identifiers in {context}")
    return set(value)


def digest(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def read_pinned(path, expected):
    raw = path.read_bytes()
    require(digest(expected) and sha256(raw).hexdigest() == expected, f"Ledger digest mismatch: {path.name}")

    def unique_object(pairs):
        result = dict(pairs)
        require(len(result) == len(pairs), f"Duplicate JSON key in {path.name}")
        return result

    def nonfinite(value):
        raise ValueError(f"Nonfinite JSON value in {path.name}: {value}")

    return json.loads(raw, object_pairs_hook=unique_object, parse_constant=nonfinite)


def index_rows(rows, expected, context):
    require(type(rows) is list, f"Expected a row list in {context}")
    index = {}
    for row in rows:
        fields(row, expected, context)
        case = row["id"]
        require(identifier(case) and case not in index, f"Invalid or duplicate case in {context}")
        index[case] = row
    return index


def unit_groups(value, allowed, context):
    require(type(value) is list, f"Expected groups in {context}")
    groups = [frozenset(identifiers(group, context)) for group in value]
    require(all(group and group <= allowed for group in groups), f"Empty or unmapped unit group in {context}")
    return groups


def probability(value):
    return type(value) in (int, float) and 0 <= value <= 1


def exact_mcnemar(wins, losses):
    """Two-sided exact conditional test, including all ties in the estimand only."""
    discordant = wins + losses
    return min(1.0, (2 * sum(comb(discordant, k) for k in range(min(wins, losses) + 1))) / (1 << discordant))


def binomial_masses(n, p):
    if p in (0, 1):
        return [float(k == n * p) for k in range(n + 1)]
    total = lgamma(n + 1)
    log_p, log_q = log(p), log1p(-p)
    return [
        exp(total - lgamma(k + 1) - lgamma(n - k + 1) + k * log_p + (n - k) * log_q)
        for k in range(n + 1)
    ]


def exact_power(n, wins, losses):
    """Power for the exact McNemar test under the registered trinomial alternative."""
    require(type(n) is int and n > 0 and probability(wins) and probability(losses)
            and wins > losses and wins + losses <= 1,
            "Power requires a positive group count and success probabilities with wins > losses")
    discordance = wins + losses
    power = []
    for d, mass in enumerate(binomial_masses(n, discordance)):
        if not mass:
            continue
        # 2 * lower_tail <= .05, evaluated without floating-point boundary error.
        cutoff, numerator = -1, 0
        for k in range(d // 2 + 1):
            numerator += comb(d, k)
            if 40 * numerator > 1 << d:
                break
            cutoff = k
        if cutoff >= 0:
            probabilities = binomial_masses(d, wins / discordance)
            power.append(mass * fsum(probabilities[:cutoff + 1] + probabilities[d - cutoff:]))
    return min(1.0, fsum(power))


def binomial_upper(count, total):
    """One-sided 95% exact Clopper–Pearson upper limit."""
    if not total:
        return None
    if count == total:
        return 1.0
    if not count:
        return 1 - ALPHA ** (1 / total)
    low, high = count / total, 1.0
    for _ in range(55):
        mid = (low + high) / 2
        if fsum(binomial_masses(total, mid)[:count + 1]) >= ALPHA:
            low = mid
        else:
            high = mid
    return high


def constrained_discordance(delta, wins, losses, ties):
    """Maximize the paired trinomial likelihood over q in [abs(delta), 1]."""
    low, high = abs(delta), 1.0

    def derivative(q):
        benefit = (wins / (q + delta) if q + delta else float("inf")) if wins else 0.0
        harm = (losses / (q - delta) if q - delta else float("inf")) if losses else 0.0
        agreement = (ties / (1 - q) if q < 1 else float("inf")) if ties else 0.0
        return benefit + harm - agreement

    if derivative(low) <= 0:
        return low
    if derivative(high) >= 0:
        return high
    for _ in range(55):
        mid = (low + high) / 2
        if derivative(mid) > 0:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def matched_score_interval(wins, losses, ties):
    """Invert the 95% paired risk-difference score test (Tango 1998, DOI 10.1002/sim780)."""
    n = wins + losses + ties
    if not n:
        return None
    mean = (wins - losses) / n

    def endpoint(bound):
        inside, outside = mean, bound
        for _ in range(55):
            delta = (inside + outside) / 2
            if abs(delta) == 1:
                break
            q = constrained_discordance(delta, wins, losses, ties)
            if n * (mean - delta) ** 2 <= Z ** 2 * (q - delta ** 2):
                inside = delta
            else:
                outside = delta
        return inside

    return [endpoint(-1.0), endpoint(1.0)]


def validate_registration(registration):
    fields(registration, {
        "schema", "phase", "population", "seed", "arms", "candidate", "comparator", "pins", "cases", "gates",
    }, "registration")
    phase = registration["phase"]
    require(registration["schema"] == REGISTRATION_SCHEMA and phase in ("development", "confirmatory")
            and identifier(registration["population"]) and type(registration["seed"]) is int,
            "Invalid registration identity")
    arms = identifiers(registration["arms"], "registered methods")
    candidate, comparator = registration["candidate"], registration["comparator"]
    require(identifier(candidate) and identifier(comparator) and candidate != comparator
            and {candidate, comparator} <= arms, "Invalid registered primary contrast")
    expected_pins = PINS | CONFIRMATORY_PINS if phase == "confirmatory" else PINS
    fields(registration["pins"], expected_pins, "registration pins")
    require(all(map(digest, registration["pins"].values())), "Invalid protocol commitment")
    cases = index_rows(registration["cases"], {"id", "group", "units", "span_map_sha256"}, "draw")
    require(cases, "Empty draw")
    for case, row in cases.items():
        require(identifier(row["group"]) and digest(row["span_map_sha256"]), f"Invalid group or span map for {case}")
        identifiers(row["units"], f"{case} registered source units")
    gates = registration["gates"]
    if phase == "development":
        require(gates is None, "Development data cannot authorize a confirmatory decision")
    else:
        fields(gates, GATES, "confirmatory gates")
        minimum = gates["min_primary_groups"]
        require(type(minimum) is int and 0 < minimum <= len({row["group"] for row in cases.values()}),
                "Registered frame cannot meet the prospective sizing gate")
        require(all(probability(gates[key]) for key in GATES - {"min_primary_groups"})
                and 0 < gates["max_false_alert_rate"] < 1 and 0 < gates["target_power"] < 1,
                "Invalid confirmatory decision thresholds")
        require(exact_power(minimum, gates["win_probability"], gates["loss_probability"]) >= gates["target_power"],
                "Registered minimum does not reach the declared paired-test power")
    return cases


def ledger_rows(ledger, schema, registration_sha, cases, extra):
    fields(ledger, {"schema", "registration_sha256", "cases"}, schema)
    require(digest(registration_sha) and ledger["schema"] == schema
            and ledger["registration_sha256"] == registration_sha, f"Wrong registration binding in {schema}")
    index = index_rows(ledger["cases"], {"id", "span_map_sha256"} | extra, schema)
    require(index.keys() == cases.keys(), f"Incomplete or foreign draw in {schema}")
    for case, row in index.items():
        require(row["span_map_sha256"] == cases[case]["span_map_sha256"], f"Mismatched source map for {case}")
    return index


def prepare_selection(registration, evaluation, registration_sha, evaluation_sha=None):
    cases = validate_registration(registration)
    references = ledger_rows(evaluation, EVALUATION_SCHEMA, registration_sha, cases, {
        "status", "mechanism", "location", "timing", "acceptable_sets", "receipt_sha256",
    })
    primary, negative, single, joint = [], [], [], []
    for case in sorted(cases):
        ref, row = references[case], cases[case]
        require(identifier(ref["status"]) and ref["status"] in EVAL_STATUSES
                and identifier(ref["location"]) and ref["location"] in LOCATIONS
                and identifier(ref["timing"]) and ref["timing"] in TIMING
                and identifier(ref["mechanism"]) and digest(ref["receipt_sha256"]), f"Invalid evaluation for {case}")
        acceptable = unit_groups(ref["acceptable_sets"], set(row["units"]), f"{case} references")
        require(not acceptable or ref["status"] == POSITIVE, f"Unexpected reference label for {case}")
        require(len(acceptable) == len(set(acceptable))
                and not any(a < b for a in acceptable for b in acceptable), f"Non-minimal reference sets for {case}")
        if any(len(a) == 1 for a in acceptable):
            single.append(case)
            if len(row["units"]) > 1:
                primary.append(case)
        if any(len(a) > 1 for a in acceptable):
            joint.append(case)
        if ref["status"] in NEGATIVES:
            negative.append(case)

    def representatives(eligible, purpose):
        chosen = {}

        def key(case_id):
            return sha256(json_bytes([registration["seed"], registration["population"], purpose, case_id])).digest()

        for case in sorted(eligible, key=key):
            chosen.setdefault(cases[case]["group"], case)
        return dict(sorted(chosen.items()))

    selection = {
        "schema": "eapg.paired.selection.v1",
        "registration_sha256": registration_sha,
        "evaluation_sha256": evaluation_sha or sha256(json_bytes(evaluation)).hexdigest(),
        "primary": representatives(primary, "positive"),
        "negative": representatives(negative, "negative"),
    }
    return cases, references, primary, negative, single, joint, selection


def select(registration, evaluation, registration_sha, evaluation_sha=None):
    """Produce the pre-join selection receipt without opening predictions."""
    return prepare_selection(registration, evaluation, registration_sha, evaluation_sha)[-1]


def parse_predictions(predictions, registration_sha, cases, arms):
    output = ledger_rows(predictions, PREDICTIONS_SCHEMA, registration_sha, cases, {"arms"})
    for case, row in output.items():
        fields(row["arms"], set(arms), f"{case} methods")
        for arm, prediction in row["arms"].items():
            context = f"{case} {arm}"
            fields(prediction, {"alert", "candidates", "ranking", "status"}, context)
            status, alert = prediction["status"], prediction["alert"]
            require(identifier(status) and status in METHOD_STATUSES and (alert is None or type(alert) is bool),
                    f"Invalid method status or alert in {context}")
            candidates = identifiers(prediction["candidates"], f"{context} candidates")
            require(candidates <= set(cases[case]["units"]), f"Unmapped candidates in {context}")
            blocks = unit_groups(prediction["ranking"], candidates, f"{context} ranking")
            require(sum(map(len, blocks)) == len(set().union(*blocks)), f"Repeated ranked unit in {context}")
            unique_first = blocks and len(blocks[0]) == 1
            if status in {"ranked", "tie"}:
                require(alert is True and blocks and bool(unique_first) == (status == "ranked"),
                        f"Ranking and alert disagree in {context}")
            else:
                require(not blocks and (status != "no_alert" or alert is False),
                        f"Ranking and abstention disagree in {context}")
    return output


def strict_prefix(ranking, budget):
    inspected = set()
    for block in ranking:
        if len(inspected) + len(block) > budget:
            break
        inspected.update(block)
    return inspected


def rate(count, total):
    return {"count": count, "total": total, "rate": count / total if total else None}


def paired_exploratory(cases, outcomes, seed, interval):
    groups = defaultdict(list)
    for case, delta in outcomes.items():
        groups[cases[case]["group"]].append(delta)
    means = [fsum(groups[g]) / len(groups[g]) for g in sorted(groups)]
    n = len(means)
    result = {"pairs": len(outcomes), "groups": n, "difference": fsum(means) / n if n else None,
              "cluster_bootstrap_95": None}
    if interval and n > 1:
        rng = Random(seed)
        draws = sorted(fsum(means[rng.randrange(n)] for _ in range(n)) / n for _ in range(10000))
        result["cluster_bootstrap_95"] = [draws[249], draws[9749]]
    return result


def arm_summary(output, references, cases, arm, singles, joint, negatives, negative_reps, confirmatory):
    predictions = {case: row["arms"][arm] for case, row in output.items()}
    unresolved = [case for case, row in references.items() if row["status"] == POSITIVE and not row["acceptable_sets"]]

    def label_sets(case, size):
        return [set(group) for group in references[case]["acceptable_sets"] if (len(group) == 1) == (size == 1)]

    def hit(case, budget, size=1):
        selected = strict_prefix(predictions[case]["ranking"], budget)
        return any(group <= selected for group in label_sets(case, size))

    def stats(ids):
        return {"top1": rate(sum(hit(case, 1) for case in ids), len(ids)),
                "top2": rate(sum(hit(case, 2) for case in ids), len(ids))}

    statuses = Counter(prediction["status"] for prediction in predictions.values())
    hits = {case: hit(case, 1) for case in singles}
    all_candidates = [case for case in singles if predictions[case]["candidates"]]
    support = {case: pred["status"] not in {"unsupported", "insufficient", "measurement_failure"}
               for case, pred in predictions.items()}
    negative_alerts = sum(predictions[case]["alert"] is True for case in negative_reps)
    unknown_negative_alerts = sum(predictions[case]["alert"] is None for case in negative_reps)
    negative_summary = rate(negative_alerts, len(negative_reps))
    negative_summary["unknown_alerts"] = unknown_negative_alerts
    negative_summary["evaluated_only"] = rate(negative_alerts, len(negative_reps) - unknown_negative_alerts)
    negative_summary["upper_95"] = binomial_upper(negative_alerts, len(negative_reps)) if confirmatory else None
    if confirmatory:
        negative_summary["upper_95_if_all_unknown_alert"] = binomial_upper(
            negative_alerts + unknown_negative_alerts, len(negative_reps))
    supported_positive_candidates = [len(predictions[case]["candidates"]) for case in all_candidates]
    expected, inspected = [], []
    for case in singles:
        prediction, acceptable = predictions[case], label_sets(case, 1)
        ranking = prediction["ranking"]
        accepted = set().union(*acceptable)
        expected.append(len(accepted & set(ranking[0])) / len(ranking[0]) if ranking else 0)
        visits = 0
        for block in ranking:
            visits += len(block)
            if accepted.intersection(block):
                inspected.append(visits)
                break
    total = len(singles) + len(unresolved)
    known_hits = sum(hits.values())
    possible = sum(predictions[case]["status"] == "ranked" for case in unresolved)
    bounds = [known_hits / total, (known_hits + possible) / total] if total else None
    summary = {
        **stats(singles),
        "status_flow": dict(sorted(statuses.items())),
        "draw_support": rate(sum(support.values()), len(cases)),
        "draw_unique_recommendations": rate(statuses["ranked"], len(cases)),
        "draw_alert_coverage": rate(sum(pred["alert"] is not None for pred in predictions.values()), len(cases)),
        "draw_first_place_ties": rate(statuses["tie"], len(cases)),
        "confirmed_positive_abstentions": rate(sum(predictions[case]["status"] != "ranked" for case in singles), len(singles)),
        "confirmed_positive_wrong_recommendations": rate(
            sum(predictions[case]["status"] == "ranked" and not hits[case] for case in singles), len(singles)),
        "candidate_emission": rate(len(all_candidates), len(singles)),
        "conditional_candidate_recall": rate(sum(
            any(label <= set(predictions[case]["candidates"]) for label in label_sets(case, 1))
            for case in all_candidates), len(all_candidates)),
        "mean_candidate_count_when_emitted": (
            fsum(supported_positive_candidates) / len(all_candidates) if all_candidates else None),
        "mean_inspection_count_to_complete_tie_block_given_hit": fsum(inspected) / len(inspected) if inspected else None,
        "inspection_hits": len(inspected),
        "expected_top1_uniform_ties": fsum(expected) / len(expected) if expected else None,
        "unresolved_top1_bounds": bounds,
        "unresolved_top1_total": total,
        "joint_top2": rate(sum(hit(case, 2, size=2) for case in joint), len(joint)),
        "joint_any_budget": rate(sum(hit(case, len(cases[case]["units"]), size=2) for case in joint), len(joint)),
        "negative_alerts": rate(sum(predictions[case]["alert"] is True for case in negatives), len(negatives)),
        "negative_abstentions": rate(sum(predictions[case]["alert"] is None for case in negatives), len(negatives)),
        "negative_representative_alerts": negative_summary,
        "strata": {
            "mechanism": {key: stats([case for case in singles if references[case]["mechanism"] == key])
                          for key in sorted({references[case]["mechanism"] for case in singles})},
            "location": {key: stats([case for case in singles if references[case]["location"] == key])
                         for key in sorted(LOCATIONS)},
            "support": {key: stats([case for case in singles if support[case] == active])
                        for key, active in (("supported", True), ("unsupported", False))},
            "change_units": {key: stats([case for case in singles if (len(cases[case]["units"]) > 1) == multi])
                             for key, multi in (("single_unit", False), ("multi_unit", True))},
        },
    }
    return summary, hits, support


def score(registration, evaluation, predictions, registration_sha, selection_sha=None, *,
          evaluation_sha=None, predictions_sha=None):
    cases, refs, multi, negatives, singles, joint, selection = prepare_selection(
        registration, evaluation, registration_sha, evaluation_sha)
    digest_selection = sha256(json_bytes(selection)).hexdigest()
    confirmatory = registration["phase"] == "confirmatory"
    require((not confirmatory and selection_sha is None) or selection_sha == digest_selection,
            "Missing or mismatched pre-join selection commitment")
    arms = registration["arms"]
    output = parse_predictions(predictions, registration_sha, cases, arms)
    summaries, hits, support = {}, {}, {}
    negative_reps = list(selection["negative"].values())
    for arm in arms:
        summaries[arm], hits[arm], support[arm] = arm_summary(
            output, refs, cases, arm, singles, joint, negatives, negative_reps, confirmatory)
    candidate, comparator = registration["candidate"], registration["comparator"]
    selected = list(selection["primary"].values())
    table = Counter((hits[candidate][case], hits[comparator][case]) for case in selected)
    wins, losses, both, neither = (table[(True, False)], table[(False, True)],
                                   table[(True, True)], table[(False, False)])
    n = len(selected)
    interval = matched_score_interval(wins, losses, both + neither) if confirmatory else None
    p_value = exact_mcnemar(wins, losses) if confirmatory and n else None
    decision = None
    if confirmatory:
        gates = registration["gates"]
        upper = summaries[candidate]["negative_representative_alerts"]["upper_95_if_all_unknown_alert"]
        adequate = n >= gates["min_primary_groups"]
        superiority = adequate and wins > losses and interval[0] > 0 and p_value <= ALPHA
        decision = {
            "group_sizing_gate_met": adequate,
            "superiority_supported": superiority,
            "practical_margin_supported": superiority and interval[0] > gates["practical_margin"],
            "false_alert_target_supported": upper is not None and upper <= gates["max_false_alert_rate"],
        }
    differences = {case: int(hits[candidate][case]) - int(hits[comparator][case]) for case in multi}
    common = {case: delta for case, delta in differences.items()
              if support[candidate][case] and support[comparator][case]}
    return {
        "schema": "eapg.paired.score.v1",
        "selection_sha256": digest_selection,
        "predictions_sha256": predictions_sha or sha256(json_bytes(predictions)).hexdigest(),
        "selection": selection,
        "population": registration["population"],
        "flow": {
            "drawn_pairs": len(cases),
            "drawn_groups": len({row["group"] for row in cases.values()}),
            "resolved_single_recommendation_pairs": len(singles),
            "confirmed_positive_unresolved_pairs": sum(
                row["status"] == POSITIVE and not row["acceptable_sets"] for row in refs.values()),
            "joint_reference_pairs": len(joint),
            "screening": {
                status: {
                    "pairs": sum(row["status"] == status for row in refs.values()),
                    "groups": len({cases[case]["group"] for case, row in refs.items() if row["status"] == status}),
                }
                for status in sorted(EVAL_STATUSES)
            },
            "timing": dict(sorted(Counter(row["timing"] for row in refs.values()).items())),
            "mutual_primary_method_support": rate(
                sum(support[candidate][case] and support[comparator][case] for case in cases), len(cases)),
        },
        "arms": summaries,
        "primary": {
            "candidate": candidate, "comparator": comparator, "groups": n,
            "table": {"wins": wins, "losses": losses, "both": both, "neither": neither},
            "difference": (wins - losses) / n if n else None,
            "matched_score_interval_95": interval,
            "mcnemar_p_exact_two_sided": p_value,
            "inference": "confirmatory" if confirmatory else "descriptive",
            "decision": decision,
        },
        "exploratory": {
            "group_macro_all_multi_unit_pairs": paired_exploratory(cases, differences, registration["seed"], confirmatory),
            "group_macro_mutually_supported_multi_unit_pairs": paired_exploratory(
                cases, common, registration["seed"], confirmatory),
        },
    }


def validate_committed_draw(registration):
    validate_registration(registration)
    require(sha256(json_bytes(registration["cases"])).hexdigest() == registration["pins"]["draw"],
            "Registered cases differ from the committed draw")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    power_parser = commands.add_parser("power", help="Compute prospective, exact-test rejection probabilities")
    power_parser.add_argument("--groups", type=int, nargs="+", required=True)
    power_parser.add_argument("--win-probability", type=float, required=True)
    power_parser.add_argument("--loss-probability", type=float, required=True)
    for name in ("select", "score"):
        command = commands.add_parser(name, help="Seal selection" if name == "select" else "Join sealed ledgers")
        for ledger in ("registration", "evaluation", *(("predictions",) if name == "score" else ())):
            command.add_argument(f"--{ledger}", type=Path, required=True)
            command.add_argument(f"--{ledger}-sha256", required=True)
        command.add_argument("--split-audit", type=Path, help="Required for confirmatory registration")
        if name == "score":
            command.add_argument("--selection-sha256")
    args = parser.parse_args()
    try:
        if args.command == "power":
            result = {"method": "exact two-sided conditional McNemar, alpha=0.05", "by_groups": [
                {"groups": n, "power": exact_power(n, args.win_probability, args.loss_probability)} for n in args.groups
            ], "win_probability": args.win_probability, "loss_probability": args.loss_probability}
        else:
            registration = read_pinned(args.registration, args.registration_sha256)
            validate_registration(registration)
            if registration["phase"] == "confirmatory":
                from .quarantine import check_registration

                require(args.split_audit is not None, "Confirmatory registration requires a pinned split audit")
                split_audit = read_pinned(args.split_audit, registration["pins"]["split_audit"])
                check_registration(split_audit, registration)
            validate_committed_draw(registration)
            require(sha256(Path(__file__).read_bytes()).hexdigest() == registration["pins"]["analysis"],
                    "Active scorer differs from the committed analysis")
            evaluation = read_pinned(args.evaluation, args.evaluation_sha256)
            selection = select(registration, evaluation, args.registration_sha256, args.evaluation_sha256)
            if args.command == "select":
                result = selection
            else:
                if registration["phase"] == "confirmatory":
                    require(args.selection_sha256 == sha256(json_bytes(selection)).hexdigest(),
                            "Missing or mismatched pre-join selection commitment")
                predictions = read_pinned(args.predictions, args.predictions_sha256)
                result = score(registration, evaluation, predictions, args.registration_sha256, args.selection_sha256,
                               evaluation_sha=args.evaluation_sha256, predictions_sha=args.predictions_sha256)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    sys.stdout.buffer.write(json_bytes(result))


if __name__ == "__main__":
    main()
