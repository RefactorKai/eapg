"""Replay the archived library calibration summaries without compiling or running C++."""

import argparse
from hashlib import sha256
import json
from math import fsum, isclose, log
from pathlib import Path

from weighted_panel_sources import SOURCES


HERE = Path(__file__).resolve().parent
EVIDENCE = HERE.parent / "artifacts" / "weighted_panel"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def slope(sizes, values):
    x, y = [log(n) for n in sizes], [log(v) for v in values]
    mean_x, mean_y = fsum(x) / len(x), fsum(y) / len(y)
    return fsum((a - mean_x) * (b - mean_y) for a, b in zip(x, y, strict=True)) / fsum(
        (a - mean_x) ** 2 for a in x
    )


def replay(lock_path, results_path):
    raw = lock_path.read_bytes()
    lock, results = json.loads(raw), json.loads(results_path.read_bytes())
    require(lock["schema"] == "eapg-weighted-panel-lock-v1"
            and results["schema"] == "eapg-weighted-panel-results-v1"
            and sha256(raw).hexdigest() == results["lock_sha256"], "Wrong panel lock or schema")
    for name, expected in lock["study_files_sha256"].items():
        require(sha256((HERE / name).read_bytes()).hexdigest() == expected, f"Source hash differs for {name}")
    for op, (plain, counted) in SOURCES.items():
        for build, source in (("plain", plain), ("counted", counted)):
            require(sha256(source.encode()).hexdigest() == lock["source_sha256"][op][build], "C++ source drift")
    builds = results["builds"]
    require(set(builds) == set(lock["optimizations"]), "Optimization grid is incomplete")
    result_rows, checks = {}, 0
    for level, ops in builds.items():
        require(set(ops) == set(SOURCES), f"Operation grid is incomplete at {level}")
        for op, build in ops.items():
            expected_names = {cell["workload"] for cell in lock["cells"] if cell["operation"] == op}
            require(set(build["workloads"]) == expected_names, f"Workload grid changed at {level} {op}")
        for cell in lock["cells"]:
            op, name = cell["operation"], cell["workload"]
            panel = ops[op]["workloads"][name]
            target = ops[op]["site"]["target_node_id"]
            require(panel["status"] == "COMPLETE", f"Incomplete panel cell: {level} {op} {name}")
            pairs = list(zip(panel["rows"], cell["inputs"], strict=True))
            for row, expected in pairs:
                require((row["n"], row["p"]) == (expected["n"], expected["p"]), "Grid coordinates changed")
                stages = row["stages"]
                wanted = {"original", "counted", "instrumented"} | ({"sanitizer"} if level == "-O2" else set())
                require(set(stages) == wanted, "Execution stage missing")
                checksum = str(expected["checksum"])
                for stage, execution in stages.items():
                    tokens = [checksum, str(expected["expected_operations"])] if stage == "counted" else [checksum]
                    require(execution["status"] == "CLEAN_COMPLETION" and execution["stdout"].split() == tokens,
                            f"Recorded oracle mismatch at {level} {op} {name} {stage}")
                    checks += 1
                require(row["operations"] == expected["expected_operations"], "Recorded count differs from oracle")
                counters = row["node_counters"]
                require((row["hits"], row["work"]) == (counters[target]["cnt"], counters[target]["work"])
                        and sum(count["work"] for count in counters.values()) == row["total_ticks"],
                        "Recorded target or total count disagrees with counter record")
            sizes = [r["n"] for r, _ in pairs]
            alpha = {k: slope(sizes, [r[k] for r, _ in pairs]) for k in ("hits", "work", "operations")}
            require(all(isclose(panel["slopes"][k]["alpha"], v, abs_tol=1e-12) for k, v in alpha.items()),
                    f"Slope mismatch at {level} {op} {name}")
            threshold = lock["site_gap_threshold"]
            oracle_qualifies = alpha["operations"] - alpha["hits"] >= threshold
            proxy_qualifies = alpha["work"] - alpha["hits"] >= threshold
            require((oracle_qualifies, proxy_qualifies) == (panel["oracle_gap_qualifies"], panel["proxy_gap_qualifies"]),
                    "Hidden-gap classification drift")
            ratios = [r["work"] / r["operations"] for r, _ in pairs]
            require(ratios == panel["work_per_operation"], "Proxy-to-operation ratios drifted")
            selected = {channel: entry["symptom"] for channel, entry in panel["selectors"].items()}
            result_rows[level, op, name] = (alpha, oracle_qualifies, proxy_qualifies, selected, target, ratios[-1])
    return result_rows, checks


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--lock", type=Path, default=EVIDENCE / "lock.json")
    cli.add_argument("--results", type=Path, default=EVIDENCE / "results.json")
    args = cli.parse_args()
    rows, checks = replay(args.lock, args.results)
    print(f"Replayed {len(rows)} condition-level records and {checks} output checks.")
    for level in ("-O2", "-O0", "-O3"):
        subset = [row for (opt, _, _), row in rows.items() if opt == level]
        agreement = sum(a == b for _, a, b, _, _, _ in subset)
        work_selected = sum(selected["work"] == target for _, _, _, selected, target, _ in subset)
        hits_alerted = sum(selected["hits"] is not None for _, _, _, selected, _, _ in subset)
        print(f"{level}: {agreement}/{len(subset)} gap agreement, {work_selected} work target selections, "
              f"{hits_alerted} hits-only alerts")
    print("Operation / workload    hit     work    oracle  proxy/operation at max N")
    for (level, op, name), (alpha, _, _, _, _, ratio) in rows.items():
        if level == "-O2":
            fits = " ".join(f"{alpha[k]:7.3f}" for k in ("hits", "work", "operations"))
            print(f"{op + ' / ' + name:<23}{fits}  {ratio:7.2f}")


if __name__ == "__main__":
    main()
