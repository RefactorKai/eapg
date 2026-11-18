"""Execute the shared prospective prediction contract through a pinned QLoRA adapter."""

import argparse
import gc
from hashlib import file_digest, sha256
import json
from pathlib import Path

from prediction_contract import prepare_prediction, rank_abstract
from run_phase2_development import load_module
from score_external import DIGEST, require
from train_phase2_adapter import MODEL, REVISION, digest_json, load_inputs


SCHEMA = "eapg-external-predictions-v1"


def verify_adapter_dir(adapter_dir, expected_manifest_sha256=None):
    """Verify PEFT adapter files and compute a canonical adapter manifest digest."""
    adapter_dir = Path(adapter_dir)
    files = {}
    for path in sorted(adapter_dir.rglob("*")):
        if path.is_file():
            with path.open("rb") as stream:
                files[path.relative_to(adapter_dir).as_posix()] = file_digest(stream, "sha256").hexdigest()
    require({"adapter_config.json", "adapter_model.safetensors"} <= files.keys(),
            f"Incomplete PEFT adapter directory: {adapter_dir}")
    manifest_sha = digest_json(files)
    if expected_manifest_sha256 is not None:
        require(bool(DIGEST.fullmatch(expected_manifest_sha256)), "Invalid expected adapter manifest SHA-256")
        require(manifest_sha == expected_manifest_sha256, "Adapter manifest SHA-256 mismatch")
    return manifest_sha, files


def load_pinned_adapter(snapshot, adapter_dir, expected_manifest_sha256=None):
    """Load the pinned 4-bit NF4 base model and PEFT adapter under strict VRAM checks."""
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, BitsAndBytesConfig

    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported(including_emulation=False):
        raise RuntimeError("Adapter inference requires a CUDA device with native BF16 support")
    manifest_sha, _ = verify_adapter_dir(adapter_dir, expected_manifest_sha256)
    gc.collect()
    torch.cuda.empty_cache()
    free, _ = torch.cuda.mem_get_info(0)
    if free < 2 * 1024**3:
        raise RuntimeError("Need at least 2 GiB free CUDA memory for 4-bit inference")
    quant = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16,
    )
    base = AutoModelForCausalLM.from_pretrained(
        snapshot, quantization_config=quant, device_map={"": 0},
        local_files_only=True, trust_remote_code=False, use_safetensors=True,
    )
    model = PeftModel.from_pretrained(base, str(adapter_dir))
    model.eval()
    return model, manifest_sha


def score_prepared(model, prefix, labels):
    """Compute exact next-token logits for candidate labels using a loaded PEFT model."""
    import torch

    if not prefix or not labels:
        return {}
    with torch.inference_mode():
        input_ids = torch.tensor([prefix], device="cuda:0")
        logits = model(input_ids=input_ids, use_cache=False, logits_to_keep=1).logits[0, -1]
        indices = list(labels.values())
        selected = logits[indices].float()
        if not torch.isfinite(selected).all().item():
            raise ValueError("Nonfinite next-token logits emitted during contract scoring")
        return dict(zip(labels.keys(), selected.tolist()))


def predict_cases(pipeline, tokenizer, cases, *, scorer_fn, study_sha256, protocol_sha256,
                  quarantine_sha256, adapter_sha256):
    """Run prepare_prediction + scorer_fn + rank_abstract and build eapg-external-predictions-v1."""
    for name, val in (("study", study_sha256), ("protocol", protocol_sha256),
                      ("quarantine", quarantine_sha256), ("adapter", adapter_sha256)):
        require(bool(DIGEST.fullmatch(val)), f"Invalid {name} SHA-256")
    pipeline_sha = getattr(pipeline, "source_sha256", None)
    require(bool(pipeline_sha and DIGEST.fullmatch(pipeline_sha)), "Pipeline must carry a verified source_sha256")

    ledger_pairs = []
    statuses = []
    for case in cases:
        pair_id = case["pair_id"]
        normalized_sha = case.get("normalized_source_sha256")
        nodes = case.get("nodes")
        fits = case.get("fits")
        if normalized_sha is None or not nodes or fits is None:
            ledger_pairs.append({
                "pair_id": pair_id,
                "normalized_source_sha256": normalized_sha,
                "symptom_id": None,
                "slice": [],
                "prompt_tokens": None,
                "symbolic": [],
                "abstract": [],
            })
            statuses.append({
                "pair_id": pair_id,
                "abstract_status": case.get("unavailable_reason", "UNAVAILABLE_PROFILE"),
            })
            continue

        row, prefix, labels = prepare_prediction(pipeline, pair_id, normalized_sha, nodes, fits, tokenizer)
        if row["abstract_status"] == "READY":
            scores = scorer_fn(prefix, labels)
            row = rank_abstract(row, scores)
        statuses.append({"pair_id": pair_id, "abstract_status": row["abstract_status"]})
        ledger_pairs.append({
            "pair_id": row["pair_id"],
            "normalized_source_sha256": row["normalized_source_sha256"],
            "symptom_id": row["symptom_id"],
            "slice": row["slice"],
            "prompt_tokens": row["prompt_tokens"],
            "symbolic": row["symbolic"],
            "abstract": row["abstract"],
        })

    ledger = {
        "schema": SCHEMA,
        "study_sha256": study_sha256,
        "protocol_sha256": protocol_sha256,
        "pipeline_sha256": pipeline_sha,
        "quarantine_sha256": quarantine_sha256,
        "adapter_sha256": adapter_sha256,
        "pairs": ledger_pairs,
    }
    return ledger, statuses


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--pipeline", type=Path, required=True)
    cli.add_argument("--pipeline-sha256", required=True)
    cli.add_argument("--adapter-dir", type=Path, required=True)
    cli.add_argument("--adapter-sha256", required=True)
    cli.add_argument("--input", type=Path, required=True, help="JSON packet with study pins and cases")
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    if args.output.exists():
        cli.error("Choose a fresh output path")

    packet = json.loads(args.input.read_text(encoding="utf-8"))
    pipeline = load_module("external_contract_pipeline", args.pipeline, args.pipeline_sha256)
    _, _, snapshot, tokenizer, _, _ = load_inputs()
    model, manifest_sha = load_pinned_adapter(snapshot, args.adapter_dir, args.adapter_sha256)
    try:
        ledger, statuses = predict_cases(
            pipeline, tokenizer, packet["cases"],
            scorer_fn=lambda prefix, labels: score_prepared(model, prefix, labels),
            study_sha256=packet["study_sha256"],
            protocol_sha256=packet["protocol_sha256"],
            quarantine_sha256=packet["quarantine_sha256"],
            adapter_sha256=manifest_sha,
        )
    finally:
        del model
        gc.collect()
        import torch
        torch.cuda.empty_cache()

    encoded = json.dumps(ledger, indent=2, allow_nan=False).encode("utf-8") + b"\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(encoded)
    print(json.dumps({
        "predictions_sha256": sha256(encoded).hexdigest(),
        "model": MODEL,
        "revision": REVISION,
        "adapter_sha256": manifest_sha,
        "statuses": statuses,
    }, indent=2))


if __name__ == "__main__":
    main()
