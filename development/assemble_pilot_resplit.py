"""Assemble a completed grouped pilot refit into the JSON consumed by CPU replay."""

import argparse
from hashlib import file_digest, sha256
import json
from pathlib import Path

from probe_adapter_objective import PILOT_SHA, PIPELINE_SHA, checked_bytes, recipe_hashes
from replay_pilot_contrast import PILOT, ROOT
from train_phase2_adapter import digest_json
from train_pilot_resplit import summarize


SCRIPTS = (
    "artifacts/phase1_correction/phase2_custody_and_probes.py",
    "development/train_pilot_resplit.py",
    "development/train_phase2_adapter.py",
)


def json_bytes(data):
    return (json.dumps(data, indent=2, allow_nan=False) + "\n").encode("utf-8")


def verify_inputs(split):
    pipeline = checked_bytes(ROOT / "pipeline.py", PIPELINE_SHA)
    if (split["pipeline_sha256"] != PIPELINE_SHA or split["pilot_sha256"] != PILOT_SHA
            or split["recipe_hashes"] != recipe_hashes(pipeline)):
        raise ValueError("Split does not match the frozen pipeline and pilot inputs")
    pilot_path = PILOT / "pilot100_results.json"
    pilot = {row["pair_id"]: row for row in json.loads(checked_bytes(pilot_path, PILOT_SHA))}
    hashes = {"pipeline.py": PIPELINE_SHA, pilot_path.relative_to(ROOT).as_posix(): PILOT_SHA}
    for name in SCRIPTS:
        expected = split["scripts"][Path(name).name]
        checked_bytes(ROOT / name, expected)
        hashes[name] = expected
    contrast_path = "development/replay_pilot_contrast.py"
    hashes[contrast_path] = sha256((ROOT / contrast_path).read_bytes()).hexdigest()
    evaluation = "artifacts/scope_isolated_pilot/node_only_ablation/evaluation_results.json"
    release_hashes = dict(line.split("  ", 1)[::-1] for line in (ROOT / "SHA256SUMS").read_text().splitlines())
    hashes[evaluation] = release_hashes[evaluation]
    checked_bytes(ROOT / evaluation, hashes[evaluation])
    return pilot, hashes


def verify_adapter(directory, provenance):
    expected = provenance["adapter_files"]
    adapter = directory / "adapter"
    paths = {p.relative_to(adapter).as_posix(): p for p in adapter.rglob("*") if p.is_file()}
    if (not {"adapter_config.json", "adapter_model.safetensors"} <= paths.keys()
            or paths.keys() != expected.keys()
            or digest_json(expected) != provenance["adapter_manifest_sha256"]):
        raise ValueError(f"{directory.name} has an incomplete or inconsistent adapter manifest")
    for name, path in paths.items():
        with path.open("rb") as stream:
            if file_digest(stream, "sha256").hexdigest() != expected[name]:
                raise ValueError(f"{directory.name} adapter digest mismatch for {name}")


def verify_prediction(pid, pred, entry, row):
    candidates = row["slicing"]["c_pruned"]
    if (entry["problem_id"] != row["problem_id"] or pred["fold"] != entry["fold"]
            or pred["group"] != entry["group"] or pred["reference"] != row["gt_node"]
            or pred["candidates"] != candidates):
        raise ValueError(f"Prediction {pid} does not match the split or published pilot")
    if sorted(pred["symbolic"]) != sorted(candidates):
        raise ValueError(f"Prediction {pid} does not rank the common slice")
    for method in ("adapted", "base"):
        logits = pred[f"{method}_logits"]
        if (logits.keys() != set(candidates)
                or pred[method] != sorted(candidates, key=logits.get, reverse=True)):
            raise ValueError(f"Prediction {pid} has an inconsistent {method} ranking")


def assemble(run):
    split_bytes = (run / "split_manifest.json").read_bytes()
    split = json.loads(split_bytes)
    if split["schema"] != "eapg-published-pilot-resplit-v1" or split_bytes != json_bytes(split):
        raise ValueError("Expected the trainer's canonical v1 split manifest")
    split_sha = sha256(split_bytes).hexdigest()
    summary = json.loads((run / "results.json").read_bytes())
    if summary["split_sha256"] != split_sha:
        raise ValueError("Trainer summary references a different split")
    pilot, inputs_sha256 = verify_inputs(split)
    ledger = split["pairs"]
    if ledger.keys() != pilot.keys() or {row["fold"] for row in ledger.values()} != set(range(5)):
        raise ValueError("Split must cover the published pilot in five nonempty folds")
    owners = {}
    for entry in ledger.values():
        for key in ("problem_id", "group", "prompt_sha256"):
            if owners.setdefault((key, entry[key]), entry["fold"]) != entry["fold"]:
                raise ValueError(f"Split assigns the same {key} to multiple folds")

    epochs = list(range(1, split["recipe"]["epochs"] + 1))
    folds, predictions = [], {}
    for fold in range(5):
        directory = run / f"fold-{fold}"
        provenance = json.loads((directory / "provenance.json").read_bytes())
        if (provenance["schema"] != "eapg-pilot-resplit-adapter-v1"
                or provenance["fold"] != fold or provenance["status"] != "COMPLETE"
                or provenance["split_sha256"] != split_sha
                or [epoch["epoch"] for epoch in provenance["epochs"]] != epochs
                or not provenance["runtime"]):
            raise ValueError(f"{directory.name} is incomplete or references a different split")
        verify_adapter(directory, provenance)
        held_out = json.loads((directory / "predictions.json").read_bytes())
        if held_out.keys() != {pid for pid, row in ledger.items() if row["fold"] == fold}:
            raise ValueError(f"{directory.name} predictions do not cover the held-out pairs")
        for pid, pred in held_out.items():
            verify_prediction(pid, pred, ledger[pid], pilot[pid])
        folds.append(provenance)
        predictions.update(held_out)
    scores = summarize(predictions)
    if scores != summary["scores"]:
        raise ValueError("Fold predictions do not reproduce the trainer summary")
    return {
        "split_sha256": split_sha, "scores": summary["scores"],
        "schema": "eapg-grouped-pilot-results-v1", "split": split, "inputs_sha256": inputs_sha256,
        "folds": folds, "predictions": predictions,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path, help="Complete output directory from train_pilot_resplit.py")
    parser.add_argument("output", type=Path, help="New JSON path in an existing directory")
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise FileExistsError(f"Output already exists: {args.output}")
        data = json_bytes(assemble(args.run))
        with args.output.open("xb") as stream:
            stream.write(data)
    except (OSError, KeyError, TypeError, ValueError) as error:
        parser.exit(1, f"Cannot assemble pilot refit: {error}\n")


if __name__ == "__main__":
    main()
