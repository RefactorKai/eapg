"""Evaluate all six EAPG prompt representations under the strict 13-group split."""

import argparse
from collections import defaultdict
import gc
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import random
import sys
import time

from replay_pilot_contrast import PILOT, contrast, verified_json
from train_phase2_adapter import (
    MODEL, PILOT_SHA, PIPELINE_SHA, RECIPE, REVISION, digest_json,
    load_inputs, save_result, train,
)
from train_pilot_resplit import prepare_split, write_json


REPRESENTATIONS = (
    "raw_code",
    "hotspot_raw",
    "static_eapg",
    "abstract_hits_only",
    "abstract_graph",
    "full_eapg",
)


def build_prompt(pipeline, row, repr_kind):
    """Build node-only prompt and canonical node/slice lists for any representation."""
    if repr_kind == "abstract_hits_only":
        _, nodes, cands = pipeline.build_variant_prompt_and_cands(
            row, "abstract_graph", tag_mode="slice", node_only=True,
        )
        info = pipeline.parse_skeleton_nodes(row)
        lines = ["Locate bottleneck node."]
        for nid in nodes:
            node = info[nid]
            role = pipeline.ROLE_SHORT_MAP.get(node["role"], "OP")
            defs_cnt = len([x for x in node["defs"].strip("{}").split(",") if x.strip()])
            uses_cnt = len([x for x in node["uses"].strip("{}").split(",") if x.strip()])
            a_hits = pipeline._fmt_exp_1d(node["a_hits"]).removesuffix(".0")
            tag = "SLICE" if nid in cands else ""
            lines.append(f"{pipeline._nid_to_code(nid)} {role} D{defs_cnt}/U{uses_cnt} {a_hits} {tag}".rstrip())
        return "\n".join(lines) + "\nAnswer:", nodes, cands
    tags = "slice" if repr_kind in ("abstract_graph", "full_eapg") else None
    return pipeline.build_variant_prompt_and_cands(row, repr_kind, tag_mode=tags, node_only=True)


def verify_multi_repr_quarantine(pipeline, rows, tokenizer, ledger):
    """Verify that prompt-token hashes for all six representations stay fold-disjoint."""
    from artifacts.phase1_correction.phase2_custody_and_probes import fingerprints, source_key

    archived = verified_json(PILOT / "node_only_ablation/evaluation_results.json")
    old_groups = {pid: i for i, group in enumerate(archived["template_groups"]) for pid in group}
    prompt_hashes = defaultdict(dict)
    keys = {}
    for pid, row in rows.items():
        features = {f"archived:{old_groups[row['problem_id']]}"}
        for side in ("slow_code", "fast_code"):
            source = row[side]
            features.update(fingerprints(source, pilot=True)[0])
            features.add(f"source:{source_key(source)}")
        for repr_kind in REPRESENTATIONS:
            prompt, _, _ = build_prompt(pipeline, row, repr_kind)
            digest = digest_json(tokenizer.encode(prompt, add_special_tokens=False))
            prompt_hashes[repr_kind][pid] = digest
            features.add(f"prompt_{repr_kind}:{digest}")
        keys[pid] = sorted(features)

    folds, _ = pipeline.split_pilot_templates(list(rows.values()), seed=42, prompt_fingerprints=keys)
    prob_fold = {pid: i for i, fold in enumerate(folds) for pid in fold}
    owners = {}
    for pid, row in rows.items():
        fold = prob_fold[row["problem_id"]]
        if fold != ledger[pid]["fold"]:
            raise ValueError(f"Adding representation {pid} changed the strict 13-group split")
        for key in keys[pid]:
            if owners.setdefault(key, fold) != fold:
                raise ValueError(f"Cross-fold leak on key {key} for {pid}")
    return prompt_hashes


def build_repr_examples(pipeline, rows, tokenizer, repr_kind, prompt_hashes):
    """Build tokenized prefix/target items bounded strictly to <= 512 tokens."""
    from string import ascii_uppercase

    labels = {code: tokenizer.encode(" " + code, add_special_tokens=False) for code in ascii_uppercase}
    if any(len(ids) != 1 for ids in labels.values()) or len({tuple(ids) for ids in labels.values()}) != 26:
        raise ValueError("Node codes must have 26 distinct single-token encodings")
    examples = []
    max_tokens = 0
    for pid in sorted(rows):
        row = rows[pid]
        prompt, nodes, candidates = build_prompt(pipeline, row, repr_kind)
        if not 1 <= len(nodes) <= 26 or row["gt_node"] not in nodes:
            raise ValueError(f"Invalid node count or target for {pid} ({repr_kind})")
        prefix = tokenizer.encode(prompt, add_special_tokens=False)
        key = digest_json(prefix)
        if key != prompt_hashes[repr_kind][pid]:
            raise ValueError(f"Prompt hash mismatch for {pid} ({repr_kind})")
        label = pipeline._nid_to_code(row["gt_node"])
        if (label not in labels or not 0 < len(prefix) < RECIPE["max_sequence"]
                or tokenizer.encode(f"{prompt} {label}", add_special_tokens=False) != prefix + labels[label]):
            raise ValueError(f"Token budget or single-token failure for {pid} ({repr_kind})")
        max_tokens = max(max_tokens, len(prefix) + 1)
        examples.append({
            "id": pid,
            "prompt_sha256": key,
            "prefix": prefix,
            "target": labels[label][0],
            "all_nodes": nodes,
            "c_pruned": candidates,
        })
    return examples, max_tokens


def predict_all_nodes(model, examples, pipeline, tokenizer):
    """Score all canonical nodes A..Z in a single forward pass per example."""
    import torch

    token_ids = {chr(65 + i): tokenizer.encode(" " + chr(65 + i), add_special_tokens=False)[0]
                 for i in range(26)}
    ranks = {}
    gc.collect()
    torch.cuda.empty_cache()
    with torch.inference_mode():
        for example in examples:
            pid = example["id"]
            all_nodes = example["all_nodes"]
            input_ids = torch.tensor([example["prefix"]], device="cuda:0")
            logits = model(input_ids=input_ids, use_cache=False, logits_to_keep=1).logits[0, -1]
            indices = [token_ids[pipeline._nid_to_code(node)] for node in all_nodes]
            selected = logits[indices].float()
            if not torch.isfinite(selected).all().item():
                raise ValueError(f"Nonfinite ranking scores for {pid}")
            scores = dict(zip(all_nodes, selected.tolist()))
            c_pruned = example["c_pruned"]
            ranks[pid] = {
                "all_logits": scores,
                "unconstrained": sorted(all_nodes, key=scores.get, reverse=True),
                "constrained": sorted(c_pruned, key=scores.get, reverse=True),
            }
    gc.collect()
    torch.cuda.empty_cache()
    return ranks


def evaluate_existing_abstract_graph(out_dir, snapshot, tokenizer, examples, rows, ledger, pipeline):
    """Reload existing 6b-slice fold adapters to verify exact continuity and capture unconstrained logits."""
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, BitsAndBytesConfig

    existing_root = Path(__file__).resolve().parents[2] / ".codex/private/pilot-resplit-2026-11-11"
    published = json.loads((PILOT.parent / "pilot_resplit/results.json").read_text(encoding="utf-8"))
    if not existing_root.is_dir():
        return None

    quant = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16,
    )
    repr_dir = out_dir / "abstract_graph"
    repr_dir.mkdir(exist_ok=True)
    predictions = {}
    for fold in range(5):
        fold_dir = repr_dir / f"fold-{fold}"
        pred_file = fold_dir / "predictions.json"
        if pred_file.exists():
            predictions.update(json.loads(pred_file.read_text(encoding="utf-8")))
            continue
        adapter_dir = existing_root / f"fold-{fold}/adapter"
        if not adapter_dir.is_dir():
            return None
        held_out = [item for item in examples if ledger[item["id"]]["fold"] == fold]
        gc.collect()
        torch.cuda.empty_cache()
        base_model = AutoModelForCausalLM.from_pretrained(
            snapshot, quantization_config=quant, device_map={"": 0},
            local_files_only=True, trust_remote_code=False, use_safetensors=True,
        )
        model = PeftModel.from_pretrained(base_model, str(adapter_dir))
        model.eval()
        adapted = predict_all_nodes(model, held_out, pipeline, tokenizer)
        with model.disable_adapter():
            base = predict_all_nodes(model, held_out, pipeline, tokenizer)
        fold_preds = {}
        for item in held_out:
            pid = item["id"]
            pub = published["predictions"][pid]
            if adapted[pid]["constrained"] != pub["adapted"] or base[pid]["constrained"] != pub["base"]:
                raise ValueError(f"Reloaded adapter diverged from pilot_resplit on {pid}")
            fold_preds[pid] = {
                "fold": fold,
                "group": ledger[pid]["group"],
                "reference": rows[pid]["gt_node"],
                "all_nodes": item["all_nodes"],
                "candidates": item["c_pruned"],
                "base_unconstrained": base[pid]["unconstrained"],
                "base_constrained": base[pid]["constrained"],
                "adapted_unconstrained": adapted[pid]["unconstrained"],
                "adapted_constrained": adapted[pid]["constrained"],
                "base_logits": base[pid]["all_logits"],
                "adapted_logits": adapted[pid]["all_logits"],
            }
        fold_dir.mkdir(exist_ok=True)
        write_json(pred_file, fold_preds)
        predictions.update(fold_preds)
        del model, base_model
        gc.collect()
        torch.cuda.empty_cache()
        print(f"[abstract_graph] Verified & extracted unconstrained logits for fold {fold + 1}/5", flush=True)
    return predictions


def run_representation(repr_kind, out_dir, snapshot, tokenizer, examples, rows, ledger, pipeline, split_sha):
    """Train or resume 5 folds for one prompt representation under strict VRAM hygiene."""
    import torch

    repr_dir = out_dir / repr_kind
    repr_dir.mkdir(exist_ok=True)
    predictions = {}
    for fold in range(5):
        fold_dir = repr_dir / f"fold-{fold}"
        pred_file = fold_dir / "predictions.json"
        if pred_file.exists():
            fold_preds = json.loads(pred_file.read_text(encoding="utf-8"))
            predictions.update(fold_preds)
            print(f"[{repr_kind}] Loaded cached fold {fold + 1}/5 ({len(fold_preds)} pairs)", flush=True)
            continue

        training = [item for item in examples if ledger[item["id"]]["fold"] != fold]
        held_out = [item for item in examples if ledger[item["id"]]["fold"] == fold]
        print(f"[{repr_kind}] Fold {fold + 1}/5: fitting {len(training)} pairs, evaluating {len(held_out)}...", flush=True)
        started = time.monotonic()
        model, history, runtime = train(training, snapshot, tokenizer)
        adapted = predict_all_nodes(model, held_out, pipeline, tokenizer)
        with model.disable_adapter():
            base = predict_all_nodes(model, held_out, pipeline, tokenizer)
        fold_preds = {}
        for item in held_out:
            pid = item["id"]
            fold_preds[pid] = {
                "fold": fold,
                "group": ledger[pid]["group"],
                "reference": rows[pid]["gt_node"],
                "all_nodes": item["all_nodes"],
                "candidates": item["c_pruned"],
                "base_unconstrained": base[pid]["unconstrained"],
                "base_constrained": base[pid]["constrained"],
                "adapted_unconstrained": adapted[pid]["unconstrained"],
                "adapted_constrained": adapted[pid]["constrained"],
                "base_logits": base[pid]["all_logits"],
                "adapted_logits": adapted[pid]["all_logits"],
            }
        fold_dir.mkdir(exist_ok=True)
        save_result(fold_dir, model, {
            "schema": "eapg-resplit-ablation-fold-v1",
            "representation": repr_kind,
            "fold": fold,
            "split_sha256": split_sha,
            "epochs": history,
            "runtime": runtime,
        })
        write_json(pred_file, fold_preds)
        predictions.update(fold_preds)
        del model
        gc.collect()
        torch.cuda.empty_cache()
        print(f"[{repr_kind}] Fold {fold + 1}/5 done in {time.monotonic() - started:.1f}s "
              f"(loss {history[0]['mean_loss']:.3f} -> {history[-1]['mean_loss']:.3f}, "
              f"peak {runtime['cuda_peak_allocated'] / 1024**3:.2f} GiB)", flush=True)
    return predictions


def summarize_matrix(all_predictions, rows):
    """Compute exact pair- and group-weighted metrics across All 100, Multi-cand 66, Off-symptom 18."""
    cohorts = {
        "all": lambda r: True,
        "multi_candidate": lambda r: len(r["slicing"]["c_pruned"]) >= 2,
        "off_symptom": lambda r: r["gt_node"] not in r["slicing"]["c_naive_work"],
        "a1": lambda r: r["track_gt"] == "A1",
        "a2": lambda r: r["track_gt"] == "A2",
        "b": lambda r: r["track_gt"] == "B",
        "reset": lambda r: r["mechanism_id"] in ("A1.1", "A1.4"),
    }

    def eval_variant(preds, key_fn, cfilter):
        groups = defaultdict(list)
        top2_groups = defaultdict(list)
        for pid, r in sorted(rows.items()):
            if not cfilter(r):
                continue
            p = preds[pid]
            ranked = key_fn(p)
            ref = r["gt_node"]
            groups[p["group"]].append(int(ranked[0] == ref))
            top2_groups[p["group"]].append(int(ref in ranked[:2]))
        pairs = sum(map(len, groups.values()))
        hits = sum(map(sum, groups.values()))
        hits2 = sum(map(sum, top2_groups.values()))
        macro1 = 100.0 * sum(sum(g) / len(g) for g in groups.values()) / len(groups)
        macro2 = 100.0 * sum(sum(g) / len(g) for g in top2_groups.values()) / len(top2_groups)
        return {
            "pairs": pairs,
            "groups": len(groups),
            "top1_hits": hits,
            "top1_pair_pct": round(100.0 * hits / pairs, 2),
            "top1_group_pct": round(macro1, 2),
            "top2_hits": hits2,
            "top2_pair_pct": round(100.0 * hits2 / pairs, 2),
            "top2_group_pct": round(macro2, 2),
        }

    summary = {}
    for repr_kind, preds in all_predictions.items():
        summary[repr_kind] = {}
        for cname, cfn in cohorts.items():
            summary[repr_kind][cname] = {
                mode: eval_variant(preds, lambda p, m=mode: p[m], cfn)
                for mode in ("base_unconstrained", "base_constrained", "adapted_unconstrained", "adapted_constrained")
            }

    contrasts = {}
    for cname, cfn in cohorts.items():
        contrasts[cname] = {}
        for mode in ("adapted_constrained", "adapted_unconstrained"):
            contrasts[cname][mode] = {}
            for lhs, rhs in (
                ("abstract_graph", "raw_code"),
                ("abstract_graph", "hotspot_raw"),
                ("abstract_graph", "static_eapg"),
                ("abstract_graph", "abstract_hits_only"),
                ("abstract_graph", "full_eapg"),
                ("full_eapg", "raw_code"),
                ("full_eapg", "static_eapg"),
            ):
                groups = defaultdict(list)
                for pid, r in sorted(rows.items()):
                    if not cfn(r):
                        continue
                    ref = r["gt_node"]
                    gl = all_predictions[lhs][pid]["group"]
                    hl = int(all_predictions[lhs][pid][mode][0] == ref)
                    hr = int(all_predictions[rhs][pid][mode][0] == ref)
                    groups[gl].append(hl - hr)
                contrasts[cname][mode][f"{lhs}_minus_{rhs}"] = contrast([groups[k] for k in sorted(groups)])
    return {"by_representation": summary, "paired_contrasts": contrasts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint_dir", type=Path, help="Private directory for adapters and fold receipts")
    parser.add_argument("--artifact-out", type=Path, required=True, help="Replayable JSON summary path (no weights)")
    parser.add_argument("--representations", nargs="+", choices=REPRESENTATIONS, default=list(REPRESENTATIONS))
    args = parser.parse_args()

    args.checkpoint_dir.mkdir(parents=True, exist_ok=True)
    pipeline, rows, snapshot, tokenizer, files, recipe_hashes = load_inputs()
    ledger, _ = prepare_split(pipeline, rows, tokenizer)
    prompt_hashes = verify_multi_repr_quarantine(pipeline, rows, tokenizer, ledger)

    split_path = args.checkpoint_dir / "split_manifest.json"
    split_obj = {
        "schema": "eapg-published-pilot-resplit-ablation-v1",
        "seed": 42,
        "pairs": ledger,
        "prompt_hashes_by_repr": prompt_hashes,
        "pilot_sha256": PILOT_SHA,
        "pipeline_sha256": PIPELINE_SHA,
        "recipe_hashes": recipe_hashes,
        "recipe": RECIPE,
        "model": MODEL,
        "revision": REVISION,
        "snapshot_files": files,
        "parsers": {name: version(name) for name in ("tree-sitter", "tree-sitter-cpp")},
    }
    if not split_path.exists():
        write_json(split_path, split_obj)
    split_sha = sha256(split_path.read_bytes()).hexdigest()

    all_predictions = {}
    max_tokens_by_repr = {}
    for repr_kind in args.representations:
        examples, max_tok = build_repr_examples(pipeline, rows, tokenizer, repr_kind, prompt_hashes)
        max_tokens_by_repr[repr_kind] = max_tok
        print(f"=== Representation: {repr_kind} (max {max_tok} tokens <= 512) ===", flush=True)
        if repr_kind == "abstract_graph":
            preds = evaluate_existing_abstract_graph(
                args.checkpoint_dir, snapshot, tokenizer, examples, rows, ledger, pipeline,
            )
            if preds is None:
                preds = run_representation(
                    repr_kind, args.checkpoint_dir, snapshot, tokenizer, examples, rows, ledger, pipeline, split_sha,
                )
        else:
            preds = run_representation(
                repr_kind, args.checkpoint_dir, snapshot, tokenizer, examples, rows, ledger, pipeline, split_sha,
            )
        all_predictions[repr_kind] = preds

    if set(all_predictions) == set(REPRESENTATIONS):
        scores = summarize_matrix(all_predictions, rows)
        output = {
            "schema": "eapg-resplit-ablation-v1",
            "split_sha256": split_sha,
            "pilot_sha256": PILOT_SHA,
            "pipeline_sha256": PIPELINE_SHA,
            "model": MODEL,
            "revision": REVISION,
            "recipe": RECIPE,
            "max_tokens_by_repr": max_tokens_by_repr,
            "split": ledger,
            "scores": scores,
            "predictions": all_predictions,
        }
        args.artifact_out.parent.mkdir(parents=True, exist_ok=True)
        args.artifact_out.write_text(json.dumps(output, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        print(f"Saved complete ablation results to {args.artifact_out}", flush=True)


if __name__ == "__main__":
    main()
