"""Independently time plain authored C++ binaries using the protected Gate 1 clock."""

import argparse
from collections import defaultdict
from pathlib import Path
import platform
from random import Random
from statistics import median
import sys

from development import gate1_sandbox

from . import panel, predict


SEED = 42
WARMUPS = 1
REPEATS = 5
SIDES = ("target", "reference")


def paired_orders(seed, warmups, repeats):
    rng = Random(seed)
    return [rng.sample(SIDES, k=2) for _ in range(warmups + repeats)]


def summarize(rows, sizes):
    by_run = defaultdict(list)
    for row in rows:
        if row["phase"] == "measured":
            by_run[row["stream"], row["size"], row["side"]].append(row["elapsed_ns"])
    screens = {}
    for stream in panel.STREAMS:
        points, summaries = [], []
        for size in sizes:
            values = [by_run[stream, size, side] for side in SIDES]
            if any(len(sample) != REPEATS for sample in values):
                raise ValueError("Timing receipt has missing repetitions")
            target, reference = map(median, values)
            points.append((size, target, reference))
            summaries.append({"size": size, **{
                side: {"median_ns": median(sample), "min_ns": min(sample), "max_ns": max(sample)}
                for side, sample in zip(SIDES, values)
            }})
        fit = predict.calculate_fit(points)
        if fit is None:
            raise ValueError("Timing size ladder is too short")
        screens[stream] = {"fit": fit, "drop_largest": predict.calculate_fit(points[:-1]),
                           "points": summaries,
                           "passes_screen": fit["slope"] >= 0.50 and fit["largest_ratio"] >= 1.50}
    return screens


def measure(cases):
    # The frozen timing script expects its sibling modules on the script search path.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    try:
        import runtime_screen
    finally:
        sys.path.pop(0)
    launcher_sha = predict.digest(Path(gate1_sandbox.__file__).read_bytes())
    if launcher_sha != runtime_screen.LAUNCHER_SHA:
        raise ValueError("Timing launcher differs from the protected, pinned launcher")
    protections = runtime_screen.authored_controls()
    startup = runtime_screen.startup_calibration()
    template = panel.TEMPLATE.read_text(encoding="utf-8")
    cache = {}
    report = {"schema": "eapg.paired.authored-timing.v1", "environment": {
        "kernel": platform.release(), "machine": platform.machine(), "python": platform.python_version(),
        "compiler": gate1_sandbox.checked_output(gate1_sandbox.invoke(["g++", "--version"])).decode(),
        "launcher_sha256": launcher_sha,
        "timer_sha256": predict.digest(Path(runtime_screen.__file__).read_bytes()),
    }, "seed": SEED, "warmups_per_side": WARMUPS, "repeats_per_side": REPEATS,
        "flags": ["-std=c++17", "-O2"], "protected_clock_probes": protections,
        "startup_control": startup, "cases": []}
    rng = Random(SEED)
    for case in cases:
        binaries, source_pins = {}, {}
        for side in SIDES:
            source, _ = panel.source_and_spans(template, getattr(case, side))
            pin = predict.digest(source)
            if pin not in cache:
                cache[pin] = gate1_sandbox.compile_cpp(source)
            binaries[side], source_pins[side] = cache[pin], pin
        rows = []
        grid = panel.workloads(case.nonmonotone)
        for (stream, n), queries in grid.items():
            if stream not in panel.STREAMS:
                continue
            counts = panel.independent_counts(case.reference, n, queries)
            expected = panel.rank_stdout(counts[0])
            data = f"1\n{n} {' '.join(map(str, queries))}\n".encode()
            orders = paired_orders(rng.randrange(2**32), WARMUPS, REPEATS)
            for block, order in enumerate(orders):
                for place, side in enumerate(order):
                    result, elapsed, step = runtime_screen.timed_execution(binaries[side], data)
                    if result.returncode != 0 or result.stdout != expected or result.stderr:
                        raise ValueError(f"Plain timing output failed the independent oracle for {case.id}")
                    rows.append({"stream": stream, "size": n, "side": side, "block": block,
                                 "order": place, "phase": "warmup" if block < WARMUPS else "measured",
                                 "elapsed_ns": elapsed, "clock_step_ns": step,
                                 "input_sha256": predict.digest(data), "output_sha256": predict.digest(result.stdout)})
        fits = summarize(rows, panel.SIZES)
        passed = all(fit["passes_screen"] for fit in fits.values())
        report["cases"].append({"id": case.id, "source_sha256": source_pins,
                                "timing": "confirmed" if passed else "unconfirmed",
                                "stream_screens": fits, "samples": rows})
        print(f"{case.id}: independent runtime screen {'passed' if passed else 'did not pass'}", flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", required=True, choices=[case.id for case in panel.CASES])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or len(args.case) != len(set(args.case)):
        parser.error("supply unique cases and a new output file")
    cases = [case for case in panel.CASES if case.id in args.case]
    print(predict.write_new(args.output, measure(cases)), args.output)


if __name__ == "__main__":
    main()
