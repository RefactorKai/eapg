"""Re-execute pilot Table I through frozen pipeline.run_pilot_100_study.process_pair.

The 100 slow/fast sources embedded in pilot100_results.json are compiled and profiled again by the
unmodified, hash-pinned pipeline.py; the fresh records are compared field by field and decision by
decision with the committed pilot and with the per-node R^2 / raw-counter receipt.
"""

import argparse
from contextlib import redirect_stdout
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from importlib.util import module_from_spec, spec_from_file_location
import io
import json
from pathlib import Path
import platform
import subprocess
import sys
from statistics import mean
from tempfile import TemporaryDirectory
import threading
import time


ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "artifacts/scope_isolated_pilot/pilot100_results.json"
RECEIPT = ROOT / "artifacts/scope_isolated_pilot/pilot100_reexec_receipt.json"
PIPELINE_SHA = "7c855651566c1a7dc003fdcb291d8edd3ff1a99c671f781eb595d72c492ae743"
PILOT_SHA = "4a3b563cdd54c471f39df95e7d40ec3ae5433259795cadcde80272955ea44cb5"
SCHEMA = "eapg.pilot100_reexec/v1"
GENERATOR_KEYS = ("pair_id", "pilot_revision", "problem_id", "track_gt", "mechanism_id", "mechanism_name",
                  "paradigm", "scope_kind", "template_fingerprints", "slow_code", "fast_code")
TIERS = ("c_naive_hits", "c_naive_work", "c_inter_only", "c_unpruned", "c_pruned")
TABLE_I_LABELS = dict(zip(TIERS, ("Hit symptom", "Work symptom", "Inter-scope slice",
                                  "Unpruned two-tier slice", "Pruned two-tier slice")))
EXP_R2_GATE = 0.85


UNIT_RECEIVER_PATCH = (
    ('c_type = var_types.get(container_name, "seq_container")',
     'c_type = var_types.get(container_name, "unknown")'),
    ('else:\r\n                                    weight_expr = f"(unsigned long long)({container_name}.size())"',
     'elif c_type == "seq_container":\r\n                                    weight_expr = f"(unsigned long long)({container_name}.size())"'),
)
PROXY_DEFAULTS = {
    "linear": "archived pilot (frozen pipeline.py): member calls on undeclared or non-container receivers weigh size()",
    "unit": "prospective default for undeclared receivers: member calls on receivers not declared as containers weigh 1; all else as archived",
}
UNSANDBOXED = ("not sandboxed: every preprocess, compile and binary run used frozen pipeline.py's own subprocess "
               "calls on the host, outside development/gate1_sandbox.py; a sandboxed rerun is deferred to the "
               "WP-F1 container (m9)")
CRLF_NOTE = ("Linux writes LF line endings and the archived pilot is CRLF: the fresh bytes are compared with the "
             "archive after rewriting every line ending to CRLF, so line terminators are the only difference allowed")
SELF_CHECK_NOTE = ("comparison.vs_receipt in this file compares the writing run's counters with themselves and only fixes "
                   "the denominators; it is not independent evidence. Normal reexec compares a later fresh run with "
                   "this receipt, which is a regression check against this script's own earlier output")
STRIP_KEYS = ("slow_code", "fast_code", "template_fingerprints")


def load_frozen_pipeline(proxy_default="linear"):
    """Hash-pinned pipeline.py; proxy_default="unit" applies UNIT_RECEIVER_PATCH in memory only."""
    source = (ROOT / "pipeline.py").read_bytes()
    if sha256(source).hexdigest() != PIPELINE_SHA:
        raise ValueError("Frozen pipeline.py hash mismatch")
    if proxy_default == "unit":
        text = source.decode("utf-8")
        for old, new in UNIT_RECEIVER_PATCH:
            if text.count(old) != 1:
                raise ValueError(f"Unit-receiver patch anchor is not unique: {old!r}")
            text = text.replace(old, new)
        source = text.encode("utf-8")
    elif proxy_default != "linear":
        raise ValueError(f"Unknown proxy default: {proxy_default}")
    module = module_from_spec(spec_from_file_location(f"frozen_pilot_pipeline_{proxy_default}", ROOT / "pipeline.py"))
    exec(compile(source, str(ROOT / "pipeline.py"), "exec"), module.__dict__)
    module.EAPG_SOURCE_SHA256 = sha256(source).hexdigest()
    return module


def crlf_sha256(raw):
    # The archived pilot was written on Windows; its pinned bytes are CRLF (.gitattributes: -text).
    return sha256(raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")).hexdigest()


def stripped(records):
    return [{k: v for k, v in r.items() if k not in STRIP_KEYS} for r in records]


def load_published():
    raw = PILOT.read_bytes()
    if sha256(raw).hexdigest() != PILOT_SHA:
        raise ValueError("Published pilot100_results.json hash mismatch")
    return json.loads(raw)


def embedded_corpus(gen, published):
    """Generator items (for input_gen) carrying the sources embedded in the published records."""
    generated = gen.generate_pilot_100_corpus()
    if len(published) != 100 or len(generated) != 100:
        raise ValueError("Expected the complete 100-pair pilot")
    corpus = []
    for frozen, item in zip(published, generated, strict=True):
        diff = [key for key in GENERATOR_KEYS if frozen[key] != item[key]]
        if diff:
            raise ValueError(f"{frozen['pair_id']}: embedded record differs from generator on {diff}")
        corpus.append({**item, "slow_code": frozen["slow_code"], "fast_code": frozen["fast_code"]})
    return corpus


def toolchain():
    def pkg(name):
        try:
            return version(name)
        except PackageNotFoundError:
            return None
    gxx = subprocess.run(["g++", "-dumpfullversion"], capture_output=True, text=True, check=True).stdout.strip()
    return {"compiler": f"g++ {gxx}", "flags": ["-std=c++17", "-O2"], "python": platform.python_version(),
            "platform": sys.platform, "kernel": platform.release(), "sandbox": UNSANDBOXED,
            "parser": {name: pkg(name) for name in ("tree-sitter", "tree-sitter-cpp")}}


def reexecute(gen, corpus):
    """Run the frozen study with the embedded corpus; capture every ladder run and per-node fit."""
    lock = threading.Lock()
    runs, ladders, weights = {}, {}, {}
    run_instrumented, ladder = gen.run_instrumented_binary, gen.execute_scaling_with_micro_ladder

    def side_key(binary_path):
        stem = Path(binary_path).stem.removeprefix("pilot_")
        pair_id, side = stem.rsplit("_", 1)
        return pair_id, side

    def recording_run(binary_path, stdin_data, n_scale, *args, **kwargs):
        status, dump = run_instrumented(binary_path, stdin_data, n_scale, *args, **kwargs)
        with lock:
            runs.setdefault(side_key(binary_path), []).append((n_scale, status, dump))
        return status, dump

    def recording_ladder(binary_path, input_generator, macro_nodes, *args, **kwargs):
        result = ladder(binary_path, input_generator, macro_nodes, *args, **kwargs)
        with lock:
            ladders[side_key(binary_path)] = ([n["id"] for n in macro_nodes], result)
            weights[side_key(binary_path)] = {n["id"]: n["weight_expr"] for n in macro_nodes}
        return result

    gen.generate_pilot_100_corpus = lambda: corpus
    gen.run_instrumented_binary = recording_run
    gen.execute_scaling_with_micro_ladder = recording_ladder
    with TemporaryDirectory(prefix="eapg_reexec_") as td:
        start = time.perf_counter()
        log = io.StringIO()
        with redirect_stdout(log):
            gen.run_pilot_100_study(Path(td) / "build", Path(td) / "out")
        elapsed = time.perf_counter() - start
        raw = (Path(td) / "out/pilot100_results.json").read_bytes()
        tables_sha = sha256((Path(td) / "out/pilot100_tables.tex").read_bytes()).hexdigest()
    return {"raw": raw, "records": json.loads(raw), "tables_tex_sha256": tables_sha,
            "elapsed_seconds": round(elapsed, 1), "counters": counters(runs, ladders),
            "weights": {f"{pid}/{side}": w for (pid, side), w in sorted(weights.items())}}


def counters(runs, ladders):
    pairs = {}
    for (pair_id, side), (node_ids, result) in sorted(ladders.items()):
        calls = sorted(runs[(pair_id, side)], key=lambda call: call[0])
        clean = {scale: dump for scale, status, dump in calls if status == "CLEAN_COMPLETION"}
        scales = next(iter(result.values()))["uncapped_scales"] if result else []
        if sorted(clean) != scales:
            raise RuntimeError(f"{pair_id} {side}: captured runs disagree with the fitted ladder")
        nodes = {}
        for nid in node_ids:
            fit = result[nid]
            hits = [clean[s].get(nid, {}).get("cnt", 0) for s in scales]
            work = [clean[s].get(nid, {}).get("work", 0) for s in scales]
            if work != fit["work_values"]:
                raise RuntimeError(f"{pair_id} {side} {nid}: captured work counters disagree with the fit")
            nodes[nid] = {"hits": hits, "work": work, "fit_hits": fit["fit_hits"], "fit_work": fit["fit_work"]}
        pairs.setdefault(pair_id, {})[side] = {
            "ladder": [[scale, status] for scale, status, _ in calls],
            "uncapped_scales": scales,
            "cap_breached": next(iter(result.values()))["cap_breached"] if result else False,
            "nodes": nodes,
        }
    return pairs


def node_decisions(fit):
    """Growth-class decisions taken from one dual-family fit, including the R^2 >= 0.85 EXP gate."""
    return {"growth": fit["growth"], "r2_exp_gate": fit["r2_exp"] >= EXP_R2_GATE,
            "exp_preferred": fit["r2_exp"] > fit["r2_poly"]}


def pair_decisions(record):
    slicing = record["slicing"]
    decisions = {"is_exp_slow": record["is_exp_slow"], "gt_node": record["gt_node"],
                 "primary_symptom": slicing["primary_symptom"]}
    for tier in TIERS:
        decisions[f"{tier}.nonempty"] = bool(slicing[tier])
        decisions[f"{tier}.retains_reference"] = record["gt_node"] in slicing[tier]
        decisions[f"{tier}.top1"] = bool(slicing[tier]) and slicing[tier][0] == record["gt_node"]
    return decisions


def diff_fields(left, right, prefix=""):
    if isinstance(left, dict) and isinstance(right, dict):
        out = []
        for key in sorted(set(left) | set(right)):
            if key not in left or key not in right:
                out.append(f"{prefix}{key}")
            else:
                out.extend(diff_fields(left[key], right[key], f"{prefix}{key}."))
        return out
    return [] if left == right else [prefix.rstrip(".")]


def count_fields(value):
    return sum(count_fields(v) for v in value.values()) if isinstance(value, dict) else 1


def compare_records(published, fresh):
    if [r["pair_id"] for r in published] != [r["pair_id"] for r in fresh]:
        raise ValueError("Fresh pair order differs from the published pilot")
    mismatches, flips, decisions = [], [], 0
    for old, new in zip(published, fresh, strict=True):
        mismatches += [f"{old['pair_id']}:{f}" for f in diff_fields(old, new)]
        old_d, new_d = pair_decisions(old), pair_decisions(new)
        decisions += len(old_d)
        flips += [f"{old['pair_id']}:{k}" for k in old_d if old_d[k] != new_d[k]]
    return {"pairs": len(published), "fields_compared": sum(count_fields(r) for r in published),
            "mismatches": mismatches, "decisions_compared": decisions, "decision_flips": flips}


def compare_counters(archived, fresh):
    mismatches = [f"{pid}:{f}" for pid in sorted(set(archived) | set(fresh))
                  for f in diff_fields(archived.get(pid, {}), fresh.get(pid, {}))]
    flips, decisions = [], 0
    for pid, sides in archived.items():
        for side, entry in sides.items():
            for nid, node in entry["nodes"].items():
                other = fresh.get(pid, {}).get(side, {}).get("nodes", {}).get(nid)
                for family in ("fit_hits", "fit_work"):
                    old_d = node_decisions(node[family])
                    new_d = node_decisions(other[family]) if other else {}
                    decisions += len(old_d)
                    flips += [f"{pid}:{side}:{nid}:{family}.{k}" for k in old_d if old_d[k] != new_d.get(k)]
    return {"mismatches": mismatches, "decisions_compared": decisions, "decision_flips": flips}


def table_i(records):
    rows = []
    for tier, label in TABLE_I_LABELS.items():
        sets = [r["slicing"][tier] for r in records]
        recall = 100 * mean(r["gt_node"] in s for r, s in zip(records, sets, strict=True))
        reduction = 100 * mean(1 - len(s) / r["v_slow"] for r, s in zip(records, sets, strict=True))
        rows.append([label, f"{recall:.0f}", f"{mean(map(len, sets)):.2f}", f"{reduction:.1f}"])
    return {"rows": rows,
            "hit_symptoms": sum(bool(r["slicing"]["c_naive_hits"]) for r in records),
            "work_symptoms": sum(bool(r["slicing"]["c_naive_work"]) for r in records)}


def weight_changes(linear, unit):
    assert linear.keys() == unit.keys() and all(linear[k].keys() == unit[k].keys() for k in linear)
    return [f"{side}/{node}: {linear[side][node]} -> {unit[side][node]}"
            for side in linear for node in linear[side] if linear[side][node] != unit[side][node]]


def unit_section(published, unit_records):
    vs_linear = compare_records(published, unit_records)
    return {"table_i": table_i(unit_records), "vs_linear": summarize(vs_linear),
            "changed_fields": vs_linear["mismatches"], "flipped_decisions": vs_linear["decision_flips"]}


def check_receipt_static(gen, receipt, published):
    """Checks that need no compiler: pins, exact denominators, and fits/maxima recomputed from raw counters."""
    assert receipt["schema"] == SCHEMA
    assert receipt["pipeline_sha256"] == PIPELINE_SHA and receipt["pilot_sha256"] == PILOT_SHA
    assert receipt["fresh_pilot_sha256"] == PILOT_SHA and receipt["identical_after_crlf_normalization"] is True
    assert receipt["line_endings"] == CRLF_NOTE and receipt["self_check"] == SELF_CHECK_NOTE
    assert receipt["fresh_pilot_raw_sha256"] in {PILOT_SHA, sha256(PILOT.read_bytes().replace(b"\r\n", b"\n")).hexdigest()}
    assert receipt["provenance"]["sandbox"] == UNSANDBOXED
    pairs = receipt["pairs"]
    assert receipt["comparison"] == {
        "vs_published": summarize(compare_records(published, published)),
        "vs_receipt": summarize(compare_counters(pairs, pairs)),
    }
    assert receipt["table_i"] == table_i(published)
    assert sorted(pairs) == sorted(r["pair_id"] for r in published)
    by_id = {r["pair_id"]: r for r in published}
    for pid, sides in pairs.items():
        record = by_id[pid]
        assert sorted(sides) == ["fast", "slow"]
        assert sorted(sides["slow"]["nodes"], key=lambda n: int(n[1:])) == \
            [f"N{i}" for i in range(1, record["v_slow"] + 1)]
        assert len(sides["fast"]["nodes"]) == record["v_fast"]
        for entry in sides.values():
            scales = entry["uncapped_scales"]
            assert scales == sorted(s for s, status in entry["ladder"] if status == "CLEAN_COMPLETION")
            for node in entry["nodes"].values():
                assert len(node["hits"]) == len(node["work"]) == len(scales)
                assert node["fit_hits"] == gen.fit_dual_family_scaling(scales, node["hits"])
                assert node["fit_work"] == gen.fit_dual_family_scaling(scales, node["work"])

        def worst(side, family):
            return max(n[family]["alpha"] if n[family]["growth"] == "POLY" else 9.99
                       for n in sides[side]["nodes"].values())
        assert worst("slow", "fit_hits") == record["max_hits_slow"], pid
        assert worst("slow", "fit_work") == record["max_work_slow"], pid
        assert worst("fast", "fit_work") == record["max_work_fast"], pid
        assert any(n["fit_work"]["growth"] == "EXP" for n in sides["slow"]["nodes"].values()) == record["is_exp_slow"]

    proxy = receipt["proxy_defaults"]
    assert sorted(proxy) == sorted(PROXY_DEFAULTS)
    assert proxy["linear"] == {"description": PROXY_DEFAULTS["linear"], "pipeline_source_sha256": PIPELINE_SHA,
                               "results_sha256": PILOT_SHA, "table_i": table_i(published)}
    unit = proxy["unit"]
    assert unit["description"] == PROXY_DEFAULTS["unit"]
    node_keys = {f"{pid}/{side}/{node}" for pid, sides in pairs.items() for side, e in sides.items() for node in e["nodes"]}
    assert unit["instrumented_nodes"] == len(node_keys)
    assert all(change.split(": ", 1)[0] in node_keys for change in unit["weight_changed_nodes"])
    assert unit["pipeline_source_sha256"] == load_frozen_pipeline("unit").EAPG_SOURCE_SHA256
    assert [r["pair_id"] for r in unit["records"]] == [r["pair_id"] for r in published]
    full_unit = [{**r, **{k: by_id[r["pair_id"]][k] for k in STRIP_KEYS}} for r in unit["records"]]
    assert {k: v for k, v in unit.items() if k in ("table_i", "vs_linear", "changed_fields", "flipped_decisions")} \
        == unit_section(published, full_unit)
    return sum(len(e["nodes"]) for s in pairs.values() for e in s.values())


def summarize(result):
    return {"mismatches": len(result["mismatches"]), "decision_flips": len(result["decision_flips"]),
            **{k: v for k, v in result.items() if k not in ("mismatches", "decision_flips")}}


def evaluate(published, archived, run, unit_run):
    """Every difference from the archive; an empty failure list is the only success."""
    vs_published = compare_records(published, run["records"])
    vs_receipt = compare_counters(archived["pairs"] if archived else run["counters"], run["counters"])
    fresh_sha = crlf_sha256(run["raw"])
    unit = unit_section(published, unit_run["records"])
    report = {
        "fresh_pilot_sha256": fresh_sha, "identical_after_crlf_normalization": fresh_sha == PILOT_SHA,
        "fresh_pilot_raw_sha256": sha256(run["raw"]).hexdigest(),
        "vs_published": summarize(vs_published), "vs_receipt": summarize(vs_receipt),
        "table_i_matches": table_i(run["records"]) == table_i(published),
        "unit_results_sha256": crlf_sha256(unit_run["raw"]),
        "unit_vs_linear": unit["vs_linear"],
        "weight_changed_nodes": len(changes := weight_changes(run["weights"], unit_run["weights"])),
        "instrumented_nodes": sum(len(w) for w in run["weights"].values()),
    }
    failures = vs_published["mismatches"] + vs_published["decision_flips"] + \
        vs_receipt["mismatches"] + vs_receipt["decision_flips"]
    if not report["identical_after_crlf_normalization"]:
        failures.append(f"fresh pilot SHA-256 after CRLF normalization {fresh_sha} != {PILOT_SHA}")
    if not report["table_i_matches"]:
        failures.append("Table I rows differ")
    if archived:
        archived_unit = archived["proxy_defaults"]["unit"]
        if report["instrumented_nodes"] != archived_unit["instrumented_nodes"]:
            failures.append("instrumented node count differs from the receipt")
        if changes != archived_unit["weight_changed_nodes"]:
            failures.append("unit-default weight changes differ from the receipt")
        if report["unit_results_sha256"] != archived_unit["results_sha256"]:
            failures.append("unit-default results SHA-256 differs from the receipt")
        failures += [f"unit:{f}" for f in diff_fields({"records": archived_unit["records"]},
                                                       {"records": stripped(unit_run["records"])})]
    return report, failures, vs_published, vs_receipt, unit


def write_receipt(path, gen, unit_gen, published, run, unit_run, results):
    report, _, vs_published, vs_receipt, unit = results
    receipt = {
        "schema": SCHEMA,
        "description": "Fresh re-execution of pilot Table I: frozen pipeline.run_pilot_100_study.process_pair "
                       "over the sources embedded in pilot100_results.json. Per-node raw hit/work counters "
                       "and dual-family fits (alpha, beta, r2_poly, r2_exp) for every slow and fast program.",
        "entry_point": "pipeline.run_pilot_100_study.process_pair",
        "pipeline_sha256": PIPELINE_SHA, "pilot_sha256": PILOT_SHA,
        "fresh_pilot_sha256": report["fresh_pilot_sha256"], "identical_after_crlf_normalization": True,
        "fresh_pilot_raw_sha256": report["fresh_pilot_raw_sha256"], "line_endings": CRLF_NOTE,
        "self_check": SELF_CHECK_NOTE,
        "tables_tex_sha256": run["tables_tex_sha256"],
        "exp_r2_gate": EXP_R2_GATE,
        "provenance": {**toolchain(), "elapsed_seconds": {"linear": run["elapsed_seconds"],
                                                          "unit": unit_run["elapsed_seconds"]}},
        "comparison": {"vs_published": summarize(vs_published), "vs_receipt": summarize(vs_receipt)},
        "table_i": table_i(run["records"]),
        "proxy_defaults": {
            "linear": {"description": PROXY_DEFAULTS["linear"], "pipeline_source_sha256": PIPELINE_SHA,
                       "results_sha256": PILOT_SHA, "table_i": table_i(published)},
            "unit": {"description": PROXY_DEFAULTS["unit"], "pipeline_source_sha256": unit_gen.EAPG_SOURCE_SHA256,
                     "patch": [list(pair) for pair in UNIT_RECEIVER_PATCH],
                     "results_sha256": report["unit_results_sha256"],
                     "instrumented_nodes": report["instrumented_nodes"],
                     "weight_changed_nodes": weight_changes(run["weights"], unit_run["weights"]), **unit,
                     "records": stripped(unit_run["records"])},
        },
        "pairs": run["counters"],
    }
    text = json.dumps({k: v for k, v in receipt.items() if k != "pairs"}, indent=2)[:-2]
    lines = [f'    {json.dumps(pid)}: {json.dumps(sides, sort_keys=True, separators=(",", ":"))}'
             for pid, sides in receipt["pairs"].items()]
    text += ',\n  "pairs": {\n' + ",\n".join(lines) + "\n  }\n}\n"
    assert json.loads(text) == receipt
    check_receipt_static(gen, receipt, published)
    path.write_text(text, encoding="utf-8")


def verify_committed(gen, published, archived, run, unit_run):
    """Normal reexec: the committed receipt must pass every static check before a fresh run is compared with it."""
    check_receipt_static(gen, archived, published)
    return evaluate(published, archived, run, unit_run)


def main():
    if not __debug__:
        raise RuntimeError("Run without Python optimization so assertions remain active")
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--write-receipt", type=Path, metavar="PATH",
                     help="Write a fresh receipt to a new PATH instead of checking the committed one.")
    cli.add_argument("--static", action="store_true", help="Check the committed receipt without compiling C++.")
    args = cli.parse_args()

    gen = load_frozen_pipeline()
    published = load_published()
    if args.static:
        nodes = check_receipt_static(gen, json.loads(RECEIPT.read_text(encoding="utf-8")), published)
        print(f"Verified pilot re-execution receipt statically ({nodes} node fits recomputed from raw counters).")
        return 0
    if args.write_receipt is not None and args.write_receipt.exists():
        cli.error(f"{args.write_receipt} exists; pass a new path")

    archived = None if args.write_receipt else json.loads(RECEIPT.read_text(encoding="utf-8"))
    run = reexecute(gen, embedded_corpus(gen, published))
    unit_gen = load_frozen_pipeline("unit")
    unit_run = reexecute(unit_gen, embedded_corpus(unit_gen, published))
    results = (evaluate(published, None, run, unit_run) if archived is None
               else verify_committed(gen, published, archived, run, unit_run))
    report, failures, vs_published, vs_receipt, _ = results
    print(json.dumps(report, indent=2))
    if failures:
        raise SystemExit(f"Pilot re-execution diverged ({len(failures)} differences): {failures[:20]}")
    if args.write_receipt is not None:
        write_receipt(args.write_receipt, gen, unit_gen, published, run, unit_run, results)
        print(f"Wrote {args.write_receipt}")
        return 0
    print(f"Re-executed pilot Table I: 0 mismatches over {vs_published['fields_compared']} fields, "
          f"0 decision flips over {vs_published['decisions_compared']} pair and "
          f"{vs_receipt['decisions_compared']} node decisions against this script's own receipt; "
          f"identical to the archived pilot after CRLF normalization; unit proxy default matches its receipt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
