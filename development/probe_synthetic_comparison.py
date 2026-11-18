"""Profile authored cases and write separate draw, reference, and prediction ledgers."""

import argparse
from hashlib import sha256
import json
from math import log
from pathlib import Path
from statistics import linear_regression
import sys

from build_reference_packet import build_packet
from probe_synthetic_intervention import AFTER, BEFORE, FAST, HIGH_GROWTH, square, triangular
from run_phase2_development import load_pipeline, normalize, profile_side
from synthetic_arms import ARM_IDS, predict_seed


HERE = Path(__file__).resolve().parent
SIZES = (8, 16, 32, 64, 128, 256)
SEEDS = (42, 43, 44)
SHAM = "cursor = i + (-1);"


def digest(value):
    return sha256(value.encode()).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def run(pipeline, output):
    slow = FAST.replace(BEFORE, AFTER)
    sham = FAST.replace(BEFORE, SHAM)
    for edited, replacement in ((slow, AFTER), (sham, SHAM)):
        if FAST.count(BEFORE) != 1 or edited.count(replacement) != 1 or edited.replace(replacement, BEFORE) != FAST:
            raise ValueError("Expected one byte-reversible authored edit")
    cases = (
        ("authored-01", "cursor-family", "positive_off_site", slow, triangular),
        ("authored-02", "pair-enumeration-family", "appropriate_superlinear", HIGH_GROWTH, square),
        ("authored-03", "cursor-family", "same_growth_sham", sham, triangular),
    )
    workloads = {pid: [{"n": n, "seed": seed, "stdin": f"{n}\n", "expected_stdout": f"{oracle(n)}\n"}
                       for seed in SEEDS for n in SIZES] for pid, _, _, _, oracle in cases}
    slots = [{"case_id": pid, "intended_slot": slot, "source_sha256": digest(source),
              "workload_sha256": sha256(encoded(workloads[pid])).hexdigest()} for pid, _, slot, source, _ in cases]
    protocol = digest("Authored synthetic comparison fixture v1")
    draw = {"schema": "eapg-synthetic-draw-v1", "protocol_sha256": protocol,
            "frame_sha256": sha256(encoded(slots)).hexdigest(), "draw_seed": 42,
            "allocation": {slot: 1 for _, _, slot, _, _ in cases}, "cases": slots}
    draw_sha = sha256(encoded(draw)).hexdigest()

    labels, profiles = [], {}
    for pid, family, slot, source, _ in cases:
        profile = profile_side(pipeline, source, workloads[pid])
        nodes = profile["nodes"]
        ids = [node["id"] for node in nodes]
        positive = slot == "positive_off_site"
        appropriate = slot == "appropriate_superlinear"
        preview = "++total;" if appropriate else "++cursor;"
        count_node, = (node["id"] for node in nodes if node["source_preview"] == preview)
        expected = [triangular(n) if positive else square(n) if appropriate else n for n in SIZES]
        for rows in profile["runs"].values():
            if any(row["status"] != "CLEAN_COMPLETION" for row in rows):
                raise ValueError(f"{pid} did not complete all authored sizes")
            if [row["nodes"][count_node]["cnt"] for row in rows] != expected:
                raise ValueError(f"{pid} counter disagrees with the authored operation formula")
        evidence = sha256(encoded({"sizes": SIZES, "operation_counts": expected,
                                  "inverse_counts": None if appropriate else SIZES})).hexdigest()
        accepted = []
        if positive:
            # The development fixture verifies only the affected operation, not the full-study inventory.
            inverse = profile_side(pipeline, FAST, workloads[pid])
            inverse_node, = (node["id"] for node in inverse["nodes"] if node["source_preview"] == preview)
            if any(any(row["status"] != "CLEAN_COMPLETION" for row in rows)
                   or [row["nodes"][inverse_node]["cnt"] for row in rows] != list(SIZES)
                   for rows in inverse["runs"].values()):
                raise ValueError("Authored inverse failed the operation formula")
            ratios = [triangular(n) / n for n in SIZES]
            slope = linear_regression([log(n) for n in SIZES], [log(ratio) for ratio in ratios]).slope
            if slope < 0.70 or ratios[-1] < 1.50:
                raise ValueError("Authored count ratio did not clear the strong-positive fixture thresholds")
            packet = build_packet(pipeline, {
                "pair_id": pid, "problem_spec": "Sum integers from 1 through N",
                "slow_code": slow, "fast_code": FAST, "protocol_sha256": protocol,
                "independent_evidence": {"record_sha256": evidence, "summary": "Authored closed-form count"},
                "profile": {"pipeline_sha256": pipeline.source_sha256, "canonical_node_ids": ids,
                            "normalized_source_sha256": profile["normalized_sha256"]},
            })
            line = slow.count("\n", 0, slow.index(AFTER)) + 1
            node, = (node["node_id"] for node in packet["pass2_map"]["nodes"]
                     if node["role"] == "STATE_UPD" and node["raw_source_lines"] == [line])
            accepted = [node]
        disposition = {"positive_off_site": "confirmed_positive", "appropriate_superlinear": "confirmed_appropriate",
                       "same_growth_sham": "confirmed_sham"}[slot]
        labels.append({"case_id": pid, "family_id": family, "disposition": disposition,
                       "normalized_source_sha256": profile["normalized_sha256"], "canonical_node_ids": ids,
                       "accepted_node_ids": accepted, "reference_status": "resolved" if positive else None,
                       "reference_reason": None, "operation_evidence_sha256": evidence})
        profiles[pid] = (normalize(pipeline, source)[0], profile)
    source_manifest = {"drawn": slots, "cursor_inverse_sha256": digest(FAST)}
    label_ledger = {"schema": "eapg-synthetic-labels-v1", "draw_sha256": draw_sha,
                    "source_manifest_sha256": sha256(encoded(source_manifest)).hexdigest(),
                    "quarantine_sha256": digest("Two authored development families only"), "cases": labels}
    labels_sha = sha256(encoded(label_ledger)).hexdigest()

    predictions = [dict(predict_seed(pipeline, normalized, profile, seed), case_id=pid)
                   for pid, (normalized, profile) in profiles.items() for seed in SEEDS]
    positive = predictions[0]["arms"]
    if any(positive[name]["status"] != "ranked" for name in ARM_IDS):
        raise ValueError(f"Expected all arms to rank the authored intervention: {positive}")
    if positive["work_scoped_symbolic"]["ranking"][0] != labels[0]["accepted_node_ids"][0]:
        raise ValueError("Authored intervention did not reproduce the symbolic reference")
    if any(row["arms"]["work_scoped"]["alert"] is not (row["case_id"] != "authored-03")
           for row in predictions):
        raise ValueError("Authored control alerts did not match development expectations")
    runner_sha = sha256(encoded({p.name: sha256(p.read_bytes()).hexdigest() for p in
                                 (Path(__file__), HERE / "synthetic_arms.py",
                                  HERE / "run_phase2_development.py")})).hexdigest()
    prediction_ledger = {
        "schema": "eapg-synthetic-predictions-v1", "draw_sha256": draw_sha,
        "labels_sha256": labels_sha, "runner_sha256": runner_sha, "pipeline_sha256": pipeline.source_sha256,
        "baseline_sha256": sha256((HERE / "backward_slice.py").read_bytes()).hexdigest(),
        "arm_ids": list(ARM_IDS), "predictions": predictions,
    }
    output.mkdir()
    for name, ledger in (("draw", draw), ("labels", label_ledger), ("predictions", prediction_ledger)):
        raw = encoded(ledger)
        with (output / f"{name}.json").open("xb") as stream:
            stream.write(raw)
        print(f"{sha256(raw).hexdigest()}  {name}.json")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--pipeline", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    if sys.platform != "linux" or args.output.exists():
        cli.error("Use the Linux fixture environment and a fresh output directory")
    run(load_pipeline(args.pipeline), args.output)


if __name__ == "__main__":
    main()
