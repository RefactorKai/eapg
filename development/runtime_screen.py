"""Screen runtime scaling on authored controls or the registered validation pair."""

import argparse
from collections import defaultdict
from hashlib import sha256
import json
import math
from pathlib import Path
import platform
import random
from statistics import median
import subprocess
from tempfile import TemporaryFile
from types import FunctionType, SimpleNamespace

import gate1_sandbox as sandbox
from run_phase2_development import WORKLOAD_SHA, historical, process_status, registered_payload, verify_oracle


LAUNCHER_SHA = "7f9bf00a3489bb97cb256b342b0cad4f5a7c5fa11d44181973b93b3e82c4d963"
ORDER_SEED = 42
REPEATS = 5
MIN_CLOCK_STEPS = 100
MIN_SIZES = 4
MIN_SIZE_RANGE = 8
MIN_RATIO_SLOPE = 0.5
MIN_LAST_RATIO = 1.5
CALIBRATION_RUNS = 20

TIMER = r'''
import ctypes, math, os, signal, subprocess, sys, time

# PID 1 is protected from candidate signals. The non-dumpable bit denies
# candidate access to its memory and open descriptors through /proc.
if os.getpid() != 1 or ctypes.CDLL(None).prctl(4, 0, 0, 0, 0) != 0:
    raise RuntimeError('Timer must be the non-dumpable namespace init')
signal.signal(signal.SIGINT, signal.SIG_DFL)
fd = int(sys.argv[1])
os.set_inheritable(fd, False)
clock = time.monotonic_ns
readings = [clock() for _ in range(64)]
step = min(b - a for a, b in zip(readings, readings[1:]) if b > a)
resolution = max(step, math.ceil(time.get_clock_info('monotonic').resolution * 1e9))
started = clock()
result = subprocess.run(['/program'], close_fds=True)
elapsed = clock() - started
wire = f'{elapsed} {resolution} {result.returncode}\n'.encode()
if os.write(fd, wire) != len(wire):
    raise RuntimeError('Short timer write')
'''


def timed_execution(binary, data=b"", *, timeout=12):
    # The pinned launcher's spawn seam enables PID-1 timing and a private FD.
    # All original scope limits, capture, timeout and cleanup still apply.
    with TemporaryFile() as receipt:
        fd = receipt.fileno()

        def spawn(args, **options):
            index = args.index("--new-session")
            args = args[:index] + ["--as-pid-1"] + args[index:]
            return subprocess.Popen(args, pass_fds=(fd,), **options)

        proxy = SimpleNamespace(Popen=spawn, run=subprocess.run, check_output=subprocess.check_output,
                                TimeoutExpired=subprocess.TimeoutExpired)
        invoke = FunctionType(sandbox.invoke.__code__, {**sandbox.invoke.__globals__, "subprocess": proxy})
        result = invoke(["python3", "-I", "-S", "-c", TIMER, str(fd)], data=data, binary=binary,
                        timeout=timeout, counter_scale=None)
        status = process_status(result)
        if status != "CLEAN_COMPLETION":
            raise RuntimeError(f"Timing supervisor failed: {status}, exit={result.returncode}, "
                               f"stderr={result.stderr[:1000]!r}")
        receipt.seek(0)
        wire = receipt.read(129)
    if len(wire) > 128 or wire.count(b"\n") != 1 or not wire.endswith(b"\n"):
        raise RuntimeError("Missing or malformed trusted timing receipt")
    elapsed, resolution, returncode = map(int, wire.split())
    if resolution <= 0 or elapsed < MIN_CLOCK_STEPS * resolution:
        raise RuntimeError(f"Timing below clock resolution floor: {elapsed=} ns, {resolution=} ns")
    result.returncode = returncode
    return result, elapsed, resolution


def summarize(rows):
    samples = defaultdict(lambda: defaultdict(list))
    for row in rows:
        samples[row["seed"], row["n"]][row["side"]].append(row["elapsed_ns"])
    seeds = defaultdict(list)
    for (seed, n), sides in sorted(samples.items()):
        if n <= 0 or set(sides) != {"slow", "fast"} or any(len(v) != REPEATS for v in sides.values()):
            raise ValueError(f"Incomplete runtime repetitions for {seed=}, {n=}")
        slow, fast = median(sides["slow"]), median(sides["fast"])
        seeds[seed].append({"n": n, "slow_median_ns": slow, "fast_median_ns": fast, "ratio": slow / fast})
    results = {}
    for seed, sizes in seeds.items():
        if len(sizes) < MIN_SIZES or sizes[-1]["n"] < MIN_SIZE_RANGE * sizes[0]["n"]:
            raise ValueError(f"Insufficient usable sizes or size range for seed {seed}")
        x = [math.log(row["n"]) for row in sizes]
        y = [math.log(row["ratio"]) for row in sizes]
        x_mean = math.fsum(x) / len(x)
        slope = math.fsum((a - x_mean) * b for a, b in zip(x, y)) / math.fsum((a - x_mean)**2 for a in x)
        last = sizes[-1]["ratio"]
        results[str(seed)] = {"sizes": sizes, "ratio_slope": slope, "largest_size_ratio": last,
                              "timing_screen_pass": slope >= MIN_RATIO_SLOPE and last >= MIN_LAST_RATIO}
    if not results:
        raise ValueError("No runtime samples")
    return results


def authored_controls():
    # A candidate must have no timer FD, no /proc access to it, and no way to
    # stop the timer. A measured sleep checks the clock scale end to end.
    source = b'''
#include <dirent.h>
#include <signal.h>
#include <unistd.h>
int main() {
    for (int fd = 3; fd < 256; ++fd) if (close(fd) == 0) return 2;
    if (opendir("/proc/1/fd")) return 3;
    kill(1, SIGSTOP);
    usleep(30000);
    char c;
    if (read(0, &c, 1) != 1 || c != 'x') return 4;
    return write(1, &c, 1) == 1 ? 0 : 5;
}
'''
    control = {"seed": 42, "n": 1, "expected_stdout": "x"}
    result, elapsed, resolution = timed_execution(sandbox.compile_cpp(source), b"x")
    verify_oracle(result, control, "timing control")
    if elapsed < 30_000_000:
        raise RuntimeError("Trusted timer undercounted the authored 30 ms sleep")
    failure, _, _ = timed_execution(sandbox.compile_cpp(b"int main() {return 7;}"))
    if failure.returncode != 7:
        raise RuntimeError("Trusted timer lost the candidate exit status")

    def control_rows(slow_times):
        return [{"seed": 42, "n": n, "side": side, "elapsed_ns": value}
                for n, slow in zip((1, 2, 4, 8), slow_times)
                for side, value in (("slow", slow), ("fast", 100)) for _ in range(REPEATS)]

    positive = summarize(control_rows((100, 200, 400, 800)))["42"]
    negative = summarize(control_rows((200, 200, 200, 200)))["42"]
    weak = summarize(control_rows((30, 60, 120, 140)))["42"]
    if not positive["timing_screen_pass"] or negative["timing_screen_pass"] or weak["timing_screen_pass"]:
        raise RuntimeError("Runtime screening thresholds failed authored controls")
    try:
        summarize(control_rows((100, 200, 400)))
    except ValueError:
        pass
    else:
        raise RuntimeError("Runtime screen accepted insufficient sizes")
    return {"protected_timer": "passed", "30_ms_sleep_ns": elapsed, "clock_step_ns": resolution,
            "nonzero_status": "passed", "ratio_and_range_checks": "passed"}


def startup_calibration():
    binary = sandbox.compile_cpp(b"int main() {return 0;}")
    samples = []
    for _ in range(CALIBRATION_RUNS):
        result, elapsed, resolution = timed_execution(binary)
        if result.returncode != 0 or result.stdout or result.stderr:
            raise RuntimeError("Startup calibration fixture failed")
        samples.append({"elapsed_ns": elapsed, "clock_step_ns": resolution})
    return {"median_ns": median(row["elapsed_ns"] for row in samples), "samples": samples}


def screen(workload, sources):
    binaries = {side: sandbox.compile_cpp(source.encode()) for side, source in sources.items()}
    jobs = [(case, side, repeat) for case in workload["inputs"] for side in ("slow", "fast")
            for repeat in range(1, REPEATS + 1)]
    random.Random(ORDER_SEED).shuffle(jobs)
    rows = []
    for case, side, repeat in jobs:
        result, elapsed, resolution = timed_execution(binaries[side], case["stdin"].encode())
        verify_oracle(result, case, "runtime screen")
        rows.append({"seed": case["seed"], "n": case["n"], "side": side, "repeat": repeat,
                     "elapsed_ns": elapsed, "clock_step_ns": resolution, "returncode": result.returncode,
                     "oracle": "passed"})
    return rows, summarize(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--probes-only", action="store_true")
    modes.add_argument("--registered-validation", type=Path, metavar="PIE_VAL_JSONL")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.registered_validation and not args.output:
        parser.error("Registered validation requires a fresh private --output path")
    if args.output and args.output.exists():
        raise FileExistsError(args.output)
    if sha256(Path(sandbox.__file__).read_bytes()).hexdigest() != LAUNCHER_SHA:
        raise RuntimeError("Timing requires the verified Gate 1 launcher revision")
    report = {"authored_controls": authored_controls(), "startup_calibration": startup_calibration(),
              "protocol": {"order_seed": ORDER_SEED, "repeats_per_side_size_seed": REPEATS,
                           "min_clock_steps": MIN_CLOCK_STEPS, "min_sizes": MIN_SIZES,
                           "min_size_range": MIN_SIZE_RANGE, "min_ratio_slope": MIN_RATIO_SLOPE,
                           "min_largest_size_ratio": MIN_LAST_RATIO,
                           "timer": "CLOCK_MONOTONIC from immediately before subprocess spawn through wait",
                           "startup_adjustment": "none; measure 20 isolated no-op launches separately",
                           "compiler_flags": ["-std=c++17", "-O2"]},
              "provenance": {"runtime_screen_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
                             "sandbox_sha256": LAUNCHER_SHA, "kernel": platform.release(),
                             "python": platform.python_version(),
                             "compiler": sandbox.checked_output(sandbox.invoke(["g++", "-dumpfullversion"])).decode().strip()}}
    if args.registered_validation:
        workload, sources = registered_payload(args.registered_validation)
        rows, results = screen(workload, sources)
        report.update(workload_sha256=WORKLOAD_SHA, validation_sha256=historical.VAL_SHA, samples=rows,
                      per_seed=results, timing_screen_pass=all(row["timing_screen_pass"] for row in results.values()),
                      human_algorithmic_confirmation="not performed by this harness")
    if args.output:
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(report, output, indent=2)
            output.write("\n")
    else:
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
