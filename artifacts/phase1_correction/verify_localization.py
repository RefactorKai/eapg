"""Verify the frozen localization evidence and reproduce the corrected Table IV."""

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PILOT = ROOT / "artifacts/scope_isolated_pilot"
RUN = PILOT / "node_only_ablation"
AUDIT = HERE.parent / "board_of_audit_professors.md"
TOKENIZER_REVISION = "df3ce67c0e24480f20468b6ef2894622d69eb73b"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def verify_snapshot():
    rows = [
        line.split(chr(96))[1::2]
        for line in AUDIT.read_text(encoding="utf-8").splitlines()
        if line.startswith("| " + chr(96))
    ]
    if len(rows) != 6:
        raise ValueError("Expected six frozen artifact hashes in the audit report")
    for name, digest in rows:
        if sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Frozen artifact hash mismatch for {name}")


def corrected_table(frozen_table):
    return (
        frozen_table.replace("Raw-Code SLM", "AST Preview SLM")
        .replace("Hotspot-Guided SLM", "Hit-Annotated Preview")
        .replace("Static EAPG", "Static AST Features")
        .replace("Deterministic PDG Slice", "Deterministic Slice Ranker")
        .replace("Naive Profiler", "Work Symptom")
        .replace("52.6 & 100.0 & 0.0 & 72.7", "52.6 & 100.0 & -- & 72.7")
        .replace(
            "Variants 6a and 7a score all nodes.",
            r"Variants 6a and 7a receive slice tags and score all nodes.",
        )
        .replace(
            "Metrics are percentages.",
            r"$R_{\text{search}}$ reports reduction from explicit slice restriction. "
            "The work-symptom row emits a single candidate directly. Metrics are percentages.",
        )
    )


def verify_prompts(records, evaluation):
    from transformers import AutoTokenizer

    sys.path.insert(0, str(ROOT))
    from pipeline import _nid_to_code, build_variant_prompt_and_cands, split_pilot_templates

    tokenizer = AutoTokenizer.from_pretrained(
        "Qwen/Qwen2.5-Coder-1.5B", revision=TOKENIZER_REVISION, local_files_only=True,
    )
    modes = [
        ("raw_code", None), ("hotspot_raw", None), ("static_eapg", None),
        ("abstract_graph", "slice"), ("abstract_graph", "rank"),
        ("full_eapg", "slice"), ("full_eapg", "rank"),
    ]
    fingerprints = {}
    longest = 0
    for row in records:
        keys = []
        for kind, tags in modes:
            prompt, _, candidates = build_variant_prompt_and_cands(row, kind, tag_mode=tags, node_only=True)
            assert candidates == row["slicing"]["c_pruned"]
            ids = tokenizer.encode(prompt, add_special_tokens=False)
            target = _nid_to_code(row["gt_node"])
            with_target = tokenizer.encode(f"{prompt} {target}", add_special_tokens=False)
            assert with_target[:-1] == ids and len(with_target) == len(ids) + 1
            longest = max(longest, len(with_target))
            keys.append(sha256(json.dumps(ids).encode("utf-8")).hexdigest())
        fingerprints[row["pair_id"]] = keys
    _, source_groups = split_pilot_templates(records)
    assert len(source_groups) == evaluation["source_template_group_count"] == 29
    folds, groups = split_pilot_templates(records, prompt_fingerprints=fingerprints)
    assert [list(group) for group in groups] == evaluation["template_groups"]
    assert {f"fold_{i}": sorted(fold) for i, fold in enumerate(folds)} == evaluation["folds"]
    assert longest == 498
    print(f"Replayed {len(records) * len(modes)} prompts, five folds and a {longest}-token maximum.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-table", action="store_true", help="Regenerate the corrected LaTeX table")
    parser.add_argument("--verify-prompts", action="store_true", help="Rebuild folds with the local pinned tokenizer")
    args = parser.parse_args()
    verify_snapshot()
    pilot = {row["pair_id"]: row for row in load(PILOT / "pilot100_results.json")}
    evaluation = load(RUN / "evaluation_results.json")
    predictions = evaluation["per_pair_predictions"]
    folds = {pid: i for i in range(5) for pid in evaluation["folds"][f"fold_{i}"]}
    groups = evaluation["template_groups"]
    slices = {pid: row["slicing"]["c_pruned"] for pid, row in pilot.items()}
    multi = {pid for pid, nodes in slices.items() if len(nodes) >= 2}
    assert len(pilot) == 100 and set(pilot) == set(predictions)
    assert evaluation["pilot_sha256"] == sha256((PILOT / "pilot100_results.json").read_bytes()).hexdigest()
    assert len(multi) == 66 and multi == set(evaluation["multi_candidate_pair_ids"])
    assert all(row["gt_node"] in slices[pid] for pid, row in pilot.items())
    assert Counter(folds[row["problem_id"]] for row in pilot.values()) == {i: 20 for i in range(5)}
    assert len(groups) == 23 and sorted(pid for group in groups for pid in group) == sorted(folds)
    assert all(len({folds[pid] for pid in group}) == 1 for group in groups)
    assert evaluation["hyperparameters"]["target_tokens"] == 1
    if args.verify_prompts:
        verify_prompts(list(pilot.values()), evaluation)
    a1 = {pid for pid, row in pilot.items() if row["track_gt"] == "A1"}
    a2 = {pid for pid, row in pilot.items() if row["track_gt"] == "A2"}
    resets = {pid for pid, row in pilot.items() if row["mechanism_id"] in ("A1.1", "A1.4")}
    reduction = round(100 * sum(1 - len(slices[pid]) / row["v_slow"] for pid, row in pilot.items()) / len(pilot), 1)

    table = (RUN / "table_ablation.tex").read_text(encoding="utf-8")
    rows = [line.removesuffix(r" \\").split(" & ") for line in table.splitlines()]
    frozen_cells = {row[0]: row[3:] for row in rows if row[0] in evaluation["variants"]}
    for variant, summary in evaluation["variants"].items():
        top1 = set()
        top2 = 0
        for pid, row in pilot.items():
            logged = predictions[pid]
            assert logged["gt_node"] == row["gt_node"] and logged["paradigm_gt"] is None
            result = logged["variants"][variant]
            assert result["pred_paradigm"] is None
            if "candidate_logits" in result:
                scores = result["candidate_logits"]
                candidates = slices[pid] if result["decoding_mode"] == "slice_constrained" else [
                    f"N{i}" for i in range(1, row["v_slow"] + 1)
                ]
                assert set(candidates) == set(scores)
                assert sorted(candidates, key=scores.get, reverse=True)[:2] == result["pred_top2"]
                assert result["fold"] == folds[row["problem_id"]]
                assert result["max_prompt_tokens"] <= evaluation["hyperparameters"]["max_seq_len_cap"]
            assert result["pred_top1"] == result["pred_top2"][0]
            if result["pred_top1"] == row["gt_node"]:
                top1.add(pid)
            top2 += row["gt_node"] in result["pred_top2"]

        def subset_top1(subset):
            return round(100 * len(top1 & subset) / len(subset), 1)

        metrics = {
            "top1": len(top1),
            "top2": top2,
            "reset_top1": subset_top1(resets),
            "a1_top1": subset_top1(a1),
            "a2_top1": subset_top1(a2),
            "multi_top1": subset_top1(multi),
        }
        assert all(summary[key] == value for key, value in metrics.items()), variant
        assert summary["r_search"] == (reduction if variant == "2" or variant.startswith(("6b-", "7b-")) else 0)
        cells = [metrics[key] for key in ("top1", "top2", "reset_top1", "a1_top1", "a2_top1")]
        cells.extend([summary["r_search"], metrics["multi_top1"]])
        assert frozen_cells[variant] == [f"{value:.1f}" for value in cells], variant
        if variant in ("2", "6b-slice"):
            counts = []
            for group in groups:
                members = {pid for pid, row in pilot.items() if row["problem_id"] in group}
                counts.append(len(top1 & members) / len(members))
            print(f"{variant} group-macro Top-1: {100 * sum(counts) / len(counts):.2f}%")
        if variant in ("3b", "4", "5"):
            correct = set()
            for pid, row in pilot.items():
                scores = predictions[pid]["variants"][variant]["candidate_logits"]
                if max(slices[pid], key=scores.get) == row["gt_node"]:
                    correct.add(pid)
            print(f"{variant} masked-logit Top-1: {len(correct)}/100 overall, {len(correct & multi)}/66 multi")

    rendered = corrected_table(table)
    destination = HERE / "table_ablation.tex"
    if args.write_table:
        destination.write_text(rendered, encoding="utf-8")
    assert destination.read_text(encoding="utf-8") == rendered
    print(f"Verified {len(evaluation['variants'])} rows and {len(pilot)} pairs against frozen evidence.")


if __name__ == "__main__":
    main()
