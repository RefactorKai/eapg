"""Rebuild the published development tables and verify their indexed evidence."""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CORPORA = ("PIE validation", "CppPerf")


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
        if ("metric" in row) != fitted or row["ranking_eligible"] and row["screen"] != "alert":
            raise ValueError(f"Inconsistent evidence for {row['id']}.")

    lines = [
        "# Paired development evidence", "",
        "The intake denominator is the fixed development draw. Isolated execution excludes",
        "dependency-only preprocessing. Numeric sample rows report logical operations in",
        "target, reference, restoration and sham order. Metrics vary across cases.", "",
        "| Corpus | Drawn | A eligible | B unsupported dependencies | B executed | Output-oracle failures | Verified restorations | Screened | Growth alerts | Ranking eligible |",
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
        "| Case | Work event | Example input | Target / reference / restoration / sham | Screen |",
        "|---|---|---|---|---|",
    ])
    for row in rows:
        if "metric" in row:
            example = " / ".join(f"{count:,}" for count in row["sample_counts"])
            lines.append(
                f"| `{row['id']}` | {row['metric']} | {row['sample_input']} | "
                f"{example} | `{row['screen']}` |"
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-tables", action="store_true", help="Render tables from the fixed ledger.")
    parser.add_argument("--verify-local", action="store_true", help="Also verify private source and execution receipts.")
    args = parser.parse_args()
    ledger = read_json(HERE / "ledger.json")
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
