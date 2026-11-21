"""Re-rank frozen CFG slices without running programs or fitting models.

Nearest preceding orders IDs below the symptom by increasing gap, then the
symptom, then IDs above it by increasing gap (ties: lower ID). A backward slice
looks upstream, making the nearest upstream candidate a natural cause guess.
Canonical IDs follow AST preorder (manuscript/method.tex, Canonicalization);
this is source-order proximity, NOT CFG shortest-path distance. No existing
nearest policy was found in method.tex, evaluation.tex or RESEARCH_RECORD.md.
The explicitly chosen preceding variant reproduces 6/20 in core Part A.
Sensitivity policies use absolute ID distance including the symptom (10/20),
or excluding it from the ranking, with lower-ID tie breaking (5/20).
Symptom-first moves the symptom first and preserves the stored remaining order.
Uniform is the exact expectation over all permutations of the original slice.
Retention always describes the original slice, even when a ranking omits nodes.
"""

import argparse
from collections import Counter
from fractions import Fraction
from hashlib import sha256
import json
from math import comb
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "development/fair_cfg_baseline.json"
TABLE = OUTPUT.with_suffix(".md")
STUDY = ROOT / "development/prospective_multiagent_results.json"
OEIS = ROOT / "development/scalar_intake_feasibility.json"
POLICIES = ("reported CFG", "symptom-first CFG", "uniform CFG",
            "nearest preceding CFG", "absolute including symptom CFG (sensitivity)",
            "absolute excluding symptom CFG (sensitivity)", "reported scoped")
METRICS = ("retention", "top1", "top3", "mrr")
SLOTS = ("positive_at_site", "positive_off_site")
NOTES = """Nearest preceding: candidates below the symptom's numeric canonical ID by increasing gap, then the symptom, then candidates above it by increasing gap; ties use lower ID. A backward slice looks upstream, so the nearest upstream candidate is a natural cause guess. This chosen variant reproduces the 6/20 anchor. IDs are AST preorder (manuscript/method.tex:8), not CFG path distances; no existing nearest policy is specified in method.tex, evaluation.tex or development/RESEARCH_RECORD.md.

Sensitivity rows order by absolute numeric ID distance, ties by lower ID, either including the symptom or excluding it from the ranking (not from the retention slice). Symptom-first moves the symptom ahead of the stored ranking, preserving the rest. Reported rankings are used as stored, including truncated Part B symbolic predictions; no missing ranks are invented.

Uniform metrics are exact expectations over random permutations of the slice: Top-1 is accepted-in-slice / slice size; Top-3 is the probability of any accepted node in the first min(3, size) draws; MRR averages the reciprocal first accepted rank. Counts for uniform and MRR are expected-hit and reciprocal-rank sums, respectively. JSON stores exact fractions as well as numeric counts/rates; displayed nonintegers are rounded to two decimals. Empty strata have denominator zero and no rate.

Part A core = confirmed_positive AND slot in {positive_at_site, positive_off_site}; excludes comparator-swap positives. OEIS uses eligible_static_and_analytic cases from development/scalar_intake_feasibility.json. Part B uses 14 confirmed positives of 16 pairs, the stored slice and symbolic_unbiased ranking; no conventional candidate sets or slot fields are present, so CFG policies and at/off-site splits are not computable. No slots are inferred from accepted nodes. All numbers are case-weighted counts/rates, without hypothesis tests or confidence intervals.

Audit anchor reconciliation: the uniform expected-hit sum over all 21 confirmed_positive rows is 1543/360 = 4.29 (rounded). The audit's 4.29/20 included the comparator-swap duplicate row in its numerator but used the 20-case core denominator. The correct core figure is 1483/360 = 4.12/20 (20.60%). The 21-row sum belongs over denominator 21 (20.41%), not 20."""


def ranking(row, policy):
    scoped = policy == "reported scoped"
    cands = row["scoped_cands" if scoped else "cands"]
    reported = row["scoped_rank" if scoped else "rank"]
    if len(cands) != len(set(cands)) or len(reported) != len(set(reported)):
        raise ValueError("Duplicate candidates or ranks")
    if not set(reported) <= set(cands):
        raise ValueError("Ranking outside candidate set")
    if policy in ("reported CFG", "reported scoped", "uniform CFG"):
        return reported
    symptom = row["symptom"]
    if symptom is None:
        raise ValueError("Missing symptom")
    if policy == "symptom-first CFG":
        return ([symptom] if symptom in cands else []) + [n for n in reported if n != symptom]
    s = int(symptom[1:])
    if policy == "nearest preceding CFG":
        return sorted(cands, key=lambda n: (0 if int(n[1:]) < s else 1 if n == symptom else 2,
                                            abs(int(n[1:]) - s), int(n[1:])))
    if policy.startswith("absolute "):
        nodes = [n for n in cands if "excluding" not in policy or n != symptom]
        return sorted(nodes, key=lambda n: (abs(int(n[1:]) - s), int(n[1:])))
    raise ValueError(f"Unknown policy: {policy}")


def case_metrics(row, policy):
    ordered = ranking(row, policy)
    cands = row["scoped_cands" if policy == "reported scoped" else "cands"]
    accepted = set(row["accepted"])
    n, m = len(cands), len(accepted.intersection(cands))
    retained = Fraction(bool(m))
    if policy == "uniform CFG":
        if not m:
            return (retained, Fraction(0), Fraction(0), Fraction(0))
        k = min(3, n)
        top3 = 1 - Fraction(comb(n - m, k) if n - m >= k else 0, comb(n, k))
        mrr = sum((Fraction(comb(n - r, m - 1), comb(n, m) * r)
                   for r in range(1, n - m + 2)), Fraction(0))
        return retained, Fraction(m, n), top3, mrr
    rank = next((i for i, node in enumerate(ordered, 1) if node in accepted), None)
    return retained, Fraction(rank == 1), Fraction(rank is not None and rank <= 3), Fraction(1, rank) if rank else Fraction(0)


def summarize(rows, policy):
    sums = [sum(values, Fraction(0)) for values in zip(*(case_metrics(r, policy) for r in rows))] if rows else [Fraction(0)] * 4
    return {name: {"count": float(value), "exact_count": str(value), "denominator": len(rows),
                   "rate": float(value / len(rows)) if rows else None}
            for name, value in zip(METRICS, sums)}


def normalize(row, conventional, scoped, identity, accepted, symptom):
    return {"id": identity, "slot": row.get("slot"), "accepted": accepted, "symptom": symptom,
            "cands": conventional["candidates"], "rank": conventional["ranking"],
            "scoped_cands": scoped["candidates"], "scoped_rank": scoped["ranking"]}


def build_receipt():
    study = json.loads(STUDY.read_text())
    active = study["part_a_prospective_scalar"]["active_slot_details"]
    assert len(active) == 42
    a = []
    for r in active:
        if r["disposition"] == "confirmed_positive" and r["slot"] in SLOTS:
            a.append(normalize(r, {"candidates": r["work_conv_cands"], "ranking": r["work_conv_rank"]},
                               {"candidates": r["work_scoped_cands"], "ranking": r["work_scoped_rank"]},
                               r["case_id"], r["accepted"], r["symptom"]))
    assert Counter(r["slot"] for r in a) == dict.fromkeys(SLOTS, 10)
    ranks = Counter(next(i for i, n in enumerate(r["rank"], 1) if n in r["accepted"]) for r in a)
    assert ranks == {2: 14, 3: 4, 4: 2}
    oeis = json.loads(OEIS.read_text())
    o = [normalize(r, r["analytic_arms"]["work_conventional"], r["analytic_arms"]["work_scoped"],
                   r["oeis_id"], [r["reference_node"]], r["analytic_arms"]["work_conventional"]["symptom_id"])
         for r in oeis["candidates"] if r["status"] == "eligible_static_and_analytic"]
    pairs = study["part_b_blinded_adjudication"]["pair_details"]
    assert len(pairs) == 16
    b = [normalize(r, {"candidates": [], "ranking": []},
                   {"candidates": r["slice"], "ranking": r["symbolic_unbiased"]},
                   r["pair_id"], r["blinded_accepted"], r["symptom_id"])
         for r in pairs if r["screening_status"] == "confirmed_positive"]
    assert len(a) == 20 and len(o) == 5 and len(b) == 14
    results = []
    for cohort, rows in (("Part A", a), ("OEIS", o), ("Part B", b)):
        for policy in POLICIES:
            for split in ("at-site", "off-site", "total"):
                reason = None
                if cohort == "Part B":
                    if policy != "reported scoped":
                        reason = "no conventional candidate set in receipt"
                    elif split != "total":
                        reason = "no slot field in receipt"
                selected = rows if split == "total" else [r for r in rows if r["slot"] == "positive_" + split.replace("-", "_")]
                results.append({"cohort": cohort, "policy": policy, "split": split,
                                "not_computable": reason, "metrics": None if reason else summarize(selected, policy)})
    def count(cohort, policy, metric, split="total"):
        return next(r["metrics"][metric]["count"] for r in results
                    if (r["cohort"], r["policy"], r["split"]) == (cohort, policy, split))
    for policy, expected in zip(POLICIES, (0, 10, None, 6, 10, 5, 15)):
        if expected is not None:
            assert count("Part A", policy, "top1") == expected
    core_uniform = sum((case_metrics(r, "uniform CFG")[1] for r in a), Fraction(0))
    all_positive = [r for r in active if r["disposition"] == "confirmed_positive"]
    audit_uniform = sum((Fraction(len(set(r["accepted"]) & set(r["work_conv_cands"])),
                                  len(r["work_conv_cands"])) for r in all_positive), Fraction(0))
    extra = [r for r in all_positive if r["slot"] not in SLOTS]
    assert len(all_positive) == 21 and len(extra) == 1
    assert extra[0]["slot"] == "comparator_swap_positive"
    assert core_uniform == Fraction(1483, 360) and f"{float(core_uniform):.2f}" == "4.12"
    assert audit_uniform == Fraction(1543, 360) and f"{float(audit_uniform):.2f}" == "4.29"
    assert audit_uniform - core_uniform == Fraction(1, 6)
    assert count("Part A", "symptom-first CFG", "top1", "at-site") == 10
    assert count("Part A", "reported CFG", "retention") == 20
    assert count("Part A", "reported scoped", "retention") == 16
    assert count("Part A", "reported scoped", "top1", "off-site") == 6
    assert count("OEIS", "reported CFG", "top1") == 0
    assert count("OEIS", "reported scoped", "top1") == 3
    return {"schema": "eapg-fair-cfg-baseline-v1", "notes": NOTES,
            "audit_anchor_reconciliation": {
                "core": {"exact_count": str(core_uniform), "count": float(core_uniform),
                         "denominator": 20, "rate": float(core_uniform / 20)},
                "all_confirmed_positive": {"exact_count": str(audit_uniform), "count": float(audit_uniform),
                                           "denominator": 21, "rate": float(audit_uniform / 21)},
                "extra_case_id": extra[0]["case_id"],
                "extra_slot": extra[0]["slot"],
                "extra_exact_count": str(audit_uniform - core_uniform),
                "explanation": "The audit's 4.29/20 included the comparator-swap duplicate row in the numerator; the core 20-case figure is 4.12/20."},
            "inputs": {str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest() for p in (STUDY, OEIS)},
            "part_a_reported_cfg_reference_ranks": dict(sorted(ranks.items())),
            "cases": {"Part A": a, "OEIS": o, "Part B": b}, "results": results}


def render_table(receipt):
    lines = ["# Fair CFG baseline", "", "| Cohort | Policy | Split | Retention | Top-1 | Top-3 | MRR |",
             "|---|---|---|---|---|---|---|"]
    for r in receipt["results"]:
        if r["not_computable"]:
            cells = ["not computable: " + r["not_computable"]] * 4
        else:
            cells = []
            for m in r["metrics"].values():
                value = m["count"]
                numerator = str(int(value)) if value.is_integer() else f"{value:.2f}"
                rate = f'{m["rate"]:.2%}' if m["rate"] is not None else "no rate"
                cells.append(f'{numerator}/{m["denominator"]} ({rate})')
        lines.append("| " + " | ".join([r["cohort"], r["policy"], r["split"], *cells]) + " |")
    return "\n".join(lines) + "\n\n" + receipt["notes"] + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Recompute and compare both committed outputs")
    args = parser.parse_args()
    receipt = build_receipt()
    outputs = {OUTPUT: json.dumps(receipt, indent=2) + "\n", TABLE: render_table(receipt)}
    for path, expected in outputs.items():
        if args.check:
            if not path.exists() or path.read_text() != expected:
                raise SystemExit(f"Fair CFG baseline mismatch: {path.relative_to(ROOT)}")
        else:
            path.write_text(expected)
    print("Fair CFG baseline: " + ("checked" if args.check else "wrote") + " receipt and table; Part A Top-1 anchors 10/20, 6/20, core uniform 4.12/20 and 21-row audit sum 4.29 verified.")


if __name__ == "__main__":
    main()
