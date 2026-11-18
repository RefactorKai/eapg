"""CPU replay and verification for the 6-representation 13-group ablation matrix."""

import argparse
import ast
from collections import defaultdict
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path
import re
from types import SimpleNamespace
from typing import Dict, List, Set

from replay_pilot_contrast import PILOT, ROOT, verified_json
from train_resplit_ablation import REPRESENTATIONS, summarize_matrix


DEFAULT_ARTIFACT = ROOT / "artifacts/pilot_resplit/ablation_results.json"


def verified_pipeline():
    manifest = dict(line.split("  ", 1)[::-1] for line in (ROOT / "SHA256SUMS").read_text().splitlines())
    raw = (ROOT / "pipeline.py").read_bytes()
    if sha256(raw).hexdigest() != manifest["pipeline.py"]:
        raise ValueError("Frozen pipeline.py SHA-256 mismatch")
    try:
        from run_phase2_development import load_module
        return load_module("replay_ablation_pipeline", ROOT / "pipeline.py", manifest["pipeline.py"])
    except ImportError:
        # Pure-stdlib subset from verified pipeline.py for `python -S` / Windows CI without tree-sitter.
        source = raw.decode("utf-8").replace("\r\n", "\n")
        wanted = {"parse_skeleton_nodes", "rank_candidates_by_role_priority"}
        segments = []
        for node in ast.parse(source).body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                if getattr(node.targets[0], "id", None) == "PILOT_REVISION":
                    segments.append(ast.get_source_segment(source, node))
            elif isinstance(node, ast.FunctionDef) and node.name in wanted:
                segments.append(ast.get_source_segment(source, node))
        ns = {"re": re, "Dict": Dict, "List": List, "Set": Set}
        exec(compile("\n\n".join(segments), str(ROOT / "pipeline.py"), "exec"), ns)
        return SimpleNamespace(**{k: ns[k] for k in wanted | {"PILOT_REVISION"}})


def compute_baselines(pipeline, pilot_rows, split_ledger, published_resplit=None):
    """Compute exact non-neural baseline scores over the strict 13-group split."""
    cohorts = {
        "all": lambda r: True,
        "multi_candidate": lambda r: len(r["slicing"]["c_pruned"]) >= 2,
        "off_symptom": lambda r: r["gt_node"] not in r["slicing"]["c_naive_work"],
        "a1": lambda r: r["track_gt"] == "A1",
        "a2": lambda r: r["track_gt"] == "A2",
        "b": lambda r: r["track_gt"] == "B",
        "reset": lambda r: r["mechanism_id"] in ("A1.1", "A1.4"),
    }

    has_ast = hasattr(pipeline, "extract_macro_nodes") or published_resplit is None
    per_pair = {}
    for pid, row in pilot_rows.items():
        cands = row["slicing"]["c_pruned"]
        sym_default = pipeline.rank_candidates_by_role_priority(row, use_loop_def_use=False)
        if has_ast:
            sym_refined = pipeline.rank_candidates_by_role_priority(row, use_loop_def_use=True)
        else:
            sym_refined = list(published_resplit["predictions"][pid]["symbolic"])
        assert sorted(sym_default) == sorted(cands) and sorted(sym_refined) == sorted(cands)
        per_pair[pid] = {
            "group": split_ledger[pid]["group"],
            "uniform": Fraction(1, len(cands)) if row["gt_node"] in cands else Fraction(0),
            "raw_order": Fraction(1) if cands[0] == row["gt_node"] else Fraction(0),
            "symbolic_default": Fraction(1) if sym_default[0] == row["gt_node"] else Fraction(0),
            "symbolic_refined": Fraction(1) if sym_refined[0] == row["gt_node"] else Fraction(0),
        }

    summary = {}
    for cname, cfn in cohorts.items():
        summary[cname] = {}
        for method in ("uniform", "raw_order", "symbolic_default", "symbolic_refined"):
            grps = defaultdict(list)
            for pid, row in sorted(pilot_rows.items()):
                if cfn(row):
                    grps[per_pair[pid]["group"]].append(per_pair[pid][method])
            pairs = sum(map(len, grps.values()))
            expected_hits = sum(sum(g) for g in grps.values())
            macro = sum(sum(g) / len(g) for g in grps.values()) / len(grps)
            summary[cname][method] = {
                "pairs": pairs,
                "groups": len(grps),
                "expected_hits": float(expected_hits),
                "pair_pct": round(float(100 * expected_hits / pairs), 2),
                "group_pct": round(float(100 * macro), 2),
            }
    return summary, per_pair


def verify_ablation_report(report, pilot_rows, published_resplit, pipeline):
    """Validate every invariant, prediction rank, score, and continuity check on CPU."""
    if report.get("schema") != "eapg-resplit-ablation-v1":
        raise ValueError(f"Unexpected schema: {report.get('schema')}")
    manifest = dict(line.split("  ", 1)[::-1] for line in (ROOT / "SHA256SUMS").read_text().splitlines())
    if report["pilot_sha256"] != manifest["artifacts/scope_isolated_pilot/pilot100_results.json"]:
        raise ValueError("pilot_sha256 mismatch")
    if report["pipeline_sha256"] != manifest["pipeline.py"]:
        raise ValueError("pipeline_sha256 mismatch")

    max_tokens = report["max_tokens_by_repr"]
    max_seq = report["recipe"]["max_sequence"]
    if set(max_tokens) != set(REPRESENTATIONS) or any(not (0 < v <= max_seq) for v in max_tokens.values()):
        raise ValueError(f"Invalid max_tokens_by_repr: {max_tokens}")

    split = report["split"]
    predictions = report["predictions"]
    if split.keys() != pilot_rows.keys() or predictions.keys() != set(REPRESENTATIONS):
        raise ValueError("Missing pairs or representations")

    owners = {}
    fold_sets = defaultdict(set)
    for pid, row in pilot_rows.items():
        meta = split[pid]
        fold = meta["fold"]
        fold_sets[fold].add(pid)
        for key_name in ("problem_id", "group", "prompt_sha256"):
            val = meta[key_name]
            if owners.setdefault((key_name, val), fold) != fold:
                raise ValueError(f"Cross-fold leak on {key_name}={val}")

    if set(fold_sets) != set(range(5)) or any(not fold_sets[f] for f in range(5)):
        raise ValueError("Expected 5 non-empty folds")

    pub_preds = published_resplit["predictions"]
    for repr_kind in REPRESENTATIONS:
        repr_preds = predictions[repr_kind]
        if repr_preds.keys() != pilot_rows.keys():
            raise ValueError(f"Incomplete pairs for {repr_kind}")
        for pid, pred in repr_preds.items():
            row = pilot_rows[pid]
            meta = split[pid]
            if (pred["fold"], pred["group"], pred["reference"], pred["candidates"]) != (
                meta["fold"], meta["group"], row["gt_node"], row["slicing"]["c_pruned"]
            ):
                raise ValueError(f"Metadata mismatch for {repr_kind}/{pid}")
            all_nodes = pred["all_nodes"]
            cands = pred["candidates"]
            for prefix in ("base", "adapted"):
                scores = pred[f"{prefix}_logits"]
                if scores.keys() != set(all_nodes):
                    raise ValueError(f"Logit key mismatch on {repr_kind}/{pid}/{prefix}")
                expected_unc = sorted(all_nodes, key=scores.get, reverse=True)
                expected_con = sorted(cands, key=scores.get, reverse=True)
                if pred[f"{prefix}_unconstrained"] != expected_unc or pred[f"{prefix}_constrained"] != expected_con:
                    raise ValueError(f"Rank sorting mismatch on {repr_kind}/{pid}/{prefix}")
            if repr_kind == "abstract_graph":
                pub = pub_preds[pid]
                if pred["adapted_constrained"] != pub["adapted"] or pred["base_constrained"] != pub["base"]:
                    raise ValueError(f"Continuity mismatch against pilot_resplit on {pid}")

    recomputed = summarize_matrix(predictions, pilot_rows)
    if recomputed != report["scores"]:
        raise ValueError("Recomputed score summary disagrees with saved scores")

    baselines, _ = compute_baselines(pipeline, pilot_rows, split, published_resplit)
    if hasattr(pipeline, "extract_macro_nodes"):
        for pid in split:
            pub = pub_preds[pid]
            sym_ref = pipeline.rank_candidates_by_role_priority(pilot_rows[pid], use_loop_def_use=True)
            if sym_ref != pub["symbolic"]:
                raise ValueError(f"Symbolic continuity mismatch on {pid}")
    return recomputed, baselines


def format_ablation_rows(recomputed, baselines, max_tokens):
    """Build exact deterministic LaTeX table rows for tab:eapg-resplit-ablation."""
    repr_labels = {
        "raw_code": r"\texttt{raw\_code}",
        "hotspot_raw": r"\texttt{hotspot\_raw}",
        "static_eapg": r"\texttt{static\_eapg}",
        "abstract_hits_only": r"\texttt{abstract\_hits\_only}",
        "abstract_graph": r"\texttt{abstract\_graph}",
        "full_eapg": r"\texttt{full\_eapg}",
    }

    def fmt_cell(block):
        return f"{block['top1_hits']}/{block['pairs']} ({block['top1_group_pct']:.2f})"

    def fmt_base_cell(block, *, is_uniform=False):
        hits = f"{block['expected_hits']:.2f}" if is_uniform else f"{int(block['expected_hits'])}"
        return f"{hits}/{block['pairs']} ({block['group_pct']:.2f})"

    rows = []
    for repr_kind in REPRESENTATIONS:
        r = recomputed["by_representation"][repr_kind]
        rows.append([
            repr_labels[repr_kind],
            str(max_tokens[repr_kind]),
            fmt_cell(r["all"]["base_unconstrained"]),
            fmt_cell(r["all"]["base_constrained"]),
            fmt_cell(r["all"]["adapted_unconstrained"]),
            fmt_cell(r["all"]["adapted_constrained"]),
            fmt_cell(r["multi_candidate"]["adapted_constrained"]),
            fmt_cell(r["off_symptom"]["adapted_constrained"]),
        ])
    for key, label in (
        ("uniform", "Uniform guessing"),
        ("raw_order", "Raw slice order"),
        ("symbolic_default", r"Symbolic (\texttt{def\_use=False})"),
        ("symbolic_refined", r"Symbolic (\texttt{def\_use=True})"),
    ):
        is_u = (key == "uniform")
        b = baselines
        rows.append([
            label,
            "--",
            "--",
            "--",
            "--",
            fmt_base_cell(b["all"][key], is_uniform=is_u),
            fmt_base_cell(b["multi_candidate"][key], is_uniform=is_u),
            fmt_base_cell(b["off_symptom"][key], is_uniform=is_u),
        ])
    return rows


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    cli.add_argument("--verify-manuscript-table", action="store_true")
    cli.add_argument("--quiet", action="store_true")
    args = cli.parse_args()
    if not __debug__:
        raise RuntimeError("Run without Python optimization so assertions remain active")

    report = json.loads(args.artifact.read_bytes())
    pilot_rows = {row["pair_id"]: row for row in verified_json(PILOT / "pilot100_results.json")}
    pub_resplit = json.loads((ROOT / "artifacts/pilot_resplit/results.json").read_bytes())
    pipeline = verified_pipeline()
    recomputed, baselines = verify_ablation_report(report, pilot_rows, pub_resplit, pipeline)
    rows = format_ablation_rows(recomputed, baselines, report["max_tokens_by_repr"])

    if args.verify_manuscript_table:
        from verify_manuscript_pilot import published_rows
        actual = published_rows("evaluation.tex", "tab:eapg-resplit-ablation")
        assert actual == rows, (actual, rows)
        print("Verified all 10 manuscript rows of tab:eapg-resplit-ablation against saved ablation logits.")

    if not args.quiet:
        print(json.dumps({
            "max_tokens_by_repr": report["max_tokens_by_repr"],
            "baselines": baselines,
            "by_representation": recomputed["by_representation"],
            "paired_contrasts_adapted_constrained_all": recomputed["paired_contrasts"]["all"]["adapted_constrained"],
            "paired_contrasts_adapted_constrained_multi": recomputed["paired_contrasts"]["multi_candidate"]["adapted_constrained"],
        }, indent=2))


if __name__ == "__main__":
    main()
