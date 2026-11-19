"""Build or replay the public authored paired-study evidence bundle."""

import argparse
from pathlib import Path

from . import panel, predict, score


HERE = Path(__file__).resolve().parent
DOCS = HERE.parents[1] / "docs"
PRIMARY_COMPARATOR = "value_impact"
DISPLAY = {
    "rewind": "Rewind attribution",
    "value_impact": "Value-sensitive change impact",
    "change_impact": "Change impact",
    "entry_vote": "Entry definition vote",
    "target_hotspot": "Target hotspot",
    "local_count": "Local count difference",
    "diff_order": "Diff source order",
}


def committed_hash(path):
    return predict.digest(path.read_bytes())


def make_registration(traces):
    cases = [
        {**{key: case[key] for key in ("id", "span_map_sha256", "units")}, "group": panel.GROUP}
        for case in traces["cases"]
    ]
    if {row["id"] for row in cases} != {case.id for case in panel.CASES}:
        raise ValueError("Authored panel inventory differs from the registered fixture")
    return {
        "schema": score.REGISTRATION_SCHEMA,
        "phase": "development",
        "population": panel.GROUP,
        "seed": 42,
        "arms": list(predict.ARMS),
        "candidate": "rewind",
        "comparator": PRIMARY_COMPARATOR,
        "pins": {
            "protocol": committed_hash(DOCS / "RESEARCH_REWORK_PLAN.md"),
            "draw": predict.digest(score.json_bytes(cases)),
            "groups": predict.digest(predict.canonical({case["id"]: case["group"] for case in cases})),
            "methods": committed_hash(Path(predict.__file__)),
            "analysis": committed_hash(Path(score.__file__)),
        },
        "cases": cases,
        "gates": None,
    }


def make_evaluation(oracle, registration_sha):
    if oracle["schema"] != "eapg.paired.authored-oracle.v1" or oracle["group"] != panel.GROUP:
        raise ValueError("This demonstration accepts only the public authored oracle")
    rows = []
    for case in oracle["cases"]:
        if (case["group"] != panel.GROUP
                or case["span_map_sha256"] != panel.digest(panel.canonical_bytes(case["span_map"]))):
            raise ValueError(f"Authored source map mismatch for {case['id']}")
        rows.append({
            **{key: case[key] for key in ("id", "span_map_sha256", "status", "location",
                                         "mechanism", "timing", "acceptable_sets")},
            "receipt_sha256": predict.digest(predict.canonical(case)),
        })
    return {"schema": score.EVALUATION_SCHEMA, "registration_sha256": registration_sha, "cases": rows}


def table(report):
    rows = [
        r"% Authored development fixtures from one family. Descriptive counts.",
        r"\begin{tabular}{lrrr}",
        r"\toprule",
        r"Method & Top-1 & Top-2 & Negative alerts \\",
        r"\midrule",
    ]
    for arm, name in DISPLAY.items():
        summary = report["arms"][arm]
        values = [f"{summary[key]['count']}/{summary[key]['total']}"
                  for key in ("top1", "top2", "negative_alerts")]
        rows.append(f"{name} & {' & '.join(values)} " + r"\\")
    rows.extend([r"\bottomrule", r"\end{tabular}"])
    return "\n".join(rows) + "\n"


def replay(traces_path, traces_sha, oracle_path, oracle_sha, output):
    # The authored oracle is public. The prediction function receives only registration and traces.
    traces = predict.read_pinned(traces_path, traces_sha)
    predict.validate_traces(traces)
    registration = make_registration(traces)
    registration_sha = predict.digest(predict.canonical(registration))
    oracle = predict.read_pinned(oracle_path, oracle_sha)
    evaluation = make_evaluation(oracle, registration_sha)
    evaluation_sha = predict.digest(predict.canonical(evaluation))
    selection = score.select(registration, evaluation, registration_sha, evaluation_sha)
    selection_sha = predict.digest(score.json_bytes(selection))
    predictions, evidence = predict.predict(traces, registration, registration_sha)
    predictions_sha = predict.digest(predict.canonical(predictions))
    report = score.score(registration, evaluation, predictions, registration_sha, selection_sha,
                         evaluation_sha=evaluation_sha, predictions_sha=predictions_sha)

    output.mkdir(parents=True, exist_ok=False)
    files = {
        "registration": registration, "evaluation": evaluation, "predictions": predictions,
        "attribution": {"traces_sha256": traces_sha, "cases": evidence},
        "scores": report,
    }
    pins = {f"{name}.json": predict.write_new(output / f"{name}.json", value)
            for name, value in files.items()}
    (output / "selection.json").write_bytes(score.json_bytes(selection))
    (output / "descriptive_table.tex").write_bytes(table(report).encode())
    pins["selection.json"] = committed_hash(output / "selection.json")
    pins["descriptive_table.tex"] = committed_hash(output / "descriptive_table.tex")
    predict.write_new(output / "manifest.json", {
        "schema": "eapg.paired.demo-manifest.v1",
        "scope": "authored controls, one family, descriptive",
        "inputs": {"traces.json": traces_sha, "oracle.json": oracle_sha},
        "outputs": pins,
    })
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Execute the authored Gate 1 panel and score it")
    run.add_argument("output", type=Path, help="New output directory")
    saved = commands.add_parser("replay", help="Score independently pinned existing panel receipts")
    saved.add_argument("output", type=Path, help="New replay directory")
    saved.add_argument("--panel", type=Path, required=True)
    saved.add_argument("--traces-sha256", required=True)
    saved.add_argument("--oracle-sha256", required=True)
    args = parser.parse_args(argv)
    if args.command == "run":
        if args.output.exists():
            parser.error("choose a new output directory")
        panel_path = args.output / "panel"
        panel.run_panel(panel_path)
        output = args.output / "analysis"
        traces_sha = committed_hash(panel_path / "traces.json")
        oracle_sha = committed_hash(panel_path / "oracle.json")
    else:
        panel_path, output = args.panel, args.output
        traces_sha, oracle_sha = args.traces_sha256, args.oracle_sha256
    report = replay(panel_path / "traces.json", traces_sha, panel_path / "oracle.json", oracle_sha, output)
    print(f"Scored {report['flow']['drawn_pairs']} authored cases in "
          f"{report['flow']['drawn_groups']} family. Outputs: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
