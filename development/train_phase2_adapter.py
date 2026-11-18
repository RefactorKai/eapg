"""Fit one Phase 2 adapter on custody-approved frozen Phase 1 6b-slice prompts."""

import argparse
import gc
from hashlib import file_digest, sha256
from importlib.metadata import version
import json
import os
from pathlib import Path
import random
import re
from string import ascii_uppercase
import sys

from probe_adapter_objective import (
    MODEL, PILOT_SHA, PIPELINE_SHA, REVISION, ROOT, checked_bytes, recipe_hashes, snapshot_hashes,
)


SCHEMA = "eapg-phase2-final-prompt-quarantine-v1"
SNAPSHOT_SHA = {
    "config.json": "984abd4b3f21edb957012c7dc4352c462b08e15ffe8384b6d55990885e9dcc9a",
    "generation_config.json": "444ea57ebf361c659d1f5c23508319b691e181d122588ea3cdd5f68d3e618b1f",
    "merges.txt": "599bab54075088774b1733fde865d5bd747cbcc7a547c5bc12610e874e26f5e3",
    "model.safetensors": "535485b26038ac24f4e8a86e1a73ed417d8992e3192f6305b7fcc4fb92efa210",
    "tokenizer.json": "c0382117ea329cdf097041132f6d735924b697924d6f6fc3945713e96ce87539",
    "tokenizer_config.json": "4a917e4772d9b246ef600e1c5d7d81e3a81ae9f3f2d10d78ccb02c86e5fb184a",
    "vocab.json": "ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910",
}
RECIPE = {
    "seed": 42, "epochs": 6, "lr": 6e-4, "weight_decay": 0.01, "microbatch": 2,
    "gradient_accumulation": 4, "max_sequence": 512, "target_tokens": 1,
    "lora_layers": list(range(20, 28)), "lora_rank": 16, "lora_alpha": 32, "lora_dropout": 0.05,
    "lora_modules": ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    "quantization": "4-bit NF4 double-quant BF16 compute",
    "training_representation": "frozen Phase 1 published 6b-slice, abstract_graph/slice/node_only",
    "objective": "full-vocabulary cross-entropy at the last nonpadding prompt position",
}


def digest_json(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def strict_object(items):
    result = dict(items)
    if len(result) != len(items):
        raise ValueError("Duplicate JSON field in the custody manifest")
    return result


def verify_custody(envelope, expected_sha):
    if type(envelope) is not dict or set(envelope) != {"manifest", "sha256"}:
        raise ValueError("Expected the prompt quarantine manifest envelope")
    manifest = envelope["manifest"]
    if (not re.fullmatch(r"[0-9a-f]{64}", expected_sha)
            or digest_json(manifest) != expected_sha or envelope["sha256"] != expected_sha):
        raise ValueError("Custody manifest SHA-256 differs from the approved digest")
    keys = {"schema", "test_groups", "validation_groups", "removed_by_test", "removed_by_validation",
            "train_pair_ids", "unsupported_prompts", "prompt_keys_by_pair"}
    if type(manifest) is not dict or set(manifest) != keys or manifest["schema"] != SCHEMA:
        raise ValueError("Expected the final prompt quarantine v1 manifest")

    def unique_ids(ids):
        if type(ids) is not list or any(type(pid) is not str or not pid for pid in ids) or len(ids) != len(set(ids)):
            raise ValueError("Custody cohort IDs must be unique nonempty strings")
        return set(ids)

    def group_ids(groups):
        if type(groups) is not dict or not groups or any(type(ids) is not list or not ids for ids in groups.values()):
            raise ValueError("Custody requires nonempty test and validation groups")
        return unique_ids([pid for ids in groups.values() for pid in ids])

    test = group_ids(manifest["test_groups"])
    validation = group_ids(manifest["validation_groups"])
    train = unique_ids(manifest["train_pair_ids"])
    removed = unique_ids(manifest["removed_by_test"]) | unique_ids(manifest["removed_by_validation"])
    unsupported = manifest["unsupported_prompts"]
    prompts = manifest["prompt_keys_by_pair"]
    if (type(unsupported) is not dict or type(prompts) is not dict or not train or test & validation
            or train & (test | validation | removed | set(unsupported))
            or set(prompts) != train | test | validation | removed | set(unsupported)):
        raise ValueError("Custody training, blocked IDs and prompt-key ledger disagree")
    for pid, digests in prompts.items():
        if (type(digests) is not list or (not digests) != (pid in unsupported)
                or any(type(key) is not str or not re.fullmatch(r"[0-9a-f]{64}", key) for key in digests)):
            raise ValueError(f"Invalid prompt key ledger for {pid}")
    return manifest


def build_examples(manifest, rows, pipeline, tokenizer):
    def encode(text):
        return tokenizer.encode(text, add_special_tokens=False)

    labels = {code: encode(" " + code) for code in ascii_uppercase}
    if any(len(ids) != 1 for ids in labels.values()) or len({tuple(ids) for ids in labels.values()}) != 26:
        raise ValueError("Node codes must have 26 distinct single-token encodings")
    examples = []
    for pid in sorted(manifest["train_pair_ids"]):
        if pid not in rows:
            raise ValueError(f"Custody train row {pid} is outside the pinned published pilot")
        row = rows[pid]
        prompt, nodes, candidates = pipeline.build_variant_prompt_and_cands(
            row, "abstract_graph", tag_mode="slice", node_only=True,
        )
        if (not 1 <= len(nodes) <= 26 or row["gt_node"] not in candidates
                or not set(candidates) <= set(nodes) or candidates != row["slicing"]["c_pruned"]):
            raise ValueError(f"Custody train row {pid} has an ineligible node set or target")
        prefix = encode(prompt)
        key = digest_json(prefix)
        if key not in manifest["prompt_keys_by_pair"][pid]:
            raise ValueError(f"Exact frozen 6b-slice prompt digest is missing from custody for {pid}")
        label = pipeline._nid_to_code(row["gt_node"])
        if (label not in labels or not 0 < len(prefix) < RECIPE["max_sequence"]
                or encode(f"{prompt} {label}") != prefix + labels[label]):
            raise ValueError(f"Custody train row {pid} exceeds the context cap or has a non-single-token target")
        examples.append({"id": pid, "prompt_sha256": key, "prefix": prefix, "target": labels[label][0]})
    return examples


def load_inputs():
    os.environ["HF_HUB_OFFLINE"] = "1"
    from huggingface_hub.constants import HF_HUB_CACHE
    from transformers import AutoTokenizer

    raw = checked_bytes(ROOT / "pipeline.py", PIPELINE_SHA)
    pilot = checked_bytes(ROOT / "artifacts/scope_isolated_pilot/pilot100_results.json", PILOT_SHA)
    sys.path.insert(0, str(ROOT))
    import pipeline

    snapshot = Path(HF_HUB_CACHE) / f"models--{MODEL.replace('/', '--')}" / "snapshots" / REVISION
    files = snapshot_hashes(snapshot)
    if {name: info["sha256"] for name, info in files.items()} != SNAPSHOT_SHA:
        raise ValueError("Local Qwen snapshot differs from the pinned tokenizer and weights")
    tokenizer = AutoTokenizer.from_pretrained(snapshot, local_files_only=True, trust_remote_code=False)
    rows = {row["pair_id"]: row for row in json.loads(pilot)}
    return pipeline, rows, snapshot, tokenizer, files, recipe_hashes(raw)


def train(examples, snapshot, tokenizer):
    import torch
    from peft import LoraConfig, get_peft_model
    from torch.nn import functional as F
    from torch.nn.utils.rnn import pad_sequence
    from transformers import AutoModelForCausalLM, BitsAndBytesConfig

    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported(including_emulation=False):
        raise RuntimeError("This recipe requires a CUDA device with native BF16 support")
    device = torch.device("cuda:0")
    free, total = torch.cuda.mem_get_info(device)
    if free < 3 * 1024**3:
        raise RuntimeError("The frozen eight-layer LoRA recipe needs at least 3 GiB free CUDA memory")
    seed = RECIPE["seed"]
    torch.manual_seed(seed)
    torch.cuda.reset_peak_memory_stats(device)
    rng = random.Random(seed)
    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                              bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16)
    base = AutoModelForCausalLM.from_pretrained(
        snapshot, quantization_config=quant, device_map={"": 0},
        local_files_only=True, trust_remote_code=False, use_safetensors=True,
    )
    if base.config.num_hidden_layers != 28 or not base.is_loaded_in_4bit:
        raise RuntimeError("Expected the pinned 28-layer Qwen model loaded in 4-bit")
    model = get_peft_model(base, LoraConfig(
        r=RECIPE["lora_rank"], lora_alpha=RECIPE["lora_alpha"], lora_dropout=RECIPE["lora_dropout"],
        target_modules=RECIPE["lora_modules"], layers_to_transform=RECIPE["lora_layers"],
        bias="none", task_type="CAUSAL_LM",
    ))
    params = {name: p for name, p in model.named_parameters() if p.requires_grad}
    if ({int(name.split(".layers.", 1)[1].split(".", 1)[0]) for name in params} != set(RECIPE["lora_layers"])
            or any(p.device != device for p in params.values())):
        raise RuntimeError("LoRA parameters are not attached to exactly the eight registered CUDA layers")
    torch.manual_seed(seed)
    for name, param in params.items():
        if ".lora_A." in name:
            torch.nn.init.kaiming_uniform_(param, a=5**0.5)
        elif ".lora_B." in name:
            torch.nn.init.zeros_(param)
        else:
            raise RuntimeError(f"Unexpected trainable parameter {name}")

    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.train()
    for layer in base.model.layers[:RECIPE["lora_layers"][0]]:
        layer.eval()
    pad_id = tokenizer.pad_token_id if tokenizer.pad_token_id is not None else tokenizer.eos_token_id
    optimizer = torch.optim.AdamW(params.values(), lr=RECIPE["lr"], weight_decay=RECIPE["weight_decay"])
    batch_size = RECIPE["microbatch"]
    group_size = batch_size * RECIPE["gradient_accumulation"]
    items = list(examples)
    history = []
    for epoch in range(1, RECIPE["epochs"] + 1):
        gc.collect()
        torch.cuda.empty_cache()
        rng.shuffle(items)
        epoch_loss = steps = 0
        for start in range(0, len(items), group_size):
            group = items[start:start + group_size]
            optimizer.zero_grad(set_to_none=True)
            for offset in range(0, len(group), batch_size):
                batch = group[offset:offset + batch_size]
                lengths = torch.tensor([len(item["prefix"]) for item in batch], device=device)
                tokens = [torch.tensor(item["prefix"], device=device) for item in batch]
                input_ids = pad_sequence(tokens, batch_first=True, padding_value=pad_id)
                mask = torch.arange(input_ids.shape[1], device=device) < lengths[:, None]
                # Project only the final prompt position, over the full vocabulary.
                hidden = base.model(input_ids=input_ids, attention_mask=mask, use_cache=False).last_hidden_state
                logits = base.lm_head(hidden[torch.arange(len(batch), device=device), lengths - 1])
                targets = torch.tensor([item["target"] for item in batch], device=device)
                loss = F.cross_entropy(logits, targets, reduction="sum")
                if not torch.isfinite(loss).item():
                    raise RuntimeError(f"Nonfinite training loss in epoch {epoch}")
                (loss / len(group)).backward()
                epoch_loss += loss.detach().item()
            optimizer.step()
            steps += 1
        optimizer.zero_grad(set_to_none=True)
        gc.collect()
        torch.cuda.empty_cache()
        history.append({"epoch": epoch, "optimizer_steps": steps, "mean_loss": epoch_loss / len(items)})
    model.eval()
    runtime = {"python": sys.version.split()[0], "cuda": torch.version.cuda,
               "gpu": torch.cuda.get_device_name(device), "cuda_free_at_start": free, "cuda_total": total,
               "cuda_peak_allocated": torch.cuda.max_memory_allocated(device),
               "attention": base.config._attn_implementation,
               "packages": {name: version(name) for name in (
                   "torch", "transformers", "tokenizers", "peft", "bitsandbytes", "accelerate", "safetensors",
               )}}
    return model, history, runtime


def save_result(output, model, report):
    adapter = output / "adapter"
    model.peft_config["default"].base_model_name_or_path = MODEL
    model.peft_config["default"].revision = REVISION
    model.save_pretrained(adapter, safe_serialization=True)
    files = {}
    for path in sorted(adapter.rglob("*")):
        if path.is_file():
            with path.open("rb") as stream:
                files[path.relative_to(adapter).as_posix()] = file_digest(stream, "sha256").hexdigest()
    if not {"adapter_config.json", "adapter_model.safetensors"} <= files.keys():
        raise RuntimeError("PEFT did not produce the required adapter files")
    report.update(status="COMPLETE", adapter_files=files, adapter_manifest_sha256=digest_json(files))
    with (output / "provenance.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")


def self_check(pipeline, rows, tokenizer):
    from prompt_quarantine import Pair, seal_splits

    row = rows["PAIR_001"]
    prompt, _, _ = pipeline.build_variant_prompt_and_cands(row, "abstract_graph", tag_mode="slice", node_only=True)
    training = Pair(row["pair_id"], row["problem_id"], row["slow_code"], row["fast_code"])
    test = Pair("fixture-test", "fixture-test", "struct A {};", "struct B {};")
    validation = Pair("fixture-validation", "fixture-validation", "bool q = false;", "double d = 0;")
    tokens = {test.pair_id: [[1]], validation.pair_id: [[2]],
              training.pair_id: [tokenizer.encode(prompt, add_special_tokens=False)]}
    sealed = seal_splits([test], [validation], [training], tokens)
    manifest = verify_custody(sealed, sealed["sha256"])
    examples = build_examples(manifest, rows, pipeline, tokenizer)
    assert [example["id"] for example in examples] == [training.pair_id]

    def rejected(check):
        try:
            check()
        except ValueError:
            return
        raise AssertionError("Invalid custody contract was accepted")

    rejected(lambda: verify_custody(sealed, "0" * 64))
    blocked = dict(manifest, train_pair_ids=[test.pair_id])
    blocked_sha = digest_json(blocked)
    rejected(lambda: verify_custody({"manifest": blocked, "sha256": blocked_sha}, blocked_sha))
    bad = seal_splits([test], [validation], [training], {**tokens, training.pair_id: [[3]]})
    rejected(lambda: build_examples(verify_custody(bad, bad["sha256"]), rows, pipeline, tokenizer))
    rejected(lambda: build_examples(manifest, {}, pipeline, tokenizer))
    print("Authored custody digest, blocked row, published ID and exact prompt-token checks passed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--self-check", action="store_true", help="Run an authored CPU-only custody fixture")
    mode.add_argument("--preflight-only", action="store_true", help="Verify authorized inputs on CPU without training")
    parser.add_argument("--custody-manifest", type=Path)
    parser.add_argument("--custody-sha256", help="Canonical payload digest supplied independently by the custodian")
    parser.add_argument("--output", type=Path, help="Fresh directory for the adapter and completion provenance")
    args = parser.parse_args()
    if args.self_check:
        if any((args.custody_manifest, args.custody_sha256, args.output)):
            parser.error("The authored self-check cannot accept production inputs")
        pipeline, rows, _, tokenizer, _, _ = load_inputs()
        self_check(pipeline, rows, tokenizer)
        return
    if not args.custody_manifest or not args.custody_sha256 or (not args.preflight_only and not args.output):
        parser.error("Supply the sealed custody manifest, approved digest and a fresh output path for training")
    if args.output is not None and os.path.lexists(args.output):
        raise FileExistsError(args.output)
    raw = args.custody_manifest.read_bytes()
    manifest = verify_custody(json.loads(raw, object_pairs_hook=strict_object), args.custody_sha256)
    pipeline, rows, snapshot, tokenizer, files, hashes = load_inputs()
    examples = build_examples(manifest, rows, pipeline, tokenizer)
    report = {"schema": "eapg-phase2-adapter-provenance-v1", "model": MODEL, "revision": REVISION,
              "snapshot_files": files, "trainer_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
              "pipeline_sha256": PIPELINE_SHA, "pilot_sha256": PILOT_SHA, "frozen_recipe_sha256_lf": hashes,
              "custody_sha256": args.custody_sha256, "custody_envelope_sha256": sha256(raw).hexdigest(),
              "train_prompt_sha256": {item["id"]: item["prompt_sha256"] for item in examples},
              "recipe": RECIPE}
    if args.preflight_only:
        print(json.dumps(dict(report, status="PREFLIGHT_PASSED"), indent=2))
        return
    args.output.mkdir(exist_ok=False)
    model, history, runtime = train(examples, snapshot, tokenizer)
    save_result(args.output, model, dict(report, epochs=history, runtime=runtime))
    print(f"Completed one Phase 2 adapter fit in {args.output}.")


if __name__ == "__main__":
    main()
