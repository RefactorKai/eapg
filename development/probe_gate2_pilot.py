"""Stress-test the candidate on a fixed set of published synthetic slow programs."""

import argparse
from hashlib import sha256
import json
from pathlib import Path

from gate1_sandbox import execute
from run_phase2_development import (
    ProfileFailure, compile_instrumented, compile_stage, load_module, load_pipeline,
    normalize, process_status, rank_by_seed, run_profile,
)


RELEASE = Path(__file__).resolve().parents[1]
PIPELINE_SHA = "7c855651566c1a7dc003fdcb291d8edd3ff1a99c671f781eb595d72c492ae743"
PILOT_SHA = "4a3b563cdd54c471f39df95e7d40ec3ae5433259795cadcde80272955ea44cb5"
SIZES = (2, 4, 8, 16, 32, 64)


def reference(published, frozen_nodes, candidate_nodes):
    label = published["gt_node"]
    target = next((node for node in frozen_nodes if node["id"] == label), None)
    if target is None or len(frozen_nodes) != published["v_slow"]:
        return {"status": "FROZEN_NODE_MAP_MISMATCH", "frozen_id": label}
    signature = (target["role"], target["source_preview"])
    anchor = next((line.split("|", 8) for line in published["skeleton"].splitlines()
                   if line.split("|", 1)[0].strip() == label), None)
    if anchor is None or (anchor[1].strip(), anchor[-1].strip()) != (signature[0], signature[1][:26].strip()):
        return {"status": "PUBLISHED_ANCHOR_MISMATCH", "frozen_id": label}
    matches = [node["id"] for node in candidate_nodes if (node["role"], node["source_preview"]) == signature]
    return {"status": "RESOLVED" if len(matches) == 1 else "CANDIDATE_ANCHOR_AMBIGUOUS_OR_MISSING",
            "frozen_id": label, "role": signature[0], "preview": signature[1], "matching_ids": matches}


def stress_pair(frozen, candidate, published, generated):
    source = generated["slow_code"]
    if source != published["slow_code"]:
        raise ValueError(f"Generator and published slow source differ for {published['pair_id']}")
    result = {key: published[key] for key in ("pair_id", "mechanism_id")}
    result["runs"] = []
    clean = []
    try:
        normalized, aliases = normalize(candidate, source)
        nodes = candidate.extract_macro_nodes(normalized, aliases)
        result["reference"] = reference(published, frozen.extract_macro_nodes(normalized, aliases), nodes)
        plain = compile_stage("plain slow build", source)
        instrumented = compile_instrumented(candidate, normalized, nodes)
        for n in SIZES:
            data = generated["input_gen"](n).encode()
            row = {"n": n}
            result["runs"].append(row)
            try:
                actual, record = run_profile(candidate, instrumented, data, n, nodes)
                row.update(status=record["status"], total_ticks=record["total_ticks"])
                if record["status"] == "CAP_BREACHED":
                    continue
                expected = execute(plain, data)
                if process_status(expected) != "CLEAN_COMPLETION":
                    raise ProfileFailure(process_status(expected), "Plain slow run failed", expected)
                if actual.stdout != expected.stdout:
                    raise ProfileFailure("OUTPUT_MISMATCH", "Instrumented stdout differed from plain slow stdout")
                clean.append((n, record["nodes"]))
            except ProfileFailure as exc:
                row.update(exc.details)
    except ProfileFailure as exc:
        return dict(result, status=exc.details["status"], failure=exc.details)

    if any(row["status"] not in ("CLEAN_COMPLETION", "CAP_BREACHED") for row in result["runs"]):
        return dict(result, status="UNEXPECTED_RUN_FAILURE")
    if len(clean) < 4 or clean[-1][0] < 8 * clean[0][0]:
        return dict(result, status="INSUFFICIENT_SCALING_SIZES")
    sizes, counters = zip(*clean)
    fits = {node["id"]: {
        channel: candidate.fit_dual_family_scaling(sizes, [row[node["id"]][key] for row in counters])
        for channel, key in (("fit_hits", "cnt"), ("fit_work", "work"))
    } for node in nodes}
    selection = rank_by_seed(candidate, {"nodes": nodes, "fits": {"fixed": fits}})["fixed"]
    target = result["reference"]
    if target["status"] == "RESOLVED":
        target_id, = target["matching_ids"]
        ranked = selection["ranked_candidates"]
        target.update(retained=target_id in ranked, rank=ranked.index(target_id) + 1 if target_id in ranked else None)
    return dict(result, status="PROFILED", clean_sizes=sizes, selection=selection)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--pipeline", type=Path, required=True)
    args = cli.parse_args()
    raw = (RELEASE / "artifacts/scope_isolated_pilot/pilot100_results.json").read_bytes()
    if sha256(raw).hexdigest() != PILOT_SHA:
        raise ValueError("Published synthetic pilot hash mismatch")
    first = {}
    pairs = sorted(json.loads(raw), key=lambda pair: pair["pair_id"])
    for pair in pairs:
        first.setdefault(pair["mechanism_id"], pair["pair_id"])
    selected = set(first.values()) | {f"PAIR_{i:03}" for i in range(33, 37)}
    frozen = load_module("frozen_pilot_generator", RELEASE / "pipeline.py", PIPELINE_SHA)
    generated = {pair["pair_id"]: pair for pair in frozen.generate_pilot_100_corpus()}
    candidate = load_pipeline(args.pipeline)
    rows = [stress_pair(frozen, candidate, pair, generated[pair["pair_id"]])
            for pair in pairs if pair["pair_id"] in selected]
    print(json.dumps({"candidate_sha256": candidate.source_sha256, "pilot_sha256": PILOT_SHA,
                      "sizes": SIZES, "pairs": rows}, indent=2))


if __name__ == "__main__":
    main()
