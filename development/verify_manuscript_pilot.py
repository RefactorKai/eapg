"""Replay the manuscript tables and diagnostics from released records."""

import argparse
from base64 import b64decode
from collections import Counter, defaultdict
from hashlib import sha256
import json
from math import isclose, log
from statistics import linear_regression, mean

from replay_pilot_contrast import PILOT, ROOT, verified_json
from runtime_screen import summarize as summarize_timing
from synthetic_arms import ARM_IDS
from verify_weighted_panel import EVIDENCE, replay as replay_library


def published_rows(source, label):
    manuscript = (ROOT / "manuscript" / source).read_text(encoding="utf-8")
    _, found, tail = manuscript.partition(r"\label{" + label + "}")
    assert found, f"Missing manuscript table: {label}"
    body = tail.split(r"\midrule", 1)[1].split(r"\bottomrule", 1)[0]
    return [[cell.strip() for cell in line.strip().removesuffix(r"\\").split("&")]
            for line in body.splitlines()
            if line.strip() and not line.strip().startswith(r"\midrule")]


def verify_candidate_selection(pilot):
    assert len(pilot) == len({row["pair_id"] for row in pilot}) == 100
    assert len({row["problem_id"] for row in pilot}) == 41
    assert len({row["mechanism_id"] for row in pilot}) == 9
    assert Counter(row["track_gt"] for row in pilot) == {"A1": 38, "A2": 24, "B": 38}

    configurations = {
        "c_naive_hits": "Hit symptom",
        "c_naive_work": "Work symptom",
        "c_inter_only": "Inter-scope slice",
        "c_unpruned": "Unpruned two-tier slice",
        "c_pruned": "Pruned two-tier slice",
    }
    expected_rows = []
    for key, label in configurations.items():
        candidates = [row["slicing"][key] for row in pilot]
        for row, nodes in zip(pilot, candidates, strict=True):
            universe = {f"N{i}" for i in range(1, row["v_slow"] + 1)}
            assert row["v_slow"] == row["slicing"]["v_total"]
            assert row["gt_node"] in universe and len(nodes) == len(set(nodes)) and set(nodes) <= universe
        recall = 100 * mean(row["gt_node"] in nodes for row, nodes in zip(pilot, candidates, strict=True))
        reduction = 100 * mean(1 - len(nodes) / row["v_slow"]
                               for row, nodes in zip(pilot, candidates, strict=True))
        expected_rows.append([label, f"{recall:.0f}", f"{mean(map(len, candidates)):.2f}", f"{reduction:.1f}"])

    actual_rows = published_rows("evaluation.tex", "tab:eapg-pilot-slicing")
    assert actual_rows == expected_rows, (actual_rows, expected_rows)

    hits = [row for row in pilot if row["slicing"]["c_naive_hits"]]
    work = [row for row in pilot if row["slicing"]["c_naive_work"]]
    assert (len(hits), len(work)) == (80, 100)
    added = Counter(row["mechanism_id"] for row in work if not row["slicing"]["c_naive_hits"])
    assert added == {"A1.2": 9, "A1.3": 11}
    work_matches = Counter(row["track_gt"] for row in work if row["gt_node"] in row["slicing"]["c_naive_work"])
    assert work_matches == {"A1": 20, "A2": 24, "B": 38}
    print("Verified all five slicing table rows and symptom coverage on the 100 archived pairs.")


def verify_grouped_diagnostics(pilot, report):
    predictions = report["predictions"]
    split = report["split"]["pairs"]
    assert predictions.keys() == split.keys() == {row["pair_id"] for row in pilot}

    mechanism_folds = defaultdict(set)
    off_symptom = []
    for row in pilot:
        pair_id = row["pair_id"]
        pred = predictions[pair_id]
        reference, candidates = row["gt_node"], row["slicing"]["c_pruned"]
        assert (pred["reference"], pred["candidates"]) == (reference, candidates)
        assert reference in candidates
        assert split[pair_id]["mechanism"] == row["mechanism_id"]
        assert pred["fold"] == split[pair_id]["fold"]
        mechanism_folds[row["mechanism_id"]].add(pred["fold"])
        if reference not in row["slicing"]["c_naive_work"]:
            off_symptom.append(pred)

    scores = [sum(pred[method][0] == pred["reference"] for pred in off_symptom)
              for method in ("adapted", "symbolic", "candidates")]
    assert (len(off_symptom), scores) == (18, [11, 14, 7])
    concentrated = sum(len(folds) == 1 for folds in mechanism_folds.values())
    assert (concentrated, len(mechanism_folds)) == (8, 9)
    print("Verified off-symptom Top-1 on 18 pairs: 11 adapted, 14 symbolic, 7 raw slice order.")
    print("Verified that 8 of 9 mechanisms occur in one refit fold each.")


def verify_ranking_table(pilot, refit):
    archived = verified_json(PILOT / "node_only_ablation/evaluation_results.json")
    owners = {problem: group for group, problems in enumerate(archived["template_groups"]) for problem in problems}
    expected_frozen = {}
    for cohort in ("All", "Multi-candidate"):
        grouped = defaultdict(list)
        for row in pilot:
            if cohort == "Multi-candidate" and len(row["slicing"]["c_pruned"]) < 2:
                continue
            entry, ref = archived["per_pair_predictions"][row["pair_id"]], row["gt_node"]
            assert entry["gt_node"] == ref
            predicted = [entry["variants"][arm]["pred_top1"] for arm in ("6b-slice", "2")]
            grouped[owners[row["problem_id"]]].append([p == ref for p in predicted])
        total = sum(map(len, grouped.values()))
        row_cells = [str(len(grouped))]
        for index in range(2):
            hits = [[item[index] for item in rows] for rows in grouped.values()]
            macro = 100 * mean(map(mean, hits))
            row_cells.append(f"{sum(map(sum, hits))}/{total} ({macro:.2f}%)")
        expected_frozen[cohort] = row_cells
    assert expected_frozen == {
        "All": ["23", "98/100 (93.48%)", "96/100 (95.65%)"],
        "Multi-candidate": ["15", "64/66 (90.00%)", "62/66 (93.33%)"],
    }, expected_frozen

    from replay_resplit_ablation import DEFAULT_ARTIFACT, format_ablation_rows, verify_ablation_report, verified_pipeline
    ablation = json.loads(DEFAULT_ARTIFACT.read_bytes())
    pilot_map = {row["pair_id"]: row for row in pilot}
    pipeline = verified_pipeline()
    recomputed, baselines = verify_ablation_report(ablation, pilot_map, refit, pipeline)
    expected_rows = format_ablation_rows(recomputed, baselines, ablation["max_tokens_by_repr"])
    assert published_rows("evaluation.tex", "tab:eapg-resplit-ablation") == expected_rows
    print("Verified frozen 23-group sensitivity counts and all 10 rows of tab:eapg-resplit-ablation.")


def verify_scalar_intake():
    report = json.loads((ROOT / "development/scalar_intake_feasibility.json").read_bytes())
    assert report["schema"] == "eapg-dev-scalar-intake-feasibility-v2"
    assert report["funnel"] == {
        "oeis_groups_covered": 10,
        "proposed_specs": 11,
        "semantic_or_single_stmt_rejected": 4,
        "domain_or_mapping_rejected": 0,
        "growth_band_failed": 2,
        "eligible_static_and_analytic": 5,
        "eligible_distinct_oeis_groups": 5,
        "eligible_distinct_mechanisms": 4,
        "scoped_top1_on_eligible": 3,
        "conventional_top1_on_eligible": 0,
        "scoped_retained_on_eligible": 4,
        "conventional_retained_on_eligible": 5,
    }
    print("Verified the 10-group OEIS scalar intake funnel (5 eligible, 4 mechanisms, 3/5 scoped vs 0/5 conv Top-1).")


def verify_library_table():
    records, checks = replay_library(EVIDENCE / "lock.json", EVIDENCE / "results.json")
    labels = {"first": "First", "sqrt": "Square root", "midpoint": "Midpoint", "last": "Last",
              "absent": "Absent", "present": "Present", "full": "Full range"}
    table, previous = [], None
    assert len(records) == 24 and checks == 480
    for (opt, operation, condition), (fits, _, _, _, _, ratio) in records.items():
        if opt == "-O2":
            table.append([rf"\texttt{{{operation}}}" if operation != previous else "", labels[condition],
                          f"{fits['operations']:.3f}", f"{ratio:.2f}"])
            previous = operation
    assert published_rows("weighted.tex", "tab:library-calibration") == table
    print("Verified all eight library-calibration table rows from counts and proxy weights.")


def verify_pilot_outputs(pilot):
    report = json.loads((ROOT / "development/pilot_output_agreement.json").read_bytes())
    assert report["schema"] == "eapg-pilot-output-agreement-v1"
    assert report["pilot_sha256"] == sha256((PILOT / "pilot100_results.json").read_bytes()).hexdigest()
    assert report["provenance"]["replay_sha256"] == sha256((ROOT / "development/replay_pilot_outputs.py").read_bytes()).hexdigest()
    assert report["provenance"]["flags"] == ["-std=c++17", "-O2"]
    common, extra = [16, 24], [1, 2, 3, 8, 32, 64]
    assert (report["common_sizes"], report["loop_bound_extra_sizes"]) == (common, extra)
    checks = 0
    for frozen, pair in zip(pilot, report["pairs"], strict=True):
        assert (frozen["pair_id"], frozen["mechanism_id"]) == (pair["pair_id"], pair["mechanism_id"])
        for side in ("slow", "fast"):
            assert pair["builds"][side]["source_sha256"] == sha256(frozen[f"{side}_code"].encode()).hexdigest()
        assert [row["n"] for row in pair["runs"]] == sorted(common + (extra if pair["mechanism_id"] == "A1.4" else []))
        for row in pair["runs"]:
            signatures = [(row[side]["status"], row[side]["returncode"], bytes.fromhex(row[side]["stdout_hex"]))
                          for side in ("slow", "fast")]
            assert signatures[0] == signatures[1] and signatures[0][:2] == ("CLEAN_COMPLETION", 0)
            checks += 1
    assert checks == report["comparison_count"] == 236
    print("Verified all 236 archived-pilot stdout pairs against the fresh uninstrumented replay.")


def verify_validation_timing():
    report = json.loads((ROOT / "development/runtime_validation_timing.json").read_bytes())
    protocol, samples = report["protocol"], report["samples"]
    assert (protocol["min_ratio_slope"], protocol["min_largest_size_ratio"]) == (0.50, 1.50)
    expected_grid = {(seed, 2**exponent, side, repeat) for seed in (42, 43, 44)
                     for exponent in range(7, 13) for side in ("slow", "fast") for repeat in range(1, 6)}
    assert len(samples) == len(expected_grid) == 180
    assert {(r["seed"], r["n"], r["side"], r["repeat"]) for r in samples} == expected_grid
    assert all(r["oracle"] == "passed" and r["returncode"] == 0
               and r["elapsed_ns"] >= protocol["min_clock_steps"] * r["clock_step_ns"] > 0 for r in samples)

    replay = summarize_timing(samples)
    assert replay.keys() == report["per_seed"].keys()
    for seed, summary in replay.items():
        saved = report["per_seed"][seed]
        assert isclose(summary["ratio_slope"], saved["ratio_slope"], abs_tol=1e-12, rel_tol=0)
        assert dict(summary, ratio_slope=saved["ratio_slope"]) == saved
        assert not summary["timing_screen_pass"]
    values = [(f"{row['largest_size_ratio']:.2f}", f"{row['ratio_slope']:.3f}") for row in replay.values()]
    assert values == [("11.21", "0.398"), ("13.77", "0.452"), ("12.74", "0.439")]
    assert report["timing_screen_pass"] is False
    print("Replayed 180 archived timing observations. All three seeds missed the 0.50 slope threshold.")


def verify_comparator_swap():
    report = json.loads((ROOT / "development/comparator_swap_results.json").read_bytes())
    assert report["schema"] == "eapg-authored-comparator-swap-v1"
    for name in ("backward_slice.py", "probe_comparator_swap.py", "synthetic_arms.py"):
        assert sha256((ROOT / "development" / name).read_bytes()).hexdigest() == report["code_sha256"][name], name

    seeds, sizes = (42, 43, 44), (8, 16, 32, 64, 128, 256)
    grid = [{"n": n, "seed": seed, "stdin": f"{n}\n", "expected_stdout": f"{n * (n + 1) // 2}\n"}
            for seed in seeds for n in sizes]
    grid_bytes = (json.dumps(grid, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    assert report["grid"] == grid and sha256(grid_bytes).hexdigest() == report["workload_sha256"]
    counts = {"evaluated": [], "linear_comparator": [], "quadratic_comparator": []}
    for row in grid:
        n = row["n"]
        counts["evaluated"].append(8 + 5 * n + n * (n + 1))
        counts["linear_comparator"].append(8 + 7 * n)
        counts["quadratic_comparator"].append(8 + 5 * n + n * (n - 1))
    assert report["operation_counts"] == counts

    positive, sham = "linear_comparator", "quadratic_comparator"
    predictions = report["predictions"]
    assert predictions[positive] == predictions[sham]
    assert [row["seed"] for row in predictions[positive]] == list(seeds)
    for row in predictions[positive]:
        assert set(row["arms"]) == set(ARM_IDS)
        alert = row["arms"]["work_symptom"]
        assert alert["alert"] is True and alert["symptom_id"] == "N5"

    for index, seed in enumerate(seeds):
        start = index * len(sizes)
        end = start + len(sizes)
        for actual, expected in zip(report["evaluated_profiles"][str(seed)], grid[start:end], strict=True):
            assert (actual["n"], actual["status"], actual["returncode"], actual["stdout"]) == (
                expected["n"], "CLEAN_COMPLETION", 0, expected["expected_stdout"])
        for name in (positive, sham):
            ratios = [a / b for a, b in zip(counts["evaluated"][start:end], counts[name][start:end], strict=True)]
            slope = linear_regression(list(map(log, sizes)), list(map(log, ratios))).slope
            saved = report["comparisons"][name][str(seed)]
            assert isclose(slope, saved["slope"], abs_tol=1e-12, rel_tol=0) and ratios[-1] == saved["largest_ratio"]
            if name == positive:
                assert saved["disposition"] == "confirmed_positive" and slope >= 0.70 and ratios[-1] >= 1.50
                assert (f"{slope:.3f}", f"{ratios[-1]:.3f}") == ("0.870", "37.267")
            else:
                assert saved["disposition"] == "confirmed_sham" and abs(slope) <= 0.10
                assert (f"{slope:.3f}", f"{ratios[-1]:.3f}") == ("-0.039", "1.008")
    print("Replayed 54 archived comparator-swap counts and all seven paired prediction arms.")


def verify_transitive_edit():
    report = json.loads((ROOT / "development/transitive_edit_results.json").read_bytes())
    assert report["schema"] == "eapg-authored-transitive-edit-v1"
    for name, expected in report["software_sha256"].items():
        assert sha256((ROOT / "development" / name).read_bytes()).hexdigest() == expected
    assert report["reference"]["accepted_node_ids"] == ["N7"]
    evidence = report["counted"]
    assert evidence["disposition"] == "confirmed_positive" and evidence["failures"] == []
    seeds, sizes = (42, 43, 44), (8, 16, 32, 64, 128, 256)
    versions, stages = ("original", "edited", "restored"), ("plain", "sanitizer", "counting")
    coordinates = {(seed, n, side, stage) for seed in seeds for n in sizes for side in versions for stage in stages}
    assert len(evidence["builds"]) == 9 and all(row["status"] == "CLEAN_COMPLETION" for row in evidence["builds"])
    assert len(evidence["runs"]) == len(coordinates) == 162
    assert {(row["seed"], row["n"], row["side"], row["stage"]) for row in evidence["runs"]} == coordinates
    for row in evidence["runs"]:
        n = row["n"]
        expected = f"{n * (n + 1) // 2}\n".encode()
        if row["stage"] == "counting":
            count = 10 + 7 * n + 2 * n * (n + 1) if row["side"] == "edited" else 10 + 11 * n
            assert row["observed_count"] == row["expected_count"] == count
            expected += f"\nEAPG-OPERATIONS-v1 {count}\n".encode()
        assert row["verification_status"] == "passed" and b64decode(row["stdout_b64"], validate=True) == expected
    for seed, prediction in zip(seeds, report["predictions"], strict=True):
        ratios = [(10 + 7 * n + 2 * n * (n + 1)) / (10 + 11 * n) for n in sizes]
        slope = linear_regression(list(map(log, sizes)), list(map(log, ratios))).slope
        fit = evidence["per_seed"][str(seed)]
        assert isclose(slope, fit["slope"], rel_tol=0, abs_tol=1e-12) and ratios[-1] == fit["largest_size_ratio"]
        assert (f"{slope:.3f}", f"{ratios[-1]:.3f}") == ("0.899", "47.200")
        assert prediction["seed"] == seed and set(prediction["arms"]) == set(ARM_IDS)
        scoped, conventional = (prediction["arms"][name] for name in ("work_scoped", "work_conventional"))
        assert scoped["symptom_id"] == conventional["symptom_id"] == "N10"
        assert len(scoped["candidates"]) == 2 and "N7" not in scoped["candidates"]
        assert len(conventional["candidates"]) == 7 and conventional["ranking"][1] == "N7"
    print("Replayed 162 transitive-edit program outputs from nine builds and the reported slice retention failure.")


def verify_scope_boundary():
    path = ROOT / "development/scope_boundary_results.json"
    raw = path.read_bytes()
    assert sha256(raw).hexdigest() == "3ef5a388b2041097ad3fe2f768a2ca09b1d1537c2d4d7ffbc52bf7780d7d27c7"
    report = json.loads(raw)
    assert report["schema"] == "eapg-authored-scope-boundary-v1" and report["profile_type"] == "analytic"
    for name, expected in report["software_sha256"].items():
        assert sha256((ROOT / "development" / name).read_bytes()).hexdigest() == expected
    grid = [(d, k) for d in (0, 1, 2, 4) for k in (0, 2, 8)]
    assert [(cell["depth"], cell["overwritten_writes"]) for cell in report["cells"]] == grid
    assert report["sizes"] == [16, 32, 64, 128, 256, 512]
    for cell, (d, k) in zip(report["cells"], grid, strict=True):
        arms = cell["prediction"]["arms"]
        scoped, conventional = arms["work_scoped"], arms["work_conventional"]
        assert scoped["symptom_id"] == conventional["symptom_id"]
        assert len(scoped["candidates"]) == k + 2 and len(conventional["candidates"]) == d + 6
        assert len(set(scoped["candidates"]) - set(conventional["candidates"])) == k
        reference = cell["reference"]
        assert (reference in scoped["candidates"]) == (d == 0) and reference in conventional["candidates"]
        visits = [row["nodes"][scoped["symptom_id"]]["cnt"] for row in cell["analytic_runs"]]
        assert visits == [n * (n + 1) // 2 for n in report["sizes"]]
    print("Verified 12 analytic scope-boundary cells, both candidate counts, and edit retention.")


def verify_uoj_header_bound():
    raw = (ROOT / "development/uoj_source_availability.json").read_bytes()
    assert sha256(raw).hexdigest() == "ab1262194cf52b7e1dde077316751b874ebec06091031c631dd26fc6610d181f"
    report = json.loads(raw)
    assert report["official_revision"] == "ce1c006d9f6cf57670d15e62c3e63a08ea669adb"
    for track, published, surviving, problems in (("easy", 500, 9, 8), ("hard", 214, 2, 2), ("pooled", 714, 11, 10)):
        cpp = report["tracks"][track]["cpp_family"]
        assert cpp["published"]["pair_rows"] == published
        assert cpp["evaluated_has_unsupported_literal_header"]["pair_rows"] == published - surviving
        assert cpp["both_without_observed_unsupported_literal_header"] == {
            "pair_rows": surviving, "distinct_problem_ids": problems}
    cpp17 = report["tracks"]["pooled"]["explicit_cpp17"]
    assert cpp17["published"] == {"pair_rows": 41, "distinct_problem_ids": 38}
    assert cpp17["evaluated_has_unsupported_literal_header"] == cpp17["published"]
    print("Verified the pinned aggregate UOJ header bound of 11 C++-family pairs across 10 problems.")


def verify_feasibility_table():
    rows = published_rows("evaluation.tex", "tab:dev-feasibility")
    assert len(rows) == 8
    assert rows[0][0] == "UOJ raw-AST audit" and "0/714" in rows[0][2] and "11 header-clean" in rows[0][2]
    assert rows[1][0] == "OEIS scalar intake" and "5 eligible" in rows[1][2] and "3/5" in rows[1][2] and "0/5" in rows[1][2]
    assert rows[2][0] == r"PIE pair \texttt{p03497}" and "2.00" in rows[2][2] and "0.50" in rows[2][2]
    assert rows[3][0] == "Cursor reset" and r"\texttt{N5}" in rows[3][2] and "1/2" in rows[3][2] and "2/5" in rows[3][2]
    assert rows[4][0] == "Comparator swap" and "0.870" in rows[4][2] and "-0.039" in rows[4][2]
    assert rows[5][0] == "Transitive edit" and "0.899" in rows[5][2] and "2/7" in rows[5][2]
    assert rows[6][0] == r"Scope grid ($d\times k$)" and "$d=0$" in rows[6][2]
    assert rows[7][0] == "Custody / contract" and "966" in rows[7][2]
    print("Verified all 8 summary rows of tab:dev-feasibility.")


def verify_prospective_multiagent():
    raw = (ROOT / "development/prospective_multiagent_results.json").read_bytes()
    assert sha256(raw).hexdigest() == "2016611a8d142b0068b5e5c03ed9f685a0196c6159510b808ca2135c7928cf81"
    report = json.loads(raw)
    assert report["schema"] == "eapg-prospective-multiagent-study-v1"
    assert report["execution_environment"]["gate1_probes"] == {
        "probe_boundaries": "passed",
        "probe_private_scratch": "passed",
        "probe_resource_limits": "passed",
        "probe_cleanup": "passed",
    }
    pa = report["part_a_prospective_scalar"]
    pb = report["part_b_blinded_adjudication"]
    assert pa["cross_os_part_a_exact_match"] is True
    assert pa["ledger_hashes"]["score"] == pa["windows_cross_os_ledger_hashes"]["score"] == "ce049b3262f536599d9c332c6a8558fd0073bd94df8f37692e901f25fab6f4b9"
    assert pa["ledger_hashes"]["frame"] == pa["windows_cross_os_ledger_hashes"]["frame"] == "79fe894baef6915f75b0cf0cb96c3f1ddacf1bafa32cbd22d24832e3913827ef"
    assert pa["execution_counts"]["active_families"] == 10
    assert pa["execution_counts"]["active_slots"] == 42
    assert pa["execution_counts"]["quarantined_slots"] == 280
    assert pa["execution_counts"]["real_exposure_collisions"] == 0
    assert pa["execution_counts"]["active_pilot_template_overlap"] == 0
    assert pa["execution_counts"]["oracle_builds"] == 378
    assert pa["execution_counts"]["oracle_runs"] == 6804
    assert pa["execution_counts"]["profile_runs"] == 738
    assert pb["cross_os_stress_exact_match"] is True

    s42 = pa["score_summary"]["by_seed"]["42"]["primary"]
    ws, wc, sym = (s42["arms"][k] for k in ("work_scoped", "work_conventional", "work_scoped_symbolic"))
    gpu = pa["neural_live_slice_eval"]
    ret_core = ws["retention"]["count"]
    f0_pos = pb["score_fold0"]["D_pos"]
    oof_pos = pb["score_strict_oof"]["D_pos"]
    oof_rank = pb["score_strict_oof"]["D_rank"]
    unb_pos = pb["score_unbiased_symbolic"]["D_pos"]
    unb_rank = pb["score_unbiased_symbolic"]["D_rank"]

    def cell(obj):
        return f"{obj['count']}/{obj['total']} ({100 * obj['family_macro_rate']:.2f})"

    def gcell(obj):
        return f"{obj['count']}/{obj['total']} ({100 * obj['group_macro_rate']:.2f})"

    def gpucore(entry):
        c = entry["core_20"]
        return f"{c['hits']}/{c['cases']} ({100 * c['family_macro_rate']:.2f})"

    expected_rows = [
        ["A (20 core)", r"\texttt{work\_scoped} (\texttt{def\_use=F})", f"{ret_core}/20", cell(ws["top1"])],
        ["A (20 core)", r"\texttt{work\_conventional} (\texttt{def\_use=F})", f"{wc['retention']['count']}/{wc['retention']['total']}", cell(wc["top1"])],
        ["A (20 core)", r"\texttt{work\_scoped\_symbolic} (\texttt{def\_use=T})", f"{sym['retention']['count']}/{sym['retention']['total']}", cell(sym["top1"])],
        ["A (20 core)", r"Base (\texttt{abstract\_graph}, Con.)", f"{ret_core}/20", gpucore(gpu["base_abstract_graph_constrained"])],
        ["A (20 core)", r"QLoRA (\texttt{abstract\_graph}, Unc.)", "20/20", gpucore(gpu["qlora_abstract_graph_fold0_unconstrained"])],
        ["A (20 core)", r"QLoRA (\texttt{abstract\_graph}, Con.)", f"{ret_core}/20", gpucore(gpu["qlora_abstract_graph_fold0_constrained"])],
        ["A (20 core)", r"QLoRA (\texttt{hotspot\_raw}, Con.)", f"{ret_core}/20", gpucore(gpu["qlora_hotspot_raw_fold0_constrained"])],
        [r"B ($D_{\mathrm{pos}}$)", r"Unbiased \texttt{symbolic} (\texttt{def\_use=F})", f"{unb_pos['slice_recall']['count']}/14", gcell(unb_pos["symbolic"]["top1"])],
        [r"B ($D_{\mathrm{pos}}$)", r"Refined \texttt{symbolic} (\texttt{def\_use=T})", f"{oof_pos['slice_recall']['count']}/14", gcell(oof_pos["symbolic"]["top1"])],
        [r"B ($D_{\mathrm{pos}}$)", r"Fold-0 \texttt{abstract\_graph} (in-fold)", f"{f0_pos['slice_recall']['count']}/14", gcell(f0_pos["abstract"]["top1"])],
        [r"B ($D_{\mathrm{pos}}$)", r"Strict OOF \texttt{abstract\_graph}", f"{oof_pos['slice_recall']['count']}/14", gcell(oof_pos["abstract"]["top1"])],
        [r"B ($D_{\mathrm{rank}}$)", r"Unbiased \texttt{symbolic} (\texttt{def\_use=F})", f"{unb_rank['slice_recall']['count']}/10", gcell(unb_rank["symbolic"]["top1"])],
        [r"B ($D_{\mathrm{rank}}$)", r"Refined \texttt{symbolic} (\texttt{def\_use=T})", f"{oof_rank['slice_recall']['count']}/10", gcell(oof_rank["symbolic"]["top1"])],
        [r"B ($D_{\mathrm{rank}}$)", r"Strict OOF \texttt{abstract\_graph}", f"{oof_rank['slice_recall']['count']}/10", gcell(oof_rank["abstract"]["top1"])],
    ]
    assert published_rows("evaluation.tex", "tab:prospective-multiagent") == expected_rows
    print("Verified all 14 rows of tab:prospective-multiagent across Parts A and B.")


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    if not __debug__:
        raise RuntimeError("Run without Python optimization so assertions remain active")
    pilot = verified_json(PILOT / "pilot100_results.json")
    refit = json.loads((ROOT / "artifacts/pilot_resplit/results.json").read_bytes())
    verify_candidate_selection(pilot)
    verify_grouped_diagnostics(pilot, refit)
    verify_ranking_table(pilot, refit)
    verify_library_table()
    verify_pilot_outputs(pilot)
    verify_validation_timing()
    verify_comparator_swap()
    verify_transitive_edit()
    verify_scope_boundary()
    verify_uoj_header_bound()
    verify_scalar_intake()
    verify_feasibility_table()
    verify_prospective_multiagent()


if __name__ == "__main__":
    main()
