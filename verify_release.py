"""Verify the released evidence without fetching PIE data or executing C++."""

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parent


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def verify_scaling():
    scaling = ROOT / "artifacts/phase1_correction/scaling"
    result = read_json(scaling / "fast_recurrence_results.json")
    assert result["script_sha256"] == digest(scaling / "check_fast_recurrences.py")
    assert result["pipeline_sha256"] == digest(ROOT / "pipeline.py")
    assert result["pilot_sha256"] == digest(ROOT / "artifacts/scope_isolated_pilot/pilot100_results.json")
    fib = [1, 1]
    for _ in range(2, 4097):
        fib.append(fib[-1] + fib[-2])
    cases = Counter()
    fast_checks = paired_checks = 0
    for record in result["records"]:
        mechanism = record["mechanism"]
        cases[mechanism] += 1
        if mechanism == "B.3":
            offset = 3 + int(re.search(r"base_ways = (\d+);", record["corrected_fast_code"])[1])
        else:
            assert mechanism == "A2.1"
            offset = 0
        assert record["corrected_max_fast_work_alpha"] == {"A2.1": 1.02, "B.3": 1.01}[mechanism]
        for scale, run in record["runs"].items():
            assert run["status"] == "CLEAN_COMPLETION" and run["exit_code"] == 0
            assert run["stdout"] == f"{(fib[int(scale)] + offset) % (2**64)}\n"
            assert run["total_ticks"] == sum(node["work"] for node in run["nodes"].values())
            fast_checks += 1
            if "frozen_slow_stdout" in run:
                assert int(scale) in (16, 24) and run["frozen_slow_stdout"] == run["stdout"]
                paired_checks += 1
    assert cases == {"A2.1": 13, "B.3": 12}
    assert (fast_checks, paired_checks) == (200, 50)
    print("Verified 200 modular recurrence outputs and 50 paired controls.")


def verify_development():
    data = ROOT / "artifacts/phase2_data"
    result = read_json(data / "development_counters.json")
    workload = read_json(data / "development_workload.json")
    assert result["workload_sha256"] == digest(data / "development_workload.json")
    assert result["released_runner_sha256"] == digest(data / "run_development.py")
    assert result["pipeline_sha256"] == digest(ROOT / "pipeline.py")
    cases = {}
    for case in workload["inputs"]:
        n, k, *values = map(int, case["stdin"].split())
        assert k == 1 and len(values) == n == case["n"]
        assert case["expected_stdout"] == f"{n - max(Counter(values).values())}\n"
        cases[str(case["seed"]), n] = case["expected_stdout"]
    assert len(cases) == 18
    for side in ("slow", "fast"):
        observed = set()
        for seed, rows in result[side]["runs"].items():
            for row in rows:
                n = row["n"]
                assert (seed, n) not in observed
                observed.add((seed, n))
                assert row["status"] == "CLEAN_COMPLETION" and row["returncode"] == 0
                assert row["stdout"] == cases[seed, n]
                assert row["total_ticks"] == sum(node["work"] for node in row["nodes"].values())
                if side == "slow":
                    assert row["nodes"]["N12"]["cnt"] == (n // 4 - 1) * (n // 2 + 2) + 1
        assert observed == set(cases)
    for seed, fit in result["slow"]["fits"].items():
        assert fit["N12"]["fit_work"]["alpha"] == 2.0
        slice_result = result["slices_by_seed"][seed]
        assert slice_result["c_pruned"] == ["N10", "N11"]
        assert "N12" in slice_result["c_unpruned"]
    print("Verified 36 PIE outputs and the quadratic traversal and slice finding.")


def main():
    if not __debug__:
        raise RuntimeError("Run without Python optimization so assertions remain active")
    for line in (ROOT / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        expected, name = line.split("  ", 1)
        if digest(ROOT / name) != expected:
            raise ValueError(f"Release hash mismatch: {name}")
    subprocess.run([sys.executable, "-B", str(ROOT / "artifacts/phase1_correction/verify_localization.py")],
                   cwd=ROOT, check=True)
    verify_scaling()
    verify_development()


if __name__ == "__main__":
    main()
