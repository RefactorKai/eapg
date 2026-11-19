"""Generate and execute the public, authored C++17 mechanism panel in Gate 1."""

import argparse
from bisect import bisect_right
from dataclasses import dataclass
from hashlib import sha256
from itertools import pairwise
import json
from math import isqrt, log
from pathlib import Path
import platform
from statistics import linear_regression

from development import gate1_sandbox


TEMPLATE = Path(__file__).with_name("fixtures") / "ranked_queries.cpp.in"
FIND_CALIBRATION = TEMPLATE.with_name("find_calibration.cpp")
SIZES = (8, 16, 32, 64, 128, 256)
STREAMS = ("dense", "plateau", "curved")
CHALLENGE = ("boundary_plateau",)
GROUP = "authored-ranked-queries-v1"
SLOTS = {
    "killed": "prior", "seed": "prior", "odd": "entry", "even": "entry",
    "key": "q", "extra": "0", "scan": "entry",
}
CLAMP = "std::min(q, n)"


@dataclass(frozen=True)
class Case:
    id: str
    name: str
    reference: dict
    target: dict
    positive: bool
    responsible: tuple
    mechanism: str = "cursor"
    nonmonotone: bool = False


CASES = (
    Case("a01", "reset and equivalent clamp", {}, {"seed": "0", "key": CLAMP}, True, ("seed",)),
    Case("a02", "reset at scan entry", {}, {"scan": "0", "key": CLAMP}, True, ("scan",)),
    Case("a03", "transitive reset and killed write", {},
         {"seed": "0", "killed": "n"}, True, ("seed",)),
    Case("a04", "nested conditional reset", {}, {"odd": "0", "key": CLAMP}, True, ("odd",)),
    Case("a05", "strong and weak resets", {},
         {"odd": "0", "even": "entry - 1"}, True, ("odd",)),
    Case("a06", "killed write despite carry", {}, {"killed": "n", "key": CLAMP}, False, ()),
    Case("a07", "same-order shams", {"seed": "q / 2"}, {"seed": "0", "key": CLAMP}, False, ()),
    Case("a08", "appropriate quadratic restart", {"seed": "0"},
         {"seed": "0", "key": CLAMP}, False, (), nonmonotone=True),
    Case("a09", "constant-factor auxiliary work", {},
         {"extra": "2", "key": CLAMP}, False, (), "other"),
    Case("a10", "quadratic auxiliary work", {},
         {"extra": "q", "key": CLAMP}, True, ("extra",), "other"),
    Case("a11", "logarithmic auxiliary work multiplier", {},
         {"extra": "log_width(n)", "key": CLAMP}, False, (), "other"),
    Case("a12", "half-power auxiliary work multiplier", {},
         {"extra": "integer_root(n)", "key": CLAMP}, False, (), "other"),
)


def canonical_bytes(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(data):
    return sha256(data).hexdigest()


def source_and_spans(template, options):
    """Record exact byte spans of governed statements and verify the marked template."""
    if not options.keys() <= SLOTS.keys():
        raise ValueError("Unknown authored fixture option")
    source = template
    for slot, value in (SLOTS | options).items():
        marker = f"@{slot}@"
        if template.count(marker) != 1:
            raise ValueError(f"Expected one template marker {marker}")
        source = source.replace(marker, value)
    spans = {}
    lines = source.splitlines(keepends=True)
    for line_number, line in enumerate(template.splitlines(keepends=True), 1):
        for slot in SLOTS:
            if f"@{slot}@" in line:
                start = sum(len(item.encode()) for item in lines[:line_number - 1])
                text = lines[line_number - 1].rstrip("\n")
                spans[slot] = {"line": line_number, "start": start,
                               "end": start + len(text.encode()), "text": text}
    return source.encode(), spans


def changed_units(template, case):
    reference_source, reference_spans = source_and_spans(template, case.reference)
    target_source, target_spans = source_and_spans(template, case.target)
    slots = [slot for slot in SLOTS
             if reference_spans[slot]["text"] != target_spans[slot]["text"]]
    if any(target_spans[right]["line"] - target_spans[left]["line"] < 2
           for left, right in pairwise(slots)):
        raise ValueError("Adjacent authored statements require one change unit")
    units = {slot: f"U{index:02}" for index, slot in enumerate(slots, 1)}
    span_map = {
        "reference_source_sha256": digest(reference_source),
        "target_source_sha256": digest(target_source),
        "units": [{"id": units[slot], "target": target_spans[slot],
                   "reference": reference_spans[slot]} for slot in slots],
    }
    for unit in span_map["units"]:
        for side, source in (("reference", reference_source), ("target", target_source)):
            span = unit[side]
            if source[span["start"]:span["end"]].decode() != span["text"]:
                raise ValueError("Source span does not match the materialized fixture")
    return units, span_map


def workloads(nonmonotone=False):
    result = {}
    for stream in (*STREAMS, *CHALLENGE):
        for n in SIZES:
            values = {
                "dense": range(1, n + 1),
                "plateau": (1 + index // 2 for index in range(n)),
                "curved": (1 + index * index // n for index in range(n)),
                "boundary_plateau": (1 if index < n // 2 else n for index in range(n)),
            }
            queries = list(values[stream])
            if nonmonotone:
                queries = [queries[n - 1 - index // 2] if index % 2 == 0 else queries[index // 2]
                           for index in range(n)]
            result[stream, n] = queries
    for n in SIZES:
        if len({tuple(result[stream, n]) for stream in (*STREAMS, *CHALLENGE)}) != 4:
            raise ValueError("Authored workloads must have distinct streams at each size")
    return result


def independent_counts(options, n, queries):
    """Evaluate rank contract and closed-form episode costs without executing the scan."""
    data = list(range(1, n + 1))
    ranks = [bisect_right(data, q) for q in queries]
    aux = {
        "0": 0, "2": 2 * n, "q": sum(queries),
        "log_width(n)": n * (n.bit_length() - 1), "integer_root(n)": n * isqrt(n),
    }[options.get("extra", "0")]
    if options.get("scan") == "0":
        return ranks, sum(ranks), aux
    previous = [0, *ranks[:-1]]
    starts = {
        "0": [0] * n,
        "q / 2": [q // 2 for q in queries],
        "prior": previous,
    }[options.get("seed", "prior")]
    starts = starts.copy()
    if options.get("odd") == "0":
        starts[::2] = [0] * (n // 2)
    if options.get("even") == "entry - 1":
        starts[1::2] = [start - 1 for start in starts[1::2]]
    if any(not 0 <= start <= end for start, end in zip(starts, ranks, strict=True)):
        raise ValueError("Inputs violate the authored variant's rank invariant")
    return ranks, sum(ranks) - sum(starts), aux


def graph(row, options, units, extent, previous_exit, query_key):
    query, start, end, killed, seed, first, second, entry, key, extra = row
    nodes = []

    def node(id, value, parents=(), slot=None, statement=None):
        nodes.append({"id": id, "statement": statement or id, "value": value,
                      "parents": list(parents), "unit": units.get(slot)})

    node("previous-exit", previous_exit)
    node("query-key", query_key)
    node("query-ordinal", query)
    node("extent", extent)
    node("killed-write", killed, slot="killed")
    seed_parents = {"0": (), "q / 2": ("query-key",), "prior": ("previous-exit",)}
    node("seed", seed, seed_parents[options.get("seed", "prior")], "seed")
    node("copy-1", first, ("seed",))
    node("copy-2", second, ("copy-1",))
    branch = "odd" if query % 2 == 0 else "even"
    parents = ("query-ordinal",) if options.get(branch) == "0" else ("copy-2", "query-ordinal")
    node("entry", entry, parents, branch, f"{branch}-entry")
    node("rank-loop", start, () if options.get("scan") == "0" else ("entry",), "scan")
    node("key", key, ("query-key", "extent") if options.get("key") == CLAMP else ("query-key",), "key")
    node("guard", None, ("rank-loop", "key", "extent"))
    auxiliary_parents = {"q": ("query-key",), "log_width(n)": ("extent",), "integer_root(n)": ("extent",)}
    node("auxiliary", extra, auxiliary_parents.get(options.get("extra"), ()), "extra")
    return {"scan": "rank-loop", "object": "data", "query": query, "extent": extent,
            "entry": start, "exit": end, "entry_nodes": ["rank-loop"],
            "work_nodes": ["guard"], "nodes": nodes,
            "other_events": [{"site": "auxiliary", "count": extra, "roots": ["auxiliary"]}]}


def verify_dependencies(row, options, n, key, previous):
    query, start, _, killed, seed, first, second, entry, observed_key, extra = row
    seed_expr = options.get("seed", "prior")
    wanted_seed = {"0": 0, "q / 2": key // 2, "prior": previous}[seed_expr]
    branch = ("odd", "even")[query % 2]
    wanted_entry = {"0": 0, "entry": second, "entry - 1": second - 1}[options.get(branch, "entry")]
    extra_expr = {"0": 0, "2": 2, "q": key, "log_width(n)": n.bit_length() - 1, "integer_root(n)": isqrt(n)}
    wanted_extra = extra_expr[options.get("extra", "0")]
    if ((killed, seed, first, second, entry, start, observed_key, extra) !=
            (n if options.get("killed") == "n" else previous, wanted_seed, seed, first,
             wanted_entry, 0 if options.get("scan") == "0" else entry, key, wanted_extra)):
        raise ValueError("Trace disagrees with the instrumented source dependence")


def parse_trace(stderr, options, units, grid, expected):
    lines = iter(stderr.decode().splitlines())
    result = {}
    for (stream, n), queries in grid.items():
        if stream not in STREAMS:
            continue
        ranks, advances, extra = expected[stream, n]
        rows = []
        previous = 0
        for index, q in enumerate(queries):
            row = [int(value) for value in next(lines, "").split()]
            if len(row) != 10 or row[0] != index or row[2] != ranks[index]:
                raise ValueError("Trace query identity or exit differs from the output oracle")
            if not 0 <= row[1] <= row[2] <= n:
                raise ValueError("Trace interval is outside the authored sequence")
            verify_dependencies(row, options, n, q, previous)
            rows.append(graph(row, options, units, n, previous, q))
            previous = row[2]
        if next(lines, "") != f"TRACE {advances} {extra}":
            raise ValueError("Trace event totals differ from independently computed counts")
        if (sum(row["exit"] - row["entry"] for row in rows) != advances or
                sum(row["nodes"][-1]["value"] for row in rows) != extra):
            raise ValueError("Trace totals differ from actual episode distances")
        result[stream, n] = {"output_sha256": digest(rank_stdout(ranks)), "work": advances + extra,
                             "advances": advances, "episodes": rows}
    if next(lines, None) is not None:
        raise ValueError("Trace contains extra records")
    return result


def rank_stdout(ranks):
    return "".join(f"{rank}\n" for rank in ranks).encode()


def run_batch(binary, grid, expected, mode):
    stdin = [str(len(grid)), *(f"{n} {' '.join(map(str, queries))}" for (_, n), queries in grid.items())]
    result = gate1_sandbox.execute(binary, ("\n".join(stdin) + "\n").encode())
    stdout = gate1_sandbox.checked_output(result)
    if result.stderr.startswith(b"CAP ") or b"\nCAP " in result.stderr:
        raise RuntimeError("Authored batch reached its registered tick cap")
    oracle_stdout = b"".join(rank_stdout(row[0]) for row in expected.values())
    if stdout != oracle_stdout:
        raise ValueError("C++ output differs from the independent rank oracle")
    if mode == "count":
        oracle_counts = b"".join(f"COUNT {advances + extra}\n".encode()
                                 for _, advances, extra in expected.values())
        if result.stderr != oracle_counts:
            raise ValueError("Independent counting mode disagrees with the authored cost oracle")
    elif mode != "trace" and result.stderr:
        raise ValueError(f"Unexpected {mode} diagnostics: {result.stderr[:300]!r}")
    return result.stderr, digest(stdout)


def screen(counts):
    checks = {}
    for stream in STREAMS:
        pairs = [counts[stream, n] for n in SIZES]
        slopes = [log(target / reference) for target, reference in pairs]
        slope = linear_regression([log(n) for n in SIZES], slopes).slope
        ratio = pairs[-1][0] / pairs[-1][1]
        checks[stream] = {"slope": slope, "largest_ratio": ratio,
                          "positive": slope >= 0.50 and ratio >= 1.50}
    return checks


def verified_restorations(counted, expected_units):
    """Check the preregistration's 80% rule on both largest sizes and all streams."""
    evidence = {}
    for unit in sorted(name.removeprefix("restore_") for name in counted if name.startswith("restore_")):
        rows = []
        for stream in (*STREAMS, *CHALLENGE):
            for n in SIZES[-2:]:
                key = stream, n
                excess = counted["target"][key] - counted["reference"][key]
                recovered = counted["target"][key] - counted[f"restore_{unit}"][key]
                rows.append({"stream": stream, "size": n, "excess": excess, "recovered": recovered})
        sufficient = all(row["excess"] > 0 and 5 * row["recovered"] >= 4 * row["excess"] for row in rows)
        evidence[unit] = {"sufficient": sufficient, "rows": rows}
    if {unit for unit, value in evidence.items() if value["sufficient"]} != set(expected_units):
        raise ValueError("Intervention recovery disagrees with the authored reference")
    return evidence


def calibrate_library():
    """Quantify the distance between calls and container-size proxies for std::find_if."""
    source = FIND_CALIBRATION.read_text(encoding="utf-8").encode()
    input_data = "".join(f"{size}\n" for size in SIZES).encode()
    rows = [
        {"size": n, "key": key, "position": key, "predicate_calls": min(key + 1, n), "size_proxy": n}
        for n in SIZES for key in (0, n // 2, n - 1, n)
    ]
    expected = "".join(f"{row['size']} {row['key']} {row['position']} {row['predicate_calls']}\n"
                       for row in rows).encode()
    builds = []
    for optimization in ("O0", "O2", "O3"):
        binary = gate1_sandbox.compile_cpp(source, f"-{optimization}")
        result = gate1_sandbox.execute(binary, input_data)
        observed = gate1_sandbox.checked_output(result)
        if observed != expected or result.stderr:
            raise ValueError(f"std::find_if calibration did not match the independent oracle at {optimization}")
        builds.append({"optimization": optimization, "binary_sha256": digest(binary),
                       "stdout_sha256": digest(observed)})
    return {"source_sha256": digest(source), "input_sha256": digest(input_data), "builds": builds,
            "rows": rows}


def run_panel(output):
    template = TEMPLATE.read_text(encoding="utf-8")
    output.mkdir(parents=True, exist_ok=False)
    source_dir = output / "sources"
    source_dir.mkdir()
    compiler = gate1_sandbox.checked_output(gate1_sandbox.invoke(["g++", "--version"])).decode()
    traces = {"schema": "eapg.paired.traces.v1", "cases": []}
    receipt = {"schema": "eapg.paired.authored-oracle.v1", "group": GROUP, "compiler": compiler,
               "platform": platform.system(), "machine": platform.machine(), "template_sha256": digest(template.encode()),
               "count_metric": "successful rank-scan advances plus completed explicit auxiliary-loop iterations",
               "special_flags": {"trace": ["-DTRACE"], "count": ["-DCOUNT"],
                                 "ubsan": ["-fsanitize=undefined", "-fno-sanitize-recover=undefined"]},
               "launcher_sha256": digest(Path(gate1_sandbox.__file__).read_bytes()), "builds": [],
               "sizes": list(SIZES), "prediction_streams": list(STREAMS),
               "challenge_streams": list(CHALLENGE), "cases": []}
    binaries = {}
    runs = {}

    def measure(options, grid, mode, optimization):
        source, _ = source_and_spans(template, options)
        source_hash = digest(source)
        path = source_dir / f"{source_hash}.cpp"
        if not path.exists():
            path.write_bytes(source)
        flags = receipt["special_flags"].get(mode, [])
        build_key = source_hash, mode, optimization
        if build_key not in binaries:
            binaries[build_key] = gate1_sandbox.compile_cpp(source, f"-{optimization}", *flags)
            receipt["builds"].append({"source_sha256": source_hash, "mode": mode,
                                      "optimization": optimization, "binary_sha256": digest(binaries[build_key])})
        expected = {key: independent_counts(options, key[1], queries) for key, queries in grid.items()}
        input_hash = digest(canonical_bytes([[stream, n, queries] for (stream, n), queries in grid.items()]))
        run_key = build_key, input_hash
        if run_key not in runs:
            runs[run_key] = run_batch(binaries[build_key], grid, expected, mode)
        return runs[run_key], expected, input_hash, source_hash

    for case in CASES:
        units, span_map = changed_units(template, case)
        span_hash = digest(canonical_bytes(span_map))
        grid = workloads(case.nonmonotone)
        prediction_grid = {key: queries for key, queries in grid.items() if key[0] in STREAMS}
        variants = {"reference": case.reference, "target": case.target}
        for slot, unit in units.items():
            variants[f"restore_{unit}"] = case.target | {slot: case.reference.get(slot, SLOTS[slot])}
        status = (
            "confirmed_positive" if case.positive else
            {"a09": "constant_factor", "a11": "indeterminate", "a12": "indeterminate"}.get(
                case.id, "verified_negative"
            )
        )
        accepted_units = [units[slot] for slot in case.responsible]
        location = "unknown"
        if accepted_units:
            location = "at_symptom" if case.responsible[0] in {"scan", "extra"} else "off_symptom"
        case_receipt = {"id": case.id, "name": case.name, "span_map_sha256": span_hash,
                        "span_map": span_map, "group": GROUP, "units": list(units.values()),
                        "status": status, "timing": "not_measured", "mechanism": case.mechanism,
                        "location": location, "acceptable_sets": [[unit] for unit in accepted_units],
                        "runs": []}
        side = {}
        counted = {}
        for variant, options in variants.items():
            modes = [("plain", "O2"), ("ubsan", "O2"), ("count", "O2")]
            if variant in {"target", "reference"}:
                modes.append(("trace", "O2"))
                modes.extend([("count", "O0"), ("count", "O3")])
            for mode, optimization in modes:
                inputs = prediction_grid if mode == "trace" else grid
                (stderr, output_hash), counts, input_hash, source_hash = measure(options, inputs, mode, optimization)
                case_receipt["runs"].append({"variant": variant, "mode": mode, "opt": optimization,
                                             "source_sha256": source_hash, "input_sha256": input_hash,
                                             "stdout_sha256": output_hash, "stderr_sha256": digest(stderr)})
                if mode == "trace":
                    side[variant] = parse_trace(stderr, options, units, inputs, counts)
                if mode == "count" and optimization == "O2":
                    counted[variant] = {key: strides + auxiliary for key, (_, strides, auxiliary) in counts.items()}
        checks = screen({key: (counted["target"][key], counted["reference"][key]) for key in grid})
        if all(check["positive"] for check in checks.values()) != case.positive:
            raise ValueError(f"Registered positive screen disagrees with the construction for {case.id}")
        case_receipt["count_screen"] = checks
        if case.positive:
            case_receipt["restorations"] = verified_restorations(counted, accepted_units)
        case_receipt["independent_counts"] = [
            {"stream": stream, "size": n, "work": {name: rows[stream, n] for name, rows in counted.items()}}
            for stream, n in grid
        ]
        receipt["cases"].append(case_receipt)
        traces["cases"].append({"id": case.id, "units": list(units.values()), "span_map_sha256": span_hash,
                                "observations": [
                                    {"stream": stream, "size": n, "status": "complete",
                                     **{name: rows[stream, n] for name, rows in side.items()}}
                                    for stream, n in prediction_grid
                                ]})
        print(f"Verified {case.id}: {case.name}", flush=True)
    receipt["unique_program_executions"] = len(runs)
    receipt["library_calibration"] = calibrate_library()
    for name, value in (("traces", traces), ("oracle", receipt)):
        (output / f"{name}.json").write_bytes(canonical_bytes(value) + b"\n")
    return traces, receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="New directory for separate trace, oracle and source outputs")
    args = parser.parse_args()
    _, receipt = run_panel(args.output)
    print(f"{len(receipt['cases'])} cases, {len(receipt['builds'])} builds, "
          f"{receipt['unique_program_executions']} batch executions")


if __name__ == "__main__":
    main()
