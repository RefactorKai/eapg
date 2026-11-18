"""Refit the published synthetic pilot under stricter, group-disjoint splits."""

import argparse
from collections import Counter, defaultdict
import gc
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import time

from replay_pilot_contrast import PILOT, contrast, verified_json
from train_phase2_adapter import (
    MODEL, PILOT_SHA, PIPELINE_SHA, RECIPE, REVISION, build_examples, digest_json,
    load_inputs, save_result, train,
)


def prepare_split(pipeline, rows, tokenizer):
    from artifacts.phase1_correction.phase2_custody_and_probes import fingerprints, source_key

    archived = verified_json(PILOT / "node_only_ablation/evaluation_results.json")
    old_groups = {pid: i for i, group in enumerate(archived["template_groups"]) for pid in group}
    tokens, keys = {}, {}
    for pid, row in rows.items():
        prompt, _, _ = pipeline.build_variant_prompt_and_cands(
            row, "abstract_graph", tag_mode="slice", node_only=True,
        )
        tokens[pid] = digest_json(tokenizer.encode(prompt, add_special_tokens=False))
        features = {f"archived:{old_groups[row['problem_id']]}", f"prompt:{tokens[pid]}"}
        for side in ("slow_code", "fast_code"):
            source = row[side]
            features.update(fingerprints(source, pilot=True)[0])
            features.add(f"source:{source_key(source)}")
        keys[pid] = sorted(features)

    folds, groups = pipeline.split_pilot_templates(list(rows.values()), seed=42, prompt_fingerprints=keys)
    problem_fold = {pid: i for i, fold in enumerate(folds) for pid in fold}
    pair_folds = {pid: problem_fold[row["problem_id"]] for pid, row in rows.items()}
    owners = {}
    for pid, row in rows.items():
        for key in [f"problem:{row['problem_id']}", *row["template_fingerprints"], *keys[pid]]:
            if owners.setdefault(key, pair_folds[pid]) != pair_folds[pid]:
                raise ValueError(f"Cross-fold fingerprint for {pid}")
    group_of = {pid: i for i, group in enumerate(groups) for pid in group}
    ledger = {pid: {"problem_id": row["problem_id"], "group": group_of[row["problem_id"]],
                    "fold": pair_folds[pid], "track": row["track_gt"], "mechanism": row["mechanism_id"],
                    "prompt_sha256": tokens[pid]} for pid, row in sorted(rows.items())}
    examples = build_examples({"train_pair_ids": list(rows), "prompt_keys_by_pair": {
        pid: [key] for pid, key in tokens.items()
    }}, rows, pipeline, tokenizer)
    return ledger, examples


def predict(model, examples, rows, pipeline, tokenizer):
    import torch

    token_ids = {chr(65 + i): tokenizer.encode(" " + chr(65 + i), add_special_tokens=False)[0]
                 for i in range(26)}
    ranks = {}
    gc.collect()
    torch.cuda.empty_cache()
    with torch.inference_mode():
        for example in examples:
            pid = example["id"]
            candidates = rows[pid]["slicing"]["c_pruned"]
            input_ids = torch.tensor([example["prefix"]], device="cuda:0")
            logits = model(input_ids=input_ids, use_cache=False, logits_to_keep=1).logits[0, -1]
            indices = [token_ids[pipeline._nid_to_code(node)] for node in candidates]
            selected = logits[indices].float()
            if not torch.isfinite(selected).all().item():
                raise ValueError(f"Nonfinite ranking scores for {pid}")
            scores = dict(zip(candidates, selected.tolist()))
            ranks[pid] = {"ranking": sorted(candidates, key=scores.get, reverse=True), "logits": scores}
    gc.collect()
    torch.cuda.empty_cache()
    return ranks


def summarize(predictions):
    result = {}
    methods = ("adapted", "base", "symbolic")
    for name, minimum in (("all", 1), ("multi_candidate", 2)):
        groups = defaultdict(list)
        for row in predictions.values():
            if len(row["candidates"]) >= minimum:
                groups[row["group"]].append(row)
        pairs = sum(map(len, groups.values()))
        hits = {method: {group: [int(row[method][0] == row["reference"]) for row in rows]
                         for group, rows in groups.items()} for method in methods}
        result[name] = {"pairs": pairs, "groups": len(groups), "top1": {
            method: {"hits": sum(map(sum, values.values())),
                     "group_macro_rate": sum(sum(group) / len(group) for group in values.values()) / len(groups)}
            for method, values in hits.items()
        }, "adapted_minus": {
            method: contrast([[a - b for a, b in zip(hits["adapted"][group], hits[method][group])]
                              for group in sorted(groups)]) for method in ("base", "symbolic")
        }}
    return result


def write_json(path, data):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(data, stream, indent=2, allow_nan=False)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="Fresh directory for the split, adapters and predictions")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    pipeline, rows, snapshot, tokenizer, files, recipe_hashes = load_inputs()
    ledger, examples = prepare_split(pipeline, rows, tokenizer)
    import train_phase2_adapter
    from artifacts.phase1_correction import phase2_custody_and_probes

    args.output.mkdir()
    split = {"schema": "eapg-published-pilot-resplit-v1", "scope": "synthetic development sensitivity",
             "seed": 42, "pairs": ledger, "pilot_sha256": PILOT_SHA, "pipeline_sha256": PIPELINE_SHA,
             "recipe_hashes": recipe_hashes, "recipe": RECIPE, "model": MODEL, "revision": REVISION,
             "snapshot_files": files, "scripts": {path.name: sha256(path.read_bytes()).hexdigest()
             for path in map(Path, (__file__, train_phase2_adapter.__file__, phase2_custody_and_probes.__file__))},
             "parsers": {name: version(name) for name in ("tree-sitter", "tree-sitter-cpp")}}
    split_path = args.output / "split_manifest.json"
    write_json(split_path, split)
    split_sha = sha256(split_path.read_bytes()).hexdigest()
    print(f"Sealed {len(ledger)} pairs in {len({row['group'] for row in ledger.values()})} groups. "
          f"Fold sizes: {dict(sorted(Counter(row['fold'] for row in ledger.values()).items()))}.", flush=True)

    predictions = {}
    import torch
    for fold in range(5):
        training = [item for item in examples if ledger[item["id"]]["fold"] != fold]
        held_out = [item for item in examples if ledger[item["id"]]["fold"] == fold]
        print(f"Fold {fold + 1}/5: fitting {len(training)} pairs and evaluating {len(held_out)}.", flush=True)
        started = time.monotonic()
        model, history, runtime = train(training, snapshot, tokenizer)
        adapted = predict(model, held_out, rows, pipeline, tokenizer)
        with model.disable_adapter():
            base = predict(model, held_out, rows, pipeline, tokenizer)
        for item in held_out:
            pid = item["id"]
            row = rows[pid]
            candidates = row["slicing"]["c_pruned"]
            symbolic = pipeline.rank_candidates_by_role_priority(row, use_loop_def_use=True)
            if set(symbolic) != set(candidates):
                raise ValueError(f"Symbolic ranker changed the common slice for {pid}")
            predictions[pid] = {"fold": fold, "group": ledger[pid]["group"], "reference": row["gt_node"],
                                "candidates": candidates, "symbolic": symbolic, "base": base[pid]["ranking"],
                                "adapted": adapted[pid]["ranking"], "base_logits": base[pid]["logits"],
                                "adapted_logits": adapted[pid]["logits"]}
        output = args.output / f"fold-{fold}"
        output.mkdir()
        save_result(output, model, {"schema": "eapg-pilot-resplit-adapter-v1", "fold": fold,
                                    "split_sha256": split_sha, "epochs": history, "runtime": runtime})
        write_json(output / "predictions.json", {item["id"]: predictions[item["id"]] for item in held_out})
        del model
        gc.collect()
        torch.cuda.empty_cache()
        print(f"Fold {fold + 1}/5 complete in {time.monotonic() - started:.1f}s. "
              f"Loss {history[0]['mean_loss']:.3f} to {history[-1]['mean_loss']:.3f}.", flush=True)
    if predictions.keys() != ledger.keys():
        raise ValueError("The out-of-fold predictions do not cover the full pilot")
    write_json(args.output / "results.json", {"split_sha256": split_sha, "scores": summarize(predictions)})


if __name__ == "__main__":
    main()
