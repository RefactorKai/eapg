"""Replay a controlled dependence-depth and overwritten-write stress case."""

import argparse
from hashlib import sha256
from pathlib import Path

from run_phase2_development import load_module
from score_synthetic import require
from synthetic_arms import predict_seed
from synthetic_frame import canonical, commitment


DEPTHS = (0, 1, 2, 4)
OVERWRITTEN = (0, 2, 8)
SIZES = (16, 32, 64, 128, 256, 512)
BEFORE = "i - 1"
AFTER = "0"
TEMPLATE = """#include <cstdio>
int main() {{
    int n = 0;
    std::scanf("%d", &n);
    volatile int cursor = 0;
    long long total = 0;
    for (int i = 1; i <= n; ++i) {{
{updates}
        while (cursor < i) {{
            ++cursor;
        }}
        total += cursor;
    }}
    std::printf("%lld\\n", total);
}}
"""


def build_original(depth, overwritten):
    updates = [f"cursor = {index + 1};" for index in range(overwritten)]
    if depth:
        updates.append(f"int start_0 = {BEFORE};")
        updates.extend(f"int start_{i} = start_{i - 1};" for i in range(1, depth))
        updates.append(f"cursor = start_{depth - 1};")
    else:
        updates.append(f"cursor = {BEFORE};")
    return TEMPLATE.format(updates="\n".join(f"        {line}" for line in updates))


def fit_profile(pipeline, normalized, nodes, outer, inner):
    runs = []
    for n in SIZES:
        # The edited cursor starts at zero on every trip and reaches the outer index.
        triangular = n * (n + 1) // 2
        counters = {}
        for node in nodes:
            nid, parent = node["id"], node["parent"]
            if nid == inner or parent == inner:
                count = triangular
            elif nid == outer or parent == outer:
                count = n
            else:
                require(parent in (None, "MAIN_SCOPE"), f"Unexpected scope in the analytic profile for {nid}")
                count = 1
            counters[nid] = {"cnt": count, "work": count}
        require(sum(cell["work"] for cell in counters.values()) < pipeline.compute_tick_ceiling(n),
                "Authored analytic profile would breach the tick ceiling")
        runs.append({"n": n, "status": "CLEAN_COMPLETION", "nodes": counters})
    fits = {}
    for node in nodes:
        nid = node["id"]
        fit = pipeline.fit_dual_family_scaling(SIZES, [row["nodes"][nid]["cnt"] for row in runs])
        fits[nid] = {"fit_hits": fit, "fit_work": fit}
    return {"normalized_sha256": sha256(normalized.encode()).hexdigest(), "nodes": nodes,
            "runs": {"42": runs}, "fits": {"42": fits}}


def run_cell(pipeline, depth, overwritten):
    original = build_original(depth, overwritten)
    require(original.count(BEFORE) == 1, "Authored edit must be unique")
    edited = original.replace(BEFORE, AFTER)
    edit_start = original.encode().index(BEFORE.encode())
    require(edited.encode()[:edit_start] + BEFORE.encode() + edited.encode()[edit_start + len(AFTER):]
            == original.encode(), "Authored inverse did not restore the original bytes")
    normalized = pipeline.normalize_synthetic_braces(edited)
    require(normalized == edited and not pipeline.parser.parse(edited.encode()).root_node.has_error,
            "Expected an already-braced authored source without preprocessing dependencies")
    nodes = pipeline.extract_macro_nodes(normalized, {})
    outer, inner = [node["id"] for node in nodes if node["role"] == "LOOP"]
    require([node["source_preview"] for node in nodes if node["parent"] == inner] == ["++cursor;"],
            "Analytic counts cover precisely one inner body node")
    owners = [(node["normalized_span"][1] - node["normalized_span"][0], node["id"]) for node in nodes
              if node["normalized_span"][0] <= edit_start < node["normalized_span"][1]]
    shortest = min(width for width, _ in owners)
    edit, = (node_id for width, node_id in owners if width == shortest)
    require(next(node for node in nodes if node["id"] == edit)["role"] == "STATE_UPD", "Unexpected edit node")
    profile = fit_profile(pipeline, normalized, nodes, outer, inner)
    pred = predict_seed(pipeline, normalized, profile, 42)
    scoped, conventional = (pred["arms"][arm] for arm in ("work_scoped", "work_conventional"))
    require(scoped["symptom_id"] == conventional["symptom_id"] == inner, "Expected same selected inner-loop symptom")
    require(all(arm["status"] == "ranked" for arm in (scoped, conventional)), "Both slicing arms must be supported")
    require((edit in scoped["candidates"]) == (depth == 0) and edit in conventional["candidates"],
            "Scope should lose only the indirect edits and conventional should retain every edit")
    require(len(scoped["candidates"]) == overwritten + 2, "Scoped candidate count must include every overwritten write")
    require(len(set(scoped["candidates"]) - set(conventional["candidates"])) == overwritten,
            "Conventional slice should exclude all overwritten writes")
    return {"depth": depth, "overwritten_writes": overwritten, "reference": edit,
            "evaluated_source_sha256": profile["normalized_sha256"],
            "canonical_nodes": [{"id": node["id"], "span": node["normalized_span"], "role": node["role"]} for node in nodes],
            "analytic_runs": profile["runs"]["42"], "prediction": pred}


def run(pipeline):
    cells = [run_cell(pipeline, depth, overwritten) for depth in DEPTHS for overwritten in OVERWRITTEN]
    for index, depth in enumerate(DEPTHS):
        group = cells[index * len(OVERWRITTEN):(index + 1) * len(OVERWRITTEN)]
        sizes = {len(cell["prediction"]["arms"]["work_conventional"]["candidates"]) for cell in group}
        require(sizes == {6 + depth}, "Conventional closure should grow with chain depth and ignore overwritten definitions")
    return {"schema": "eapg-authored-scope-boundary-v1", "profile_type": "analytic",
            "pipeline_sha256": pipeline.source_sha256,
            "software_sha256": {name: sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                for name in ("probe_scope_boundary.py", "synthetic_arms.py", "backward_slice.py")},
            "sizes": SIZES, "cells": cells}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--pipeline", type=Path, required=True)
    cli.add_argument("--pipeline-sha256", required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    if args.output.exists() or not args.output.parent.is_dir():
        cli.error("Choose a new output path in an existing directory")
    report = run(load_module("scope_boundary_pipeline", args.pipeline, args.pipeline_sha256))
    with args.output.open("xb") as stream:
        stream.write(canonical(report))
    print(f"{commitment(report)}  {args.output.name}")


if __name__ == "__main__":
    main()
