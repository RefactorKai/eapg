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


def load_frozen_pipeline():
    source = (ROOT / "pipeline.py").read_bytes()
    if sha256(source).hexdigest() != PIPELINE_SHA:
        raise ValueError("Frozen pipeline.py hash mismatch")
    module = module_from_spec(spec_from_file_location("frozen_pilot_pipeline", ROOT / "pipeline.py"))
    exec(compile(source, str(ROOT / "pipeline.py"), "exec"), module.__dict__)
    return module


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
            "platform": sys.platform, "kernel": platform.release(),
            "parser": {name: pkg(name) for name in ("tree-sitter", "tree-sitter-cpp")}}


def reexecute(gen, corpus):
    """Run the frozen study with the embedded corpus; capture every ladder run and per-node fit."""
    lock = threading.Lock()
    runs, ladders = {}, {}
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
            "elapsed_seconds": round(elapsed, 1), "counters": counters(runs, ladders)}


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


def check_receipt_static(gen, receipt, published):
    """Checks that need no compiler: pins, recorded zeros, and fits/maxima recomputed from raw counters."""
    assert receipt["schema"] == SCHEMA
    assert receipt["pipeline_sha256"] == PIPELINE_SHA and receipt["pilot_sha256"] == PILOT_SHA
    assert receipt["fresh_pilot_sha256"] == PILOT_SHA and receipt["byte_identical"] is True
    for key in ("vs_published", "vs_receipt"):
        result = receipt["comparison"][key]
        assert result["mismatches"] == 0 and result["decision_flips"] == 0, key
    assert receipt["table_i"] == table_i(published)
    pairs = receipt["pairs"]
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
            for node in entry["nodes"].values():
                assert node["fit_hits"] == gen.fit_dual_family_scaling(scales, node["hits"])
                assert node["fit_work"] == gen.fit_dual_family_scaling(scales, node["work"])

        def worst(side, family):
            return max(n[family]["alpha"] if n[family]["growth"] == "POLY" else 9.99
                       for n in sides[side]["nodes"].values())
        assert worst("slow", "fit_hits") == record["max_hits_slow"], pid
        assert worst("slow", "fit_work") == record["max_work_slow"], pid
        assert worst("fast", "fit_work") == record["max_work_fast"], pid
        assert any(n["fit_work"]["growth"] == "EXP" for n in sides["slow"]["nodes"].values()) == record["is_exp_slow"]
    nodes = sum(len(e["nodes"]) for s in pairs.values() for e in s.values())
    return nodes


def summarize(result):
    return {"mismatches": len(result["mismatches"]), "decision_flips": len(result["decision_flips"]),
            **{k: v for k, v in result.items() if k not in ("mismatches", "decision_flips")}}


def main():
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
    vs_published = compare_records(published, run["records"])
    vs_receipt = compare_counters(archived["pairs"], run["counters"]) if archived else \
        compare_counters(run["counters"], run["counters"])
    # The archived pilot was written on Windows; the receipt pins its CRLF bytes (.gitattributes: -text).
    fresh_sha = sha256(run["raw"].replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")).hexdigest()
    fresh_table = table_i(run["records"])
    report = {
        "fresh_pilot_sha256": fresh_sha, "byte_identical": fresh_sha == PILOT_SHA,
        "elapsed_seconds": run["elapsed_seconds"],
        "vs_published": summarize(vs_published), "vs_receipt": summarize(vs_receipt),
        "table_i_matches": fresh_table == table_i(published),
    }
    failures = vs_published["mismatches"] + vs_published["decision_flips"] + \
        vs_receipt["mismatches"] + vs_receipt["decision_flips"]
    if args.write_receipt is not None:
        if failures or not report["byte_identical"]:
            raise SystemExit(f"Refusing to write a receipt for a divergent rerun: {failures[:20]}")
        receipt = {
            "schema": SCHEMA,
            "description": "Fresh re-execution of pilot Table I: frozen pipeline.run_pilot_100_study.process_pair "
                           "over the sources embedded in pilot100_results.json. Per-node raw hit/work counters "
                           "and dual-family fits (alpha, beta, r2_poly, r2_exp) for every slow and fast program.",
            "entry_point": "pipeline.run_pilot_100_study.process_pair",
            "pipeline_sha256": PIPELINE_SHA, "pilot_sha256": PILOT_SHA,
            "fresh_pilot_sha256": fresh_sha, "byte_identical": True,
            "tables_tex_sha256": run["tables_tex_sha256"],
            "exp_r2_gate": EXP_R2_GATE,
            "provenance": {**toolchain(), "elapsed_seconds": run["elapsed_seconds"]},
            "comparison": {"vs_published": summarize(vs_published),
                           "vs_receipt": {"mismatches": 0, "decision_flips": 0,
                                          "decisions_compared": vs_receipt["decisions_compared"]}},
            "table_i": fresh_table,
            "pairs": run["counters"],
        }
        text = json.dumps({k: v for k, v in receipt.items() if k != "pairs"}, indent=2)[:-2]
        lines = [f'    {json.dumps(pid)}: {json.dumps(sides, sort_keys=True, separators=(",", ":"))}'
                 for pid, sides in receipt["pairs"].items()]
        text += ',\n  "pairs": {\n' + ",\n".join(lines) + "\n  }\n}\n"
        assert json.loads(text) == receipt
        args.write_receipt.write_text(text, encoding="utf-8")
        check_receipt_static(gen, receipt, published)
        print(json.dumps(report, indent=2))
        print(f"Wrote {args.write_receipt}")
        return 0

    print(json.dumps(report, indent=2))
    if failures or not report["table_i_matches"]:
        raise SystemExit(f"Pilot re-execution diverged ({len(failures)} differences): {failures[:20]}")
    print(f"Re-executed pilot Table I: 0 mismatches over {vs_published['fields_compared']} fields, "
          f"0 decision flips over {vs_published['decisions_compared']} pair and "
          f"{vs_receipt['decisions_compared']} node decisions ({run['elapsed_seconds']} s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
