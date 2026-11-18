"""Check the pinned Qwen tokenizer on the authored intervention profile."""

import argparse
from hashlib import sha256
import json
from pathlib import Path

from prediction_contract import prepare_prediction
from run_phase2_development import load_pipeline
from train_phase2_adapter import load_inputs


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--pipeline", required=True, type=Path)
    cli.add_argument("--profile", required=True, type=Path)
    args = cli.parse_args()
    raw = args.profile.read_bytes()
    report = json.loads(raw)
    pipeline = load_pipeline(args.pipeline)
    if (report["schema"] != "eapg-authored-intervention-smoke-v1"
            or report["provenance"]["pipeline_sha256"] != pipeline.source_sha256):
        raise ValueError("Expected the authored fixture profile from the same candidate")
    _, _, _, tokenizer, _, _ = load_inputs()
    results = {}
    for name, profile in report["profiles"].items():
        row, tokens, labels = prepare_prediction(pipeline, name, profile["normalized_sha256"],
                                                profile["nodes"], profile["fits"]["0"], tokenizer)
        expected = report["selectors"][name]
        if (row["slice"] != expected["c_pruned"] or row["symbolic"] != expected["ranked_candidates"][:2]
                or row["symptom_id"] != expected["primary_symptom"]):
            raise ValueError(f"Prediction path changed the profiled slice for {name}")
        if name == "inverse":
            if row["abstract_status"] != "NO_SYMPTOM" or tokens or labels:
                raise ValueError("The linear inverse must abstain")
        elif row["abstract_status"] != "READY" or set(labels) != set(row["slice"]):
            raise ValueError(f"The authored prompt is not eligible for {name}")
        results[name] = {"status": row["abstract_status"], "prompt_tokens": row["prompt_tokens"],
                         "target_tokens": labels}
    print(json.dumps({"profile_sha256": sha256(raw).hexdigest(), "cases": results}, indent=2))


if __name__ == "__main__":
    main()
