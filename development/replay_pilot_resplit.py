"""Verify and replay the grouped synthetic refit from saved predictions on CPU."""

from hashlib import sha256
import json

from replay_pilot_contrast import PILOT, ROOT, verified_json
from train_pilot_resplit import summarize


def main():
    if not __debug__:
        raise RuntimeError("Run without Python optimization so assertions remain active")
    report = json.loads((ROOT / "artifacts/pilot_resplit/results.json").read_bytes())
    split, predictions = report["split"], report["predictions"]
    split_sha = sha256((json.dumps(split, indent=2, allow_nan=False) + "\n").encode()).hexdigest()
    assert split_sha == report["split_sha256"]
    for name, expected in report["inputs_sha256"].items():
        assert sha256((ROOT / name).read_bytes()).hexdigest() == expected, name

    ledger = split["pairs"]
    pilot = {row["pair_id"]: row for row in verified_json(PILOT / "pilot100_results.json")}
    assert ledger.keys() == predictions.keys() == pilot.keys()
    owners = {}
    fold_sizes = []
    for fold in report["folds"]:
        index = fold["fold"]
        assert fold["status"] == "COMPLETE" and fold["split_sha256"] == split_sha
        fold_sizes.append(sum(row["fold"] == index for row in ledger.values()))
    assert [fold["fold"] for fold in report["folds"]] == list(range(5)) and all(fold_sizes)
    for pid, pred in predictions.items():
        entry, row = ledger[pid], pilot[pid]
        assert entry["problem_id"] == row["problem_id"] and pred["fold"] == entry["fold"]
        assert pred["group"] == entry["group"] and pred["reference"] == row["gt_node"]
        assert pred["candidates"] == row["slicing"]["c_pruned"]
        for key in ("problem_id", "group", "prompt_sha256"):
            assert owners.setdefault((key, entry[key]), entry["fold"]) == entry["fold"]
        for method in ("adapted", "base", "symbolic"):
            assert sorted(pred[method]) == sorted(pred["candidates"])
        for method in ("adapted", "base"):
            scores = pred[f"{method}_logits"]
            assert scores.keys() == set(pred["candidates"])
            assert pred[method] == sorted(pred["candidates"], key=scores.get, reverse=True)

    scores = summarize(predictions)
    assert scores == report["scores"]
    print(f"Replayed {len(predictions)} grouped pilot predictions across folds {fold_sizes}.")
    print(json.dumps(scores, indent=2))


if __name__ == "__main__":
    main()
