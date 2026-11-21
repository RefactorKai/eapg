"""Run the 25 frozen and corrected fast recurrences under UBSan and record a receipt."""

import hashlib
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCALING = ROOT / "artifacts/phase1_correction/scaling"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCALING))

import check_fast_recurrences as scaling  # noqa: E402
from pipeline import generate_pilot_100_corpus, instrument_cpp_source  # noqa: E402

SIZES = (16, 24, 91, 92, 256, 1024, 4096)
FLAGS = ("-std=c++17", "-O2", "-fsanitize=undefined", "-fno-sanitize-recover=all")
RESULTS = HERE / "fast_recurrence_sanitizer_results.json"
SCALING_RESULTS = SCALING / "fast_recurrence_results.json"
DUMP = re.compile(r"\s*---EAPG_DUMP_START---\s*(\{.*\})\s*---EAPG_DUMP_END---\s*", re.DOTALL)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def compile_source(source, executable):
    subprocess.run(["g++", *FLAGS, "-x", "c++", "-", "-o", str(executable)],
                   input=source.encode(), capture_output=True, timeout=120, check=True)


def run(executable, n, input_gen):
    result = subprocess.run([str(executable)], input=input_gen(n), capture_output=True, text=True,
                            timeout=30, env={**os.environ, "EAPG_N": str(n)}, start_new_session=True)
    finding = next((line.strip() for line in result.stderr.splitlines() if "runtime error:" in line), None)
    if finding:
        finding = re.sub(r"^.*?(runtime error:)", r"\1", finding)
    return result, finding


def instrumented_source(corrected):
    normalized, nodes = scaling.normalized_nodes(corrected)
    instrumented = instrument_cpp_source(normalized, nodes)
    instrumented = instrumented.replace("    std::exit(0);", "    if (breached) std::exit(0);")
    return "static_assert(~0ULL == 18446744073709551615ULL);\n" + instrumented


def check_pair(record, fixture, oracle, scratch):
    pair_id, input_gen = record["pair_id"], fixture["input_gen"]
    frozen, corrected = fixture["fast_code"], record["corrected_fast_code"]
    assert digest(frozen.encode()) == record["frozen_fast_sha256"], pair_id
    assert digest(corrected.encode()) == record["corrected_fast_sha256"], pair_id
    instrumented = instrumented_source(corrected)
    assert digest(instrumented.encode()) == record["instrumented_fast_sha256"], pair_id
    is_memo = record["mechanism"] == "A2.1"
    bias = 0 if is_memo else int(re.search(r"long long base_ways = (\d+);", frozen)[1]) + 3
    builds = {}
    for name, source in (("frozen", frozen), ("corrected", corrected), ("instrumented", instrumented)):
        builds[name] = scratch / f"{pair_id}_{name}"
        compile_source(source, builds[name])
    sizes = {}
    for n in SIZES:
        expected = str((oracle[n] + bias) % scaling.MODULUS) + "\n"
        frozen_result, frozen_finding = run(builds["frozen"], n, input_gen)
        assert frozen_finding or (frozen_result.returncode == 0 and frozen_result.stdout == expected), (pair_id, n)
        entry = {"frozen": {"exit_code": frozen_result.returncode, "finding": frozen_finding}}
        for name in ("corrected", "instrumented"):
            result, finding = run(builds[name], n, input_gen)
            assert result.returncode == 0 and finding is None and result.stdout == expected, (pair_id, name, n)
            if name == "instrumented":
                trace = json.loads(DUMP.fullmatch(result.stderr)[1])
                assert trace["status"] == "CLEAN_COMPLETION", (pair_id, n)
            else:
                assert not result.stderr, (pair_id, n)
            entry[name] = {"exit_code": 0, "finding": None, "stdout": result.stdout.strip()}
        sizes[str(n)] = entry
    return {"pair_id": pair_id, "mechanism": record["mechanism"],
            "frozen_fast_sha256": record["frozen_fast_sha256"],
            "corrected_fast_sha256": record["corrected_fast_sha256"],
            "instrumented_fast_sha256": record["instrumented_fast_sha256"], "sizes": sizes}


def main():
    if not __debug__:
        raise RuntimeError("Run without Python optimization so that fixture checks are active")
    assert digest((ROOT / "pipeline.py").read_bytes()) == scaling.PIPELINE_SHA
    receipt = json.loads(SCALING_RESULTS.read_text("utf-8"))
    records = receipt["records"]
    assert [r["mechanism"] for r in records].count("A2.1") == 13
    assert [r["mechanism"] for r in records].count("B.3") == 12
    generated = {r["pair_id"]: r for r in generate_pilot_100_corpus()}
    oracle = [1, 1]
    while len(oracle) <= max(SIZES):
        oracle.append((oracle[-2] + oracle[-1]) % scaling.MODULUS)
    assert oracle[92] == 12_200_160_415_121_876_738
    compiler = subprocess.check_output(["g++", "--version"], text=True).splitlines()[0]
    with TemporaryDirectory(prefix="ubsan-") as workdir:
        with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as executor:
            checked = list(executor.map(
                lambda r: check_pair(r, generated[r["pair_id"]], oracle, Path(workdir)), records))
    frozen_trapped = {n: sum(r["sizes"][str(n)]["frozen"]["finding"] is not None for r in checked) for n in SIZES}
    output = {
        "protocol": "wp-f2 fast recurrence sanitizer check",
        "pipeline_sha256": scaling.PIPELINE_SHA,
        "scaling_results_sha256": digest(SCALING_RESULTS.read_bytes()),
        "script_sha256": digest(Path(__file__).read_bytes()),
        "compiler": compiler,
        "compiler_flags": FLAGS,
        "python": sys.version.split()[0],
        "sizes": SIZES,
        "programs": len(checked),
        "corrected_runs_clean": sum(len(SIZES) for _ in checked),
        "instrumented_runs_clean": sum(len(SIZES) for _ in checked),
        "frozen_programs_with_finding_by_size": {str(n): frozen_trapped[n] for n in SIZES},
        "records": checked,
    }
    RESULTS.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(checked)} corrected and instrumented programs UBSan-clean at N={list(SIZES)}; "
          f"frozen programs with a finding by N: {output['frozen_programs_with_finding_by_size']}")


if __name__ == "__main__":
    main()
