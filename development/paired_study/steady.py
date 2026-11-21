"""Measure the authored a01 kernels in process inside the registered Linux runner."""

import argparse
from io import BytesIO
from pathlib import Path
from random import Random
from statistics import median
import tarfile

from development import gate1_sandbox as gate
from . import panel, predict, timing


SIZES = (256, 512, 1024, 2048, 4096, 8192)
HARNESS = panel.TEMPLATE.with_name("a01_steady.cpp")
KERNEL = """#include <algorithm>
unsigned long long @name@(const int* data, const int* queries, int* ranks, int n) {
    int prior = 0;
    unsigned long long advances = 0;
    for (int query = 0; query < n; ++query) {
        const int q = queries[query];
        const int entry = @entry@;
        const int key = @key@;
        int cursor;
        for (cursor = entry; cursor < n && data[cursor] <= key; ++cursor) {
#if defined(COUNT)
            ++advances;
#endif
        }
        prior = ranks[query] = cursor;
    }
    return advances;
}
"""


def build(sources, *flags):
    archive = BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        for name, source in sources.items():
            item = tarfile.TarInfo(name)
            item.size = len(source)
            tar.addfile(item, BytesIO(source))
    return gate.checked_output(gate.invoke([
        "/bin/sh", "-ec",
        'tar -xf -; g++ -std=c++17 -O2 -fno-lto "$@" harness.cpp target.cpp reference.cpp empty.cpp '
        '-o /tmp/program; exec cat /tmp/program',
        "a01-steady", *flags,
    ], data=archive.getvalue(), timeout=25))


def checked(binary, data):
    result = gate.execute(binary, data)
    output = gate.checked_output(result)
    if result.stderr:
        raise ValueError(result.stderr[:1000])
    return output.decode()


def source_inputs():
    case, = (case for case in panel.CASES if case.id == "a01")
    sides = timing.SIDES
    template = panel.TEMPLATE.read_text(encoding="utf-8")
    originals, sources = {}, {"harness.cpp": HARNESS.read_bytes()}
    for side in sides:
        originals[side], _ = panel.source_and_spans(template, getattr(case, side))
        options = panel.SLOTS | getattr(case, side)
        if (options["odd"], options["even"], options["scan"], options["extra"]) != (
            "entry", "entry", "entry", "0"
        ):
            raise ValueError("The authored a01 scan contract changed")
        sources[f"{side}.cpp"] = KERNEL.replace("@name@", side).replace(
            "@entry@", options["seed"]
        ).replace("@key@", options["key"]).encode()
    sources["empty.cpp"] = b"unsigned long long empty(const int*, const int*, int*, int) { return 0; }\n"
    return originals, sources


def measure():
    sides = timing.SIDES
    originals, sources = source_inputs()
    plain = build(sources)
    ubsan = build(sources, "-DVALIDATION", "-fsanitize=undefined", "-fno-sanitize-recover=undefined")
    counted = build(sources, "-DVALIDATION", "-DCOUNT")
    bridge = {side: gate.compile_cpp(src) for side, src in originals.items()}
    rng = Random(timing.SEED)
    grids = panel.workloads()
    rows = []
    for stream in panel.STREAMS:
        for n in SIZES:
            queries = list({
                "dense": range(1, n + 1),
                "plateau": (1 + i // 2 for i in range(n)),
                "curved": (1 + i * i // n for i in range(n)),
            }[stream])
            ranks, *_ = panel.independent_counts(case.reference, n, queries)
            counts = [panel.independent_counts(getattr(case, side), n, queries)[1] for side in sides]
            order = [rng.randrange(2), *rng.sample([0, 1], 2), *rng.sample([0] * 4 + [1] * 4, 8)]
            query_text = " ".join(map(str, queries))
            data = f"{n} {''.join(map(str, order))}\n{query_text}\n{' '.join(map(str, ranks))}\n".encode()
            if n == SIZES[0]:
                if queries != grids[stream, n] or any(
                    checked(binary, f"1\n{n} {query_text}\n".encode()).encode() != panel.rank_stdout(ranks)
                    for binary in bridge.values()
                ):
                    raise ValueError("Historical a01 bridge failed")
            if list(map(int, checked(ubsan, data).split())) != [0, 0]:
                raise ValueError("Sanitized kernel failed")
            if list(map(int, checked(counted, data).split())) != counts:
                raise ValueError("Instrumented kernel disagrees with independent advance counts")
            raw = checked(plain, data).splitlines()
            pilots, blocks = [], []
            for line in raw[1:]:
                kind, *values = line.split()
                (pilots if kind == "pilot" else blocks).append(list(map(int, values)))
            if len(blocks) != 10 or [block[1] for block in blocks] != order[1:]:
                raise ValueError("Timing schedule did not complete")
            rows.append({"stream": stream, "size": n, "order": order, "tick_ns": int(raw[0]),
                         "pilots": pilots, "blocks": blocks, "advances": counts,
                         "input_sha256": predict.digest(data),
                         "rank_sha256": predict.digest(panel.rank_stdout(ranks))})
    screens = {}
    for stream in panel.STREAMS:
        points, sample_rows = [], []
        for row in rows:
            if row["stream"] != stream:
                continue
            samples = [[], [], []]
            for reps, first, a, b, control in row["blocks"][2:]:
                samples[first].append(a / reps)
                samples[1 - first].append(b / reps)
                samples[2].append(control / reps)
            points.append((row["size"], median(samples[0]), median(samples[1])))
            sample_rows.append({"size": row["size"], **{
                side: {"median_ns": median(values), "min_ns": min(values), "max_ns": max(values)}
                for side, values in zip((*sides, "empty"), samples, strict=True)
            }})
        fit = predict.calculate_fit(points)
        screens[stream] = {"fit": fit, "drop_largest": predict.calculate_fit(points[:-1]),
                           "samples": sample_rows,
                           "passes_screen": fit["slope"] >= .50 and fit["largest_ratio"] >= 1.50}
    return {"schema": "eapg.path-b.a01-steady.v1", "held_out_used": False, "seed": timing.SEED,
            "source_sha256": {name: predict.digest(data) for name, data in sources.items()},
            "historical_source_sha256": {side: predict.digest(data) for side, data in originals.items()},
            "binary_sha256": {name: predict.digest(binary) for name, binary in
                              (("plain", plain), ("ubsan", ubsan), ("count", counted))},
            "compiler": gate.checked_output(gate.invoke(["g++", "--version"])).decode().splitlines()[0],
            "launcher_sha256": predict.digest(Path(gate.__file__).read_bytes()),
            "ubsan_clean": True, "bridge_size": 256, "warmup_pairs": 2, "measured_pairs": 8,
            "clock": "std::chrono::steady_clock", "rows": rows, "screens": screens,
            "all_stream_alert": all(row["passes_screen"] for row in screens.values()),
            "any_stream_alert": any(row["passes_screen"] for row in screens.values())}


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("output", type=Path)
    args = cli.parse_args()
    if args.output.exists():
        cli.error("use a new receipt path")
    print(predict.write_new(args.output, measure()))
