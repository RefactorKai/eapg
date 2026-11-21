"""Rebuild the published development tables and verify their indexed evidence."""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
from runpy import run_path
from statistics import median
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CORPORA = ("PIE validation", "CppPerf")
PREFIX = "artifacts/paired_development/"
ARCHIVED_SHA = "3d12f67f151c5daf4363575c8476f0bdb4ae487c6960aadd7b8d14d7720fffcd"
RESULTS = ("precedence-sweep.json", "desk-agreement-existing.json", "desk-agreement-reaudit.json")
PUBLIC_REQUIRED = {
    *(PREFIX + name for name in ("README.md", "ledger.json", "tables.md", "replay.py", "historical-ledger.json",
                                  "historical-tables.md", "historical-manifest.json", "a01-steady.json",
                                  "precedence_sweep.py", "desk_agreement.py", *RESULTS)),
    *("development/paired_study/" + name for name in ("census.py", "prescreen.py", "path_b_cases.py",
      "path_b_run.py", "path_b_close.py", "steady.py", "fixtures/a01_steady.cpp", "predict.py", "intake.py",
      "score.py", "timing.py", "panel.py", "fixtures/ranked_queries.cpp.in")),
    "development/gate1_sandbox.py", "development/probe_gate1.py", "docs/PAIRED_STUDY_INTAKE.md",
    "docs/PAIRED_STUDY_RUNBOOK.md", "requirements-ast.txt",
}
SEALED = {"pie_test.jsonl", "pie_merged_testcases.tar.gz", "pie_test_static_manifest.json"}
ARTIFACT_SCHEMA = "eapg.path-b.artifact.v1"


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_bytes())


def verify_index(files: dict[str, str]) -> None:
    for name, expected in files.items():
        path = (REPO / name).resolve()
        if not path.is_relative_to(REPO) or digest(path) != expected:
            raise ValueError(f"Artifact SHA-256 mismatch: {name}")


def counts(rows: list[dict]) -> dict[str, int]:
    return {
        "draw": len(rows),
        "a_pass": sum(row["phase_a"] == "eligible" for row in rows),
        "b_preprocess_only": sum(row["phase_b"] == "unsupported_dependencies" for row in rows),
        "b_executed": sum(row["phase_b"] in {"oracle_confirmed", "output_mismatch"} for row in rows),
        "b_validated": sum(row["phase_b"] == "oracle_confirmed" for row in rows),
        "b_wrong": sum(row["phase_b"] == "output_mismatch" for row in rows),
        "screened": sum(row["screen"] in {"no_alert", "alert"} for row in rows),
        "positive": sum(row["screen"] == "alert" for row in rows),
        "ranked": sum(row["ranking_eligible"] for row in rows),
    }


def render(ledger: dict) -> str:
    rows = ledger["cases"]
    if ledger["schema"] != "eapg.paired.development-ledger.v1" or len({r["id"] for r in rows}) != 24:
        raise ValueError("Expected the fixed 24 distinct development slots.")
    if Counter(r["corpus"] for r in rows) != dict.fromkeys(CORPORA, 12) or len(rows) != 24:
        raise ValueError("Expected 12 cases per corpus.")
    for row in rows:
        eligible = row["phase_a"] == "eligible"
        reached_b = row["phase_b"] in {"oracle_confirmed", "output_mismatch", "unsupported_dependencies"}
        fitted = row["screen"] in {"no_alert", "alert"}
        if eligible != reached_b or fitted != (row["phase_b"] == "oracle_confirmed"):
            raise ValueError(f"Inconsistent flow for {row['id']}.")
        if ("metric" in row) != fitted or bool(row.get("finite_range")) != fitted or (
            row["ranking_eligible"] and row["screen"] != "alert"
        ):
            raise ValueError(f"Inconsistent evidence for {row['id']}.")

    lines = [
        "# Paired development evidence", "",
        "The intake denominator is the fixed development draw. Isolated execution excludes",
        "dependency-only preprocessing. Numeric sample rows report logical operations in",
        "target, reference, restoration and sham order. Metrics vary across cases.", "",
        "| Corpus | Drawn | A eligible | B dependency-only stops | B executed | Output-oracle failures | Verified restorations | Screened | Growth alerts | Ranking eligible |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    flow_keys = ("draw", "a_pass", "b_preprocess_only", "b_executed", "b_wrong", "b_validated", "screened", "positive", "ranked")
    for corpus in CORPORA:
        flow = counts([r for r in rows if r["corpus"] == corpus])
        lines.append(f"| {corpus} | " + " | ".join(str(flow[key]) for key in flow_keys) + " |")
    flow = counts(rows)
    lines.append("| **Total** | " + " | ".join(str(flow[key]) for key in flow_keys) + " |")
    lines.extend([
        "", f"Desk feasibility was {flow['a_pass']}/{flow['draw']}. Of those eligible,",
        f"{flow['b_executed']}/{flow['a_pass']} ran and {flow['b_validated']}/{flow['b_executed']}",
        f"of the executed cases validated a scoped restoration. All {flow['screened']}",
        f"verified cases were screened and {flow['positive']}/{flow['screened']} alerted.",
        f"Full alignment and mutual ranking support were available for {flow['ranked']}/{flow['draw']}",
        "natural cases. Natural localization ties and abstention rates have no eligible",
        "denominator. The final verified controls had no recorded count caps. All draw",
        "slots have dispositions. Annotation time and overlap beyond the drawn group",
        "identifiers were not measured. External labels were collected for 0/24 cases.",
        "", "## Verified scoped restorations", "",
        "The fit uses the screened event. Each pair gives the target/reference count ratio",
        "at the largest common size and the slope of the log ratio against log size.",
        "The example input can be smaller than the largest common size.",
        "An alert requires a ratio ≥1.50× and slope ≥0.50 on every registered stream.", "",
        "| Case | Restoration event | Example input | Target / reference / restoration / sham | Screened event and counts when distinct | Largest ratio / slope by stream | Screen |",
        "|---|---|---|---|---|---|---|",
    ])
    for row in rows:
        if "metric" in row:
            example = " / ".join(f"{count:,}" for count in row["sample_counts"])
            screened = "Same event"
            if sample := row.get("screen_sample"):
                totals = " / ".join(f"{count:,}" for count in sample["counts"])
                screened = f"{sample['metric']} ({totals})"
            fits: dict[tuple[float, float], list[str]] = {}
            for stream in row["finite_range"]:
                fit = stream["largest_ratio"], stream["slope"]
                fits.setdefault(fit, []).append(stream["stream"])
            ratios = "<br>".join(
                f"{', '.join(streams)} ({ratio:.6g}× / {slope:.6g})"
                for (ratio, slope), streams in fits.items()
            )
            lines.append(
                f"| `{row['id']}` | {row['metric']} | {row['sample_input']} | "
                f"{example} | {screened} | {ratios} | `{row['screen']}` |"
            )
    for corpus in CORPORA:
        lines.extend([
            "", f"## {corpus} dispositions", "",
            "| Case | Phase A | Phase B | Evidence |",
            "|---|---|---|---|",
        ])
        for row in rows:
            if row["corpus"] == corpus:
                lines.append(f"| `{row['id']}` | {row['phase_a'].replace('_', ' ')} | "
                             f"{row['phase_b'].replace('_', ' ')} | {row['reason']} |")
    lines.extend([
        "", "No natural case met the prerequisites for the paired ranking comparison.",
        "The authored comparison remains a separate one-family experiment. Rewind ranked",
        "5/6 positives first and value-sensitive change impact ranked 6/6 first. Both",
        "reported 0/4 control alerts. The authored a01 timing result remained unconfirmed.",
        "", "Neither external adjudication nor held-out evaluation is part of this artifact.",
    ])
    return "\n".join(lines) + "\n"


def path_b_groups(ledger):
    rows = ledger["rows"]
    groups = {
        "147 distinct": rows,
        "PIE 77": [r for r in rows if r["corpus"] == "pie-validation"],
        "CppPerf 42": [r for r in rows if r["corpus"] == "cppperf-census"],
        "119 census": [r for r in rows if r["census_slot"] is not None],
        "Significant 34": [r for r in rows if r["stratum_slot"] is not None],
    }
    if (ledger["held_out_used"] is not False or
            not all(type(r["intake_rank"]) is int for r in rows) or
            [r["intake_rank"] for r in rows] != list(range(1, 148)) or
            [len(group) for group in groups.values()] != [147, 77, 42, 119, 34] or
            sum(r["stratum_slot"] is not None for r in groups["CppPerf 42"]) != 6):
        raise ValueError("Path B frame membership mismatch")
    for name, field, size in (("PIE 77", "census_slot", 77), ("CppPerf 42", "census_slot", 42),
                              ("Significant 34", "stratum_slot", 34)):
        if sorted(r[field] for r in groups[name]) != list(range(1, size + 1)):
            raise ValueError(f"Missing or duplicate membership in {name}")
    if len({(r["case_id"], r["target"], r["reference"]) for r in rows}) != 147:
        raise ValueError("Duplicate oriented pair")
    return groups


def validate_timing(timing):
    if (timing["schema"], timing["held_out_used"], timing["bridge_size"], timing["warmup_pairs"],
            timing["measured_pairs"], timing["seed"], timing["ubsan_clean"]) != (
                "eapg.path-b.a01-steady.v1", False, 256, 2, 8, 42, True):
        raise ValueError("Authored timing identity or measurement boundary mismatch")
    if timing["launcher_sha256"] != digest(REPO / "development/gate1_sandbox.py"):
        raise ValueError("Authored timing launcher mismatch")
    streams = ("dense", "plateau", "curved")
    sizes = [256, 512, 1024, 2048, 4096, 8192]
    observations = {(row["stream"], row["size"]): row for row in timing["rows"]}
    if (set(timing["screens"]) != set(streams) or len(timing["rows"]) != 18
            or set(observations) != {(stream, size) for stream in streams for size in sizes}):
        raise ValueError("Incomplete authored timing coverage")
    fit = run_path(str(REPO / "development/paired_study/predict.py"))["calculate_fit"]
    passes = []
    for stream in streams:
        result = timing["screens"][stream]
        if [row["size"] for row in result["samples"]] != sizes:
            raise ValueError(f"Invalid timing ladder for {stream}")
        points = []
        for sample in result["samples"]:
            row = observations[stream, sample["size"]]
            if len(row["blocks"]) != 10 or [block[1] for block in row["blocks"]] != row["order"][1:]:
                raise ValueError(f"Invalid paired block order for {stream} {sample['size']}")
            values = [[], [], []]
            for batch, first, a, b, empty in row["blocks"][2:]:
                if first not in (0, 1) or not 1 <= batch <= 1024 or min(a, b, empty) <= 0:
                    raise ValueError("Invalid authored timing block")
                values[first].append(a / batch)
                values[1 - first].append(b / batch)
                values[2].append(empty / batch)
            for label, times in zip(("target", "reference", "empty"), values, strict=True):
                if sample[label] != {"min_ns": min(times), "median_ns": median(times), "max_ns": max(times)}:
                    raise ValueError(f"Authored timing block summary mismatch for {stream} {sample['size']}")
            points.append((sample["size"], median(values[0]), median(values[1])))
        summary = fit(points)
        passed = summary["slope"] >= .50 and summary["largest_ratio"] >= 1.50
        if (summary, fit(points[:-1]), passed) != (result["fit"], result["drop_largest"], result["passes_screen"]):
            raise ValueError(f"Authored timing screen mismatch for {stream}")
        passes.append(passed)
    if (timing["all_stream_alert"], timing["any_stream_alert"]) != (all(passes), any(passes)):
        raise ValueError("Authored timing verdict mismatch")


def render_path_b(ledger, timing):
    rows = ledger["rows"]
    groups = path_b_groups(ledger)
    disposition_counts = Counter(r["final_disposition"] for r in rows)
    if disposition_counts != ledger["totals"]:
        raise ValueError("Final dispositions do not reconcile")
    desk_bucket = run_path(str(HERE / "desk_agreement.py"))["desk_bucket"]
    desk_rows = {r["intake_rank"]: desk_bucket(r) for r in rows if r["final_disposition"] in
                 {"desk_excluded", "historical_desk_excluded", "desk_blocked"}}
    if Counter(desk_rows.values()) != {"source": 48, "contract": 48, "route": 7}:
        raise ValueError("Desk buckets do not reproduce the 103 stops")
    historical = read_json(HERE / "historical-ledger.json")
    inherited = {(r["target"], r["reference"]): r for r in historical["cases"] if r["phase_b"] == "oracle_confirmed"}
    fit = run_path(str(REPO / "development/paired_study/predict.py"))["calculate_fit"]
    fit_rows = []
    for row in rows:
        alerts = []
        rank = row["intake_rank"]
        archived = row["final_disposition"] == "verified_historical_control"
        if row["screen_status"] in {"alert", "no_alert"}:
            if not archived and (row["final_disposition"] != "verified_growth_evaluation" or
                                 row["phase_b"]["executed"] is not True):
                raise ValueError(f"Fitted rank {rank} lacks a verified execution")
            if (len(row["stream_screens"]) != 3 or len(row["registered_streams"]) != 3 or
                    {s["stream"] for s in row["stream_screens"]} != set(row["registered_streams"])):
                raise ValueError(f"Missing stream at intake slot {rank}")
            if archived:
                ancestor = inherited[(row["target"], row["reference"])]
                if ancestor["id"] != row["case_id"] or row["stream_screens"] != ancestor["finite_range"]:
                    raise ValueError(f"Historical fit mismatch at rank {rank}")
            for s in row["stream_screens"]:
                f = s.get("fit", s)
                if not archived:
                    points = [(p["size"], p["target"], p["reference"]) for p in s["points"]]
                    sizes = [p[0] for p in points]
                    if (sizes != sorted(set(sizes)) or len(sizes) < 4 or sizes[-1] < 8 * sizes[0]
                            or any(min(p) <= 0 for p in points) or fit(points) != f
                            or fit(points[:-1]) != s["drop_largest"]):
                        raise ValueError(f"Fit or drop-largest mismatch at rank {rank}")
                alerts.append(f["slope"] >= .50 and f["largest_ratio"] >= 1.50)
                fit_rows.append((row, s, f, ancestor["metric"] if archived else row["phase_b"]["events"][0]))
        expected = (all(alerts), any(alerts)) if alerts else (None, None)
        if (row["all_stream_alert"], row["any_stream_alert"]) != expected:
            raise ValueError(f"Alert verdict mismatch at slot {row['intake_rank']}")
    if (len(fit_rows), sum(r["all_stream_alert"] is True for r in rows),
            sum(r["any_stream_alert"] is True for r in rows)) != (39, 4, 4):
        raise ValueError("Unexpected fitted or alert count")
    lines = ["# Path B empirical census", "",
             "Six CppPerf patches share the project census and significant-test stratum. The overall",
             "denominator counts each patch once. Every slot has a final disposition.", "",
             "| Final disposition | " + " | ".join(groups) + " |",
             "|---|---:|---:|---:|---:|---:|"]
    for label in sorted(disposition_counts):
        values = [sum(r["final_disposition"] == label for r in group) for group in groups.values()]
        lines.append(f"| `{label}` | " + " | ".join(map(str, values)) + " |")
    lines.extend(["", "## Audit flow by frame", "", "| Stage | " + " | ".join(groups) + " |",
                  "|---|---:|---:|---:|---:|---:|"])
    for name, predicate in (
            ("Desk stops", lambda r: r["intake_rank"] in desk_rows),
            *((label, lambda r, bucket=name: desk_rows.get(r["intake_rank"]) == bucket)
              for name, label in (("source", "↳ Source-level witness"), ("contract", "↳ Contract-level gap"),
                                  ("route", "↳ Route-conditional desk stop"))),
            ("Eligible control or diagnostic deferred", lambda r: r["final_disposition"] == "desk_eligible_control_deferred"),
            ("Single-TU preprocessing stops", lambda r: r["final_disposition"] in
             {"historical_dependency_stop", "support_boundary_closed"}),
            ("↳ New dependency-only closure", lambda r: r["final_disposition"] == "support_boundary_closed"),
            ("↳ Historical dependency stop", lambda r: r["final_disposition"] == "historical_dependency_stop"),
            ("Reached isolated execution", lambda r: r["final_disposition"] in
             {"execution_oracle_failure", "verified_historical_control", "verified_growth_evaluation"}),
            ("↳ Oracle failure", lambda r: r["final_disposition"] == "execution_oracle_failure"),
            ("↳ Fitted historical controls", lambda r: r["final_disposition"] == "verified_historical_control"),
            ("↳ Fitted new growth evaluations", lambda r: r["final_disposition"] == "verified_growth_evaluation"),
            ("Total intake", lambda r: True)):
        lines.append(f"| {name} | " + " | ".join(str(sum(map(predicate, group))) for group in groups.values()) + " |")
    lines.extend(["", "## Fitted denominator and stream sensitivity", "",
                  "| Frame | Fitted | All streams | Any stream | Unfitted |",
                  "|---|---:|---:|---:|---:|"])
    for name, group in groups.items():
        fitted = sum(r["all_stream_alert"] is not None for r in group)
        lines.append(f"| {name} | {fitted} | {sum(r['all_stream_alert'] is True for r in group)} | "
                     f"{sum(r['any_stream_alert'] is True for r in group)} | {len(group) - fitted} |")
    project_counts = Counter(row["case_id"] for row in groups["Significant 34"])
    lines.extend(["", "Significant-test patches per project. " + ", ".join(
        f"`{name}` {count}" for name, count in sorted(project_counts.items())
    ) + ".", "", "## Desk exclusions and blocks", "",
                  "| Desk reason | Excluded | Blocked |", "|---|---:|---:|"])
    desk = Counter((row["phase_a"]["reason"], row["final_disposition"])
                   for row in rows if row["final_disposition"] in {"desk_excluded", "desk_blocked"})
    for reason in sorted({reason for reason, _ in desk}):
        lines.append(f"| `{reason}` | {desk[reason, 'desk_excluded']} | {desk[reason, 'desk_blocked']} |")
    lines.extend(["", "| Rank | Disposition | Bucket | Census | Stratum | Verbatim reason |",
                  "|---:|---|---|---:|---:|---|"])
    for rank, bucket in desk_rows.items():
        row = rows[rank - 1]
        reason = row["phase_a"]["reason"].replace("|", r"\|")
        lines.append(f"| {rank} | {row['final_disposition']} | {bucket} | {row['census_slot'] or '—'} | "
                     f"{row['stratum_slot'] or '—'} | {reason} |")
    lines.extend(["", "## All finite-range fits", "",
                  "Inherited summaries come from [historical-ledger.json](historical-ledger.json) and "
                  "[historical-tables.md](historical-tables.md). A dash marks unavailable grid details.", "",
                  "| Rank | Case | Origin | Scoped event | Stream | Largest ratio | Slope | Ratio pass | Slope pass |",
                  "|---:|---|---|---|---|---:|---:|---|---|"])
    for row, screen, fit_result, event in fit_rows:
        origin = "Historical" if row["final_disposition"] == "verified_historical_control" else "New"
        ratio, slope = fit_result["largest_ratio"], fit_result["slope"]
        lines.append(f"| {row['intake_rank']} | {row['case_id']} | {origin} | {event} | {screen['stream']} | "
                     f"{ratio:.6g} | {slope:.6g} | {ratio >= 1.50} | {slope >= .50} |")
    lines.extend(["", "## Dependency-only closures", "",
                  "| Intake slot | Case | Translation unit | First unavailable include |",
                  "|---:|---|---|---|"])
    for rank in ledger["support_closures"]:
        row = rows[rank - 1]
        prep = row["phase_b"]["preprocessing"]
        includes = sorted({result["diagnostic"].split("fatal error: ", 1)[1].split(": No such", 1)[0]
                           for result in prep["attempts"].values()})
        lines.append(f"| {rank} | {row['case_id']} | `{prep['unit']}` | "
                     + ", ".join(f"`{name}`" for name in includes) + " |")
    lines.extend(["", "## New isolated comparisons", "",
                  "Counts are target, reference, restoration and sham. The screen concerns the first",
                  "registered event. An empty drop-largest slope means the shorter grid lacks four",
                  "distinct sizes spanning eightfold.", "",
                  "| Case | Stream | Largest size | Four counts | Ratio | Slope | Drop-largest slope | Pass |",
                  "|---|---|---:|---|---:|---:|---:|---|"])
    for rank in ledger["execution_queue"]:
        row = rows[rank - 1]
        for screen in row["stream_screens"]:
            fit = screen["fit"]
            if fit is None or row["all_stream_alert"] is None:
                lines.append(f"| {row['case_id']} | {screen['stream']} | — | — | — | — | — | {row['screen_status']} |")
                continue
            size = screen["points"][-1]["size"]
            counts, = (m["counts"] for m in row["phase_b"]["measurements"]
                       if m["stream"] == screen["stream"] and m["size"] == size)
            values = " / ".join(str(counts[s][0]) for s in ("target", "reference", "restored", "sham"))
            drop = screen["drop_largest"]
            drop_text = f"{drop['slope']:.4f}" if drop else "—"
            passed = fit["slope"] >= .50 and fit["largest_ratio"] >= 1.50
            lines.append(f"| {row['case_id']} | {screen['stream']} | {size} | {values} | "
                         f"{fit['largest_ratio']:.4f} | {fit['slope']:.4f} | {drop_text} | {'yes' if passed else 'no'} |")
    lines.extend(["", "## Authored a01 steady-state timing", "",
                  "Medians are nanoseconds per full request. The historical no-op process median",
                  "was 731,000 ns and the startup-inclusive growth screen was unconfirmed.",
                  f"At dense size 256 the target median is {timing['screens']['dense']['samples'][0]['target']['median_ns']:.2f} ns. "
                  f"The historical control is {731000 / (731000 + timing['screens']['dense']['samples'][0]['target']['median_ns']):.1%} "
                  "of the sum of those separate medians.", "",
                  "| Stream | Size | Target median (ns) | Reference median (ns) | Empty median (ns) |",
                  "|---|---:|---:|---:|---:|"])
    for stream, value in timing["screens"].items():
        for row in value["samples"]:
            values = " | ".join(f"{row[side]['median_ns']:.2f}" for side in ("target", "reference", "empty"))
            lines.append(f"| {stream} | {row['size']} | {values} |")
    lines.extend(["", "| Stream | Largest ratio | Slope | Drop-largest slope | Pass |",
                  "|---|---:|---:|---:|---|"])
    for stream, s in timing["screens"].items():
        f = s["fit"]
        lines.append(f"| {stream} | {f['largest_ratio']:.3f} | {f['slope']:.4f} | "
                     f"{s['drop_largest']['slope']:.4f} | {'yes' if s['passes_screen'] else 'no'} |")
    return "\n".join(lines) + "\n"


def relative_parts(value):
    path = PurePosixPath(value)
    if (not path.parts or path.is_absolute() or path.as_posix() != value or ".." in path.parts
            or "\\" in value or ":" in value or SEALED.intersection(part.casefold() for part in path.parts)):
        raise ValueError(f"Invalid evidence path {value!r}")
    return path.parts


def checked_path(root, value):
    path = root.joinpath(*relative_parts(value)).resolve()
    if not path.is_relative_to(root.resolve()) or SEALED.intersection(part.casefold() for part in path.parts):
        raise ValueError(f"Evidence path escapes its custody root: {value!r}")
    return path


def sha_format(value):
    return isinstance(value, str) and len(value) == 64 and set(value) <= set("0123456789abcdef")


def canonical_digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def historical_index():
    path = HERE / "historical-manifest.json"
    if digest(path) != ARCHIVED_SHA:
        raise ValueError("Historical index differs from its recorded seal")
    archived = read_json(path)
    if archived["schema"] != "eapg.paired.development-artifact.v1":
        raise ValueError("Unknown historical manifest schema")
    for name in ("ledger.json", "tables.md"):
        if digest(HERE / f"historical-{name}") != archived["public"][PREFIX + name]:
            raise ValueError(f"Historical {name} differs from the archived manifest")
    if render(read_json(HERE / "historical-ledger.json")).encode() != (HERE / "historical-tables.md").read_bytes():
        raise ValueError("Historical table rendering mismatch")
    return archived


def row_index(ledger):
    evidence = {}
    for row in ledger["rows"]:
        rank = row["intake_rank"]
        record = row["evidence"]
        historical = record["file"] == PREFIX + "historical-ledger.json"
        expected = (ledger["historical_ledger_sha256"] if historical else ledger["batch_receipts"][record["file"]])
        if record["sha256"] != expected:
            raise ValueError(f"Desk evidence digest disagrees at rank {rank}")
        entry = {"desk": record["file"] if historical else "batch:" + record["file"], "desk_sha256": expected}
        receipt = row["phase_b"].get("receipt")
        if receipt:
            entry["phase_b"] = "support" if receipt.endswith("/support.json") else f"run:{rank}:run1.json"
        evidence[str(rank)] = entry
    return evidence


def verify_public(manifest, ledger, timing):
    if (manifest["schema"] != ARTIFACT_SCHEMA or manifest["ledger_schema"] != "eapg.path-b.ledger.v2"
            or manifest["held_out_used"] is not False):
        raise ValueError("Path B artifact schema or quarantine mismatch")
    if set(manifest["public"]) != PUBLIC_REQUIRED:
        raise ValueError("Path B public inventory mismatch")
    for name, expected in manifest["public"].items():
        if not sha_format(expected) or digest(checked_path(REPO, name)) != expected:
            raise ValueError(f"Public SHA-256 mismatch: {name}")
    historical = historical_index()
    pins = manifest["pins"]
    intake = run_path(str(REPO / "development/paired_study/intake.py"))
    expected_pins = {"pie_split": "validation", "pie_sha256": intake["PIE_VALIDATION_SHA256"],
                     "cppperf_tree": intake["CPPPERF_REVISION"], "selection_seed": intake["DRAW_SEED"]}
    expected_pins.update({key: ledger[key] for key in
                          ("intake_sha256", "prescreen_sha256", "draft_sha256", "historical_ledger_sha256")})
    if any(pins[key] != value for key, value in expected_pins.items()):
        raise ValueError("Manifest does not reproduce study pins")
    if pins["draft_sha256"] != "29176fea17f9f65273f4d70f2f6cbc420add1dcd1b4cfdc37d20296af7afb00d":
        raise ValueError("Desk draft disagrees with the registered pin")
    if historical["public"][PREFIX + "ledger.json"] != pins["historical_ledger_sha256"]:
        raise ValueError("Historical ledger and Path B pin disagree")
    if manifest["row_evidence"] != row_index(ledger):
        raise ValueError("Path B row evidence identifiers disagree")
    entries = manifest["local_evidence"]
    roles = set()
    for identity, entry in entries.items():
        if (entry["root_id"] not in {"repo_custody", "workspace_custody"}
                or entry["digest_mode"] not in {"bytes", "canonical-json"}
                or not sha_format(entry["sha256"]) or not entry["role"]):
            raise ValueError(f"Invalid local index metadata for {identity}")
        relative_parts(entry["path"])
        roles.add(entry["role"])
    for name, expected in historical["local_evidence"].items():
        relative = name.removeprefix(".codex/private/")
        if entries["archive:" + relative] != {"path": relative, "root_id": "repo_custody", "sha256": expected,
                                               "digest_mode": "bytes", "role": "historical"}:
            raise ValueError(f"Historical local evidence pin disagrees: {name}")
    for name, expected in ledger["batch_receipts"].items():
        entry = entries["batch:" + name]
        if entry["sha256"] != expected or PurePosixPath(entry["path"]).name != name or entry["role"] != "desk_batch":
            raise ValueError(f"Desk batch mapping disagrees: {name}")
    for identity, pin in (("intake", "intake_sha256"), ("prescreen", "prescreen_sha256"), ("draft", "draft_sha256")):
        if entries[identity]["sha256"] != pins[pin]:
            raise ValueError(f"Missing pinned local input: {identity}")
    for rank, record in manifest["row_evidence"].items():
        if "phase_b" in record:
            item = entries[record["phase_b"]]
            path = ".codex/private/" + item["path"]
            if item["root_id"] != "repo_custody" or path != ledger["rows"][int(rank) - 1]["phase_b"]["receipt"]:
                raise ValueError(f"Invalid execution or preprocessing reference at rank {rank}")
    if set(pins["results"]) != set(RESULTS):
        raise ValueError("Sanitized results are incomplete")
    for name, pin in pins["results"].items():
        public = read_json(HERE / name)
        full_pin = public.get("custody_receipt_sha256", public.get("full_receipt_sha256"))
        ledger_sha = public.get("ledger_sha256", public.get("inputs", {}).get("ledger_sha256"))
        if (public["held_out_used"] is not False or ledger_sha != manifest["public"][PREFIX + "ledger.json"]
                or pin["sha256"] != manifest["public"][PREFIX + name] or pin["schema"] != public["schema"]
                or entries[pin["receipt"]]["sha256"] != full_pin):
            raise ValueError(f"Sanitized result pin mismatch: {name}")
    validate_timing(timing)
    sys.path.insert(0, str(REPO))
    from development.paired_study.steady import source_inputs
    originals, sources = source_inputs()
    for key, collection in (("historical_source_sha256", originals), ("source_sha256", sources)):
        if timing[key] != {name: sha256(blob).hexdigest() for name, blob in collection.items()}:
            raise ValueError(f"Authored timing source provenance mismatch: {key}")
    if render_path_b(ledger, timing).encode() != (HERE / "tables.md").read_bytes():
        raise ValueError("Regenerated Path B tables differ")
    return roles


def verify_local(manifest, ledger, roots):
    entries = manifest["local_evidence"]
    paths = {}
    for identity, item in entries.items():
        path = checked_path(roots[item["root_id"]], item["path"])
        if not path.is_file():
            raise ValueError(f"Missing custody evidence {identity} ({item['role']})")
        expected = canonical_digest(read_json(path)) if item["digest_mode"] == "canonical-json" else digest(path)
        if expected != item["sha256"]:
            raise ValueError(f"Local SHA-256 mismatch for {identity} ({item['role']})")
        paths[identity] = path
    intake, prescreen, draft = (read_json(paths[name]) for name in ("intake", "prescreen", "draft"))
    if (any(value["held_out_used"] is not False for value in (intake, prescreen, draft))
            or intake["seed"] != manifest["pins"]["selection_seed"]
            or draft["intake_sha256"] != ledger["intake_sha256"]
            or draft["prescreen_sha256"] != ledger["prescreen_sha256"]
            or draft["batch_receipts"] != ledger["batch_receipts"]):
        raise ValueError("Intake, prescreen or desk draft join disagrees")
    for row, previous in zip(ledger["rows"], draft["rows"], strict=True):
        if any(row[key] != previous[key] for key in
               ("intake_rank", "pins", "target", "reference", "census_slot", "stratum_slot", "phase_a")):
            raise ValueError(f"Public row and pinned draft differ at rank {row['intake_rank']}")
    support = read_json(paths["support"])
    expected_support = [ledger["rows"][rank - 1]["phase_b"]["preprocessing"] for rank in ledger["support_closures"]]
    if (support["schema"] != "eapg.path-b.support.v1" or support["held_out_used"] is not False
            or support["rows"] != expected_support or any(row["cxx_executed"] is not False for row in expected_support)):
        raise ValueError("Preprocessing evidence disagrees with the pinned public rows")
    from development.paired_study import path_b_close, path_b_run
    for rank in ledger["execution_queue"]:
        row = ledger["rows"][rank - 1]
        prep, first, second, pred, repeat = (paths[f"run:{rank}:{name}"] for name in
                                            ("prepared.json", "run1.json", "run2.json", "run1.prediction.json",
                                             "run2.prediction.json"))
        if first.read_bytes() != second.read_bytes() or pred.read_bytes() != repeat.read_bytes():
            raise ValueError(f"Execution or prediction rerun differs at rank {rank}")
        bundle, run, prediction = map(read_json, (prep, first, pred))
        if (not (bundle["rank"] == run["rank"] == rank) or not (bundle["id"] == run["id"] == path_b_close.cases.CASES[rank])
                or bundle["held_out_used"] is not False or run["held_out_used"] is not False
                or bundle["draft_sha256"] != ledger["draft_sha256"] or run["prep_sha256"] != digest(prep)
                or run["prediction_sha256"] != row["phase_b"]["prediction_sha256"]
                or digest(pred) != row["phase_b"]["prediction_sha256"]
                or path_b_run.seal_prediction(bundle, run["execution"]) != prediction):
            raise ValueError(f"Run identity or sealed prediction mismatch at rank {rank}")
        summary = path_b_close.summarize_run(rank, first.parent.parent)
        if any(row[key] != value for key, value in summary.items()):
            raise ValueError(f"Execution evidence differs from public summary at rank {rank}")
    from desk_agreement import public_summary
    from precedence_sweep import public_projection
    for name, pin in manifest["pins"]["results"].items():
        full = read_json(paths[pin["receipt"]])
        public = read_json(HERE / name)
        if name == "precedence-sweep.json":
            expected = public_projection(full, entries[pin["receipt"]]["sha256"])
        else:
            expected = public_summary(full, entries[pin["receipt"]]["sha256"])
        if public != expected:
            raise ValueError(f"Sanitized projection disagrees: {name}")
    audit = read_json(paths["desk-draw"])
    packet_manifest = read_json(paths["packet-manifest"])
    index = read_json(paths["sweep-index"])
    if (audit["ledger_sha256"] != packet_manifest["ledger_sha256"] or index["ledger_sha256"] != audit["ledger_sha256"]
            or index["historical_manifest_sha256"] != ARCHIVED_SHA or index["pie_validation_sha256"] != manifest["pins"]["pie_sha256"]
            or index["cppperf_revision"] != manifest["pins"]["cppperf_tree"]
            or packet_manifest["source_index_sha256"] != entries["packet-source-index"]["sha256"]
            or packet_manifest["draw_sha256"] != entries["desk-draw"]["sha256"]
            or packet_manifest["contract_sha256"] != entries["desk-contracts"]["sha256"]):
        raise ValueError("Sweep or blind packet source identity disagrees")
    if len({(item["intake_rank"], item["side"], item["path"]) for item in index["files"]}) != len(index["files"]):
        raise ValueError("Duplicate rank/side/path in source index")
    for item in index["files"]:
        rank = item["intake_rank"]
        if item["status"] == "verified":
            item_path = checked_path(paths["sweep-index"].parent, item["storage"])
            if paths["source:" + item["sha256"]] != item_path:
                raise ValueError(f"Unindexed verified source at rank {rank}")
            if "commit" in item and item["commit"] != ledger["rows"][rank - 1][item["side"]]:
                raise ValueError(f"Wrong CppPerf side commit at rank {rank}")
    if "fresh-seals" in paths:
        from desk_agreement import score
        seals = read_json(paths["fresh-seals"])
        fresh = read_json(paths[manifest["pins"]["results"]["desk-agreement-reaudit.json"]["receipt"]])
        ballots = {key: read_json(paths["fresh-ballot:" + key]) for key in "abc"}
        if (seals["packet_manifest_sha256"] != fresh["packet_manifest_sha256"]
                or fresh["packet_manifest_sha256"] != entries["packet-manifest"]["sha256"]
                or fresh["draw_sha256"] != entries["desk-draw"]["sha256"]
                or fresh["verdict_seals_sha256"] != entries["fresh-seals"]["sha256"]
                or seals["verdict_sha256"] != {key: entries["fresh-ballot:" + key]["sha256"] for key in "abc"}):
            raise ValueError("Independent ballot seals disagree")
        replay = score(ledger, audit, packet_manifest, ballots)
        if any(fresh[key] != json.loads(json.dumps(value)) for key, value in replay.items()):
            raise ValueError("Retallied independent ballots differ from the sealed result")
    return len(paths)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--write-tables", action="store_true", help="Render tables from the fixed ledger.")
    modes.add_argument("--verify-public", action="store_true", help="Reproduce the public artifact (default).")
    modes.add_argument("--verify-local", "--verify-all", action="store_true", help="Also verify local custody receipts.")
    parser.add_argument("--repo-custody", type=Path, default=REPO / ".codex/private")
    parser.add_argument("--workspace-custody", type=Path, default=REPO.parent / ".codex/private")
    parser.add_argument("--manifest-sha256", help="Require the separately recorded manifest digest.")
    args = parser.parse_args()
    ledger = read_json(checked_path(HERE, "ledger.json"))
    if ledger["schema"] == "eapg.path-b.ledger.v2":
        timing = read_json(checked_path(HERE, "a01-steady.json"))
        if args.write_tables:
            historical_index()
            validate_timing(timing)
            checked_path(HERE, "tables.md").write_bytes(render_path_b(ledger, timing).encode())
            return
        path = checked_path(HERE, "manifest.json")
        if args.manifest_sha256 and digest(path) != args.manifest_sha256:
            raise ValueError("Artifact manifest disagrees with its external SHA-256 anchor")
        manifest = read_json(path)
        roles = verify_public(manifest, ledger, timing)
        print(f"147 Path B slots reproduced. {len(manifest['public'])} public files verified.", flush=True)
        if args.verify_local:
            count = verify_local(manifest, ledger, {"repo_custody": args.repo_custody,
                                                   "workspace_custody": args.workspace_custody})
            print(f"{count} local evidence files verified.")
        else:
            print("Custody required for " + ", ".join(sorted(roles)) + ".")
        return
    table = render(ledger).encode()
    dest = HERE / "tables.md"
    if args.write_tables:
        if args.verify_local:
            parser.error("verify the index in a separate invocation")
        dest.write_bytes(table)
        return
    manifest = read_json(HERE / "manifest.json")
    if manifest["schema"] != "eapg.paired.development-artifact.v1":
        raise ValueError("Unknown manifest schema.")
    verify_index(manifest["public"])
    if args.verify_local:
        verify_index(manifest["local_evidence"])
    if dest.read_bytes() != table:
        raise ValueError("Regenerated tables differ from the indexed tables.")
    print(f"{len(ledger['cases'])} slots, {len(manifest['public'])} public files, "
          f"{len(manifest['local_evidence']) if args.verify_local else 0} local evidence files verified.")


if __name__ == "__main__":
    main()
