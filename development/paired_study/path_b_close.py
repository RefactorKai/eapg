"""Assemble the 147-slot census from the pinned desk draft and local run receipts."""

from collections import Counter
import json
from runpy import run_path

from . import path_b_cases as cases, path_b_run as run, predict


ARTIFACT = cases.REPO / "artifacts/paired_development"
PHASE_B = cases.CUSTODY / "phase-b"
DEFERRED = "desk_eligible_control_deferred"


def summarize_run(rank, phase_b=PHASE_B):
    folder = phase_b / str(rank)
    first = folder / "run1.json"
    executed = json.loads(first.read_bytes())
    bundle = json.loads((folder / "prepared.json").read_bytes())
    prediction = json.loads((folder / "run1.prediction.json").read_bytes())
    if executed["rank"] != rank or bundle["rank"] != rank or executed["held_out_used"] or bundle["held_out_used"]:
        raise ValueError(f"Execution identity or custody mismatch for slot {rank}")

    issues, measured = [], []
    for i, sample in enumerate(bundle["samples"]):
        clean = True
        counts = {}
        for side, modes in executed["execution"].items():
            for mode, observations in modes.items():
                result = observations[i]
                if result["status"] != "complete":
                    issues.append({"stream": sample["stream"], "size": sample["size"],
                                   "variant": side, "mode": mode, **result})
                    clean = clean and result["status"] == "tick_cap"
            levels = [modes[mode][i] for mode in ("O0", "O2", "O3")]
            if not levels[0] == levels[1] == levels[2]:
                raise ValueError(f"Slot {rank} {side} counters differ across optimization levels")
            if levels[0]["status"] == "complete":
                counts[side] = levels[0]["counts"]
        if clean and set(counts) == set(cases.VARIANTS):
            if sample["checks"] is not None:
                for side, expected in zip(cases.VARIANTS, sample["checks"], strict=True):
                    if expected is not None and counts[side][0] != expected:
                        raise ValueError(f"Independent counter check failed for slot {rank} {side}")
            if counts["target"] != counts["sham"]:
                raise ValueError(f"Sham changed measured work in slot {rank}")
            if rank == 62 and {pair[1] for pair in counts.values()} != {(sample["size"] + 1) ** 2}:
                raise ValueError("RGB candidate-visit calibration failed")
            if rank == 137 and len({pair[1] for pair in counts.values()}) != 1:
                raise ValueError("LeetCode rank-search comparison counts differ")
            measured.append({"stream": sample["stream"], "size": sample["size"],
                             "counts": counts})

    screens = prediction["result"]["screen"]
    hard_failures = [issue for issue in issues if issue["status"] != "tick_cap"]
    fitted = not hard_failures and all(screen["fit"] is not None for screen in screens)
    alerts = [screen["fit"]["slope"] >= .50 and screen["fit"]["largest_ratio"] >= 1.50
              for screen in screens] if fitted else []
    if hard_failures:
        status = "execution_oracle_failure" if any(
            issue["status"] == "invalid_output" for issue in hard_failures
        ) else "execution_validation_failure"
        screen_status = "invalid_output_or_execution"
        first_issue = hard_failures[0]
        reason = (f"{first_issue['variant']} failed {first_issue['mode']} on "
                  f"{first_issue['stream']} at size {first_issue['size']}.")
    else:
        status = "verified_growth_evaluation"
        screen_status = "alert" if fitted and all(alerts) else "no_alert" if fitted else "insufficient_fit"
        reason = ("Finite-range fit on the registered primary event." if fitted else
                  "At least one registered stream lacks an admissible fit.")
    return {
        "final_disposition": status, "screen_status": screen_status, "screen_reason": reason,
        "all_stream_alert": all(alerts) if fitted else None,
        "any_stream_alert": any(alerts) if fitted else None,
        "registered_streams": [screen["stream"] for screen in screens],
        "stream_screens": screens,
        "phase_b": {"status": status, "events": bundle["events"], "executed": True,
                    "modes": list(run.MODES), "checks": len(bundle["samples"]) * 4 * len(run.MODES),
                    "issues": issues, "measurements": measured,
                    "prediction": prediction["result"]["arms"], "prediction_validation": prediction["validation"],
                    "ranking_eligible": False, "byte_exact_replay": True,
                    "receipt": (PHASE_B / str(rank) / first.name).relative_to(cases.REPO).as_posix(),
                    "prediction_sha256": executed["prediction_sha256"]},
    }


def assemble():
    draft = json.loads(cases.DRAFT.read_bytes())
    support_file = PHASE_B / "support.json"
    support = {r["rank"]: r for r in json.loads(support_file.read_bytes())["rows"]}
    deferred = set(draft["a4_draft_diagnostics"])
    for tier in draft["a4_draft_priority"]:
        deferred.update(tier["intake_ranks"])
    deferred.difference_update(cases.CASES)
    if len(deferred) != 18 or list(support) != draft["a4_draft_support_blockers"]:
        raise ValueError("Narrowed queue disagrees with the pinned proposals")
    for row in draft["rows"]:
        rank = row["intake_rank"]
        original = row["phase_b"]["status"]
        if rank in cases.CASES:
            row.update(summarize_run(rank))
        elif rank in support:
            item = support[rank]
            if item["cxx_executed"]:
                raise ValueError("A support-only slot executed")
            row["final_disposition"] = "support_boundary_closed"
            row["phase_b"] = {"status": row["final_disposition"], "executed": False,
                              "preprocessing": item, "receipt": support_file.relative_to(cases.REPO).as_posix()}
            row["screen_status"] = "not_fitted"
            row["screen_reason"] = "Dependency-only preprocessing stopped at the documented single-TU boundary."
        elif rank in deferred:
            row["final_disposition"] = DEFERRED
            row["phase_b"] = {"status": DEFERRED, "executed": False,
                              "reason": row["phase_a"]["reason"]}
            row["screen_status"] = "not_fitted"
            row["screen_reason"] = "Omitted from narrowed execution queue with archived controls retained."
        elif original == "HISTORICAL":
            row["final_disposition"] = {
                "oracle_confirmed": "verified_historical_control",
                "output_mismatch": "execution_oracle_failure",
                "unsupported_dependencies": "historical_dependency_stop",
                "not_run": "historical_desk_excluded",
            }[row["phase_b"]["disposition"]]
            row["evidence"]["file"] = "artifacts/paired_development/historical-ledger.json"
        else:
            row["final_disposition"] = {"BLOCKED": "desk_blocked", "REJECTED": "desk_excluded"}[original]
    rows = draft["rows"]
    ledger = {key: draft[key] for key in ("schema", "held_out_used", "intake_sha256", "prescreen_sha256",
                                          "historical_ledger_sha256", "batch_receipts")}
    ledger.update({"draft_sha256": cases.DRAFT_SHA, "rows": rows,
                   "totals": dict(Counter(row["final_disposition"] for row in rows)),
                   "execution_queue": list(cases.CASES), "support_closures": list(support),
                   "deferred": sorted(deferred), "natural_ranking_eligible": 0})
    timing = json.loads((ARTIFACT / "a01-steady.json").read_bytes())
    render = run_path(str(ARTIFACT / "replay.py"))["render_path_b"]
    tables = render(ledger, timing)
    previous = json.loads((ARTIFACT / "ledger.json").read_bytes())
    if previous["schema"] == "eapg.paired.development-ledger.v1":
        for name in ("ledger.json", "tables.md"):
            (ARTIFACT / f"historical-{name}").write_bytes((ARTIFACT / name).read_bytes())
    (ARTIFACT / "ledger.json").write_bytes(predict.canonical(ledger))
    (ARTIFACT / "tables.md").write_bytes(tables.encode())


if __name__ == "__main__":
    assemble()
