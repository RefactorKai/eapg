"""Reprofile the 25 affected synthetic fast programs without changing Phase 1."""

import hashlib
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

from pipeline import (
    compute_tick_ceiling,
    extract_macro_nodes,
    fit_dual_family_scaling,
    generate_pilot_100_corpus,
    instrument_cpp_source,
    normalize_synthetic_braces,
    preprocess_pass_zero,
)

FIT_SIZES = (16, 64, 256, 1024, 4096)
CHECK_SIZES = (24, 91, 92)
PAIR_SIZES = (16, 24)
MODULUS = 1 << 64
FLAGS = ("-std=c++17", "-O2")
FROZEN_SHA = "4a3b563cdd54c471f39df95e7d40ec3ae5433259795cadcde80272955ea44cb5"
PIPELINE_SHA = "7c855651566c1a7dc003fdcb291d8edd3ff1a99c671f781eb595d72c492ae743"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def compile_source(source, executable):
    subprocess.run(
        ["g++", *FLAGS, "-x", "c++", "-", "-o", str(executable)],
        input=source.encode(), capture_output=True, timeout=30, check=True,
    )


def execute(executable, n, input_gen):
    # The source hashes are checked before compilation. This runner is for the
    # fixed synthetic fixtures, which print one answer and one small dump.
    isolation = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == "nt" else {"start_new_session": True}
    )
    result = subprocess.run(
        [str(executable)], input=input_gen(n), capture_output=True, text=True,
        timeout=5, check=True, env={**os.environ, "EAPG_N": str(n)}, **isolation,
    )
    assert len(result.stdout) < 64 and len(result.stderr) < 16_384
    return result


def normalized_nodes(source):
    expanded, aliases = preprocess_pass_zero(source)
    normalized = normalize_synthetic_braces(expanded)
    return normalized, extract_macro_nodes(normalized, aliases)


def topology(nodes):
    return [
        tuple(node[key] for key in ("id", "role", "parent", "weight_expr"))
        for node in nodes
    ]


def profile_pair(row, input_gen, scratch, oracle):
    pair_id = row["pair_id"]
    is_memo = row["mechanism_id"] == "A2.1"
    original = row["fast_code"]
    patched, replacements = re.subn(r"\blong long\b", "unsigned long long", original)
    assert replacements in ((3, 4) if is_memo else (5,)), pair_id
    # Memo uses unsigned maximum as its sentinel after the type change.
    if is_memo:
        assert "!= -1" in patched and "int init_val = -1;" in patched
        assert all(value != MODULUS - 1 for value in oracle)
        patched = patched.replace("!= -1", "!= ~0ULL")
        patched = patched.replace("int init_val = -1;", "unsigned long long init_val = ~0ULL;")
    bias = 0 if is_memo else int(re.search(r"long long base_ways = (\d+);", original)[1]) + 3
    _, original_nodes = normalized_nodes(original)
    normalized, nodes = normalized_nodes(patched)
    assert len(nodes) == row["v_fast"] and topology(nodes) == topology(original_nodes), pair_id
    instrumented = instrument_cpp_source(normalized, nodes)
    assert instrumented.count("    std::exit(0);") == 1
    # The successful atexit dump returns normally. The cap path still exits.
    instrumented = instrumented.replace("    std::exit(0);", "    if (breached) std::exit(0);")
    instrumented = "static_assert(~0ULL == 18446744073709551615ULL);\n" + instrumented
    fast_binary = scratch / f"{pair_id}_fast.exe"
    slow_binary = scratch / f"{pair_id}_slow.exe"
    compile_source(instrumented, fast_binary)
    compile_source(row["slow_code"], slow_binary)
    runs = {}
    for n in sorted(FIT_SIZES + CHECK_SIZES):
        expected = str((oracle[n] + bias) % MODULUS)
        result = execute(fast_binary, n, input_gen)
        match = re.fullmatch(
            r"\s*---EAPG_DUMP_START---\s*(\{.*\})\s*---EAPG_DUMP_END---\s*",
            result.stderr, re.DOTALL,
        )
        assert match and result.stdout == expected + "\n", (pair_id, n, result)
        trace = json.loads(match[1])
        assert trace["status"] == "CLEAN_COMPLETION", (pair_id, n, trace)
        assert set(trace["nodes"]) == {node["id"] for node in nodes}, (pair_id, n)
        assert sum(c["work"] for c in trace["nodes"].values()) == trace["total_ticks"]
        assert 0 < trace["total_ticks"] < compute_tick_ceiling(n), (pair_id, n)
        run = {
            **trace,
            "exit_code": result.returncode,
            "input": input_gen(n),
            "oracle": expected,
            "stdout": result.stdout,
        }
        if n in PAIR_SIZES:
            slow = execute(slow_binary, n, input_gen)
            assert not slow.stderr and slow.stdout == result.stdout, (pair_id, n, slow)
            run["frozen_slow_stdout"] = slow.stdout
        runs[n] = run

    fits = {}
    for node in nodes:
        nid = node["id"]
        fits[nid] = {
            channel: fit_dual_family_scaling(
                FIT_SIZES, [runs[n]["nodes"][nid][key] for n in FIT_SIZES],
            )
            for channel, key in (("hits", "cnt"), ("work", "work"))
        }
    assert all(fit["work"]["growth"] == "POLY" for fit in fits.values()), pair_id
    best_work = max((fit["work"] for fit in fits.values()), key=lambda fit: fit["alpha"])
    assert best_work["r2_poly"] >= 0.95 and best_work["points"] == 5, pair_id
    return {
        "pair_id": pair_id,
        "mechanism": row["mechanism_id"],
        "frozen_fast_sha256": digest(original.encode()),
        "corrected_fast_sha256": digest(patched.encode()),
        "instrumented_fast_sha256": digest(instrumented.encode()),
        "corrected_fast_code": patched,
        "frozen_max_fast_work_alpha": row["max_work_fast"],
        "corrected_max_fast_work_alpha": best_work["alpha"],
        "fits": fits,
        "runs": runs,
    }


def main():
    if not __debug__:
        raise RuntimeError("Run without Python optimization so that fixture checks are active")
    pilot = (ROOT / "artifacts/scope_isolated_pilot/pilot100_results.json").read_bytes()
    assert digest(pilot) == FROZEN_SHA
    assert digest((ROOT / "pipeline.py").read_bytes()) == PIPELINE_SHA
    affected = [r for r in json.loads(pilot) if r["mechanism_id"] in {"A2.1", "B.3"}]
    assert sum(row["mechanism_id"] == "A2.1" for row in affected) == 13
    assert sum(row["mechanism_id"] == "B.3" for row in affected) == 12
    generated = {r["pair_id"]: r for r in generate_pilot_100_corpus()}
    oracle = [1, 1]
    while len(oracle) <= max(FIT_SIZES):
        oracle.append((oracle[-2] + oracle[-1]) % MODULUS)
    assert oracle[16] == 1597 and oracle[92] == 12_200_160_415_121_876_738
    compiler = subprocess.check_output(["g++", "--version"], text=True).splitlines()[0]
    with TemporaryDirectory(prefix="build-", dir=HERE) as workdir:
        scratch = Path(workdir)

        def profile(row):
            fixture = generated[row["pair_id"]]
            for key in ("slow_code", "fast_code", "mechanism_id"):
                assert row[key] == fixture[key], (row["pair_id"], key)
            return profile_pair(row, fixture["input_gen"], scratch, oracle)

        with ThreadPoolExecutor(max_workers=4) as executor:
            records = list(executor.map(profile, affected))

    summary = {}
    for mechanism in ("A2.1", "B.3"):
        cohort = [r for r in records if r["mechanism"] == mechanism]
        alphas = [r["corrected_max_fast_work_alpha"] for r in cohort]
        summary[mechanism] = {
            "pairs": len(cohort),
            "mean_max_fast_work_alpha": sum(alphas) / len(alphas),
            "min_max_fast_work_alpha": min(alphas),
            "max_max_fast_work_alpha": max(alphas),
            "pairs_matching_frozen_alpha": sum(
                r["corrected_max_fast_work_alpha"] == r["frozen_max_fast_work_alpha"] for r in cohort
            ),
        }
    output = {
        "protocol": "phase1-correction-v1, fast recurrence reprofile",
        "arithmetic": "unsigned 64-bit recurrence modulo 2^64",
        "pilot_sha256": FROZEN_SHA,
        "pipeline_sha256": PIPELINE_SHA,
        "script_sha256": digest(Path(__file__).read_bytes()),
        "compiler": compiler,
        "compiler_flags": FLAGS,
        "python": sys.version.split()[0],
        "dependencies": {package: version(package) for package in ("tree-sitter", "tree-sitter-cpp")},
        "fit_sizes": FIT_SIZES,
        "additional_oracle_sizes": CHECK_SIZES,
        "frozen_slow_pair_sizes": PAIR_SIZES,
        "oracle_comparisons": len(records) * len(FIT_SIZES + CHECK_SIZES),
        "paired_stdout_comparisons": len(records) * len(PAIR_SIZES),
        "summary": summary,
        "records": records,
    }
    path = HERE / "fast_recurrence_results.json"
    path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(summary, indent=2))
    print(f"{output['oracle_comparisons']} oracle and {output['paired_stdout_comparisons']} paired comparisons passed.")


if __name__ == "__main__":
    main()
