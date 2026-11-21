"""Recompute the paired qualification and secondary development statistics from public rows."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction
from functools import lru_cache
from hashlib import sha256
import json
from math import comb, lcm
from runpy import run_path

from replay_pilot_contrast import DRAWS, PILOT, ROOT, SEED, contrast, verified_json
from replay_resplit_ablation import compute_baselines, verified_pipeline
from verify_weighted_panel import replay as replay_weighted_panel


RECEIPT = ROOT / "development/grouped_statistics.json"
MACROS = ROOT / "manuscript/grouped_statistics_macros.tex"
SPECIFICITY = ROOT / "development/specificity_sweeps.json"
PAIRED = ROOT / "artifacts/paired_development"
RESPLIT = ROOT / "artifacts/pilot_resplit"
PRIMARY = ("desk_stop_minus_execution", "all_stream_alert_minus_no_alert")
REPRESENTATION_PAIRS = (
    *(("abstract_graph", rhs) for rhs in
      ("raw_code", "hotspot_raw", "static_eapg", "abstract_hits_only", "full_eapg")),
    ("full_eapg", "raw_code"), ("full_eapg", "static_eapg"),
)


def read_json(path):
    return json.loads(path.read_bytes())


def file_digest(path):
    return sha256(path.read_bytes()).hexdigest()


def holm(p_values):
    adjusted = {}
    running = 0.0
    ordered = sorted(p_values, key=p_values.get)
    for remaining, key in zip(range(len(ordered), 0, -1), ordered, strict=True):
        running = max(running, min(1.0, remaining * p_values[key]))
        adjusted[key] = running
    return adjusted


@lru_cache(maxsize=None)
def clopper_pearson(k, n):
    def lower(successes):
        if successes == 0:
            return 0.0
        terms = [(i, comb(n, i)) for i in range(successes, n + 1)]
        lo, hi = 0.0, 1.0
        for _ in range(53):
            p = (lo + hi) / 2
            tail = sum(coef * p**i * (1 - p)**(n - i) for i, coef in terms)
            if tail < 0.025:
                lo = p
            else:
                hi = p
        return (lo + hi) / 2

    return lower(k), 1 - lower(n - k)


def rate(count, total):
    if not 0 <= count <= total or total == 0:
        raise ValueError(f"Undefined rate: {count}/{total}")
    return {
        "count": count, "total": total, "percent": round(100 * count / total, 1),
        "clopper_pearson_95pct_percent": [round(100 * x, 1) for x in clopper_pearson(count, total)],
    }


def proportion(rows, predicate):
    return rate(sum(map(predicate, rows)), len(rows))


def sign_flip_p(weights):
    observed = abs(sum(weights))
    if observed == 0:
        return 1.0
    totals = Counter({0: 1})
    for weight in filter(None, weights):
        next_totals = Counter()
        for value, count in totals.items():
            next_totals[value + weight] += count
            next_totals[value - weight] += count
        totals = next_totals
    return sum(count for value, count in totals.items() if abs(value) >= observed) / totals.total()


def paired(rows, group_id, left, right):
    groups = defaultdict(list)
    for row in rows:
        groups[group_id(row)].append(int(left(row)) - int(right(row)))
    ordered = [groups[key] for key in sorted(groups)]
    stats = contrast(ordered)
    effects = [Fraction(sum(group), len(group)) for group in ordered]
    denominator = lcm(*(effect.denominator for effect in effects))
    limits = stats["leave_one_group_out_delta_pp"]
    return {
        "left": proportion(rows, left), "right": proportion(rows, right),
        "groups": stats["groups"],
        "discordant_pairs": {
            "left_only": stats["discordant_pairs"]["neural_only"],
            "right_only": stats["discordant_pairs"]["symbolic_only"],
        },
        "pair_weighted_delta_pp": round(stats["pair_weighted_delta_pp"], 1),
        "group_weighted_delta_pp": round(stats["group_weighted_delta_pp"], 1),
        "group_bootstrap_95pct_delta_pp": [round(x, 1) for x in stats["group_bootstrap_95pct_delta_pp"]],
        "leave_one_group_out_range_delta_pp": None if limits is None else [round(x, 1) for x in limits],
        "cluster_sign_flip_p": sign_flip_p([int(effect * denominator) for effect in effects]),
    }


def qualification():
    replay = run_path(str(PAIRED / "replay.py"))
    ledger = read_json(PAIRED / "ledger.json")
    replay["verify_public"](read_json(PAIRED / "manifest.json"), ledger, read_json(PAIRED / "a01-steady.json"))
    frames = replay["path_b_groups"](ledger)
    rows = frames["147 distinct"]

    def desk_stop(row):
        return row["final_disposition"] in {"desk_excluded", "historical_desk_excluded", "desk_blocked"}

    def execution(row):
        return row["final_disposition"] in {
            "execution_oracle_failure", "verified_historical_control", "verified_growth_evaluation",
        }

    def fitted(row):
        return row["all_stream_alert"] is not None

    def all_stream(row):
        return row["all_stream_alert"] is True

    def any_stream(row):
        return row["any_stream_alert"] is True

    def sensitivity_admitted(row):
        return fitted(row) and all(s.get("drop_largest") is not None for s in row["stream_screens"])

    def sensitivity_alert(row):
        return sensitivity_admitted(row) and all(
            s["drop_largest"]["largest_ratio"] >= 1.50 and s["drop_largest"]["slope"] >= 0.50
            for s in row["stream_screens"]
        )

    def group(row):
        return row["case_id"]

    primary = {
        "desk_stop_minus_execution": paired(rows, group, desk_stop, execution),
        "all_stream_alert_minus_no_alert": paired(list(filter(fitted, rows)), group,
                                                  all_stream, lambda row: not all_stream(row)),
    }
    for key, adjusted in holm({key: primary[key]["cluster_sign_flip_p"] for key in PRIMARY}).items():
        primary[key]["holm_p"] = adjusted
    return {
        "primary": primary,
        "frame_rates": {name: {
            "desk_stops_per_selected": proportion(frame, desk_stop),
            "execution_per_selected": proportion(frame, execution),
            "fits_per_selected": proportion(frame, fitted),
            "all_stream_alerts_per_selected": proportion(frame, all_stream),
            "all_stream_alerts_per_fit": proportion(list(filter(fitted, frame)), all_stream),
            "any_stream_alerts_per_fit": proportion(list(filter(fitted, frame)), any_stream),
        } for name, frame in frames.items()},
        "drop_largest_sensitivity": paired(list(filter(sensitivity_admitted, rows)), group,
                                           all_stream, sensitivity_alert),
        "all_stream_alerts_with_admitted_sensitivity": [
            row["case_id"] for row in rows if all_stream(row) and sensitivity_alert(row)
        ],
        "all_stream_alerts_without_admitted_sensitivity": [
            row["case_id"] for row in rows if all_stream(row) and not sensitivity_admitted(row)
        ],
    }


def pilot_statistics():
    pilot = {row["pair_id"]: row for row in verified_json(PILOT / "pilot100_results.json")}
    historical = verified_json(PILOT / "node_only_ablation/evaluation_results.json")
    strict = read_json(RESPLIT / "ablation_results.json")
    refit = read_json(RESPLIT / "results.json")
    _, baselines = compute_baselines(verified_pipeline(), pilot, strict["split"], refit)
    rows = list(pilot.values())
    owners = {problem: i for i, group in enumerate(historical["template_groups"]) for problem in group}

    def historical_hit(variant):
        return lambda row: (historical["per_pair_predictions"][row["pair_id"]]["variants"][variant]["pred_top1"]
                            == row["gt_node"])

    def strict_group(row):
        return strict["split"][row["pair_id"]]["group"]

    def strict_hit(method, mode):
        return lambda row: strict["predictions"][method][row["pair_id"]][mode][0] == row["gt_node"]

    def refit_hit(method):
        return lambda row: refit["predictions"][row["pair_id"]][method][0] == row["gt_node"]

    def baseline_hit(method):
        return lambda row: baselines[row["pair_id"]][method] == 1

    def slice_hit(key):
        return lambda row: row["gt_node"] in row["slicing"][key]

    cohorts = {
        "all": rows,
        "multi_candidate": [r for r in rows if len(r["slicing"]["c_pruned"]) >= 2],
        "off_symptom": [r for r in rows if not slice_hit("c_naive_work")(r)],
        **{track.lower(): [r for r in rows if r["track_gt"] == track] for track in ("A1", "A2", "B")},
        "reset": [r for r in rows if r["mechanism_id"] in {"A1.1", "A1.4"}],
    }
    return {
        "symptom_alerts_work_minus_hits": paired(rows, strict_group,
            lambda r: bool(r["slicing"]["c_naive_work"]), lambda r: bool(r["slicing"]["c_naive_hits"])),
        "slice_reference_retention": {key: proportion(rows, slice_hit(key)) for key in
            ("c_naive_hits", "c_naive_work", "c_inter_only", "c_unpruned", "c_pruned")},
        "frozen_23_group_ranking": {
            name: paired(cohorts[name], lambda r: owners[r["problem_id"]], historical_hit("6b-slice"), historical_hit("2"))
            for name in ("all", "multi_candidate")
        },
        "refit_13_group_ranking": {name: {
            f"adapted_minus_{rhs}": paired(cohorts[name], strict_group, refit_hit("adapted"), refit_hit(rhs))
            for rhs in ("base", "symbolic")
        } for name in ("all", "multi_candidate")},
        "strict_13_group_ablations": {name: {mode: {
            f"{left}_minus_{right}": paired(cohort, strict_group, strict_hit(left, mode), strict_hit(right, mode))
            for left, right in REPRESENTATION_PAIRS
        } for mode in ("adapted_constrained", "adapted_unconstrained")} for name, cohort in cohorts.items()},
        "strict_13_group_symbolic_comparisons": {name: {
            f"{left}_minus_{right}": paired(cohorts[name], strict_group,
                strict_hit(left, "adapted_constrained"), baseline_hit(right))
            for left in ("abstract_graph", "hotspot_raw") for right in ("symbolic_default", "symbolic_refined")
        } for name in ("all", "multi_candidate", "off_symptom")},
    }


def part_a_statistics(receipt):
    details = receipt["active_slot_details"]
    core = [row for row in details if row["slot"] in {"positive_at_site", "positive_off_site"}
            and row["disposition"] == "confirmed_positive"]

    def group(row):
        return row["family_id"]

    def hit(arm):
        return lambda row: bool(set(row[f"{arm}_rank"][:1]).intersection(row["accepted"]))

    def retained(arm):
        return lambda row: bool(set(row["accepted"]).intersection(row[f"{arm}_cands"]))

    def alert(row):
        return row["work_scoped_alert"]

    def symptom_hit(row):
        return row["symptom"] in row["accepted"]

    live = {method: {row["id"]: row["top1"] for row in arm["details"]}
            for method, arm in receipt["neural_live_slice_eval"].items()}

    def neural_hit(method):
        return lambda row: live[method][row["case_id"]] in row["accepted"]

    raw_primary = receipt["score_summary"]["by_seed"]["42"]["primary"]["arms"]
    shams = {r["family_id"]: r for r in details if r["slot"] == "same_growth_sham"}
    appropriate = [r for r in details if r["slot"] == "appropriate_superlinear"]
    uniform_hits = sum(Fraction(len(set(r["accepted"]).intersection(r["work_conv_cands"])),
                                len(r["work_conv_cands"])) for r in core)
    return {
        "scoped_minus_cfg_top1": {
            name: paired(rows, group, hit("work_scoped"), hit("work_conv"))
            for name, rows in {
                "core": core, "at_site": [r for r in core if r["slot"] == "positive_at_site"],
                "off_site": [r for r in core if r["slot"] == "positive_off_site"],
            }.items()
        },
        "scoped_minus_cfg_retention": paired(core, group, retained("work_scoped"), retained("work_conv")),
        "uniform_cfg_top1": {
            "expected_hits_exact": str(uniform_hits), "expected_hits": round(float(uniform_hits), 2),
            "total": len(core), "expected_percent": round(100 * float(uniform_hits / len(core)), 2),
            "interval_method": "not applicable: analytic expectation conditional on the fixed candidate sets",
        },
        "scoped_minus_symptom_top1": paired(core, group, hit("work_scoped"), symptom_hit),
        "scoped_minus_symptom_off_site_top1": paired([r for r in core if r["slot"] == "positive_off_site"],
                                                    group, hit("work_scoped"), symptom_hit),
        "aggregate_core_top1": {arm: rate(raw_primary[arm]["top1"]["count"], raw_primary[arm]["top1"]["total"])
            for arm in ("hits_scoped", "hit_growth", "work_scoped_symbolic")},
        "alert_rates": {slot: proportion([r for r in details if r["slot"] == slot], alert) for slot in
                        ("same_growth_sham", "appropriate_superlinear", "comparator_swap_sham")},
        "appropriate_minus_sham_alerts": paired(appropriate, group, alert, lambda r: alert(shams[group(r)])),
        "neural_top1": {arm: proportion(core, neural_hit(arm)) for arm in live},
        "neural_contrasts": {
            f"qlora_abstract_graph_fold0_constrained_minus_{right}": paired(
                core, group, neural_hit("qlora_abstract_graph_fold0_constrained"), neural_hit(right))
            for right in ("base_abstract_graph_constrained", "qlora_hotspot_raw_fold0_constrained")
        },
    }


def part_b_statistics(receipt):
    details = receipt["pair_details"]
    positive = [row for row in details if row["screening_status"] == "confirmed_positive"]
    negative = [row for row in details if row["screening_status"] == "verified_negative"]

    def hit(method):
        return lambda row: bool(set(row[method][:1]).intersection(row["blinded_accepted"]))

    def group(row):
        return row["group_id"]

    return {
        "contrasts": {name: {method: paired(rows, group, hit("abstract_oof"), hit(method))
            for method in ("symbolic", "symbolic_unbiased", "abstract_fold0")
        } for name, rows in {
            "adjudicated_positives": positive,
            "multi_candidate": [r for r in positive if len(r["slice"]) >= 2],
            "without_g_stress_08": [r for r in positive if group(r) != "G_STRESS_08"],
            "without_pie_dev": [r for r in positive if r["pair_id"] != "PIE_DEV_p03497"],
        }.items()},
        "reference_retention": proportion(positive, lambda r: bool(set(r["slice"]).intersection(r["blinded_accepted"]))),
        "verified_negative_alerts": proportion(negative, lambda r: r["symptom_id"] is not None),
    }


def desk_agreement_statistics():
    existing = read_json(PAIRED / "desk-agreement-existing.json")
    fresh = read_json(PAIRED / "desk-agreement-reaudit.json")

    def summary(row, method):
        def interval(key, scale):
            return [round(scale * x, 1) for x in row["bootstrap"][key]["interval_95"]]

        return {
            "interval_method": method,
            "unanimous_rows": {"count": row["unanimous"], "total": row["n"],
                               "percent": round(row["unanimous_percentage"], 1),
                               "bootstrap_95pct_percent": interval("unanimous_percentage", 1)},
            "matching_judgment_pairs": {"count": row["matching_pairs"], "total": row["total_pairs"],
                                        "percent": round(100 * row["p_bar"], 1),
                                        "bootstrap_95pct_percent": interval("p_bar", 100)},
            "kappa": row["kappa"], "kappa_bootstrap_95pct_points": interval("kappa", 100),
        }

    cross = fresh["versus_original"]
    confusion = cross["confusion"]
    exact = sum(counts[label] for label, counts in confusion.items())
    votes = sum(sum(counts.values()) for counts in confusion.values())
    if (exact, votes) != (cross["exact_agreements"], cross["vote_count"]):
        raise ValueError("Desk re-audit agreement does not reconcile")
    return {
        "existing": {key: summary(row, "archived project-cluster bootstrap")
                     for key, row in existing["results"].items()},
        "reaudit": summary(fresh["results"]["five_label"], "archived whole-vector bootstrap within allocation cells"),
        "reaudit_agreement_with_original": {"count": exact, "total": votes, "percent": round(100 * exact / votes, 1),
                                           "interval_method": "not estimated: public counts lack vote-cluster detail"},
    }


def oeis_statistics(receipt):
    rows = [r for r in receipt["candidates"] if r["status"] == "eligible_static_and_analytic"]

    def arm_hit(row, arm):
        return row["reference_node"] in row["analytic_arms"][arm]["ranking"][:1]

    def nearest_preceding_hit(row):
        cfg = row["analytic_arms"]["work_conventional"]
        symptom = int(cfg["symptom_id"][1:])
        nodes = {int(node[1:]): node for node in cfg["candidates"]}
        upstream = [n for n in nodes if n < symptom]
        first = max(upstream) if upstream else min(nodes)
        return nodes[first] == row["reference_node"]

    def mechanism(row):
        return row["mechanism_family"]

    return {
        "eligible": rate(len(rows), len(receipt["candidates"])),
        "nearest_preceding_cfg_minus_scoped_top1": paired(
            rows, mechanism, nearest_preceding_hit, lambda r: arm_hit(r, "work_scoped")),
        "reported_cfg_minus_scoped_top1": paired(
            rows, mechanism, lambda r: arm_hit(r, "work_conventional"), lambda r: arm_hit(r, "work_scoped")),
    }


def specificity_statistics(sweeps, part_a, qualification):
    def counts(row):
        return row["k"], row["n"]

    nominal = sweeps["paired"]["nominal"]
    robust = sweeps["paired"]["nominal_with_drop_largest"]
    fitted = qualification["frame_rates"]["147 distinct"]["all_stream_alerts_per_fit"]
    if (counts(nominal["alerts"]) != (fitted["count"], fitted["total"])
            or set(robust["cases"]) != set(qualification["all_stream_alerts_with_admitted_sensitivity"])
            or set(nominal["cases"]) - set(robust["cases"]) !=
            set(qualification["all_stream_alerts_without_admitted_sensitivity"])):
        raise ValueError("WP-S1 paired sensitivity disagrees with qualification replay")
    seed_table = sweeps["part_a"]["seed_table"]
    for primary_name, category in (("same_growth_sham", "sham_all"),
                                   ("appropriate_superlinear", "appropriate_superlinear"),
                                   ("comparator_swap_sham", "swap_sham")):
        expected = part_a["alert_rates"][primary_name]
        if counts(seed_table["42"]["alerts"][category]) != (expected["count"], expected["total"]):
            raise ValueError(f"WP-S1 disagrees with Part A seed-42 alerts for {category}")
    return {seed: {category: {
        "false_alerts": rate(*counts(row["alerts"][category])),
        "correct_rejections": rate(*counts(rejections)),
    } for category, rejections in row["correct_rejections"].items()} for seed, row in seed_table.items()}


def recompute():
    prospective = ROOT / "development/prospective_multiagent_results.json"
    oeis = ROOT / "development/scalar_intake_feasibility.json"
    development = read_json(prospective)
    panel = ROOT / "artifacts/weighted_panel"
    library, checks = replay_weighted_panel(panel / "lock.json", panel / "results.json")
    inputs = (prospective, oeis, SPECIFICITY, ROOT / "pipeline.py", panel / "lock.json", panel / "results.json",
              PILOT / "pilot100_results.json", PILOT / "node_only_ablation/evaluation_results.json",
              RESPLIT / "ablation_results.json", RESPLIT / "results.json", PAIRED / "ledger.json",
              PAIRED / "manifest.json", PAIRED / "a01-steady.json", PAIRED / "desk-agreement-existing.json",
              PAIRED / "desk-agreement-reaudit.json", PAIRED / "replay.py")
    paired_results = qualification()
    part_a = part_a_statistics(development["part_a_prospective_scalar"])
    return {
        "schema": "eapg-grouped-statistics-v1",
        "input_sha256": {path.relative_to(ROOT).as_posix(): file_digest(path) for path in inputs},
        "script_sha256": file_digest(ROOT / "development/replay_grouped_statistics.py"),
        "evidence_class": "replay-only",
        "methods": {
            "rate_intervals": "two-sided 95% Clopper-Pearson (binomial reference; no cluster adjustment)",
            "contrast_test": "exact two-sided sign flips of whole-cluster mean paired differences",
            "contrast_intervals": "descriptive 95% whole-cluster percentile bootstrap, not used to test",
            "bootstrap_group_order": "ascending group ID; sorted resampled statistics, nearest ranks 250 and 9750",
            "bootstrap_draws": DRAWS, "bootstrap_seed": SEED,
            "primary_multiplicity": "Holm; only the two declared paired qualification contrasts",
        },
        "paired_qualification": paired_results,
        "secondary_desk_agreement": desk_agreement_statistics(),
        "frozen_pilot": pilot_statistics(),
        "part_a": part_a,
        "part_a_specificity_by_seed": specificity_statistics(read_json(SPECIFICITY), part_a, paired_results),
        "part_b": part_b_statistics(development["part_b_blinded_adjudication"]),
        "oeis_development": oeis_statistics(read_json(oeis)),
        "library_calibration": {
            "checks": checks,
            "growth_class_agreement": {
                level: proportion([row for key, row in library.items() if key[0] == level], lambda r: r[1] == r[2])
                for level in sorted({key[0] for key in library})
            },
        },
    }


def render_macros(receipt):
    def limits(values, signed=False):
        return "[" + ", ".join(f"{v:+.1f}" if signed and v else f"{v:.1f}" for v in values) + "]"

    boot = "group_bootstrap_95pct_delta_pp"
    pilot = receipt["frozen_pilot"]
    old = pilot["frozen_23_group_ranking"]
    strict = pilot["strict_13_group_ablations"]
    multi = strict["multi_candidate"]["adapted_constrained"]
    full = "abstract_graph_minus_full_eapg"
    part_a = receipt["part_a"]["scoped_minus_cfg_top1"]
    part_b = receipt["part_b"]["contrasts"]["adjudicated_positives"]
    desk = receipt["secondary_desk_agreement"]
    nearest = receipt["oeis_development"]["nearest_preceding_cfg_minus_scoped_top1"]["left"]
    specificity = receipt["part_a_specificity_by_seed"]["42"]
    values = {
        "GroupedFrozenAllCI": limits(old["all"][boot]),
        "GroupedFrozenMultiCI": limits(old["multi_candidate"][boot]),
        "GroupedHitsOnlyCI": limits(multi["abstract_graph_minus_abstract_hits_only"][boot], signed=True),
        "GroupedFullAllCI": limits(strict["all"]["adapted_constrained"][full][boot], signed=True),
        "GroupedFullMultiCI": limits(multi[full][boot], signed=True),
        "GroupedRefinedCI": limits(pilot["strict_13_group_symbolic_comparisons"]["multi_candidate"]
                                   ["abstract_graph_minus_symbolic_refined"][boot], signed=True),
        "GroupedPartACoreCI": limits(part_a["core"][boot], signed=True),
        "GroupedPartACoreRange": limits(part_a["core"]["leave_one_group_out_range_delta_pp"], signed=True),
        "GroupedPartAOffSiteCI": limits(part_a["off_site"][boot], signed=True),
        "GroupedPartBUnbiasedCI": limits(part_b["symbolic_unbiased"][boot], signed=True),
        "GroupedPartBRefinedCI": limits(part_b["symbolic"][boot], signed=True),
        "GroupedDeskExistingCI": limits(desk["existing"]["coarse"]["kappa_bootstrap_95pct_points"]),
        "GroupedDeskReauditCI": limits(desk["reaudit"]["kappa_bootstrap_95pct_points"]),
        "GroupedNearestCFG": f"{nearest['count']}/{nearest['total']}",
        "GroupedBootstrapDraws": f"{DRAWS:,}",
        "GroupedBootstrapSeed": str(SEED),
    }
    for label, category, outcome in (
        ("QuadraticFalse", "sham_quadratic", "false_alerts"),
        ("LinearFalse", "sham_linear", "false_alerts"),
        ("SameGrowthFalse", "sham_all", "false_alerts"),
        ("AppropriateFalse", "appropriate_superlinear", "false_alerts"),
        ("AppropriateCorrect", "appropriate_superlinear", "correct_rejections"),
        ("SwapFalse", "swap_sham", "false_alerts"),
    ):
        cell = specificity[category][outcome]
        values[f"Grouped{label}"] = f"{cell['count']}/{cell['total']} = {cell['percent']:.1f}\\%"
    return "% Generated by development/replay_grouped_statistics.py\n" + "".join(
        f"\\newcommand{{\\{key}}}{{{value}}}\n" for key, value in sorted(values.items()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Regenerate the grouped statistics receipt.")
    args = parser.parse_args()
    computed = recompute()
    macros = render_macros(computed)
    if args.write:
        RECEIPT.write_text(json.dumps(computed, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        MACROS.write_bytes(macros.encode("utf-8"))
    elif computed != read_json(RECEIPT):
        raise ValueError("Grouped statistics receipt differs; regenerate with --write and inspect the changes.")
    elif macros.encode("utf-8") != MACROS.read_bytes():
        raise ValueError("Grouped statistics manuscript macros differ from the recomputed receipt.")
    else:
        print("Verified grouped statistics against public receipts (Holm family: 2 qualification contrasts).")


if __name__ == "__main__":
    main()
