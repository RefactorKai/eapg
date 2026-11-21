"""WP-S1: Part A specificity and alert-threshold sweeps from committed evidence.

`--regenerate` re-profiles the 42 active Part A cases with a direct, unsandboxed
runner (the programs are the repository's own synthetic families) and writes
`specificity_sweeps_profiles.json`. Every other mode works offline: it refits
those counters with the frozen release fitter, requires the nominal 0.70 result
to reproduce the committed seed-42 alerts, symptoms and scoped slices in
`prospective_multiagent_results.json`, sweeps the hidden-work gap threshold, and
sweeps the paired slope and ratio thresholds over `artifacts/paired_development/ledger.json`.
`--check` fails unless the committed receipt and plot match a fresh rebuild.
"""

import argparse
from collections import Counter
from hashlib import sha256
import ast
import json
import math
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

PROFILES = HERE / "specificity_sweeps_profiles.json"
RECEIPT = HERE / "specificity_sweeps.json"
PLOT = HERE / "specificity_sweeps.svg"
COMMITTED = HERE / "prospective_multiagent_results.json"
LEDGER = REPO / "artifacts/paired_development/ledger.json"
SCHEMA = "eapg-wp-s1-specificity-sweeps-v1"
PROFILE_SCHEMA = "eapg-wp-s1-part-a-counter-projections-v1"
NOMINAL_GAP, NOMINAL_SLOPE, NOMINAL_RATIO = 0.70, 0.50, 1.50
GAP_GRID = [round(0.05 * i, 2) for i in range(4, 41)]
SLOPE_GRID = [round(0.05 * i, 2) for i in range(0, 45)]
RATIO_GRID = sorted({1.5, *(round(10 ** (i / 20), 4) for i in range(0, 81))})
SEEDS = (42, 43, 44)
GAP_TEXT = "if hidden_gap >= 0.7:"
SYMPTOM_TEXT = "elif delta_a >= 0.7 and alpha_w >= 1.5:"
CORE = ("positive_off_site", "positive_at_site", "same_growth_sham", "appropriate_superlinear")
CATEGORIES = (
    ("positive", lambda c: c["slot"] in CORE and c["disposition"] == "confirmed_positive"),
    ("sham_quadratic", lambda c: c["slot"] == "same_growth_sham" and c["sham_class"] == "quadratic"),
    ("sham_linear", lambda c: c["slot"] == "same_growth_sham" and c["sham_class"] == "linear"),
    ("sham_all", lambda c: c["slot"] == "same_growth_sham"),
    ("appropriate_superlinear", lambda c: c["slot"] == "appropriate_superlinear"),
    ("swap_positive", lambda c: c["slot"] == "comparator_swap_positive"),
    ("swap_sham", lambda c: c["slot"] == "comparator_swap_sham"),
)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return sha256(canonical(value).encode("utf-8")).hexdigest()


def file_digest(path):
    return sha256(path.read_bytes()).hexdigest()


def study():
    import run_prospective_multiagent_study as study_module
    return study_module


def load_pipeline():
    """Build and load the prospective candidate, keeping its source for threshold sweeps."""
    m = study()
    from build_candidate import build_candidate
    with TemporaryDirectory(prefix="eapg_wp_s1_") as td:
        built = Path(td) / "prospective.py"
        build_candidate(built, prospective=True)
        pipeline = m.r2d.load_module("eapg_wp_s1_pipeline", built, m.PROSPECTIVE_SHA)
        pipeline.wp_s1_source = built.read_bytes().decode("utf-8").replace("\r\n", "\n")
    return pipeline


def active_cases():
    """Yield the 42 active Part A cases exactly as `run_part_a` registers them."""
    m = study()
    for fam in m.build_ten_families():
        fid, sizes = fam["family_id"], [fam["n0"] << j for j in range(6)]
        slots = [(name, fam[name]) for name in m.CORE_SLOTS]
        if "comparator_swap" in fam:
            slots += [("comparator_swap_positive", fam["comparator_swap"]["positive"]),
                      ("comparator_swap_sham", fam["comparator_swap"]["sham"])]
        for slot, srec in slots:
            if slot == "appropriate_superlinear":
                source, band = srec["source"], "appropriate"
            else:
                source, _ = m.make_patch(srec["original"], srec["removed"], srec["inserted"])
                band = srec.get("band", "same")
            grid = [{"seed": seed, "n": n, "stdin": f"{n} {m.SALT_BY_SEED[seed]}\n",
                     "expected_stdout": f"{srec['out_fn'](n, m.SALT_BY_SEED[seed])}\n"}
                    for seed in m.SEEDS for n in sizes]
            yield {"case_id": m.sha256_text(f"{fid}:{slot}")[:32], "family": fid, "slot": slot,
                   "band": band, "sham_class": fam["sham_class"]}, source, grid


def direct_execute(binary, data=b"", *, timeout=12, counter_scale=None):
    with TemporaryDirectory(prefix="eapg_wp_s1_") as td:
        program, wire = Path(td) / "program", Path(td) / "counter"
        program.write_bytes(binary)
        program.chmod(0o500)
        env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
        if counter_scale is not None:
            env.update(EAPG_N=str(counter_scale), EAPG_COUNTER_FILE=str(wire))
        try:
            proc = subprocess.run([str(program)], input=data, capture_output=True, timeout=timeout, env=env, cwd=td)
            timed_out, code, out, err = False, proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as error:
            timed_out, code, out, err = True, -1, error.stdout or b"", error.stderr or b""
        return SimpleNamespace(returncode=code, stdout=out, stderr=err, timed_out=timed_out, events={},
                               counter_wire=wire.read_bytes() if wire.exists() else b"")


def regenerate(pipeline):
    m = study()
    m.install_windows_sandbox_adapter()
    import run_phase2_development as r2d
    import synthetic_trace as st
    cases = []
    for meta, source, grid in active_cases():
        normalized, aliases = r2d.normalize(pipeline, source)
        nodes = pipeline.extract_macro_nodes(normalized, aliases)
        binary = st.compile_instrumented(pipeline, normalized, nodes)
        seeds = {str(seed): {"status": "not_run", "runs": []} for seed in SEEDS}
        for row in grid:
            result = direct_execute(binary, row["stdin"].encode(), counter_scale=row["n"])
            counters = r2d.validate_counter(result, nodes, pipeline.compute_tick_ceiling(row["n"]))
            if counters["status"] == "CLEAN_COMPLETION" and result.stdout == row["expected_stdout"].encode():
                seeds[str(row["seed"])]["runs"].append({"n": row["n"], "status": "CLEAN_COMPLETION",
                                                        "nodes": counters["nodes"]})
        for seed in seeds.values():
            seed["status"] = "eligible" if st.complete_grid([r["n"] for r in seed["runs"]]) else "insufficient_clean_rows"
        projection = {"schema": st.SCHEMA, "normalized_source": normalized,
                      "normalized_source_sha256": sha256(normalized.encode("utf-8")).hexdigest(),
                      "nodes": [{k: v for k, v in node.items() if k in st.NODE_FIELDS} for node in nodes],
                      "seeds": seeds}
        st.prediction_rows(projection)
        cases.append(dict(meta, projection=projection))
    return {"schema": PROFILE_SCHEMA, "pipeline_sha256": pipeline.source_sha256,
            "runner": "direct subprocess on the host, no Gate 1 isolation; binding to the committed "
                      "Part A result is checked by specificity_sweeps.py",
            "cases": cases}


def tier_evaluator(pipeline, gap, symptom):
    """Return the prospective tier evaluator with its hidden-work gap and work-jump thresholds replaced."""
    text = pipeline.wp_s1_source
    functions = {n.name: ast.get_source_segment(text, n) for n in ast.parse(text).body
                 if isinstance(n, ast.FunctionDef) and n.name in ("_select_work_symptom", "evaluate_four_slicing_tiers")}
    selector = functions["_select_work_symptom"]
    if selector.count(GAP_TEXT) != 1 or selector.count(SYMPTOM_TEXT) != 1:
        raise ValueError("Prospective _select_work_symptom no longer has one gap and one work-jump threshold")
    selector = (selector.replace(GAP_TEXT, "if hidden_gap >= __gap:")
                .replace(SYMPTOM_TEXT, "elif delta_a >= __symptom and alpha_w >= 1.5:"))
    namespace = dict(vars(pipeline), __gap=gap, __symptom=symptom)
    exec(compile(selector + "\n\n" + functions["evaluate_four_slicing_tiers"], "<wp-s1-thresholds>", "exec"), namespace)
    return namespace["evaluate_four_slicing_tiers"]


def part_a_fits(pipeline, profiles):
    from synthetic_arms import eligible_fit
    out = []
    for case in profiles["cases"]:
        projection, seeds = case["projection"], {}
        for seed in SEEDS:
            block = projection["seeds"][str(seed)]
            if block["status"] != "eligible":
                seeds[seed] = None
                continue
            rows, sizes = block["runs"], [row["n"] for row in block["runs"]]
            seeds[seed] = {node["id"]: {
                channel: eligible_fit(pipeline.fit_dual_family_scaling(sizes, [r["nodes"][node["id"]][key] for r in rows]),
                                      [r["nodes"][node["id"]][key] for r in rows])
                for channel, key in (("fit_hits", "cnt"), ("fit_work", "work"))} for node in projection["nodes"]}
        out.append((case, seeds))
    return out


def scoped_alert(evaluate, nodes, fits):
    """Return the work-scoped arm's (alert, symptom, scoped slice) for one seed."""
    if fits is None or not any(f["fit_work"]["growth"] != "UNAVAILABLE" for f in fits.values()):
        return None, None, []
    tiers = evaluate(nodes, fits)
    return bool(tiers["primary_symptom"]), tiers["primary_symptom"], sorted(tiers["c_pruned"])


def bind_part_a(pipeline, profiles, fitted):
    import synthetic_trace as st
    if profiles["pipeline_sha256"] != pipeline.source_sha256:
        raise ValueError("Profiles were captured with a different prospective pipeline")
    committed = {r["case_id"]: r for r in
                 json.loads(COMMITTED.read_text(encoding="utf-8"))["part_a_prospective_scalar"]["active_slot_details"]}
    registered = [meta for meta, _, _ in active_cases()]
    if ([{k: c[k] for k in ("case_id", "family", "slot", "band", "sham_class")} for c, _ in fitted] != registered
            or sorted(committed) != sorted(c["case_id"] for c in registered)):
        raise ValueError("Profiles do not cover the 42 committed active Part A cases")
    nominal = tier_evaluator(pipeline, NOMINAL_GAP, NOMINAL_GAP)
    for case, seeds in fitted:
        row = committed[case["case_id"]]
        if row["slot"] != case["slot"]:
            raise ValueError(f"Slot mismatch for {case['case_id']}")
        predictions = st.predict_case(pipeline, case["projection"])
        for prediction in predictions:
            arm = prediction["arms"]["work_scoped"]
            got = scoped_alert(nominal, case["projection"]["nodes"], seeds[prediction["seed"]])
            if got != (arm["alert"], arm["symptom_id"], sorted(arm["candidates"])):
                raise ValueError(f"Threshold re-evaluation differs from predictor for {case['case_id']}")
            if prediction["seed"] == 42 and got != (row["work_scoped_alert"], row["symptom"],
                                                     sorted(row["work_scoped_cands"])):
                raise ValueError(f"Profiles do not reproduce committed seed-42 alert for {case['case_id']}")
        case["disposition"] = row["disposition"]
    return len(committed)


def rate(k, n):
    return {"k": k, "n": n, "rate": round(k / n, 4) if n else None}


def part_a_counts(fitted, evaluate, seed):
    alerts = {c["case_id"]: scoped_alert(evaluate, c["projection"]["nodes"], s[seed])[0] for c, s in fitted}
    return {name: rate(sum(alerts[c["case_id"]] is True for c, _ in fitted if test(c)),
                       sum(1 for c, _ in fitted if test(c))) for name, test in CATEGORIES}, alerts


def part_a(pipeline, fitted):
    table = {}
    for seed in SEEDS:
        counts, _ = part_a_counts(fitted, tier_evaluator(pipeline, NOMINAL_GAP, NOMINAL_GAP), seed)
        table[str(seed)] = {**counts, "specificity_shams": rate(counts["sham_all"]["n"] - counts["sham_all"]["k"],
                                                               counts["sham_all"]["n"]),
                            "specificity_appropriate": rate(counts["appropriate_superlinear"]["n"]
                                                            - counts["appropriate_superlinear"]["k"],
                                                            counts["appropriate_superlinear"]["n"])}
    sweeps = {}
    for mode, pair in (("gap_only", lambda t: (t, NOMINAL_GAP)), ("gap_and_work_jump", lambda t: (t, t))):
        rows = []
        for threshold in GAP_GRID:
            counts, _ = part_a_counts(fitted, tier_evaluator(pipeline, *pair(threshold)), 42)
            rows.append({"threshold": threshold, **counts})
        sweeps[mode] = rows
    return {"seed_table": table, "sweeps_seed42": sweeps}


def stream_fit(screen):
    return screen.get("fit", screen)


def paired(ledger):
    rows = [r for r in ledger["rows"] if r["screen_status"] in {"alert", "no_alert"}]
    fits = []
    for r in rows:
        streams = [{"stream": s["stream"], "ratio": stream_fit(s)["largest_ratio"], "slope": stream_fit(s)["slope"],
                    "drop_largest_slope": (s.get("drop_largest") or {}).get("slope")} for s in r["stream_screens"]]
        nominal = all(s["slope"] >= NOMINAL_SLOPE and s["ratio"] >= NOMINAL_RATIO for s in streams)
        if nominal != r["all_stream_alert"]:
            raise ValueError(f"Paired alert does not reproduce for {r['case_id']}")
        fits.append({"intake_rank": r["intake_rank"], "case_id": r["case_id"],
                     "origin": "historical_control" if r["final_disposition"] == "verified_historical_control" else "new",
                     "min_ratio": min(s["ratio"] for s in streams), "min_slope": min(s["slope"] for s in streams),
                     "min_drop_largest_slope": None if any(s["drop_largest_slope"] is None for s in streams)
                     else min(s["drop_largest_slope"] for s in streams), "nominal_alert": nominal})
    if (len(fits), sum(f["nominal_alert"] for f in fits), sum(f["origin"] == "new" for f in fits)) != (13, 4, 5):
        raise ValueError("Paired fits are not the committed 13 fits with 4 alerts")

    def summary(slope, ratio, robust=False):
        def passes(f):
            drop = f["min_drop_largest_slope"]
            return (f["min_slope"] >= slope and f["min_ratio"] >= ratio
                    and (not robust or (drop is not None and drop >= slope)))
        controls = [f for f in fits if f["origin"] == "historical_control"]
        return {"alerts": rate(sum(map(passes, fits)), len(fits)),
                "historical_control_alerts": rate(sum(map(passes, controls)), len(controls)),
                "cases": [f["case_id"] for f in fits if passes(f)]}

    def only(case_id):
        found, = (f for f in fits if f["case_id"] == case_id)
        return found

    sqlpp11, p03999 = only("rbock/sqlpp11"), only("p03999")
    return {
        "fits": fits,
        "nominal": summary(NOMINAL_SLOPE, NOMINAL_RATIO),
        "nominal_with_drop_largest": summary(NOMINAL_SLOPE, NOMINAL_RATIO, robust=True),
        "slope_sweep": [{"slope": s, **summary(s, NOMINAL_RATIO)} for s in SLOPE_GRID],
        "ratio_sweep": [{"ratio": q, **summary(NOMINAL_SLOPE, q)} for q in RATIO_GRID],
        "ratio_sweep_slope_0": [{"ratio": q, **summary(0.0, q)} for q in RATIO_GRID],
        "sensitivity": {
            "sqlpp11": {"min_ratio": sqlpp11["min_ratio"], "min_slope": sqlpp11["min_slope"],
                        "alerts_at_slope_0_ratio_1_50": sqlpp11["case_id"] in summary(0.0, NOMINAL_RATIO)["cases"],
                        "alerts_at_slope_0_ratio_1_55": sqlpp11["case_id"] in summary(0.0, 1.55)["cases"]},
            "p03999": {"min_ratio": p03999["min_ratio"], "min_slope": p03999["min_slope"],
                       "min_drop_largest_slope": p03999["min_drop_largest_slope"],
                       "alerts_at_nominal": p03999["nominal_alert"],
                       "alerts_when_drop_largest_required": p03999["case_id"] in
                       summary(NOMINAL_SLOPE, NOMINAL_RATIO, robust=True)["cases"]},
        },
    }


def build(pipeline, profiles):
    fitted = part_a_fits(pipeline, profiles)
    bound = bind_part_a(pipeline, profiles, fitted)
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    return {
        "schema": SCHEMA,
        "inputs": {"profiles_sha256": file_digest(PROFILES), "committed_part_a_sha256": file_digest(COMMITTED),
                   "paired_ledger_sha256": file_digest(LEDGER), "pipeline_sha256": pipeline.source_sha256},
        "nominal": {"gap": NOMINAL_GAP, "slope": NOMINAL_SLOPE, "ratio": NOMINAL_RATIO},
        "part_a_binding": {"active_cases": bound, "seed42_alert_symptom_slice_reproduced": bound},
        "part_a": part_a(pipeline, fitted),
        "paired": paired(ledger),
    }


def svg(receipt):
    width, height, pad, pw, ph = 960, 700, 60, 380, 200
    part_a_series = [("positive", "#1f77b4", "20 positives", "", 5), ("sham_quadratic", "#d62728", "5 quadratic shams", "8 4", 3.5),
                     ("sham_linear", "#ff7f0e", "5 linear shams", "", 2),
                     ("appropriate_superlinear", "#2ca02c", "10 appropriate controls", "2 3", 2)]
    paired_series = [("alerts", "#9467bd", "13 fitted pairs", "", 3),
                     ("historical_control_alerts", "#8c564b", "8 historical controls", "5 3", 2)]
    sweeps = receipt["part_a"]["sweeps_seed42"]
    panels = [
        ("Part A seed 42: hidden-work gap only (work jump 0.70)", sweeps["gap_only"], "threshold",
         "gap threshold", NOMINAL_GAP, part_a_series),
        ("Part A seed 42: gap and work-jump thresholds together", sweeps["gap_and_work_jump"], "threshold",
         "gap = work-jump threshold", NOMINAL_GAP, part_a_series),
        ("Paired: slope threshold (ratio 1.50)", receipt["paired"]["slope_sweep"], "slope", "slope threshold",
         NOMINAL_SLOPE, paired_series),
        ("Paired: ratio threshold, log axis (slope 0.50)", receipt["paired"]["ratio_sweep"], "ratio",
         "ratio threshold", NOMINAL_RATIO, paired_series),
    ]
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
             f'viewBox="0 0 {width} {height}" font-family="sans-serif" font-size="11">',
             f'<rect width="{width}" height="{height}" fill="white"/>']
    for index, (title, rows, key, label, nominal, series) in enumerate(panels):
        x0, y0 = pad + (index % 2) * (pw + 2 * pad), 40 + (index // 2) * (ph + 130)
        scale = math.log10 if key == "ratio" else float
        xs = [scale(row[key]) for row in rows]
        lo, hi = min(xs), max(xs)
        px = lambda v: x0 + (scale(v) - lo) / (hi - lo) * pw
        py = lambda r: y0 + ph - r * ph
        parts.append(f'<text x="{x0}" y="{y0 - 10}" font-weight="bold">{title}</text>')
        parts.append(f'<rect x="{x0}" y="{y0}" width="{pw}" height="{ph}" fill="none" stroke="#333"/>')
        for tick in (0, 0.5, 1):
            parts.append(f'<text x="{x0 - 6}" y="{py(tick) + 4:.1f}" text-anchor="end">{tick:.1f}</text>')
        ticks = (1, 10, 100, 1000, 10000) if key == "ratio" else (lo, (lo + hi) / 2, hi)
        for tick in ticks:
            parts.append(f'<text x="{px(tick):.1f}" y="{y0 + ph + 14}" text-anchor="middle">{tick:g}</text>')
        parts.append(f'<text x="{x0 + pw / 2}" y="{y0 + ph + 28}" text-anchor="middle">{label}</text>')
        parts.append(f'<text x="{x0 - 40}" y="{y0 + ph / 2}" text-anchor="middle" '
                     f'transform="rotate(-90 {x0 - 40} {y0 + ph / 2})">alert rate</text>')
        parts.append(f'<line x1="{px(nominal):.1f}" y1="{y0}" x2="{px(nominal):.1f}" y2="{y0 + ph}" '
                     f'stroke="#555" stroke-dasharray="4 3"/>')
        for offset, (field, colour, name, dash, stroke) in enumerate(series):
            points = " ".join(f"{px(row[key]):.1f},{py(row[field]['rate']):.1f}" for row in rows)
            parts.append(f'<polyline points="{points}" fill="none" stroke="{colour}" stroke-width="{stroke}"'
                         f'{f" stroke-dasharray={chr(34)}{dash}{chr(34)}" if dash else ""}/>')
            parts.append(f'<text x="{x0 + (offset % 2) * pw / 2}" y="{y0 + ph + 46 + 14 * (offset // 2)}" '
                         f'fill="{colour}">{name}</text>')
    parts.append(f'<text x="{pad}" y="{height - 10}">Alert rate = alerts / cases in each group (group sizes in the '
                 'legends). Dashed vertical line: nominal threshold. Data: development/specificity_sweeps.json</text>')
    parts.append("</svg>\n")
    return "\n".join(parts)


def write(path, text):
    path.write_text(text, encoding="utf-8", newline="\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--regenerate", action="store_true", help="re-profile the 42 active Part A cases")
    parser.add_argument("--check", action="store_true", help="fail unless committed outputs match a rebuild")
    args = parser.parse_args(argv)
    pipeline = load_pipeline()
    if args.regenerate:
        write(PROFILES, canonical(regenerate(pipeline)) + "\n")
    profiles = json.loads(PROFILES.read_text(encoding="utf-8"))
    receipt = build(pipeline, profiles)
    text, plot = json.dumps(receipt, indent=1, sort_keys=True) + "\n", svg(receipt)
    if args.check:
        if RECEIPT.read_text(encoding="utf-8") != text or PLOT.read_text(encoding="utf-8") != plot:
            raise SystemExit("WP-S1 receipt or plot does not match a rebuild from committed inputs")
        print("WP-S1 specificity sweeps: receipt and plot reproduce")
        return 0
    write(RECEIPT, text)
    write(PLOT, plot)
    print(f"wrote {RECEIPT.name} and {PLOT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
