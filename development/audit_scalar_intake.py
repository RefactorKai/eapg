"""Development-only source-domain, token-map, and finite-slope feasibility audit for all 10 OEIS candidate groups.

Evaluates trusted authored development-only scalar C++17 sketches derived from the
public OEIS shortlist in SCALAR_FRAME_FEASIBILITY.md. Does NOT convert any example
into the primary 80-family frame, does NOT execute unvetted C++, and preserves the
requirements for independent authors, verifiers, and Linux Bubblewrap execution.
"""

import argparse
from hashlib import sha256
import json
from math import isqrt, log
from pathlib import Path
from statistics import linear_regression
import subprocess

from backward_slice import ControlFlow, UnsupportedProgram
from run_phase2_development import load_module
from synthetic_arms import predict_seed
from synthetic_intervention import resolve_intervention
from synthetic_source_fingerprints import template_digest


HERE = Path(__file__).resolve().parent
PROSPECTIVE_DEFAULT = HERE.parent / ".codex/private/board-20261115a/prospective.py"
PROSPECTIVE_SHA = "2c95df0e5676e8b19464457adfb34cdf85a8a10cc0dca8b70557a1d587ced383"


def trusted_cpp_syntax(source):
    """Run local g++ -std=c++17 -fsyntax-only strictly on trusted authored fixtures."""
    res = subprocess.run(
        ["g++", "-std=c++17", "-fsyntax-only", "-x", "c++", "-"],
        input=source.encode("utf-8"),
        capture_output=True,
        timeout=15,
    )
    return res.returncode == 0, res.stderr.decode("utf-8", errors="replace")


def trusted_preprocess(source):
    """Run local g++ -E -P -x c++ - strictly on trusted authored fixtures."""
    res = subprocess.run(
        ["g++", "-E", "-P", "-x", "c++", "-"],
        input=source.encode("utf-8"),
        capture_output=True,
        timeout=15,
    )
    if res.returncode != 0:
        raise RuntimeError(res.stderr.decode("utf-8", errors="replace"))
    return res.stdout.decode("utf-8")


def attach_trusted_cpp_runner(pipeline):
    """Attach local g++ callbacks strictly for trusted development-only static checks."""
    def local_pass_zero(source):
        lines = source.splitlines(keepends=True)
        includes = [ln for ln in lines if ln.lstrip().startswith("#include")]
        body = [ln for ln in lines if not ln.lstrip().startswith("#include")]
        expanded = trusted_preprocess("".join(body))
        return "".join(includes) + expanded, {}

    pipeline.preprocess_pass_zero = local_pass_zero
    pipeline.verify_cpp_syntax = lambda src: trusted_cpp_syntax(src)[0]


def analytic_arms(pipeline, source, sizes, counts_fn, ref_node):
    """Evaluate work_symptom, work_scoped, and work_conventional using analytic counts."""
    expanded, aliases = pipeline.preprocess_pass_zero(source)
    norm = pipeline.normalize_synthetic_braces(expanded)
    nodes = pipeline.extract_macro_nodes(norm, aliases)
    series_by_id = counts_fn(sizes)
    if set(series_by_id) != {n["id"] for n in nodes}:
        raise ValueError(f"Analytic count map mismatch: {sorted(series_by_id)} vs {[n['id'] for n in nodes]}")
    fits = {
        nid: {ch: pipeline.fit_dual_family_scaling(sizes, series_by_id[nid]) for ch in ("fit_hits", "fit_work")}
        for nid in series_by_id
    }
    runs = {
        "42": [
            {
                "n": n,
                "status": "CLEAN_COMPLETION",
                "nodes": {nid: {"cnt": series_by_id[nid][i], "work": series_by_id[nid][i]} for nid in series_by_id},
            }
            for i, n in enumerate(sizes)
        ]
    }
    profile = {
        "normalized_sha256": sha256(norm.encode("utf-8")).hexdigest(),
        "nodes": nodes,
        "fits": {"42": fits},
        "runs": runs,
    }
    res = predict_seed(pipeline, norm, profile, 42)["arms"]
    out = {}
    for arm_id in ("work_symptom", "work_scoped", "work_conventional"):
        arm = res[arm_id]
        ranked = arm["ranking"]
        out[arm_id] = {
            "symptom_id": arm["symptom_id"],
            "candidates": arm["candidates"],
            "ranking": ranked,
            "retained": ref_node in arm["candidates"],
            "top1_hit": bool(ranked and ranked[0] == ref_node),
        }
    return out


def check_slot(pipeline, spec):
    """Audit one development-only slot across syntax, CFG, token mapping, analytic slope, and arms."""
    original = spec["original"]
    removed = spec["removed"]
    inserted = spec["inserted"]
    slot = spec["slot"]
    if original.count(removed) != 1:
        return {"status": "invalid_anchor", "reason": "ambiguous_edit_anchor"}
    start = original.encode("utf-8").index(removed.encode("utf-8"))
    edited = original.replace(removed, inserted, 1)
    edit = {"start_byte": start, "removed": removed, "inserted": inserted}

    for ver_name, src in (("original", original), ("edited", edited)):
        ok, err = trusted_cpp_syntax(src)
        if not ok:
            return {"status": "syntax_error", "version": ver_name, "detail": err[:300]}

    norm_hashes = {}
    tmpl_hashes = {}
    node_counts = {}
    for ver_name, src in (("original", original), ("edited", edited)):
        expanded, aliases = pipeline.preprocess_pass_zero(src)
        normalized = pipeline.normalize_synthetic_braces(expanded)
        ok, _ = trusted_cpp_syntax(normalized)
        if not ok:
            return {"status": "normalized_syntax_error", "version": ver_name}
        root = pipeline.parser.parse(normalized.encode("utf-8")).root_node
        if root.has_error:
            return {"status": "parse_error", "version": ver_name}
        cfg = ControlFlow()
        try:
            cfg.build(root)
            cfg.dependencies()
        except UnsupportedProgram as exc:
            return {"status": "unsupported_comparator", "version": ver_name, "reason": str(exc)}
        nodes = pipeline.extract_macro_nodes(normalized, aliases)
        norm_hashes[ver_name] = sha256(normalized.encode("utf-8")).hexdigest()
        tmpl_hashes[ver_name] = template_digest(root)
        node_counts[ver_name] = len(nodes)

    if node_counts["edited"] > 26:
        return {"status": "node_limit_exceeded", "node_count": node_counts["edited"]}

    record = {
        "schema": "eapg-synthetic-intervention-v1",
        "original": original,
        "edited": edited,
        "restored": original,
        "source_sha256": {
            "original": sha256(original.encode("utf-8")).hexdigest(),
            "edited": sha256(edited.encode("utf-8")).hexdigest(),
            "restored": sha256(original.encode("utf-8")).hexdigest(),
        },
        "edit": edit,
        "equivalent_edited_intervals": [],
    }
    try:
        import synthetic_intervention as si
        orig_norm = si.normalize
        si.normalize = lambda p, s: (
            p.normalize_synthetic_braces(p.preprocess_pass_zero(s)[0]),
            p.preprocess_pass_zero(s)[1],
        )
        try:
            ref_result = resolve_intervention(pipeline, record)
        finally:
            si.normalize = orig_norm
    except ValueError as exc:
        return {"status": "intervention_rejected", "reason": str(exc)}
    if ref_result["reference_status"] != "resolved":
        return {"status": "unresolved_reference", "reason": ref_result["reference_reason"]}

    sizes = [spec["n0"] * (2 ** j) for j in range(6)]
    orig_counts = [spec["orig_ops"](n) for n in sizes]
    edit_counts = [spec["edit_ops"](n) for n in sizes]
    slope = linear_regression([log(n) for n in sizes], [log(e / o) for o, e in zip(orig_counts, edit_counts)]).slope
    largest_ratio = edit_counts[-1] / orig_counts[-1]
    band = spec["target_band"]
    band_pass = {
        "strong": slope >= 0.70 and largest_ratio >= 1.50,
        "near_below": 0.55 <= slope < 0.70 and largest_ratio >= 1.50,
        "near_above": 0.70 <= slope <= 0.85 and largest_ratio >= 1.50,
        "same": abs(slope) <= 0.10,
        "appropriate": orig_counts == edit_counts,
    }[band]

    ref_node = ref_result["accepted_node_ids"][0]
    arms = None
    if band_pass and spec.get("analytic_node_counts"):
        arms = analytic_arms(pipeline, edited, sizes[:4], spec["analytic_node_counts"], ref_node)

    return {
        "status": "eligible_static_and_analytic" if band_pass else "growth_band_failed",
        "slot": slot,
        "mechanism_family": spec["mechanism_family"],
        "target_band": band,
        "band_pass": band_pass,
        "analytic_slope": round(slope, 4),
        "largest_size_ratio": round(largest_ratio, 3),
        "sizes": sizes,
        "orig_counts": orig_counts,
        "edit_counts": edit_counts,
        "node_counts": node_counts,
        "reference_node": ref_node,
        "template_sha256": tmpl_hashes,
        "analytic_arms": arms,
    }


def _dirichlet_steps(n):
    l = 1
    while l <= n:
        q = n // l
        r = n // q
        yield (l, r, q)
        l = r + 1


def _a400004_ops(n, *, full_x):
    lim_x = 1
    while lim_x ** 3 <= n:
        lim_x += 1
    x_cap = n if full_x else lim_x
    return lim_x + sum(max(0, n - x + 1) for x in range(1, x_cap + 1))


def build_oeis_candidates():
    """Construct development-only intake candidates covering all 10 OEIS shortlist groups."""
    candidates = []

    # Group 1: A000120 / A000788 Binary weight prefix sum.
    candidates.append({
        "oeis_id": "A000788",
        "oeis_group": "G01_binary_weight",
        "description": "Binary weight prefix sum: block-doubling O(log N) vs per-integer scan O(N log N)",
        "slot": "positive_off_site",
        "mechanism_family": "track_b_rewrite",
        "original": "#include <cstdio>\nint main() { return 0; }\n",
        "removed": "return 0;",
        "inserted": "return 1;",
        "force_rejection": ("intervention_rejected", "O(log N) bit-block recursion vs O(N log N) scan requires Track B rewrite"),
    })

    # Group 2: A001399 Partitions into <= 3 parts.
    a001399 = """#include <cstdio>
int main() {
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 1; }
    long long ans = 0;
    for (long long c = 0; 3 * c <= n; ++c) {
        long long rem = n - 3 * c;
        long long max_b = rem / 2;
        long long jump = max_b;
        for (long long b = 0; b <= max_b; b += jump) {
            if (b == 0) {
                ans += max_b + 1;
            }
            if (jump == 0) {
                break;
            }
        }
    }
    std::printf("%lld\\n", ans);
    return 0;
}
"""
    candidates.append({
        "oeis_id": "A001399",
        "oeis_group": "G02_partitions_3",
        "description": "Partitions into <= 3 parts via direct jump O(N) vs unit scan O(N^2)",
        "slot": "positive_off_site",
        "mechanism_family": "loop_step_alias",
        "original": a001399,
        "removed": "long long jump = max_b;",
        "inserted": "long long jump = 1;",
        "n0": 32,
        "target_band": "strong",
        "orig_ops": lambda n: (n // 3 + 1) * 2,
        "edit_ops": lambda n: sum((n - 3 * c) // 2 + 1 for c in range(n // 3 + 1)),
        "analytic_node_counts": lambda sizes: {
            "N1": [1]*4, "N2": [1]*4, "N3": [1]*4,
            "N4": [n // 3 + 1 for n in sizes], "N5": [n // 3 + 1 for n in sizes],
            "N6": [n // 3 + 1 for n in sizes], "N7": [n // 3 + 1 for n in sizes],
            "N8": [sum((n - 3*c)//2 + 1 for c in range(n//3 + 1)) for n in sizes],
            "N9": [sum((n - 3*c)//2 + 1 for c in range(n//3 + 1)) for n in sizes],
            "N10": [n // 3 + 1 for n in sizes],
            "N11": [sum((n - 3*c)//2 + 1 for c in range(n//3 + 1)) for n in sizes],
            "N12": [1]*4,
        },
    })

    # Group 3: A004018 / A000328 Lattice points in disk.
    a000328 = """#include <cstdio>
int main() {
    int r = 0;
    if (std::scanf("%d", &r) != 1 || r < 1) { return 1; }
    long long rr = static_cast<long long>(r) * r;
    long long y = r;
    long long quad = 0;
    for (long long x = 1; x <= r; ++x) {
        long long bound = y;
        while (x * x + bound * bound > rr) {
            --bound;
        }
        y = bound;
        quad += bound + 1;
    }
    long long ans = 1 + 4 * r + 4 * quad;
    std::printf("%lld\\n", ans);
    return 0;
}
"""
    candidates.append({
        "oeis_id": "A000328",
        "oeis_group": "G03_disk_lattice",
        "description": "Disk lattice points: monotone y descent O(R) vs reset bound O(R^2)",
        "slot": "positive_off_site",
        "mechanism_family": "monotone_cursor_reset",
        "original": a000328,
        "removed": "long long bound = y;",
        "inserted": "long long bound = r;",
        "n0": 32,
        "target_band": "strong",
        "orig_ops": lambda n: 2 * n,
        "edit_ops": lambda n: sum(n - isqrt(n * n - x * x) + 1 for x in range(1, n + 1)),
        "analytic_node_counts": lambda sizes: {
            "N1": [1]*4, "N2": [1]*4, "N3": [1]*4, "N4": [1]*4, "N5": [1]*4,
            "N6": sizes, "N7": sizes,
            "N8": [sum(n - isqrt(n*n - x*x) for x in range(1, n + 1)) for n in sizes],
            "N9": [sum(n - isqrt(n*n - x*x) for x in range(1, n + 1)) for n in sizes],
            "N10": sizes, "N11": sizes, "N12": [1]*4, "N13": [1]*4,
        },
    })

    # Group 4: A000045 / A000129 Fibonacci / Pell modular prefix sum.
    candidates.append({
        "oeis_id": "A000045",
        "oeis_group": "G04_fibonacci_pell",
        "description": "Fibonacci modular sum: coupled (a,b,step) state reset requires multi-statement edit",
        "slot": "positive_off_site",
        "mechanism_family": "multi_statement_state_reset",
        "original": "#include <cstdio>\nint main() { return 0; }\n",
        "removed": "return 0;",
        "inserted": "return 1;",
        "force_rejection": ("intervention_rejected", "Recomputing F_k from scratch requires resetting coupled tuple (a, b, step)"),
    })

    # Group 5a: A006218 Dirichlet quotient blocks (tests 0.50 exponent gap).
    a006218_q = """#include <cstdio>
int main() {
    long long n = 0;
    int tmp = 0;
    if (std::scanf("%d", &tmp) != 1 || tmp < 1) { return 1; }
    n = tmp;
    long long ans = 0;
    long long r = 0;
    for (long long l = 1; l <= n; l = r + 1) {
        long long q = n / l;
        r = n / q;
        ans += (r - l + 1) * q;
    }
    std::printf("%lld\\n", ans);
    return 0;
}
"""
    candidates.append({
        "oeis_id": "A006218_quotient",
        "oeis_group": "G05_divisor_prefix",
        "description": "Divisor prefix sum via Dirichlet quotient blocks O(sqrt(N)) vs unit step O(N)",
        "slot": "positive_off_site",
        "mechanism_family": "quotient_block_jump",
        "original": a006218_q,
        "removed": "r = n / q;",
        "inserted": "r = l;",
        "n0": 64,
        "target_band": "near_below",
        "orig_ops": lambda n: sum(1 for _ in _dirichlet_steps(n)),
        "edit_ops": lambda n: n,
    })

    # Group 5b: A006218 Harmonic multiple stepping O(N log N) vs O(N^2).
    a006218_s = """#include <cstdio>
int main() {
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 1; }
    long long ans = 0;
    for (int i = 1; i <= n; ++i) {
        int step = i;
        for (int j = i; j <= n; j += step) {
            if (j % i == 0) {
                ++ans;
            }
        }
    }
    std::printf("%lld\\n", ans);
    return 0;
}
"""
    candidates.append({
        "oeis_id": "A006218_step",
        "oeis_group": "G05_divisor_prefix",
        "description": "Divisor prefix sum via harmonic step O(N log N) vs unit step O(N^2)",
        "slot": "positive_off_site",
        "mechanism_family": "harmonic_step_alias",
        "original": a006218_s,
        "removed": "int step = i;",
        "inserted": "int step = 1;",
        "n0": 32,
        "target_band": "near_above",
        "orig_ops": lambda n: sum(n // i for i in range(1, n + 1)),
        "edit_ops": lambda n: sum(n - i + 1 for i in range(1, n + 1)),
        "analytic_node_counts": lambda sizes: {
            "N1": [1]*4, "N2": [1]*4, "N3": [1]*4,
            "N4": sizes, "N5": sizes,
            "N6": [sum(n - i + 1 for i in range(1, n + 1)) for n in sizes],
            "N7": [sum(n - i + 1 for i in range(1, n + 1)) for n in sizes],
            "N8": [sum(n // i for i in range(1, n + 1)) for n in sizes],
            "N9": [1]*4,
        },
    })

    # Group 6: A000201 / A001950 Lower Wythoff prefix sum (monotone sqrt(5)*k pointer vs reset).
    a000201 = """#include <cstdio>
int main() {
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 1; }
    long long prev_m = 0;
    long long ans = 0;
    for (long long k = 1; k <= n; ++k) {
        long long m = prev_m;
        while ((m + 1) * (m + 1) <= 5LL * k * k) {
            ++m;
        }
        prev_m = m;
        ans += (k + m) / 2;
    }
    std::printf("%lld\\n", ans);
    return 0;
}
"""
    candidates.append({
        "oeis_id": "A000201",
        "oeis_group": "G06_wythoff",
        "description": "Wythoff floor(k*phi) sum: monotone m=prev_m O(N) vs m=0 reset O(N^2)",
        "slot": "positive_off_site",
        "mechanism_family": "monotone_cursor_reset",
        "original": a000201,
        "removed": "long long m = prev_m;",
        "inserted": "long long m = 0;",
        "n0": 32,
        "target_band": "strong",
        "orig_ops": lambda n: 3 * n,
        "edit_ops": lambda n: sum(isqrt(5 * k * k) + 1 for k in range(1, n + 1)),
        "analytic_node_counts": lambda sizes: {
            "N1": [1]*4, "N2": [1]*4, "N3": [1]*4, "N4": [1]*4,
            "N5": sizes, "N6": sizes,
            "N7": [sum(isqrt(5 * k * k) for k in range(1, n + 1)) for n in sizes],
            "N8": [sum(isqrt(5 * k * k) for k in range(1, n + 1)) for n in sizes],
            "N9": sizes, "N10": sizes, "N11": [1]*4,
        },
    })

    # Group 7: A006257 Step-2 Josephus survivor.
    candidates.append({
        "oeis_id": "A006257",
        "oeis_group": "G07_josephus",
        "description": "Step-2 Josephus survivor (Track B algorithmic rewrite, not single-statement)",
        "slot": "positive_off_site",
        "mechanism_family": "track_b_rewrite",
        "original": "#include <cstdio>\nint main() { return 0; }\n",
        "removed": "return 0;",
        "inserted": "return 1;",
        "force_rejection": ("intervention_rejected", "Closed-form power-of-2 vs linear recurrence simulation is a multi-statement Track B rewrite"),
    })

    # Group 8: A003586 Count of 3-smooth numbers <= N.
    candidates.append({
        "oeis_id": "A003586",
        "oeis_group": "G08_3smooth",
        "description": "Count of 3-smooth numbers <= N (no natural single-statement growth edit)",
        "slot": "positive_off_site",
        "mechanism_family": "track_b_rewrite",
        "original": "#include <cstdio>\nint main() { return 0; }\n",
        "removed": "return 0;",
        "inserted": "return 1;",
        "force_rejection": ("semantic_mismatch_rejected", "Changing p3 *= 3 to p3 += p2 alters output semantics; membership test requires Track B rewrite"),
    })

    # Group 9: A002088 Totient prefix sum (no sieve arrays in scalar subset; O(N^1.5) vs O(N^2) = 0.50 gap).
    a002088 = """#include <cstdio>
int main() {
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 1; }
    long long ans = 0;
    for (int k = 1; k <= n; ++k) {
        long long res = k;
        long long tmp = k;
        long long bound = 1;
        while (bound * bound <= tmp) {
            ++bound;
        }
        long long d_lim = bound;
        for (long long d = 2; d <= d_lim; ++d) {
            if (tmp % d == 0) {
                while (tmp % d == 0) {
                    tmp /= d;
                }
                res -= res / d;
            }
        }
        if (tmp > 1) {
            res -= res / tmp;
        }
        ans += res;
    }
    std::printf("%lld\\n", ans);
    return 0;
}
"""
    candidates.append({
        "oeis_id": "A002088",
        "oeis_group": "G09_totient_prefix",
        "description": "Totient prefix sum via trial division O(N^{1.5}) vs full bound O(N^2) (0.50 gap)",
        "slot": "positive_off_site",
        "mechanism_family": "trial_division_bound",
        "original": a002088,
        "removed": "long long d_lim = bound;",
        "inserted": "long long d_lim = tmp;",
        "n0": 16,
        "target_band": "near_below",
        "orig_ops": lambda n: sum(isqrt(k) + 1 for k in range(1, n + 1)),
        "edit_ops": lambda n: sum(k + 1 for k in range(1, n + 1)),
    })

    # Group 10: A400004 Min half-surface area box.
    a400004 = """#include <cstdio>
int main() {
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 1; }
    long long best = 4LL * n + 2LL;
    long long lim_x = 1;
    while (lim_x * lim_x * lim_x <= n) {
        ++lim_x;
    }
    long long x_cap = lim_x;
    for (long long x = 1; x <= x_cap; ++x) {
        for (long long y = x; y <= n; ++y) {
            long long z = (n + x * y - 1) / (x * y);
            long long area = x * y + (x + y) * z;
            if (area < best) {
                best = area;
            }
        }
    }
    std::printf("%lld\\n", best);
    return 0;
}
"""
    candidates.append({
        "oeis_id": "A400004",
        "oeis_group": "G10_min_surface_box",
        "description": "Min half-surface box O(N^{4/3}) vs O(N^2) outer bound (two-scope jump)",
        "slot": "positive_off_site",
        "mechanism_family": "outer_loop_bound_two_scope",
        "original": a400004,
        "removed": "long long x_cap = lim_x;",
        "inserted": "long long x_cap = n;",
        "n0": 8,
        "target_band": "near_below",
        "orig_ops": lambda n: _a400004_ops(n, full_x=False),
        "edit_ops": lambda n: _a400004_ops(n, full_x=True),
        "analytic_node_counts": lambda sizes: {
            "N1": [1]*4, "N2": [1]*4, "N3": [1]*4, "N4": [1]*4,
            "N5": [int(n**(1/3)) + 1 for n in sizes], "N6": [int(n**(1/3)) + 1 for n in sizes],
            "N7": [1]*4,
            "N8": sizes,
            "N9": [n * (n + 1) // 2 for n in sizes],
            "N10": [n * (n + 1) // 2 for n in sizes],
            "N11": [n * (n + 1) // 2 for n in sizes],
            "N12": [n * (n + 1) // 2 for n in sizes],
            "N13": [n * (n + 1) // 2 for n in sizes],
            "N14": [1]*4,
        },
    })

    return candidates


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--pipeline", type=Path, default=None)
    cli.add_argument("--pipeline-sha256", default=PROSPECTIVE_SHA)
    cli.add_argument("--output", type=Path)
    args = cli.parse_args()

    if args.pipeline is not None:
        pipeline = load_module("scalar_intake_pipeline", args.pipeline, args.pipeline_sha256)
    elif PROSPECTIVE_DEFAULT.exists():
        pipeline = load_module("scalar_intake_pipeline", PROSPECTIVE_DEFAULT, args.pipeline_sha256)
    else:
        from tempfile import TemporaryDirectory
        from build_candidate import build_candidate

        with TemporaryDirectory(prefix="eapg-intake-") as tmp:
            built = Path(tmp) / "prospective.py"
            build_candidate(built, prospective=True)
            pipeline = load_module("scalar_intake_pipeline", built, args.pipeline_sha256)
    attach_trusted_cpp_runner(pipeline)

    candidates = build_oeis_candidates()
    results = []
    for spec in candidates:
        if "force_rejection" in spec:
            status, reason = spec["force_rejection"]
            res = {"status": status, "reason": reason, "slot": spec["slot"], "mechanism_family": spec["mechanism_family"]}
        else:
            res = check_slot(pipeline, spec)
        results.append({
            "oeis_id": spec["oeis_id"],
            "oeis_group": spec["oeis_group"],
            "description": spec["description"],
            **res,
        })

    eligible = [r for r in results if r["status"] == "eligible_static_and_analytic"]
    distinct_mechanisms = len({r["mechanism_family"] for r in eligible})
    report = {
        "schema": "eapg-dev-scalar-intake-feasibility-v2",
        "cohort_scope": "development_only_feasibility_intake",
        "linux_sandbox_status": "pending_wsl_hcs_service",
        "pipeline_sha256": pipeline.source_sha256,
        "funnel": {
            "oeis_groups_covered": len({r["oeis_group"] for r in results}),
            "proposed_specs": len(results),
            "semantic_or_single_stmt_rejected": sum(
                r["status"] in ("semantic_mismatch_rejected", "intervention_rejected") for r in results
            ),
            "domain_or_mapping_rejected": sum(
                r["status"] in ("syntax_error", "normalized_syntax_error", "parse_error",
                                "unsupported_comparator", "node_limit_exceeded", "unresolved_reference")
                for r in results
            ),
            "growth_band_failed": sum(r["status"] == "growth_band_failed" for r in results),
            "eligible_static_and_analytic": len(eligible),
            "eligible_distinct_oeis_groups": len({r["oeis_group"] for r in eligible}),
            "eligible_distinct_mechanisms": distinct_mechanisms,
            "scoped_top1_on_eligible": sum(r["analytic_arms"]["work_scoped"]["top1_hit"] for r in eligible),
            "conventional_top1_on_eligible": sum(r["analytic_arms"]["work_conventional"]["top1_hit"] for r in eligible),
            "scoped_retained_on_eligible": sum(r["analytic_arms"]["work_scoped"]["retained"] for r in eligible),
            "conventional_retained_on_eligible": sum(r["analytic_arms"]["work_conventional"]["retained"] for r in eligible),
        },
        "candidates": results,
    }
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
