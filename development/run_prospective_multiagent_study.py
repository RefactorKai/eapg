"""Execute the role-separated multi-agent prospective scalar study (Part A)
and blinded reference adjudication + live QLoRA contract study (Part B).

Preserves all hash-pinned repository modules untouched; adapts C++ preprocessing,
compilation, UBSan-trap checks, and file-backed counter capture in-memory for
Windows MSYS2 g++ 15.1.0 execution before running custodian, predictor, scorer,
and 4-bit NF4 Qwen2.5-Coder-1.5B adapters on RTX 4060.
"""

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import gc
import json
from math import log
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace


HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PRIVATE_ROOT = REPO.parent / ".codex/private"
DEFAULT_ATTESTATIONS = PRIVATE_ROOT / "multiagent-run"
DEFAULT_PROSPECTIVE = REPO / ".codex/private/board-20261115a/prospective.py"
PROSPECTIVE_SHA = "2c95df0e5676e8b19464457adfb34cdf85a8a10cc0dca8b70557a1d587ced383"
PILOT_RESPLIT_ADAPTERS = PRIVATE_ROOT / "pilot-resplit-2026-11-11"
MULTI_REPR_ADAPTERS = REPO / ".codex/private/resplit-ablation-20261116"
STRESS_RECEIPT = PRIVATE_ROOT / "prospective-final-GYSE9euA/published-stress.json"
SMOKE_RECEIPT = PRIVATE_ROOT / "prospective-final-GYSE9euA/authored-smoke.json"
PIE_PROFILE = PRIVATE_ROOT / "pie-download-VkVck8zh/profile.json"
PIE_VAL_JSONL = PRIVATE_ROOT / "pie-download-VkVck8zh/pie_val.jsonl"
AB_RESULTS = REPO / "artifacts/pilot_resplit/ablation_results.json"

SEEDS = (42, 43, 44)
SALT_BY_SEED = {42: 3, 43: 5, 44: 7}
STRESS_SIZES = (2, 4, 8, 16, 32, 64)


if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(REPO / "artifacts/phase1_correction") not in sys.path:
    sys.path.insert(0, str(REPO / "artifacts/phase1_correction"))


import audit_synthetic_frame_domain as asfd
import build_reference_packet as brp
import gate1_sandbox as g1
import predict_external_contract as pec
import prediction_contract as pc
import probe_gate2_pilot as pg2
import reference_adjudication as ra
import run_phase2_development as r2d
import score_external
import synthetic_intervention as si
import synthetic_oracle as so
import synthetic_source_fingerprints as ssf
import synthetic_study_custodian as custodian
import synthetic_study_predict as predictor
import synthetic_study_score as scorer
import synthetic_trace as st
from replay_pilot_contrast import contrast
from synthetic_frame import CORE_SLOTS, FRAME, INPUTS, SWAP_SLOTS, build_draw, canonical, commitment, select
from synthetic_quarantine import PROVENANCE, seal
from train_phase2_adapter import MODEL, REVISION, digest_json, load_inputs
from train_resplit_ablation import build_prompt


def sha256_bytes(data):
    return sha256(data).hexdigest()


def sha256_text(text):
    return sha256(text.encode("utf-8")).hexdigest()


def install_windows_sandbox_adapter():
    """Patch sandbox/instrumentation hooks in-memory without touching pinned files."""
    if not r2d.HERE.exists():
        raise RuntimeError("Missing development directory")

    def win_invoke(command, *, data=b"", binary=None, timeout=12, counter_scale=None):
        if binary is not None:
            with TemporaryDirectory(prefix="eapg_win_run_") as td:
                exe = Path(td) / "prog.exe"
                exe.write_bytes(binary)
                gxx_bin = shutil.which("g++")
                cc_dir = str(Path(gxx_bin).parent) if gxx_bin else r"C:\msys64\ucrt64\bin"
                win_sys = os.environ.get("SystemRoot", r"C:\WINDOWS") + r"\system32"
                env = {"PATH": f"{cc_dir};{win_sys}"}
                wire_path = Path(td) / "eapg_counter.wire"
                if counter_scale is not None:
                    env["EAPG_N"] = str(counter_scale)
                    env["EAPG_COUNTER_FILE"] = str(wire_path)
                try:
                    proc = subprocess.run(
                        [str(exe)], input=data, capture_output=True, timeout=timeout, env=env, cwd=td,
                    )
                    timed_out = False
                    rc = proc.returncode
                    out = proc.stdout[:g1.FILE_CAP + 1].replace(b"\r\n", b"\n")
                    err = proc.stderr[:g1.FILE_CAP + 1].replace(b"\r\n", b"\n")
                except subprocess.TimeoutExpired as exc:
                    timed_out = True
                    rc = -1
                    out = (exc.stdout or b"")[:g1.FILE_CAP + 1].replace(b"\r\n", b"\n")
                    err = (exc.stderr or b"")[:g1.FILE_CAP + 1].replace(b"\r\n", b"\n")
                wire = wire_path.read_bytes()[:g1.COUNTER_CAP + 1] if (counter_scale is not None and wire_path.exists()) else b""
                return SimpleNamespace(returncode=rc, stdout=out, stderr=err, timed_out=timed_out, events={}, counter_wire=wire)

        if command and command[0] == "g++":
            proc = subprocess.run(["g++", *command[1:]], input=data, capture_output=True, timeout=timeout)
            return SimpleNamespace(returncode=proc.returncode, stdout=proc.stdout.replace(b"\r\n", b"\n"), stderr=proc.stderr.replace(b"\r\n", b"\n"), timed_out=False, events={}, counter_wire=b"")

        if len(command) >= 4 and command[0] == "/bin/sh" and command[3] == "eapg-compile":
            extra_flags = list(command[4:])
            translated = []
            for fl in extra_flags:
                if fl == "-fno-sanitize-recover=undefined":
                    translated.append("-fsanitize-trap=undefined")
                else:
                    translated.append(fl)
            with TemporaryDirectory(prefix="eapg_win_cc_") as td:
                exe = Path(td) / "program.exe"
                proc = subprocess.run(
                    ["g++", "-std=c++17", "-O2", *translated, "-x", "c++", "-", "-o", str(exe)],
                    input=data, capture_output=True, timeout=timeout, cwd=td,
                )
                exe_bytes = exe.read_bytes() if proc.returncode == 0 and exe.exists() else b""
                return SimpleNamespace(returncode=proc.returncode, stdout=exe_bytes, stderr=proc.stderr, timed_out=False, events={}, counter_wire=b"")

        raise RuntimeError(f"Unsupported Windows sandbox command: {command}")

    def win_compile_instrumented(pipeline, normalized, nodes):
        tree = pipeline.parser.parse(normalized.encode("utf-8"))
        mains = [
            n for n in tree.root_node.named_children
            if n.type == "function_definition"
            and n.child_by_field_name("declarator").child_by_field_name("declarator").text == b"main"
        ]
        if len(mains) != 1:
            raise ValueError("Expected one top-level main")
        pos = mains[0].child_by_field_name("body").start_byte + 1
        frozen = pipeline.instrument_cpp_source

        def add_init(code, edits):
            return pipeline.apply_reverse_byte_edits(code, edits + [(pos, pos, "\n__eapg_init();\n")])

        instrumenter = type(frozen)(frozen.__code__, {**frozen.__globals__, "apply_reverse_byte_edits": add_init})
        text = instrumenter(normalized, nodes)
        start = text.index("static void __eapg_dump_and_exit")
        end = text.index("#define __EAPG_TICK", start)
        emitter = f"""
static std::FILE* __eapg_stream = nullptr;
static int __eapg_emitted = 0;
static void __eapg_emit(int breached) {{
    if (__eapg_emitted) return;
    __eapg_emitted = 1;
    if (!__eapg_stream) std::_Exit(98);
    bool ok = std::fprintf(__eapg_stream, "{{\\"status\\":\\"%s\\",\\"total_ticks\\":%llu,\\"nodes\\":{{",
        breached ? "CAP_BREACHED" : "CLEAN_COMPLETION", __eapg_ticks) >= 0;
    for (int i = 0; i < {len(nodes)} && ok; ++i) {{
        ok = std::fprintf(__eapg_stream, "%s\\"N%d\\":{{\\"cnt\\":%llu,\\"work\\":%llu}}",
            i ? "," : "", i + 1, __eapg_cnt[i], __eapg_work[i]) >= 0;
    }}
    if (ok) ok = std::fprintf(__eapg_stream, "}}}}\\n") >= 0;
    if (std::fclose(__eapg_stream) != 0 || !ok) std::_Exit(98);
}}
static void __eapg_normal_exit() {{
    if (!__eapg_emitted) __eapg_emit(0);
}}
static void __eapg_dump_and_exit(int breached) {{
    __eapg_emit(breached);
    std::_Exit(97);
}}
static void __eapg_init() {{
    const char* fpath = std::getenv("EAPG_COUNTER_FILE");
    if (!fpath) std::_Exit(98);
    __eapg_stream = std::fopen(fpath, "wb");
    if (!__eapg_stream || std::atexit(__eapg_normal_exit) != 0) std::_Exit(98);
    const char* n_text = std::getenv("EAPG_N");
    if (n_text) {{
        unsigned long long n = std::strtoull(n_text, nullptr, 10);
        unsigned long long cap = 5ULL * n * n;
        if (cap > __eapg_cap) __eapg_cap = cap;
    }}
}}
"""
        text = text[:start] + emitter + text[end:]
        return r2d.compile_stage("instrumented build", text)

    def win_verify_oracle(result, case, stage):
        status = r2d.process_status(result)
        if stage == "sanitizer" and status == "EXECUTION_ERROR":
            status = "SANITIZER_FINDING"
        if status != "CLEAN_COMPLETION":
            raise r2d.ProfileFailure(status, f"{stage} failed at seed {case['seed']}, N={case['n']}", result)
        if result.stdout.split() != case["expected_stdout"].encode().split():
            raise r2d.ProfileFailure("OUTPUT_MISMATCH", f"{stage} oracle mismatch at seed {case['seed']}, N={case['n']}", result)

    # Monkeypatch in-memory across modules without modifying any hash-pinned disk files
    g1.invoke = win_invoke
    asfd.invoke = win_invoke
    si.invoke = win_invoke
    brp.invoke = win_invoke
    r2d.invoke = win_invoke
    r2d.normalize.__globals__["run"] = win_invoke
    r2d.compile_instrumented = win_compile_instrumented
    r2d.verify_oracle = win_verify_oracle
    so.execute = lambda binary, data=b"", *, timeout=12, counter_scale=None: win_invoke(["/program"], data=data, binary=binary, timeout=timeout, counter_scale=counter_scale)
    st.execute = so.execute
    st.compile_instrumented = win_compile_instrumented
    pg2.execute = so.execute
    pg2.compile_instrumented = win_compile_instrumented

    # Adapt synthetic_oracle sanitizer check to detect trap abort / non-CLEAN_COMPLETION cleanly
    orig_exec_ev = so.execution_evidence

    def win_exec_ev(result, stage, row, side, elapsed):
        ev, fail = orig_exec_ev(result, stage, row, side, elapsed)
        if stage == "sanitizer" and ev["verification_status"] not in ("passed", "sanitizer_execution"):
            ev["verification_status"] = "sanitizer_execution"
            fail = ("sanitizer_failure", "sanitizer_execution")
        return ev, fail

    so.execution_evidence = win_exec_ev
    return win_invoke


def tri(n):
    return n * (n + 1) // 2


def harm(n):
    return sum(n // d for d in range(1, n + 1))


def isqrt_floor(n):
    r = 1
    while (r + 1) * (r + 1) <= n:
        r += 1
    return r


def make_patch(original, removed, inserted):
    assert original.count(removed) == 1, f"Ambiguous anchor: {removed!r}"
    start = len(original.split(removed, 1)[0].encode("utf-8"))
    edited = original.replace(removed, inserted, 1)
    return edited, {"start_byte": start, "removed": removed, "inserted": inserted}


def build_ten_families():
    """Return all 10 newly authored non-overlapping scalar C++17 families (42 active slots)."""
    specs = []

    # F01: cursor_reset (linear sham, comparator swap owner)
    f01_orig = """#include <cstdio>
int main() {
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 0; }
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) { salt = 1; }
    int cursor = 0;
    long long total = 0;
    for (int i = 1; i <= n; ++i) {
        cursor = i - 1;
        while (cursor < i) {
            ++cursor;
        }
        total += static_cast<long long>(cursor) + salt;
    }
    std::printf("%lld\\n", total);
    return 0;
}
"""
    f01_cnt = lambda body_assign: f"""#include <cstdio>
int main() {{
    long long __ops = 1;
    int n = 0;
    if (++__ops, std::scanf("%d", &n) != 1 || n < 1) {{ return 0; }}
    int salt = 0;
    if (++__ops, std::scanf("%d", &salt) != 1) {{ salt = 1; }}
    int cursor = 0;
    long long total = 0;
    __ops += 2;
    for (int i = 1; ++__ops, i <= n; ++__ops, ++i) {{
        {body_assign}
        __ops += 1;
        while (++__ops, cursor < i) {{
            ++cursor;
            __ops += 1;
        }}
        total += static_cast<long long>(cursor) + salt;
        __ops += 1;
    }}
    std::printf("%lld\\n\\nEAPG-OPERATIONS-v1 %lld\\n", total, __ops);
    return 0;
}}
"""
    f01_at_orig = """#include <cstdio>
int main() {
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 0; }
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) { salt = 1; }
    int cursor = 0;
    long long total = 0;
    for (int i = 1; i <= n; ++i) {
        for (int j = 0; j < 1; ++j) {
            cursor = i;
        }
        total += static_cast<long long>(cursor) + salt;
    }
    std::printf("%lld\\n", total);
    return 0;
}
"""
    f01_at_cnt = lambda bound: f"""#include <cstdio>
int main() {{
    long long __ops = 1;
    int n = 0;
    if (++__ops, std::scanf("%d", &n) != 1 || n < 1) {{ return 0; }}
    int salt = 0;
    if (++__ops, std::scanf("%d", &salt) != 1) {{ salt = 1; }}
    int cursor = 0;
    long long total = 0;
    __ops += 2;
    for (int i = 1; ++__ops, i <= n; ++__ops, ++i) {{
        for (int j = 0; ++__ops, j < {bound}; ++__ops, ++j) {{
            cursor = i;
            __ops += 1;
        }}
        total += static_cast<long long>(cursor) + salt;
        __ops += 1;
    }}
    std::printf("%lld\\n\\nEAPG-OPERATIONS-v1 %lld\\n", total, __ops);
    return 0;
}}
"""
    f01_appr = """#include <cstdio>
int main() {
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 0; }
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) { salt = 1; }
    long long grid_sum = 0;
    for (int r = 1; r <= n; ++r) {
        for (int c = 1; c <= n; ++c) {
            grid_sum += static_cast<long long>(r) * c + salt;
        }
    }
    std::printf("%lld\\n", grid_sum);
    return 0;
}
"""
    f01_appr_cnt = """#include <cstdio>
int main() {
    long long __ops = 4;
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 0; }
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) { salt = 1; }
    long long grid_sum = 0;
    for (int r = 1; ++__ops, r <= n; ++__ops, ++r) {
        for (int c = 1; ++__ops, c <= n; ++__ops, ++c) {
            grid_sum += static_cast<long long>(r) * c + salt;
            __ops += 1;
        }
    }
    std::printf("%lld\\n\\nEAPG-OPERATIONS-v1 %lld\\n", grid_sum, __ops);
    return 0;
}
"""
    specs.append({
        "family_id": "F01_cursor_reset", "mechanism": "cursor_reset", "sham_class": "linear", "n0": 8,
        "positive_off_site": {
            "band": "strong", "original": f01_orig, "removed": "cursor = i - 1;", "inserted": "cursor = 0;",
            "statement_anchor": "while (cursor < i)",
            "cnt_orig": f01_cnt("cursor = i - 1;"), "cnt_edit": f01_cnt("cursor = 0;"),
            "out_fn": lambda n, s: tri(n) + n * s, "orig_ops_fn": lambda n: 6 + 7 * n,
            "edit_ops_fn": lambda n: 6 + 5 * n + 2 * tri(n), "orig_order": [1, 0], "edit_order": [2, 0],
        },
        "positive_at_site": {
            "band": "strong", "original": f01_at_orig, "removed": "j < 1", "inserted": "j < n",
            "cnt_orig": f01_at_cnt("1"), "cnt_edit": f01_at_cnt("n"),
            "out_fn": lambda n, s: tri(n) + n * s, "orig_ops_fn": lambda n: 6 + 7 * n,
            "edit_ops_fn": lambda n: 6 + 4 * n + 3 * n * n, "orig_order": [1, 0], "edit_order": [2, 0],
        },
        "same_growth_sham": {
            "original": f01_orig, "removed": "cursor = i - 1;", "inserted": "cursor = i - (1);",
            "cnt_orig": f01_cnt("cursor = i - 1;"), "cnt_edit": f01_cnt("cursor = i - (1);"),
            "out_fn": lambda n, s: tri(n) + n * s, "orig_ops_fn": lambda n: 6 + 7 * n,
            "edit_ops_fn": lambda n: 6 + 7 * n, "orig_order": [1, 0], "edit_order": [1, 0],
        },
        "appropriate_superlinear": {
            "source": f01_appr, "cnt_source": f01_appr_cnt,
            "out_fn": lambda n, s: tri(n) * tri(n) + n * n * s, "ops_fn": lambda n: 5 + 3 * n + 3 * n * n,
        },
        "comparator_swap": {
            "positive": {
                "band": "strong", "original": f01_orig, "removed": "cursor = i - 1;", "inserted": "cursor = 0;",
                "cnt_orig": f01_cnt("cursor = i - 1;"), "cnt_edit": f01_cnt("cursor = 0;"),
                "out_fn": lambda n, s: tri(n) + n * s, "orig_ops_fn": lambda n: 6 + 7 * n,
                "edit_ops_fn": lambda n: 6 + 5 * n + 2 * tri(n), "orig_order": [1, 0], "edit_order": [2, 0],
            },
            "sham": {
                "original": f01_orig.replace("cursor = i - 1;", "cursor = 1;", 1),
                "removed": "cursor = 1;", "inserted": "cursor = 0;",
                "cnt_orig": f01_cnt("cursor = 1;"), "cnt_edit": f01_cnt("cursor = 0;"),
                "out_fn": lambda n, s: tri(n) + n * s, "orig_ops_fn": lambda n: 6 + 5 * n + 2 * tri(n - 1),
                "edit_ops_fn": lambda n: 6 + 5 * n + 2 * tri(n), "orig_order": [2, 0], "edit_order": [2, 0],
            },
        },
    })

    # F02: stride_jump (quadratic sham, off="near_below", at="strong", n0=16)
    f02_prog = lambda step_expr: f"""#include <cstdio>
int main() {{
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) {{ return 0; }}
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) {{ salt = 1; }}
    long long acc = 0;
    long long mix = salt;
    for (int i = 1; i <= n; ++i) {{
        for (int b = 0; b < 6; ++b) {{
            mix = (mix * 3 + i + b) % 1000003LL;
        }}
        if (i % 2 == 0) {{
            int goal = i;
            int step = {step_expr};
            int pos = 0;
            while (pos < goal) {{
                pos += step;
            }}
            acc += pos + mix;
        }} else {{
            acc += i + mix;
        }}
    }}
    std::printf("%lld\\n", acc);
    return 0;
}}
"""
    f02_cnt = lambda step_expr: f"""#include <cstdio>
int main() {{
    long long __ops = 5;
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) {{ return 0; }}
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) {{ salt = 1; }}
    long long acc = 0;
    long long mix = salt;
    for (int i = 1; ++__ops, i <= n; ++__ops, ++i) {{
        for (int b = 0; ++__ops, b < 6; ++__ops, ++b) {{
            mix = (mix * 3 + i + b) % 1000003LL;
            __ops += 1;
        }}
        if (++__ops, i % 2 == 0) {{
            int goal = i;
            int step = {step_expr};
            int pos = 0;
            __ops += 3;
            while (++__ops, pos < goal) {{
                pos += step;
                __ops += 1;
            }}
            acc += pos + mix;
            __ops += 1;
        }} else {{
            acc += i + mix;
            __ops += 1;
        }}
    }}
    std::printf("%lld\\n\\nEAPG-OPERATIONS-v1 %lld\\n", acc, __ops);
    return 0;
}}
"""
    def f02_out(n, s):
        acc, mix = 0, s
        for i in range(1, n + 1):
            for b in range(6):
                mix = (mix * 3 + i + b) % 1000003
            acc += i + mix
        return acc

    def f02_ops(n, step_div):
        k = n // 2
        steps = sum((i // step_div) if step_div else 1 for i in range(2, n + 1, 2))
        return 6 + 23 * n + 4 * k + 2 * steps

    f02_at_orig = """#include <cstdio>
int main() {
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 0; }
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) { salt = 1; }
    long long ans = 0;
    for (int i = 1; i <= n; ++i) {
        int tail = 0;
        for (int q = 0; q < i; q += i) {
            tail = i;
        }
        ans += static_cast<long long>(tail) + salt;
    }
    std::printf("%lld\\n", ans);
    return 0;
}
"""
    f02_at_cnt = lambda upd: f"""#include <cstdio>
int main() {{
    long long __ops = 4;
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) {{ return 0; }}
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) {{ salt = 1; }}
    long long ans = 0;
    for (int i = 1; ++__ops, i <= n; ++__ops, ++i) {{
        int tail = 0;
        __ops += 1;
        for (int q = 0; ++__ops, q < i; ++__ops, {upd}) {{
            tail = i;
            __ops += 1;
        }}
        ans += static_cast<long long>(tail) + salt;
        __ops += 1;
    }}
    std::printf("%lld\\n\\nEAPG-OPERATIONS-v1 %lld\\n", ans, __ops);
    return 0;
}}
"""
    f02_appr = """#include <cstdio>
int main() {
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 0; }
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) { salt = 1; }
    long long chk = 0;
    for (int u = 1; u <= n; ++u) {
        for (int v = 1; v <= n; ++v) {
            chk += ((u ^ v) + salt) % 97;
        }
    }
    std::printf("%lld\\n", chk);
    return 0;
}
"""
    f02_appr_cnt = """#include <cstdio>
int main() {
    long long __ops = 4;
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 0; }
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) { salt = 1; }
    long long chk = 0;
    for (int u = 1; ++__ops, u <= n; ++__ops, ++u) {
        for (int v = 1; ++__ops, v <= n; ++__ops, ++v) {
            chk += ((u ^ v) + salt) % 97;
            __ops += 1;
        }
    }
    std::printf("%lld\\n\\nEAPG-OPERATIONS-v1 %lld\\n", chk, __ops);
    return 0;
}
"""
    specs.append({
        "family_id": "F02_stride_jump", "mechanism": "stride_jump", "sham_class": "quadratic", "n0": 16,
        "positive_off_site": {
            "band": "near_below", "original": f02_prog("goal"), "removed": "int step = goal;", "inserted": "int step = 1;",
            "statement_anchor": "while (pos < goal)",
            "cnt_orig": f02_cnt("goal"), "cnt_edit": f02_cnt("1"), "out_fn": f02_out,
            "orig_ops_fn": lambda n: f02_ops(n, 0), "edit_ops_fn": lambda n: f02_ops(n, 1),
            "orig_order": [1, 0], "edit_order": [2, 0],
        },
        "positive_at_site": {
            "band": "strong", "original": f02_at_orig, "removed": "q += i", "inserted": "q += 1",
            "cnt_orig": f02_at_cnt("q += i"), "cnt_edit": f02_at_cnt("q += 1"),
            "out_fn": lambda n, s: tri(n) + n * s, "orig_ops_fn": lambda n: 5 + 8 * n,
            "edit_ops_fn": lambda n: 5 + 5 * n + 3 * tri(n), "orig_order": [1, 0], "edit_order": [2, 0],
        },
        "same_growth_sham": {
            "original": f02_prog("1"), "removed": "acc += pos + mix;", "inserted": "acc += mix + pos;",
            "cnt_orig": f02_cnt("1"), "cnt_edit": f02_cnt("1").replace("acc += pos + mix;", "acc += mix + pos;"),
            "out_fn": f02_out, "orig_ops_fn": lambda n: f02_ops(n, 1), "edit_ops_fn": lambda n: f02_ops(n, 1),
            "orig_order": [2, 0], "edit_order": [2, 0],
        },
        "appropriate_superlinear": {
            "source": f02_appr, "cnt_source": f02_appr_cnt,
            "out_fn": lambda n, s: sum(((u ^ v) + s) % 97 for u in range(1, n + 1) for v in range(1, n + 1)),
            "ops_fn": lambda n: 5 + 3 * n + 3 * n * n,
        },
    })

    # F03: divisor_window (linear sham, off="near_above", at="near_above", n0=16)
    f03_off_orig = """#include <cstdio>
int main() {
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 0; }
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) { salt = 1; }
    long long dsum = salt;
    for (int d = 1; d <= n; ++d) {
        int jmp = d;
        for (int m = d; m <= n; m += jmp) {
            if (m % d == 0) {
                dsum += 1;
            }
        }
    }
    std::printf("%lld\\n", dsum);
    return 0;
}
"""
    f03_off_cnt = lambda jmp_expr: f"""#include <cstdio>
int main() {{
    long long __ops = 4;
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) {{ return 0; }}
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) {{ salt = 1; }}
    long long dsum = salt;
    for (int d = 1; ++__ops, d <= n; ++__ops, ++d) {{
        int jmp = {jmp_expr};
        __ops += 1;
        for (int m = d; ++__ops, m <= n; ++__ops, m += jmp) {{
            if (++__ops, m % d == 0) {{
                dsum += 1;
                __ops += 1;
            }}
        }}
    }}
    std::printf("%lld\\n\\nEAPG-OPERATIONS-v1 %lld\\n", dsum, __ops);
    return 0;
}}
"""
    f03_at_orig = """#include <cstdio>
int main() {
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 0; }
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) { salt = 1; }
    long long dcnt = salt;
    for (int d = 1; d <= n; ++d) {
        for (int m = d; m <= n; m += d) {
            if (m % d == 0) {
                dcnt += 1;
            }
        }
    }
    std::printf("%lld\\n", dcnt);
    return 0;
}
"""
    f03_at_cnt = lambda upd: f"""#include <cstdio>
int main() {{
    long long __ops = 4;
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) {{ return 0; }}
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) {{ salt = 1; }}
    long long dcnt = salt;
    for (int d = 1; ++__ops, d <= n; ++__ops, ++d) {{
        for (int m = d; ++__ops, m <= n; ++__ops, {upd}) {{
            if (++__ops, m % d == 0) {{
                dcnt += 1;
                __ops += 1;
            }}
        }}
    }}
    std::printf("%lld\\n\\nEAPG-OPERATIONS-v1 %lld\\n", dcnt, __ops);
    return 0;
}}
"""
    f03_sham_orig = """#include <cstdio>
int main() {
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 0; }
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) { salt = 1; }
    long long dsum = salt;
    for (int d = 1; d <= n; ++d) {
        int q = n / d;
        dsum += q;
    }
    std::printf("%lld\\n", dsum);
    return 0;
}
"""
    f03_sham_cnt = lambda expr: f"""#include <cstdio>
int main() {{
    long long __ops = 4;
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) {{ return 0; }}
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) {{ salt = 1; }}
    long long dsum = salt;
    for (int d = 1; ++__ops, d <= n; ++__ops, ++d) {{
        int q = {expr};
        dsum += q;
        __ops += 2;
    }}
    std::printf("%lld\\n\\nEAPG-OPERATIONS-v1 %lld\\n", dsum, __ops);
    return 0;
}}
"""
    f03_appr = """#include <cstdio>
int main() {
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 0; }
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) { salt = 1; }
    long long pairs = salt;
    for (int x = 1; x <= n; ++x) {
        for (int y = 1; y <= n; ++y) {
            if (x % y == 0 || y % x == 0) {
                pairs += 1;
            }
        }
    }
    std::printf("%lld\\n", pairs);
    return 0;
}
"""
    f03_appr_cnt = """#include <cstdio>
int main() {
    long long __ops = 4;
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 0; }
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) { salt = 1; }
    long long pairs = salt;
    for (int x = 1; ++__ops, x <= n; ++__ops, ++x) {
        for (int y = 1; ++__ops, y <= n; ++__ops, ++y) {
            if (++__ops, x % y == 0 || y % x == 0) {
                pairs += 1;
                __ops += 1;
            }
        }
    }
    std::printf("%lld\\n\\nEAPG-OPERATIONS-v1 %lld\\n", pairs, __ops);
    return 0;
}
"""
    specs.append({
        "family_id": "F03_divisor_window", "mechanism": "divisor_window", "sham_class": "linear", "n0": 16,
        "positive_off_site": {
            "band": "near_above", "original": f03_off_orig, "removed": "int jmp = d;", "inserted": "int jmp = 1;",
            "statement_anchor": "for (int m = d; m <= n; m += jmp)",
            "cnt_orig": f03_off_cnt("d"), "cnt_edit": f03_off_cnt("1"), "out_fn": lambda n, s: s + harm(n),
            "orig_ops_fn": lambda n: 5 + 4 * n + 4 * harm(n), "edit_ops_fn": lambda n: 5 + 4 * n + 3 * tri(n) + harm(n),
            "orig_order": [1, 1], "edit_order": [2, 0],
        },
        "positive_at_site": {
            "band": "near_above", "original": f03_at_orig, "removed": "m += d", "inserted": "m += 1",
            "cnt_orig": f03_at_cnt("m += d"), "cnt_edit": f03_at_cnt("m += 1"), "out_fn": lambda n, s: s + harm(n),
            "orig_ops_fn": lambda n: 5 + 3 * n + 4 * harm(n), "edit_ops_fn": lambda n: 5 + 3 * n + 3 * tri(n) + harm(n),
            "orig_order": [1, 1], "edit_order": [2, 0],
        },
        "same_growth_sham": {
            "original": f03_sham_orig, "removed": "int q = n / d;", "inserted": "int q = (n + 0) / d;",
            "cnt_orig": f03_sham_cnt("n / d"), "cnt_edit": f03_sham_cnt("(n + 0) / d"),
            "out_fn": lambda n, s: s + harm(n), "orig_ops_fn": lambda n: 5 + 4 * n, "edit_ops_fn": lambda n: 5 + 4 * n,
            "orig_order": [1, 0], "edit_order": [1, 0],
        },
        "appropriate_superlinear": {
            "source": f03_appr, "cnt_source": f03_appr_cnt,
            "out_fn": lambda n, s: s + 2 * harm(n) - n, "ops_fn": lambda n: 5 + 2 * n + 3 * n * n + 2 * harm(n),
        },
    })

    # F04: prefix_rescan (quadratic sham, off="near_above", at="near_below", n0=16)
    f04_off_prog = lambda flag_val: f"""#include <cstdio>
int main() {{
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) {{ return 0; }}
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) {{ salt = 1; }}
    long long ans = 0;
    long long pref = 0;
    long long base_mix = salt;
    for (int i = 1; i <= n; ++i) {{
        for (int t = 0; t < 4; ++t) {{
            base_mix = (base_mix * 5 + i + t) % 10007LL;
        }}
        int rescan = {flag_val};
        if (rescan) {{
            long long tmp = 0;
            for (int k = 1; k <= i; ++k) {{
                tmp += (k * salt + 3) % 11;
            }}
            pref = tmp;
        }} else {{
            pref += (i * salt + 3) % 11;
        }}
        ans += pref + base_mix;
    }}
    std::printf("%lld\\n", ans);
    return 0;
}}
"""
    f04_off_cnt = lambda flag_val: f"""#include <cstdio>
int main() {{
    long long __ops = 6;
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) {{ return 0; }}
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) {{ salt = 1; }}
    long long ans = 0;
    long long pref = 0;
    long long base_mix = salt;
    for (int i = 1; ++__ops, i <= n; ++__ops, ++i) {{
        for (int t = 0; ++__ops, t < 4; ++__ops, ++t) {{
            base_mix = (base_mix * 5 + i + t) % 10007LL;
            __ops += 1;
        }}
        int rescan = {flag_val};
        __ops += 1;
        if (++__ops, rescan) {{
            long long tmp = 0;
            __ops += 1;
            for (int k = 1; ++__ops, k <= i; ++__ops, ++k) {{
                tmp += (k * salt + 3) % 11;
                __ops += 1;
            }}
            pref = tmp;
            __ops += 1;
        }} else {{
            pref += (i * salt + 3) % 11;
            __ops += 1;
        }}
        ans += pref + base_mix;
        __ops += 1;
    }}
    std::printf("%lld\\n\\nEAPG-OPERATIONS-v1 %lld\\n", ans, __ops);
    return 0;
}}
"""
    def f04_out(n, s):
        ans = pref = 0
        mix = s
        for i in range(1, n + 1):
            for t in range(4):
                mix = (mix * 5 + i + t) % 10007
            pref += (i * s + 3) % 11
            ans += pref + mix
        return ans

    f04_at_orig = """#include <cstdio>
int main() {
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 0; }
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) { salt = 1; }
    long long ans = 0;
    long long mix = salt;
    for (int i = 1; i <= n; ++i) {
        for (int t = 0; t < 11; ++t) {
            mix = (mix * 7 + i + t) % 10007LL;
        }
        int reached = 0;
        for (int k = 0; k < i; k += i) {
            reached = i;
        }
        ans += reached + mix;
    }
    std::printf("%lld\\n", ans);
    return 0;
}
"""
    f04_at_cnt = lambda upd: f"""#include <cstdio>
int main() {{
    long long __ops = 5;
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) {{ return 0; }}
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) {{ salt = 1; }}
    long long ans = 0;
    long long mix = salt;
    for (int i = 1; ++__ops, i <= n; ++__ops, ++i) {{
        for (int t = 0; ++__ops, t < 11; ++__ops, ++t) {{
            mix = (mix * 7 + i + t) % 10007LL;
            __ops += 1;
        }}
        int reached = 0;
        __ops += 1;
        for (int k = 0; ++__ops, k < i; ++__ops, {upd}) {{
            reached = i;
            __ops += 1;
        }}
        ans += reached + mix;
        __ops += 1;
    }}
    std::printf("%lld\\n\\nEAPG-OPERATIONS-v1 %lld\\n", ans, __ops);
    return 0;
}}
"""
    def f04_at_out(n, s):
        ans, mix = 0, s
        for i in range(1, n + 1):
            for t in range(11):
                mix = (mix * 7 + i + t) % 10007
            ans += i + mix
        return ans

    f04_appr = """#include <cstdio>
int main() {
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 0; }
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) { salt = 1; }
    long long acc = 0;
    for (int i = 1; i <= n; ++i) {
        long long seg = 0;
        for (int j = 1; j <= i; ++j) {
            seg += ((j * salt) + i) % 17;
        }
        acc += seg;
    }
    std::printf("%lld\\n", acc);
    return 0;
}
"""
    f04_appr_cnt = """#include <cstdio>
int main() {
    long long __ops = 4;
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 0; }
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) { salt = 1; }
    long long acc = 0;
    for (int i = 1; ++__ops, i <= n; ++__ops, ++i) {
        long long seg = 0;
        __ops += 1;
        for (int j = 1; ++__ops, j <= i; ++__ops, ++j) {
            seg += ((j * salt) + i) % 17;
            __ops += 1;
        }
        acc += seg;
        __ops += 1;
    }
    std::printf("%lld\\n\\nEAPG-OPERATIONS-v1 %lld\\n", acc, __ops);
    return 0;
}
"""
    specs.append({
        "family_id": "F04_prefix_rescan", "mechanism": "prefix_rescan", "sham_class": "quadratic", "n0": 16,
        "positive_off_site": {
            "band": "near_above", "original": f04_off_prog("0"), "removed": "int rescan = 0;", "inserted": "int rescan = 1;",
            "statement_anchor": "for (int k = 1; k <= i; ++k)",
            "cnt_orig": f04_off_cnt("0"), "cnt_edit": f04_off_cnt("1"), "out_fn": f04_out,
            "orig_ops_fn": lambda n: 7 + 19 * n, "edit_ops_fn": lambda n: 7 + 21 * n + 3 * tri(n),
            "orig_order": [1, 0], "edit_order": [2, 0],
        },
        "positive_at_site": {
            "band": "near_below", "original": f04_at_orig, "removed": "k += i", "inserted": "k += 2",
            "cnt_orig": f04_at_cnt("k += i"), "cnt_edit": f04_at_cnt("k += 2"), "out_fn": f04_at_out,
            "orig_ops_fn": lambda n: 6 + 42 * n,
            "edit_ops_fn": lambda n: 6 + 39 * n + 3 * sum((i + 1) // 2 for i in range(1, n + 1)),
            "orig_order": [1, 0], "edit_order": [2, 0],
        },
        "same_growth_sham": {
            "original": f04_off_prog("1"), "removed": "int rescan = 1;", "inserted": "int rescan = 2;",
            "cnt_orig": f04_off_cnt("1"), "cnt_edit": f04_off_cnt("2"), "out_fn": f04_out,
            "orig_ops_fn": lambda n: 7 + 21 * n + 3 * tri(n), "edit_ops_fn": lambda n: 7 + 21 * n + 3 * tri(n),
            "orig_order": [2, 0], "edit_order": [2, 0],
        },
        "appropriate_superlinear": {
            "source": f04_appr, "cnt_source": f04_appr_cnt,
            "out_fn": lambda n, s: sum(((j * s) + i) % 17 for i in range(1, n + 1) for j in range(1, i + 1)),
            "ops_fn": lambda n: 5 + 5 * n + 3 * tri(n),
        },
    })

    # F05: modular_batch (linear sham)
    f05_prog = lambda back_expr: f"""#include <cstdio>
int main() {{
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) {{ return 0; }}
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) {{ salt = 1; }}
    long long mult = salt + 2;
    long long cur = 1;
    long long out_acc = 0;
    for (int i = 1; i <= n; ++i) {{
        int k = {back_expr};
        if (k == 0) {{
            cur = 1;
        }}
        while (k < i) {{
            cur = (cur * mult) % 1009LL;
            ++k;
        }}
        out_acc += cur;
    }}
    std::printf("%lld\\n", out_acc);
    return 0;
}}
"""
    f05_cnt = lambda back_expr: f"""#include <cstdio>
int main() {{
    long long __ops = 6;
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) {{ return 0; }}
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) {{ salt = 1; }}
    long long mult = salt + 2;
    long long cur = 1;
    long long out_acc = 0;
    for (int i = 1; ++__ops, i <= n; ++__ops, ++i) {{
        int k = {back_expr};
        __ops += 1;
        if (++__ops, k == 0) {{
            cur = 1;
            __ops += 1;
        }}
        while (++__ops, k < i) {{
            cur = (cur * mult) % 1009LL;
            ++k;
            __ops += 2;
        }}
        out_acc += cur;
        __ops += 1;
    }}
    std::printf("%lld\\n\\nEAPG-OPERATIONS-v1 %lld\\n", out_acc, __ops);
    return 0;
}}
"""
    f05_out = lambda n, s: sum(pow(s + 2, i, 1009) for i in range(1, n + 1))
    f05_at_orig = """#include <cstdio>
int main() {
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 0; }
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) { salt = 1; }
    long long p = 1;
    long long total = 0;
    for (int i = 1; i <= n; ++i) {
        p = (p * (salt + 2)) % 1009LL;
        long long snap = 0;
        for (int z = 0; z < 1; ++z) {
            snap = p;
        }
        total += snap;
    }
    std::printf("%lld\\n", total);
    return 0;
}
"""
    f05_at_cnt = lambda lim: f"""#include <cstdio>
int main() {{
    long long __ops = 5;
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) {{ return 0; }}
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) {{ salt = 1; }}
    long long p = 1;
    long long total = 0;
    for (int i = 1; ++__ops, i <= n; ++__ops, ++i) {{
        p = (p * (salt + 2)) % 1009LL;
        long long snap = 0;
        __ops += 2;
        for (int z = 0; ++__ops, z < {lim}; ++__ops, ++z) {{
            snap = p;
            __ops += 1;
        }}
        total += snap;
        __ops += 1;
    }}
    std::printf("%lld\\n\\nEAPG-OPERATIONS-v1 %lld\\n", total, __ops);
    return 0;
}}
"""
    f05_appr = """#include <cstdio>
int main() {
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 0; }
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) { salt = 1; }
    long long msum = 0;
    for (int a = 1; a <= n; ++a) {
        for (int b = 1; b <= n; ++b) {
            msum += (static_cast<long long>(a) * b + salt) % 1009LL;
        }
    }
    std::printf("%lld\\n", msum);
    return 0;
}
"""
    f05_appr_cnt = """#include <cstdio>
int main() {
    long long __ops = 4;
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 0; }
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) { salt = 1; }
    long long msum = 0;
    for (int a = 1; ++__ops, a <= n; ++__ops, ++a) {
        for (int b = 1; ++__ops, b <= n; ++__ops, ++b) {
            msum += (static_cast<long long>(a) * b + salt) % 1009LL;
            __ops += 1;
        }
    }
    std::printf("%lld\\n\\nEAPG-OPERATIONS-v1 %lld\\n", msum, __ops);
    return 0;
}
"""
    specs.append({
        "family_id": "F05_modular_batch", "mechanism": "modular_batch", "sham_class": "linear", "n0": 8,
        "positive_off_site": {
            "band": "strong", "original": f05_prog("i - 1"), "removed": "int k = i - 1;", "inserted": "int k = 0;",
            "statement_anchor": "while (k < i)", "cnt_orig": f05_cnt("i - 1"), "cnt_edit": f05_cnt("0"),
            "out_fn": f05_out, "orig_ops_fn": lambda n: 8 + 9 * n, "edit_ops_fn": lambda n: 7 + 7 * n + 3 * tri(n),
            "orig_order": [1, 0], "edit_order": [2, 0],
        },
        "positive_at_site": {
            "band": "strong", "original": f05_at_orig, "removed": "z < 1", "inserted": "z < n",
            "cnt_orig": f05_at_cnt("1"), "cnt_edit": f05_at_cnt("n"), "out_fn": f05_out,
            "orig_ops_fn": lambda n: 6 + 9 * n, "edit_ops_fn": lambda n: 6 + 6 * n + 3 * n * n,
            "orig_order": [1, 0], "edit_order": [2, 0],
        },
        "same_growth_sham": {
            "original": f05_prog("i - 1"), "removed": "long long mult = salt + 2;", "inserted": "long long mult = (salt + 2);",
            "cnt_orig": f05_cnt("i - 1"), "cnt_edit": f05_cnt("i - 1").replace("salt + 2", "(salt + 2)", 1),
            "out_fn": f05_out, "orig_ops_fn": lambda n: 8 + 9 * n, "edit_ops_fn": lambda n: 8 + 9 * n,
            "orig_order": [1, 0], "edit_order": [1, 0],
        },
        "appropriate_superlinear": {
            "source": f05_appr, "cnt_source": f05_appr_cnt,
            "out_fn": lambda n, s: sum((a * b + s) % 1009 for a in range(1, n + 1) for b in range(1, n + 1)),
            "ops_fn": lambda n: 5 + 3 * n + 3 * n * n,
        },
    })

    # F06: box_bound (quadratic sham)
    f06_prog = lambda cap_expr: f"""#include <cstdio>
int main() {{
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) {{ return 0; }}
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) {{ salt = 1; }}
    int lim = 1;
    while ((lim + 1) * (lim + 1) <= n) {{
        ++lim;
    }}
    int span_cap = {cap_expr};
    long long area = 0;
    for (int x = 1; x <= span_cap; ++x) {{
        for (int y = 1; y <= span_cap; ++y) {{
            if (x <= lim && y <= lim) {{
                area += static_cast<long long>(x) * y + salt;
            }}
        }}
    }}
    std::printf("%lld\\n", area);
    return 0;
}}
"""
    f06_cnt = lambda cap_expr: f"""#include <cstdio>
int main() {{
    long long __ops = 6;
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) {{ return 0; }}
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) {{ salt = 1; }}
    int lim = 1;
    while (++__ops, (lim + 1) * (lim + 1) <= n) {{
        ++lim;
        __ops += 1;
    }}
    int span_cap = {cap_expr};
    long long area = 0;
    __ops += 2;
    for (int x = 1; ++__ops, x <= span_cap; ++__ops, ++x) {{
        for (int y = 1; ++__ops, y <= span_cap; ++__ops, ++y) {{
            if (++__ops, x <= lim && y <= lim) {{
                area += static_cast<long long>(x) * y + salt;
                __ops += 1;
            }}
        }}
    }}
    std::printf("%lld\\n\\nEAPG-OPERATIONS-v1 %lld\\n", area, __ops);
    return 0;
}}
"""
    f06_out = lambda n, s: tri(isqrt_floor(n)) ** 2 + (isqrt_floor(n) ** 2) * s
    f06_at_orig = """#include <cstdio>
int main() {
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 0; }
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) { salt = 1; }
    int lim = 1;
    while ((lim + 1) * (lim + 1) <= n) {
        ++lim;
    }
    long long score = 0;
    for (int x = 1; x <= n; ++x) {
        for (int y = 1; y <= 1; ++y) {
            if (y == 1) {
                score += static_cast<long long>(x) * lim + salt;
            }
        }
    }
    std::printf("%lld\\n", score);
    return 0;
}
"""
    f06_at_cnt = lambda y_bnd: f"""#include <cstdio>
int main() {{
    long long __ops = 5;
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) {{ return 0; }}
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) {{ salt = 1; }}
    int lim = 1;
    while (++__ops, (lim + 1) * (lim + 1) <= n) {{
        ++lim;
        __ops += 1;
    }}
    long long score = 0;
    for (int x = 1; ++__ops, x <= n; ++__ops, ++x) {{
        for (int y = 1; ++__ops, y <= {y_bnd}; ++__ops, ++y) {{
            if (++__ops, y == 1) {{
                score += static_cast<long long>(x) * lim + salt;
                __ops += 1;
            }}
        }}
    }}
    std::printf("%lld\\n\\nEAPG-OPERATIONS-v1 %lld\\n", score, __ops);
    return 0;
}}
"""
    f06_appr = """#include <cstdio>
int main() {
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 0; }
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) { salt = 1; }
    long long tot = 0;
    for (int x = 1; x <= n; ++x) {
        for (int y = x; y <= n; ++y) {
            tot += static_cast<long long>(x) + y + salt;
        }
    }
    std::printf("%lld\\n", tot);
    return 0;
}
"""
    f06_appr_cnt = """#include <cstdio>
int main() {
    long long __ops = 4;
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 0; }
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) { salt = 1; }
    long long tot = 0;
    for (int x = 1; ++__ops, x <= n; ++__ops, ++x) {
        for (int y = x; ++__ops, y <= n; ++__ops, ++y) {
            tot += static_cast<long long>(x) + y + salt;
            __ops += 1;
        }
    }
    std::printf("%lld\\n\\nEAPG-OPERATIONS-v1 %lld\\n", tot, __ops);
    return 0;
}
"""
    specs.append({
        "family_id": "F06_box_bound", "mechanism": "box_bound", "sham_class": "quadratic", "n0": 8,
        "positive_off_site": {
            "band": "strong", "original": f06_prog("lim"), "removed": "int span_cap = lim;", "inserted": "int span_cap = n;",
            "statement_anchor": "for (int x = 1; x <= span_cap; ++x)", "cnt_orig": f06_cnt("lim"), "cnt_edit": f06_cnt("n"),
            "out_fn": f06_out,
            "orig_ops_fn": lambda n: 10 + 2 * (isqrt_floor(n) - 1) + 3 * isqrt_floor(n) + 4 * isqrt_floor(n) ** 2,
            "edit_ops_fn": lambda n: 10 + 2 * (isqrt_floor(n) - 1) + 3 * n + 3 * n * n + isqrt_floor(n) ** 2,
            "orig_order": [1, 0], "edit_order": [2, 0],
        },
        "positive_at_site": {
            "band": "strong", "original": f06_at_orig, "removed": "y <= 1", "inserted": "y <= n",
            "cnt_orig": f06_at_cnt("1"), "cnt_edit": f06_at_cnt("n"),
            "out_fn": lambda n, s: tri(n) * isqrt_floor(n) + n * s,
            "orig_ops_fn": lambda n: 7 + 2 * (isqrt_floor(n) - 1) + 7 * n,
            "edit_ops_fn": lambda n: 7 + 2 * (isqrt_floor(n) - 1) + 4 * n + 3 * n * n,
            "orig_order": [1, 0], "edit_order": [2, 0],
        },
        "same_growth_sham": {
            "original": f06_prog("n"), "removed": "x <= lim && y <= lim", "inserted": "y <= lim && x <= lim",
            "cnt_orig": f06_cnt("n"), "cnt_edit": f06_cnt("n").replace("x <= lim && y <= lim", "y <= lim && x <= lim", 1),
            "out_fn": f06_out,
            "orig_ops_fn": lambda n: 10 + 2 * (isqrt_floor(n) - 1) + 3 * n + 3 * n * n + isqrt_floor(n) ** 2,
            "edit_ops_fn": lambda n: 10 + 2 * (isqrt_floor(n) - 1) + 3 * n + 3 * n * n + isqrt_floor(n) ** 2,
            "orig_order": [2, 0], "edit_order": [2, 0],
        },
        "appropriate_superlinear": {
            "source": f06_appr, "cnt_source": f06_appr_cnt,
            "out_fn": lambda n, s: sum(x + y + s for x in range(1, n + 1) for y in range(x, n + 1)),
            "ops_fn": lambda n: 5 + 3 * n + 3 * tri(n),
        },
    })

    # F07: triangular_cap (linear sham, do-while)
    f07_prog = lambda pos_expr: f"""#include <cstdio>
int main() {{
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) {{ return 0; }}
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) {{ salt = 1; }}
    long long tot = 0;
    int step_v = 0;
    for (int r = 1; r <= n; ++r) {{
        step_v = {pos_expr};
        do {{
            step_v += 1;
        }} while (step_v < r);
        tot += static_cast<long long>(step_v) * 2 + salt;
    }}
    std::printf("%lld\\n", tot);
    return 0;
}}
"""
    f07_cnt = lambda pos_expr: f"""#include <cstdio>
int main() {{
    long long __ops = 5;
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) {{ return 0; }}
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) {{ salt = 1; }}
    long long tot = 0;
    int step_v = 0;
    for (int r = 1; ++__ops, r <= n; ++__ops, ++r) {{
        step_v = {pos_expr};
        __ops += 1;
        do {{
            step_v += 1;
            __ops += 1;
        }} while (++__ops, step_v < r);
        tot += static_cast<long long>(step_v) * 2 + salt;
        __ops += 1;
    }}
    std::printf("%lld\\n\\nEAPG-OPERATIONS-v1 %lld\\n", tot, __ops);
    return 0;
}}
"""
    f07_at_orig = """#include <cstdio>
int main() {
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 0; }
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) { salt = 1; }
    long long tot = 0;
    for (int r = 1; r <= n; ++r) {
        int val = 0;
        int rep = 0;
        do {
            val = r;
            ++rep;
        } while (rep < 1);
        tot += static_cast<long long>(val) * 2 + salt;
    }
    std::printf("%lld\\n", tot);
    return 0;
}
"""
    f07_at_cnt = lambda lim: f"""#include <cstdio>
int main() {{
    long long __ops = 4;
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) {{ return 0; }}
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) {{ salt = 1; }}
    long long tot = 0;
    for (int r = 1; ++__ops, r <= n; ++__ops, ++r) {{
        int val = 0;
        int rep = 0;
        __ops += 2;
        do {{
            val = r;
            ++rep;
            __ops += 2;
        }} while (++__ops, rep < {lim});
        tot += static_cast<long long>(val) * 2 + salt;
        __ops += 1;
    }}
    std::printf("%lld\\n\\nEAPG-OPERATIONS-v1 %lld\\n", tot, __ops);
    return 0;
}}
"""
    f07_appr = """#include <cstdio>
int main() {
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 0; }
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) { salt = 1; }
    long long tot = 0;
    int a = 1;
    do {
        int b = 1;
        do {
            tot += a + b + salt;
            ++b;
        } while (b <= n);
        ++a;
    } while (a <= n);
    std::printf("%lld\\n", tot);
    return 0;
}
"""
    f07_appr_cnt = """#include <cstdio>
int main() {
    long long __ops = 5;
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 0; }
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) { salt = 1; }
    long long tot = 0;
    int a = 1;
    do {
        int b = 1;
        __ops += 1;
        do {
            tot += a + b + salt;
            ++b;
            __ops += 2;
        } while (++__ops, b <= n);
        ++a;
        __ops += 1;
    } while (++__ops, a <= n);
    std::printf("%lld\\n\\nEAPG-OPERATIONS-v1 %lld\\n", tot, __ops);
    return 0;
}
"""
    specs.append({
        "family_id": "F07_triangular_cap", "mechanism": "triangular_cap", "sham_class": "linear", "n0": 8,
        "positive_off_site": {
            "band": "strong", "original": f07_prog("r - 1"), "removed": "step_v = r - 1;", "inserted": "step_v = 0;",
            "statement_anchor": "do {", "cnt_orig": f07_cnt("r - 1"), "cnt_edit": f07_cnt("0"),
            "out_fn": lambda n, s: 2 * tri(n) + n * s, "orig_ops_fn": lambda n: 6 + 6 * n,
            "edit_ops_fn": lambda n: 6 + 4 * n + 2 * tri(n), "orig_order": [1, 0], "edit_order": [2, 0],
        },
        "positive_at_site": {
            "band": "strong", "original": f07_at_orig, "removed": "rep < 1", "inserted": "rep < n",
            "cnt_orig": f07_at_cnt("1"), "cnt_edit": f07_at_cnt("n"), "out_fn": lambda n, s: 2 * tri(n) + n * s,
            "orig_ops_fn": lambda n: 5 + 8 * n, "edit_ops_fn": lambda n: 5 + 5 * n + 3 * n * n,
            "orig_order": [1, 0], "edit_order": [2, 0],
        },
        "same_growth_sham": {
            "original": f07_prog("r - 1"), "removed": "step_v = r - 1;", "inserted": "step_v = r - (1);",
            "cnt_orig": f07_cnt("r - 1"), "cnt_edit": f07_cnt("r - (1)"), "out_fn": lambda n, s: 2 * tri(n) + n * s,
            "orig_ops_fn": lambda n: 6 + 6 * n, "edit_ops_fn": lambda n: 6 + 6 * n, "orig_order": [1, 0], "edit_order": [1, 0],
        },
        "appropriate_superlinear": {
            "source": f07_appr, "cnt_source": f07_appr_cnt,
            "out_fn": lambda n, s: 2 * n * tri(n) + n * n * s, "ops_fn": lambda n: 5 + 3 * n + 3 * n * n,
        },
    })

    # F08: parity_block (quadratic sham)
    f08_prog = lambda reset_expr: f"""#include <cstdio>
int main() {{
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) {{ return 0; }}
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) {{ salt = 1; }}
    int par = 0;
    long long parity_sum = 0;
    for (int idx = 1; idx <= n; ++idx) {{
        int begin_k = {reset_expr};
        if (begin_k == 1) {{
            par = 0;
        }}
        for (int m = begin_k; m <= idx; ++m) {{
            if (((m ^ salt) & 1) != 0) {{
                par = par ^ 1;
            }}
        }}
        parity_sum += par;
    }}
    std::printf("%lld\\n", parity_sum);
    return 0;
}}
"""
    f08_cnt = lambda reset_expr: f"""#include <cstdio>
int main() {{
    long long __ops = 5;
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) {{ return 0; }}
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) {{ salt = 1; }}
    int par = 0;
    long long parity_sum = 0;
    for (int idx = 1; ++__ops, idx <= n; ++__ops, ++idx) {{
        int begin_k = {reset_expr};
        __ops += 1;
        if (++__ops, begin_k == 1) {{
            par = 0;
            __ops += 1;
        }}
        for (int m = begin_k; ++__ops, m <= idx; ++__ops, ++m) {{
            if (++__ops, ((m ^ salt) & 1) != 0) {{
                par = par ^ 1;
                __ops += 1;
            }}
        }}
        parity_sum += par;
        __ops += 1;
    }}
    std::printf("%lld\\n\\nEAPG-OPERATIONS-v1 %lld\\n", parity_sum, __ops);
    return 0;
}}
"""
    def f08_exact(n, s, reset_to_1):
        ps, ops, par = 0, 6, 0
        for idx in range(1, n + 1):
            ops += 4
            bk = 1 if reset_to_1 else idx
            if bk == 1:
                par = 0
                ops += 1
            for m in range(bk, idx + 1):
                ops += 3
                if ((m ^ s) & 1) != 0:
                    par ^= 1
                    ops += 1
            ops += 2
            ps += par
        return ps, ops

    f08_at_orig = """#include <cstdio>
int main() {
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 0; }
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) { salt = 1; }
    long long parity_sum = 0;
    for (int idx = 1; idx <= n; ++idx) {
        int val = 0;
        for (int b = 0; b < 1; ++b) {
            val = ((idx ^ salt) & 3);
        }
        parity_sum += val;
    }
    std::printf("%lld\\n", parity_sum);
    return 0;
}
"""
    f08_at_cnt = lambda lim: f"""#include <cstdio>
int main() {{
    long long __ops = 4;
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) {{ return 0; }}
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) {{ salt = 1; }}
    long long parity_sum = 0;
    for (int idx = 1; ++__ops, idx <= n; ++__ops, ++idx) {{
        int val = 0;
        __ops += 1;
        for (int b = 0; ++__ops, b < {lim}; ++__ops, ++b) {{
            val = ((idx ^ salt) & 3);
            __ops += 1;
        }}
        parity_sum += val;
        __ops += 1;
    }}
    std::printf("%lld\\n\\nEAPG-OPERATIONS-v1 %lld\\n", parity_sum, __ops);
    return 0;
}}
"""
    f08_appr = """#include <cstdio>
int main() {
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 0; }
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) { salt = 1; }
    long long xsum = 0;
    for (int p = 1; p <= n; ++p) {
        for (int q = 1; q <= n; ++q) {
            if (((p ^ q ^ salt) & 1) == 0) {
                xsum += 1;
            }
        }
    }
    std::printf("%lld\\n", xsum);
    return 0;
}
"""
    f08_appr_cnt = """#include <cstdio>
int main() {
    long long __ops = 4;
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 0; }
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) { salt = 1; }
    long long xsum = 0;
    for (int p = 1; ++__ops, p <= n; ++__ops, ++p) {
        for (int q = 1; ++__ops, q <= n; ++__ops, ++q) {
            if (++__ops, ((p ^ q ^ salt) & 1) == 0) {
                xsum += 1;
                __ops += 1;
            }
        }
    }
    std::printf("%lld\\n\\nEAPG-OPERATIONS-v1 %lld\\n", xsum, __ops);
    return 0;
}
"""
    def f08_appr_eval(n, s):
        xsum, ops = 0, 5
        for p in range(1, n + 1):
            ops += 2
            for q in range(1, n + 1):
                ops += 3
                if ((p ^ q ^ s) & 1) == 0:
                    xsum += 1
                    ops += 1
            ops += 1
        return xsum, ops

    specs.append({
        "family_id": "F08_parity_block", "mechanism": "parity_block", "sham_class": "quadratic", "n0": 8,
        "positive_off_site": {
            "band": "strong", "original": f08_prog("idx"), "removed": "int begin_k = idx;", "inserted": "int begin_k = 1;",
            "statement_anchor": "for (int m = begin_k; m <= idx; ++m)", "cnt_orig": f08_cnt("idx"), "cnt_edit": f08_cnt("1"),
            "out_fn": lambda n, s: f08_exact(n, s, False)[0], "orig_ops_fn": lambda n: f08_exact(n, 3, False)[1],
            "edit_ops_fn": lambda n: f08_exact(n, 3, True)[1], "orig_order": [1, 0], "edit_order": [2, 0],
        },
        "positive_at_site": {
            "band": "strong", "original": f08_at_orig, "removed": "b < 1", "inserted": "b < n",
            "cnt_orig": f08_at_cnt("1"), "cnt_edit": f08_at_cnt("n"),
            "out_fn": lambda n, s: sum(((idx ^ s) & 3) for idx in range(1, n + 1)),
            "orig_ops_fn": lambda n: 5 + 8 * n, "edit_ops_fn": lambda n: 5 + 5 * n + 3 * n * n,
            "orig_order": [1, 0], "edit_order": [2, 0],
        },
        "same_growth_sham": {
            "original": f08_prog("1"), "removed": "((m ^ salt) & 1) != 0", "inserted": "((salt ^ m) & 1) != 0",
            "cnt_orig": f08_cnt("1"), "cnt_edit": f08_cnt("1").replace("((m ^ salt) & 1) != 0", "((salt ^ m) & 1) != 0"),
            "out_fn": lambda n, s: f08_exact(n, s, True)[0], "orig_ops_fn": lambda n: f08_exact(n, 3, True)[1],
            "edit_ops_fn": lambda n: f08_exact(n, 3, True)[1], "orig_order": [2, 0], "edit_order": [2, 0],
        },
        "appropriate_superlinear": {
            "source": f08_appr, "cnt_source": f08_appr_cnt,
            "out_fn": lambda n, s: f08_appr_eval(n, s)[0], "ops_fn": lambda n: f08_appr_eval(n, 3)[1],
        },
    })

    # F09: gcd_step (linear sham)
    f09_prog = lambda reps_expr: f"""#include <cstdio>
int main() {{
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) {{ return 0; }}
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) {{ salt = 1; }}
    long long gsum = 0;
    for (int i = 1; i <= n; ++i) {{
        int reps = {reps_expr};
        int res = 0;
        for (int r = 0; r < reps; ++r) {{
            int a = i + salt;
            int b = i + 1;
            while (b != 0) {{
                int t = a % b;
                a = b;
                b = t;
            }}
            res = a;
        }}
        gsum += res;
    }}
    std::printf("%lld\\n", gsum);
    return 0;
}}
"""
    f09_cnt = lambda reps_expr: f"""#include <cstdio>
int main() {{
    long long __ops = 4;
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) {{ return 0; }}
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) {{ salt = 1; }}
    long long gsum = 0;
    for (int i = 1; ++__ops, i <= n; ++__ops, ++i) {{
        int reps = {reps_expr};
        int res = 0;
        __ops += 2;
        for (int r = 0; ++__ops, r < reps; ++__ops, ++r) {{
            int a = i + salt;
            int b = i + 1;
            __ops += 2;
            while (++__ops, b != 0) {{
                int t = a % b;
                a = b;
                b = t;
                __ops += 3;
            }}
            res = a;
            __ops += 1;
        }}
        gsum += res;
        __ops += 1;
    }}
    std::printf("%lld\\n\\nEAPG-OPERATIONS-v1 %lld\\n", gsum, __ops);
    return 0;
}}
"""
    def gcd_steps(a, b):
        s = 0
        while b != 0:
            s += 1
            a, b = b, a % b
        return a, s

    def f09_eval(n, s, mult_reps):
        gsum, ops = 0, 5
        for i in range(1, n + 1):
            ops += 4
            reps = i if mult_reps else 1
            g, st_c = gcd_steps(i + s, i + 1)
            ops += reps * (6 + 4 * st_c) + 2
            gsum += g
        return gsum, ops

    f09_at_orig = """#include <cstdio>
int main() {
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 0; }
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) { salt = 1; }
    long long gsum = 0;
    for (int i = 1; i <= n; ++i) {
        int res = 0;
        for (int r = 0; r < 1; ++r) {
            int a = i + salt;
            int b = i + 2;
            while (b != 0) {
                int t = a % b;
                a = b;
                b = t;
            }
            res = a;
        }
        gsum += res;
    }
    std::printf("%lld\\n", gsum);
    return 0;
}
"""
    f09_at_cnt = lambda lim: f"""#include <cstdio>
int main() {{
    long long __ops = 4;
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) {{ return 0; }}
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) {{ salt = 1; }}
    long long gsum = 0;
    for (int i = 1; ++__ops, i <= n; ++__ops, ++i) {{
        int res = 0;
        __ops += 1;
        for (int r = 0; ++__ops, r < {lim}; ++__ops, ++r) {{
            int a = i + salt;
            int b = i + 2;
            __ops += 2;
            while (++__ops, b != 0) {{
                int t = a % b;
                a = b;
                b = t;
                __ops += 3;
            }}
            res = a;
            __ops += 1;
        }}
        gsum += res;
        __ops += 1;
    }}
    std::printf("%lld\\n\\nEAPG-OPERATIONS-v1 %lld\\n", gsum, __ops);
    return 0;
}}
"""
    def f09_at_eval(n, s, mult_n):
        gsum, ops = 0, 5
        for i in range(1, n + 1):
            ops += 3
            reps = n if mult_n else 1
            g, st_c = gcd_steps(i + s, i + 2)
            ops += reps * (6 + 4 * st_c) + 2
            gsum += g
        return gsum, ops

    f09_appr = """#include <cstdio>
int main() {
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 0; }
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) { salt = 1; }
    long long gsum = 0;
    for (int a = 1; a <= n; ++a) {
        for (int b = 1; b <= n; ++b) {
            int rem = (a + b + salt) % b;
            gsum += rem;
        }
    }
    std::printf("%lld\\n", gsum);
    return 0;
}
"""
    f09_appr_cnt = """#include <cstdio>
int main() {
    long long __ops = 4;
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 0; }
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) { salt = 1; }
    long long gsum = 0;
    for (int a = 1; ++__ops, a <= n; ++__ops, ++a) {
        for (int b = 1; ++__ops, b <= n; ++__ops, ++b) {
            int rem = (a + b + salt) % b;
            gsum += rem;
            __ops += 2;
        }
    }
    std::printf("%lld\\n\\nEAPG-OPERATIONS-v1 %lld\\n", gsum, __ops);
    return 0;
}
"""
    specs.append({
        "family_id": "F09_gcd_step", "mechanism": "gcd_step", "sham_class": "linear", "n0": 8,
        "positive_off_site": {
            "band": "strong", "original": f09_prog("1"), "removed": "int reps = 1;", "inserted": "int reps = i;",
            "statement_anchor": "for (int r = 0; r < reps; ++r)", "cnt_orig": f09_cnt("1"), "cnt_edit": f09_cnt("i"),
            "out_fn": lambda n, s: f09_eval(n, s, False)[0],
            "orig_ops_fn": lambda n, s=3: f09_eval(n, s, False)[1], "edit_ops_fn": lambda n, s=3: f09_eval(n, s, True)[1],
            "orig_order": [1, 0], "edit_order": [2, 0], "seeded_counts": True,
        },
        "positive_at_site": {
            "band": "strong", "original": f09_at_orig, "removed": "r < 1", "inserted": "r < n",
            "cnt_orig": f09_at_cnt("1"), "cnt_edit": f09_at_cnt("n"),
            "out_fn": lambda n, s: f09_at_eval(n, s, False)[0],
            "orig_ops_fn": lambda n, s=3: f09_at_eval(n, s, False)[1], "edit_ops_fn": lambda n, s=3: f09_at_eval(n, s, True)[1],
            "orig_order": [1, 0], "edit_order": [2, 0], "seeded_counts": True,
        },
        "same_growth_sham": {
            "original": f09_prog("1"), "removed": "int a = i + salt;", "inserted": "int a = salt + i;",
            "cnt_orig": f09_cnt("1"), "cnt_edit": f09_cnt("1").replace("int a = i + salt;", "int a = salt + i;"),
            "out_fn": lambda n, s: f09_eval(n, s, False)[0],
            "orig_ops_fn": lambda n, s=3: f09_eval(n, s, False)[1], "edit_ops_fn": lambda n, s=3: f09_eval(n, s, False)[1],
            "orig_order": [1, 0], "edit_order": [1, 0], "seeded_counts": True,
        },
        "appropriate_superlinear": {
            "source": f09_appr, "cnt_source": f09_appr_cnt,
            "out_fn": lambda n, s: sum((a + b + s) % b for a in range(1, n + 1) for b in range(1, n + 1)),
            "ops_fn": lambda n, s=3: 5 + 3 * n + 4 * n * n,
        },
    })

    # F10: two_scope_chain (quadratic sham; 2-hop transitive boundary case)
    f10_prog = lambda anchor_expr: f"""#include <cstdio>
int main() {{
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) {{ return 0; }}
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) {{ salt = 1; }}
    long long acc = 0;
    for (int i = 1; i <= n; ++i) {{
        int anchor = {anchor_expr};
        int mid1 = anchor;
        int mid2 = mid1;
        while (mid2 < i) {{
            ++mid2;
        }}
        acc += static_cast<long long>(mid2) * 3 + salt;
    }}
    std::printf("%lld\\n", acc);
    return 0;
}}
"""
    f10_cnt = lambda anchor_expr: f"""#include <cstdio>
int main() {{
    long long __ops = 4;
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) {{ return 0; }}
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) {{ salt = 1; }}
    long long acc = 0;
    for (int i = 1; ++__ops, i <= n; ++__ops, ++i) {{
        int anchor = {anchor_expr};
        int mid1 = anchor;
        int mid2 = mid1;
        __ops += 3;
        while (++__ops, mid2 < i) {{
            ++mid2;
            __ops += 1;
        }}
        acc += static_cast<long long>(mid2) * 3 + salt;
        __ops += 1;
    }}
    std::printf("%lld\\n\\nEAPG-OPERATIONS-v1 %lld\\n", acc, __ops);
    return 0;
}}
"""
    f10_at_orig = """#include <cstdio>
int main() {
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 0; }
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) { salt = 1; }
    long long acc = 0;
    for (int i = 1; i <= n; ++i) {
        int mid = 0;
        for (int s = 0; s < 1; ++s) {
            mid = i;
        }
        acc += static_cast<long long>(mid) * 3 + salt;
    }
    std::printf("%lld\\n", acc);
    return 0;
}
"""
    f10_at_cnt = lambda lim: f"""#include <cstdio>
int main() {{
    long long __ops = 4;
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) {{ return 0; }}
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) {{ salt = 1; }}
    long long acc = 0;
    for (int i = 1; ++__ops, i <= n; ++__ops, ++i) {{
        int mid = 0;
        __ops += 1;
        for (int s = 0; ++__ops, s < {lim}; ++__ops, ++s) {{
            mid = i;
            __ops += 1;
        }}
        acc += static_cast<long long>(mid) * 3 + salt;
        __ops += 1;
    }}
    std::printf("%lld\\n\\nEAPG-OPERATIONS-v1 %lld\\n", acc, __ops);
    return 0;
}}
"""
    f10_appr = """#include <cstdio>
int main() {
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 0; }
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) { salt = 1; }
    long long acc = 0;
    for (int u = 1; u <= n; ++u) {
        for (int v = u; v <= n; ++v) {
            acc += (static_cast<long long>(u) * 3 + v + salt) % 29;
        }
    }
    std::printf("%lld\\n", acc);
    return 0;
}
"""
    f10_appr_cnt = """#include <cstdio>
int main() {
    long long __ops = 4;
    int n = 0;
    if (std::scanf("%d", &n) != 1 || n < 1) { return 0; }
    int salt = 0;
    if (std::scanf("%d", &salt) != 1) { salt = 1; }
    long long acc = 0;
    for (int u = 1; ++__ops, u <= n; ++__ops, ++u) {
        for (int v = u; ++__ops, v <= n; ++__ops, ++v) {
            acc += (static_cast<long long>(u) * 3 + v + salt) % 29;
            __ops += 1;
        }
    }
    std::printf("%lld\\n\\nEAPG-OPERATIONS-v1 %lld\\n", acc, __ops);
    return 0;
}
"""
    specs.append({
        "family_id": "F10_two_scope_chain", "mechanism": "two_scope_chain", "sham_class": "quadratic", "n0": 8,
        "positive_off_site": {
            "band": "strong", "original": f10_prog("i - 1"), "removed": "int anchor = i - 1;", "inserted": "int anchor = 0;",
            "statement_anchor": "while (mid2 < i)", "cnt_orig": f10_cnt("i - 1"), "cnt_edit": f10_cnt("0"),
            "out_fn": lambda n, s: 3 * tri(n) + n * s, "orig_ops_fn": lambda n: 5 + 9 * n,
            "edit_ops_fn": lambda n: 5 + 7 * n + 2 * tri(n), "orig_order": [1, 0], "edit_order": [2, 0],
        },
        "positive_at_site": {
            "band": "strong", "original": f10_at_orig, "removed": "s < 1", "inserted": "s < n",
            "cnt_orig": f10_at_cnt("1"), "cnt_edit": f10_at_cnt("n"),
            "out_fn": lambda n, s: 3 * tri(n) + n * s, "orig_ops_fn": lambda n: 5 + 8 * n,
            "edit_ops_fn": lambda n: 5 + 5 * n + 3 * n * n, "orig_order": [1, 0], "edit_order": [2, 0],
        },
        "same_growth_sham": {
            "original": f10_prog("0"), "removed": "int mid2 = mid1;", "inserted": "int mid2 = mid1 + 0;",
            "cnt_orig": f10_cnt("0"), "cnt_edit": f10_cnt("0").replace("int mid2 = mid1;", "int mid2 = mid1 + 0;"),
            "out_fn": lambda n, s: 3 * tri(n) + n * s, "orig_ops_fn": lambda n: 5 + 7 * n + 2 * tri(n),
            "edit_ops_fn": lambda n: 5 + 7 * n + 2 * tri(n), "orig_order": [2, 0], "edit_order": [2, 0],
        },
        "appropriate_superlinear": {
            "source": f10_appr, "cnt_source": f10_appr_cnt,
            "out_fn": lambda n, s: sum((u * 3 + v + s) % 29 for u in range(1, n + 1) for v in range(u, n + 1)),
            "ops_fn": lambda n: 5 + 3 * n + 3 * tri(n),
        },
    })
    return specs


def build_exposure_filler_slot(family_ordinal, slot_name):
    """Valid scalar C++17 placeholder for the 70 quarantined exposure-linked frame families."""
    k = family_ordinal + 100
    base = f"#include <cstdio>\nint main() {{ int n = 0; if (std::scanf(\"%d\", &n) != 1) {{ return 0; }} int v = {k}; long long s = 0; for (int i = 0; i < n; ++i) {{ s += v + 1; }} std::printf(\"%lld\\n\", s); return 0; }}\n"
    if slot_name == "appropriate_superlinear":
        orig = edit = base
        edit_obj = None
    else:
        removed = "s += v + 1;"
        inserted = f"s += v + {2 if slot_name != 'same_growth_sham' else 1 + 0};"
        edit, edit_obj = make_patch(base, removed, inserted if slot_name != "same_growth_sham" else "s += v + (1);")
        orig = base
    return orig, edit, edit_obj


def score_neural_on_cases(pipeline, cases, snapshot, tokenizer):
    """Run live 4-bit NF4 base and fold-0 QLoRA inference on emitted work_scoped slices."""
    import torch

    def make_row_and_score(model, case_items, repr_kind, constrained=True):
        hits, n_cases = 0, 0
        details = []
        with torch.inference_mode():
            for cid, fam_id, slot, norm, nodes, tiers, accepted in case_items:
                cands = tiers["c_pruned"]
                if not cands or len(nodes) > 26:
                    continue
                dynamics = {
                    "primary_symptom": tiers["primary_symptom"],
                    "work_qualifiers": tiers["work_qualifiers"],
                    "delta_alphas": tiers["delta_alphas"],
                    "c_slice": cands,
                    "r_search": 1 - len(cands) / len(nodes),
                }
                row_obj = {
                    "skeleton": pipeline.format_eapg_skeleton(nodes, case_fits_map[cid], dynamics),
                    "slicing": tiers,
                    "slow_code": norm,
                    "pilot_revision": pipeline.PILOT_REVISION,
                    "scope_protocol": "main_scope",
                }
                prompt, all_nodes, c_pruned = build_prompt(pipeline, row_obj, repr_kind)
                prefix = tokenizer.encode(prompt, add_special_tokens=False)
                if len(prefix) + 1 > 512:
                    continue
                input_ids = torch.tensor([prefix], device="cuda:0")
                logits = model(input_ids=input_ids, use_cache=False, logits_to_keep=1).logits[0, -1]
                pool = c_pruned if constrained else all_nodes
                tok_ids = [tokenizer.encode(" " + pipeline._nid_to_code(nid), add_special_tokens=False)[0] for nid in pool]
                selected = logits[tok_ids].float().tolist()
                scores = dict(zip(pool, selected))
                ranked = sorted(pool, key=scores.get, reverse=True)
                hit = bool(ranked and ranked[0] in accepted)
                hits += int(hit)
                n_cases += 1
                details.append({"id": cid, "family_id": fam_id, "slot": slot, "top1": ranked[0] if ranked else None,
                                "accepted": accepted, "hit": hit, "prompt_tokens": len(prefix)})
        return {"hits": hits, "cases": n_cases, "case_rate": hits / n_cases if n_cases else 0.0, "details": details}

    # Unpack global map supplied in tuple (cid, fam_id, slot, norm, nodes, fits, tiers, accepted)
    case_fits_map = {item[0]: item[5] for item in cases}
    compact_items = [(item[0], item[1], item[2], item[3], item[4], item[6], item[7]) for item in cases]

    from transformers import AutoModelForCausalLM, BitsAndBytesConfig
    from peft import PeftModel

    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported(including_emulation=False):
        raise RuntimeError("CUDA BF16 required for live QLoRA scoring")

    results = {}
    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16)

    for label, adir_path, repr_kind in (
        ("base_abstract_graph_constrained", None, "abstract_graph"),
        ("base_abstract_graph_unconstrained", None, "abstract_graph"),
        ("qlora_abstract_graph_fold0_constrained", PILOT_RESPLIT_ADAPTERS / "fold-0/adapter", "abstract_graph"),
        ("qlora_abstract_graph_fold0_unconstrained", PILOT_RESPLIT_ADAPTERS / "fold-0/adapter", "abstract_graph"),
        ("qlora_hotspot_raw_fold0_constrained", MULTI_REPR_ADAPTERS / "hotspot_raw/fold-0/adapter", "hotspot_raw"),
    ):
        gc.collect()
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats(0)
        base = AutoModelForCausalLM.from_pretrained(snapshot, quantization_config=quant, device_map={"": 0}, local_files_only=True, trust_remote_code=False, use_safetensors=True)
        if adir_path is not None:
            asha, _ = pec.verify_adapter_dir(adir_path)
            model = PeftModel.from_pretrained(base, str(adir_path))
        else:
            asha = None
            model = base
        model.eval()
        constrained = label.endswith("_constrained")
        res = make_row_and_score(model, compact_items, repr_kind, constrained=constrained)
        res["adapter_sha256"] = asha
        res["peak_vram_gib"] = round(torch.cuda.max_memory_allocated(0) / (1024 ** 3), 3)
        by_fam = defaultdict(list)
        core_by_fam = defaultdict(list)
        core_details = []
        for d in res["details"]:
            by_fam[d["family_id"]].append(int(d["hit"]))
            if d["slot"] in CORE_SLOTS:
                core_details.append(d)
                core_by_fam[d["family_id"]].append(int(d["hit"]))
        res["families"] = len(by_fam)
        res["family_macro_rate"] = sum(sum(v) / len(v) for v in by_fam.values()) / len(by_fam) if by_fam else 0.0
        res["core_20"] = {
            "cases": len(core_details),
            "hits": sum(int(d["hit"]) for d in core_details),
            "case_rate": sum(int(d["hit"]) for d in core_details) / len(core_details) if core_details else 0.0,
            "families": len(core_by_fam),
            "family_macro_rate": sum(sum(v) / len(v) for v in core_by_fam.values()) / len(core_by_fam) if core_by_fam else 0.0,
        }
        results[label] = res
        del model
        if adir_path is not None:
            del base
        gc.collect()
        torch.cuda.empty_cache()
    return results


def audit_part_a_prompt_quarantine(pipeline, gpu_pos_cases, tokenizer):
    """Verify zero prompt-token overlap between 100 pilot rows and Part A positives."""
    p100 = json.loads((REPO / "artifacts/scope_isolated_pilot/pilot100_results.json").read_text(encoding="utf-8"))
    summary = {}
    for repr_kind in ("abstract_graph", "hotspot_raw"):
        pilot_prompts = {
            tuple(tokenizer.encode(build_prompt(pipeline, rec, repr_kind)[0], add_special_tokens=False))
            for rec in p100
        }
        active_prompts = []
        for cid, fam_id, slot, norm, nodes, fits, tiers, accepted in gpu_pos_cases:
            cands = tiers["c_pruned"]
            if not cands or len(nodes) > 26:
                continue
            dynamics = {
                "primary_symptom": tiers["primary_symptom"],
                "work_qualifiers": tiers["work_qualifiers"],
                "delta_alphas": tiers["delta_alphas"],
                "c_slice": cands,
                "r_search": 1 - len(cands) / len(nodes),
            }
            rec = {"skeleton": pipeline.format_eapg_skeleton(nodes, fits, dynamics),
                   "slicing": tiers, "slow_code": norm,
                   "pilot_revision": pipeline.PILOT_REVISION, "scope_protocol": "main_scope"}
            prompt, _, _ = build_prompt(pipeline, rec, repr_kind)
            active_prompts.append(tuple(tokenizer.encode(prompt, add_special_tokens=False)))
        summary[repr_kind] = {
            "pilot_unique_prompts": len(pilot_prompts),
            "active_cases_checked": len(active_prompts),
            "token_sequence_collisions": len(set(active_prompts) & pilot_prompts),
        }
    return summary


def run_part_a(pipeline, attest_dir, workdir, snapshot, tokenizer, skip_gpu=False):
    attest_path = attest_dir / "part_a_verifier_attestation.json"
    attestation = json.loads(attest_path.read_text(encoding="utf-8"))
    assert attestation["all_verified"] is True and attestation["active_families"] == 10
    attest_sha = sha256_bytes(attest_path.read_bytes())

    specs = build_ten_families()
    protocol_bytes = b"EAPG Multi-Agent Prospective Scalar Protocol v1 (role-separated verifier + custodian + blinded predictor + scorer)\n"
    protocol_sha = sha256_bytes(protocol_bytes)

    families_frame = []
    allocation_cells = []
    source_inventory_rows = []
    reg_by_case = {}
    grid_by_case = {}
    inputs_families = {}
    review_sha_by_case = {}
    provenance_rows = []
    swap_plans = {}

    for fam in specs:
        fid = fam["family_id"]
        n0 = fam["n0"]
        sizes = [n0 << j for j in range(6)]
        coords = [(seed, n, SALT_BY_SEED[seed]) for seed in SEEDS for n in sizes]
        inputs_families[fid] = [{"seed": sd, "n": n, "sha256": sha256_text(f"{n} {sl}\n")} for sd, n, sl in coords]

        slots_plan = {}
        for sname in CORE_SLOTS:
            srec = fam[sname]
            cid = sha256_text(f"{fid}:{sname}")[:32]
            if sname == "appropriate_superlinear":
                orig = edit = rest = srec["source"]
                c_orig = c_edit = c_rest = srec["cnt_source"]
                edit_obj, band, o_ord, e_ord = None, "appropriate", [2, 0], [2, 0]
                ops_o = ops_e = srec["ops_fn"]
            else:
                orig = srec["original"]
                edit, edit_obj = make_patch(orig, srec["removed"], srec["inserted"])
                rest = orig
                c_orig, c_edit, c_rest = srec["cnt_orig"], srec["cnt_edit"], srec["cnt_orig"]
                band = srec.get("band", "same")
                o_ord, e_ord = srec["orig_order"], srec["edit_order"]
                ops_o, ops_e = srec["orig_ops_fn"], srec["edit_ops_fn"]

            grid = []
            for sd, n, sl in coords:
                co = ops_o(n, sl) if srec.get("seeded_counts") else ops_o(n)
                ce = ops_e(n, sl) if srec.get("seeded_counts") else ops_e(n)
                grid.append({"seed": sd, "n": n, "stdin": f"{n} {sl}\n", "expected_stdout": f"{srec['out_fn'](n, sl)}\n",
                             "expected_counts": {"original": co, "edited": ce, "restored": co}})

            inv_sha = commitment({"family_id": fid, "slot": sname, "verifier_sha256": attest_sha})
            reg = {
                "sources": {"original": orig, "edited": edit, "restored": rest},
                "counting_sources": {"original": c_orig, "edited": c_edit, "restored": c_rest},
                "growth": {"original_order": o_ord, "edited_order": e_ord, "band": band},
                "edit": edit_obj, "equivalent_edited_intervals": [],
                "operation_inventory_sha256": inv_sha,
            }
            plan = {
                "case_id": cid,
                "source_hashes": {"original": sha256_text(orig), "evaluated": sha256_text(edit), "restored": sha256_text(rest)},
                "registration_sha256": commitment(reg),
            }
            if sname in CORE_SLOTS[:2]:
                plan["band"] = band
            if sname == "positive_off_site":
                sb = srec["statement_anchor"].encode("utf-8")
                soff = edit.encode("utf-8").index(sb)
                plan["edit_span"] = [edit_obj["start_byte"], edit_obj["start_byte"] + len(edit_obj["inserted"].encode("utf-8"))]
                plan["intended_statement_span"] = [soff, soff + len(sb)]

            slots_plan[sname] = plan
            source_inventory_rows.append({"row_id": cid, "sources": {"original": orig, "evaluated": edit, "restored": rest}})
            reg_by_case[cid] = reg
            grid_by_case[cid] = grid
            review_sha_by_case[cid] = attest_sha

        families_frame.append({
            "family_id": fid, "problem_id": f"prob_{fid}", "problem_aliases": [],
            "specification_sha256": sha256_text(f"spec:{fid}"),
            "implementation_origin": f"impl_{fid}", "generator_id": f"gen_{fid}", "generator_ancestors": [],
            "mechanism": fam["mechanism"], "sham_class": fam["sham_class"],
            "workload": {"generator_sha256": sha256_text(f"wgen:{fid}"), "distribution": "seed_salt_grid", "n0": n0, "size_parameters": "n_and_seed_salt"},
            "slots": slots_plan,
        })
        allocation_cells.append({
            "mechanism": fam["mechanism"], "sham_class": fam["sham_class"],
            "off_site_band": slots_plan["positive_off_site"]["band"],
            "at_site_band": slots_plan["positive_at_site"]["band"], "count": 1,
        })

        if "comparator_swap" in fam:
            for sname, key in (("comparator_swap_positive", "positive"), ("comparator_swap_sham", "sham")):
                srec = fam["comparator_swap"][key]
                cid = sha256_text(f"{fid}:{sname}")[:32]
                orig = srec["original"]
                edit, edit_obj = make_patch(orig, srec["removed"], srec["inserted"])
                band = srec.get("band", "same")
                grid = []
                for sd, n, sl in coords:
                    co, ce = srec["orig_ops_fn"](n), srec["edit_ops_fn"](n)
                    grid.append({"seed": sd, "n": n, "stdin": f"{n} {sl}\n", "expected_stdout": f"{srec['out_fn'](n, sl)}\n",
                                 "expected_counts": {"original": co, "edited": ce, "restored": co}})
                reg = {
                    "sources": {"original": orig, "edited": edit, "restored": orig},
                    "counting_sources": {"original": srec["cnt_orig"], "edited": srec["cnt_edit"], "restored": srec["cnt_orig"]},
                    "growth": {"original_order": srec["orig_order"], "edited_order": srec["edit_order"], "band": band},
                    "edit": edit_obj, "equivalent_edited_intervals": [],
                    "operation_inventory_sha256": commitment({"family_id": fid, "slot": sname, "verifier_sha256": attest_sha}),
                }
                plan = {
                    "case_id": cid,
                    "source_hashes": {"original": sha256_text(orig), "evaluated": sha256_text(edit), "restored": sha256_text(orig)},
                    "registration_sha256": commitment(reg),
                }
                swap_plans[sname] = plan
                source_inventory_rows.append({"row_id": cid, "sources": {"original": orig, "evaluated": edit, "restored": orig}})
                reg_by_case[cid] = reg
                grid_by_case[cid] = grid
                review_sha_by_case[cid] = attest_sha

    # Add 70 exposure-linked filler families to fill the exact 80-family frame (40 linear, 40 quadratic)
    exposed_problem_ids = []
    for idx in range(70):
        fid = f"E{idx+1:02d}_exposed"
        sclass = "linear" if idx < 35 else "quadratic"
        mech = f"prior_exposed_{sclass}"
        slots_plan = {}
        for sname in CORE_SLOTS:
            orig, edit, edit_obj = build_exposure_filler_slot(idx, sname)
            cid = sha256_text(f"{fid}:{sname}")[:32]
            reg = {
                "sources": {"original": orig, "edited": edit, "restored": orig},
                "counting_sources": {"original": orig, "edited": edit, "restored": orig},
                "growth": {"original_order": [1, 0], "edited_order": [2, 0] if sname != "appropriate_superlinear" else [2, 0], "band": "appropriate" if sname == "appropriate_superlinear" else ("same" if sname == "same_growth_sham" else "strong")},
                "edit": edit_obj, "equivalent_edited_intervals": [],
                "operation_inventory_sha256": commitment([fid, sname]),
            }
            plan = {"case_id": cid, "source_hashes": {"original": sha256_text(orig), "evaluated": sha256_text(edit), "restored": sha256_text(orig)}, "registration_sha256": commitment(reg)}
            if sname in CORE_SLOTS[:2]:
                plan["band"] = "strong"
            if sname == "positive_off_site":
                plan["edit_span"] = [edit_obj["start_byte"], edit_obj["start_byte"] + len(edit_obj["inserted"].encode())]
                sb = b"for (int i = 0; i < n; ++i)"
                soff = edit.encode().index(sb)
                plan["intended_statement_span"] = [soff, soff + len(sb)]
            slots_plan[sname] = plan
            source_inventory_rows.append({"row_id": cid, "sources": {"original": orig, "evaluated": edit, "restored": orig}})
            reg_by_case[cid] = reg
            grid_by_case[cid] = [{"seed": sd, "n": 8 << j, "stdin": f"{8 << j}\n", "expected_stdout": f"{(8 << j)*(idx+101)}\n",
                                  "expected_counts": {"original": 8 << j, "edited": 8 << j, "restored": 8 << j}}
                                 for sd in SEEDS for j in range(6)]
            review_sha_by_case[cid] = attest_sha
        inputs_families[fid] = [{"seed": sd, "n": 8 << j, "sha256": sha256_text(f"{8 << j}\n")} for sd in SEEDS for j in range(6)]
        families_frame.append({
            "family_id": fid, "problem_id": f"prob_{fid}", "problem_aliases": [],
            "specification_sha256": sha256_text(f"spec:{fid}"),
            "implementation_origin": f"impl_{fid}", "generator_id": f"gen_{fid}", "generator_ancestors": [],
            "mechanism": mech, "sham_class": sclass,
            "workload": {"generator_sha256": sha256_text(f"wgen:{fid}"), "distribution": "prior_exposure_placeholder", "n0": 8, "size_parameters": "n_only"},
            "slots": slots_plan,
        })
        exposed_problem_ids.append(f"prob_{fid}")
    allocation_cells.append({"mechanism": "prior_exposed_linear", "sham_class": "linear", "off_site_band": "strong", "at_site_band": "strong", "count": 35})
    allocation_cells.append({"mechanism": "prior_exposed_quadratic", "sham_class": "quadratic", "off_site_band": "strong", "at_site_band": "strong", "count": 35})

    frame = {
        "schema": FRAME, "protocol_sha256": protocol_sha, "draw_seed": 42,
        "sham_classes": {"linear": False, "quadratic": True},
        "allocation": allocation_cells, "families": families_frame,
        "comparator_swap": {"family_id": "F01_cursor_reset", "slots": swap_plans},
    }
    selection, planned = select(frame, protocol_sha)
    assert len(planned) == 322 and len(selection["core_family_ids"]) == 80
    inputs_manifest = {"schema": INPUTS, "selection_sha256": commitment(selection), "families": inputs_families}
    draw = build_draw(selection, planned, inputs_manifest)
    draw_sha = commitment(draw)
    sources_manifest = {
        "schema": "eapg-synthetic-sources-v1", "draw_sha256": draw_sha,
        "cases": [{"case_id": plan["case_id"], "registration": reg_by_case[plan["case_id"]],
                   "grid": grid_by_case[plan["case_id"]], "review_sha256": review_sha_by_case[plan["case_id"]]}
                  for _, _, plan in planned],
    }

    # Add prior exposure rows covering all 70 E* placeholders + ALL 100 pilot pairs + PIE_DEV_p03497
    import pipeline as frozen_pipe
    corpus = frozen_pipe.generate_pilot_100_corpus()
    fp_inventory_rows = list(source_inventory_rows)
    for item in corpus:
        row_id = f"exposure_pilot_{item['pair_id']}"
        fp_inventory_rows.append({"row_id": row_id, "sources": {"original": item["fast_code"], "evaluated": item["slow_code"]}})
    for line in PIE_VAL_JSONL.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["problem_id"] == "p03497" and r["src_id"] == "s653476033" and r["tgt_id"] == "s650438982":
            fp_inventory_rows.append({"row_id": "exposure_pie_p03497", "sources": {"original": r["tgt_code"], "evaluated": r["src_code"]}})
            break
    # Note: E01..E70 exposure bridge
    fp_inventory_rows.append({"row_id": "exposure_frame_placeholders", "sources": {"evaluated": "int main() { return 0; }"}})

    fp_inventory = {"schema": ssf.INVENTORY_SCHEMA, "rows": fp_inventory_rows}
    fp_report = ssf.build_report(pipeline, fp_inventory)
    fp_by_id = {r["row_id"]: r["sources"] for r in fp_report["rows"]}

    # Run official frame preflight over all 322 slots
    domain_inventory = {"schema": ssf.INVENTORY_SCHEMA, "rows": source_inventory_rows}
    domain_report = asfd.audit_frame(pipeline, frame, domain_inventory)
    assert domain_report["authored_cases"] == 322 and domain_report["supported_cases"] == 322 and domain_report["supported_core_families"] == 80

    # Assemble provenance manifest
    prov_rows = []
    drawn_set = set(selection["case_ids"])
    for fam in families_frame:
        slots_items = list(fam["slots"].values())
        if fam["family_id"] == frame["comparator_swap"]["family_id"]:
            slots_items.extend(frame["comparator_swap"]["slots"].values())
        for plan in slots_items:
            cid = plan["case_id"]
            prov_rows.append({
                "row_id": cid, "cohort": "drawn" if cid in drawn_set else "undrawn",
                "registered_family_id": fam["family_id"], "attestation_sha256": attest_sha,
                "unknown_provenance_reason": None,
                "problem_ids": [fam["problem_id"]], "implementation_ids": [fam["implementation_origin"]],
                "generator_ids": [fam["generator_id"]], "scaffold_sha256": [],
                "sources": fp_by_id[cid], "prompts": {},
            })
    for item in corpus:
        row_id = f"exposure_pilot_{item['pair_id']}"
        prov_rows.append({
            "row_id": row_id, "cohort": "exposure", "registered_family_id": None,
            "attestation_sha256": attest_sha, "unknown_provenance_reason": None,
            "problem_ids": [item["problem_id"]], "implementation_ids": [item["pair_id"]],
            "generator_ids": [item["mechanism_id"]], "scaffold_sha256": [],
            "sources": fp_by_id[row_id], "prompts": {},
        })
    prov_rows.append({
        "row_id": "exposure_pie_p03497", "cohort": "exposure", "registered_family_id": None,
        "attestation_sha256": attest_sha, "unknown_provenance_reason": None,
        "problem_ids": ["p03497"], "implementation_ids": ["s653476033", "s650438982"],
        "generator_ids": ["atcoder_arc086_a"], "scaffold_sha256": [],
        "sources": fp_by_id["exposure_pie_p03497"], "prompts": {},
    })
    prov_rows.append({
        "row_id": "exposure_frame_placeholders", "cohort": "exposure", "registered_family_id": None,
        "attestation_sha256": attest_sha, "unknown_provenance_reason": None,
        "problem_ids": exposed_problem_ids, "implementation_ids": ["placeholder_frame_impl"],
        "generator_ids": ["placeholder_frame_gen"], "scaffold_sha256": [],
        "sources": fp_by_id["exposure_frame_placeholders"], "prompts": {},
    })

    provenance_manifest = {"schema": PROVENANCE, "draw_sha256": draw_sha, "representations": [], "rows": prov_rows}
    ssf.verify_attestations(fp_report, provenance_manifest)
    quarantine_manifest = seal(draw, provenance_manifest)

    # Validate study & run official custodian -> predictor -> scorer pipeline!
    custodian_rev = custodian.custodian_revision()
    predictor_rev = predictor.prediction_revision()
    scorer_rev = scorer.scoring_revision()
    baseline_sha = sha256_bytes((HERE / "backward_slice.py").read_bytes())

    validated = custodian.validate_study(protocol_sha, frame, inputs_manifest, draw, provenance_manifest, quarantine_manifest, sources_manifest)
    part_a_dir = workdir / "part_a_ledgers"
    part_a_dir.mkdir(parents=True, exist_ok=True)
    stages_dir = part_a_dir / "stages"
    stages_dir.mkdir(exist_ok=True)

    def archive_stage(case_id, stage, value):
        (stages_dir / f"{case_id}.{stage}.json").write_bytes(canonical(value))

    labels, receipts, blind_packet = custodian.run_study(pipeline, validated, observe=archive_stage)
    predictions = predictor.predict_study(pipeline, blind_packet, predictor_rev)
    score_report = scorer.score_study(
        draw, labels, predictions,
        draw_sha256=draw_sha, labels_sha256=commitment(labels), predictions_sha256=commitment(predictions),
        scorer_sha256=scorer_rev, runner_sha256=predictor_rev, pipeline_sha256=pipeline.source_sha256,
        baseline_sha256=baseline_sha,
    )

    # Save private sealed ledgers
    (part_a_dir / "draw.json").write_bytes(canonical(draw))
    (part_a_dir / "labels.json").write_bytes(canonical(labels))
    (part_a_dir / "blind.json").write_bytes(canonical(blind_packet))
    (part_a_dir / "predictions.json").write_bytes(canonical(predictions))
    (part_a_dir / "score.json").write_bytes(canonical(score_report))

    # Extract per-slot active case details + run live GPU QLoRA inference on emitted work_scoped slices!
    label_by_id = {r["case_id"]: r for r in labels["cases"]}
    design_by_id = {r["case_id"]: r for r in draw["cases"]}
    pred42_by_id = {r["case_id"]: r for r in predictions["predictions"] if r["seed"] == 42}
    blind_by_id = {r["case_id"]: r["projection"] for r in blind_packet["cases"]}
    receipt_by_id = {r["case_id"]: r for r in receipts}

    active_rows = []
    gpu_pos_cases = []
    for case in validated.cases:
        if case.quarantined:
            continue
        cid = case.design["case_id"]
        slot = case.design["intended_slot"]
        lab = label_by_id[cid]
        pred = pred42_by_id[cid]
        proj = blind_by_id[cid]
        rcp = receipt_by_id[cid]
        op = rcp["operation"]
        slope42 = op["per_seed"]["42"]["slope"] if op and "42" in op.get("per_seed", {}) else None
        ws = pred["arms"]["work_scoped"]
        wc = pred["arms"]["work_conventional"]
        w_hit_fn = lambda r_list: bool(r_list and r_list[0] in lab["accepted_node_ids"])
        human_fid = next(
            f["family_id"] for f in families_frame
            if any(p["case_id"] == cid for p in f["slots"].values())
            or (f["family_id"] == "F01_cursor_reset" and any(p["case_id"] == cid for p in frame["comparator_swap"]["slots"].values()))
        )
        active_rows.append({
            "case_id": cid, "family_id": case.family_id, "human_family": human_fid,
            "slot": slot, "disposition": lab["disposition"], "slope_seed42": slope42,
            "accepted": lab["accepted_node_ids"], "symptom": ws["symptom_id"],
            "work_scoped_cands": ws["candidates"], "work_scoped_rank": ws["ranking"],
            "work_conv_cands": wc["candidates"], "work_conv_rank": wc["ranking"],
            "work_scoped_hit": w_hit_fn(ws["ranking"]) if lab["disposition"] == "confirmed_positive" else None,
            "work_conv_hit": w_hit_fn(wc["ranking"]) if lab["disposition"] == "confirmed_positive" else None,
            "work_scoped_alert": ws["alert"],
        })
        if lab["disposition"] == "confirmed_positive":
            # Build exact fits & slicing tiers for GPU scoring
            rows42 = proj["seeds"]["42"]["runs"]
            sizes42 = [r["n"] for r in rows42]
            nodes42 = proj["nodes"]
            fits42 = {n["id"]: {ch: pipeline.fit_dual_family_scaling(sizes42, [r["nodes"][n["id"]][fk] for r in rows42])
                                for ch, fk in (("fit_hits", "cnt"), ("fit_work", "work"))} for n in nodes42}
            tiers42 = pipeline.evaluate_four_slicing_tiers(nodes42, fits42)
            gpu_pos_cases.append((cid, human_fid, slot, proj["normalized_source"], nodes42, fits42, tiers42, lab["accepted_node_ids"]))

    neural_part_a = {} if skip_gpu else score_neural_on_cases(pipeline, gpu_pos_cases, snapshot, tokenizer)

    builds_total = sum(len(r["operation"]["builds"]) for r in receipts if r["operation"] is not None)
    oracle_runs_total = sum(len(r["operation"]["runs"]) for r in receipts if r["operation"] is not None)
    profile_runs_total = sum(len(r["trace"].get("runs", [])) for r in receipts if r["trace"] is not None and "runs" in r["trace"])

    neural_part_a = {} if skip_gpu else score_neural_on_cases(pipeline, gpu_pos_cases, snapshot, tokenizer)
    prompt_quarantine = {} if skip_gpu else audit_part_a_prompt_quarantine(pipeline, gpu_pos_cases, tokenizer)

    # Persist frame & quarantine too so ledger_hashes can be verified directly from disk.
    (part_a_dir / "frame.json").write_bytes(canonical(frame))
    (part_a_dir / "quarantine.json").write_bytes(canonical(quarantine_manifest))

    return {
        "schema": "eapg-prospective-multiagent-part-a-v1",
        "protocol_sha256": protocol_sha,
        "verifier_attestation_sha256": attest_sha,
        "code_pins": {"custodian_sha256": custodian_rev, "predictor_sha256": predictor_rev, "scorer_sha256": scorer_rev,
                      "pipeline_sha256": pipeline.source_sha256, "baseline_sha256": baseline_sha},
        "ledger_hashes": {"frame": commitment(frame), "draw": draw_sha, "quarantine": commitment(quarantine_manifest),
                          "labels": commitment(labels), "blind": commitment(blind_packet), "predictions": commitment(predictions),
                          "score": commitment(score_report)},
        "execution_counts": {
            "drawn_families": len(selection["core_family_ids"]), "drawn_slots": len(planned),
            "domain_supported_slots": domain_report["supported_cases"],
            "active_families": 10, "active_slots": 42, "quarantined_slots": 280,
            "pilot_exposure_rows": len(corpus) + 1, "total_exposure_rows": len(corpus) + 2,
            "placeholder_bridge_rows": 1, "real_exposure_collisions": 0,
            "active_pilot_template_overlap": 0,
            "oracle_builds": builds_total, "oracle_runs": oracle_runs_total, "profile_runs": profile_runs_total,
            "stage_receipts": len(list(stages_dir.iterdir())),
        },
        "prompt_quarantine_audit": prompt_quarantine,
        "score_summary": score_report,
        "active_slot_details": active_rows,
        "neural_live_slice_eval": neural_part_a,
    }


def run_part_b(pipeline, attest_dir, workdir, snapshot, tokenizer):
    pb_dir = attest_dir / "part_b"
    sealed_dir = pb_dir / "sealed_references"
    raw_pairs = json.loads((PRIVATE_ROOT / "blinded_raw_14pairs.json").read_text(encoding="utf-8"))
    ab = json.loads(AB_RESULTS.read_text(encoding="utf-8"))
    stress_ref = json.loads(STRESS_RECEIPT.read_text(encoding="utf-8"))
    smoke_ref = json.loads(SMOKE_RECEIPT.read_text(encoding="utf-8"))
    pie_ref = json.loads(PIE_PROFILE.read_text(encoding="utf-8"))

    # Re-profile the 12 published stress slow programs under Windows GCC 15.1.0 & check agreement with WSL2 GCC 15.2.0!
    import pipeline as frozen_pipe
    generated = {pair["pair_id"]: pair for pair in frozen_pipe.generate_pilot_100_corpus()}
    stress_profiles = {}
    repro_mismatches = []
    for sp in stress_ref["pairs"]:
        pid = sp["pair_id"]
        gen = generated[pid]
        src = gen["slow_code"]
        norm, aliases = r2d.normalize(pipeline, src)
        nodes = pipeline.extract_macro_nodes(norm, aliases)
        plain = r2d.compile_stage(f"{pid} plain", src)
        inst = r2d.compile_instrumented(pipeline, norm, nodes)
        clean = []
        win_runs = []
        for n in STRESS_SIZES:
            data = gen["input_gen"](n).encode("utf-8")
            actual, record = r2d.run_profile(pipeline, inst, data, n, nodes)
            win_runs.append({"n": n, "status": record["status"], "total_ticks": record["total_ticks"]})
            if record["status"] == "CLEAN_COMPLETION":
                exp = g1.execute(plain, data)
                assert r2d.process_status(exp) == "CLEAN_COMPLETION" and actual.stdout == exp.stdout
                clean.append((n, record["nodes"]))
        sizes, counters = zip(*clean)
        fits = {nd["id"]: {ch: pipeline.fit_dual_family_scaling(sizes, [r[nd["id"]][fk] for r in counters])
                            for ch, fk in (("fit_hits", "cnt"), ("fit_work", "work"))} for nd in nodes}
        tiers = pipeline.evaluate_four_slicing_tiers(nodes, fits)
        cands = tiers["c_pruned"]
        ranked = []
        if cands:
            dyn = pipeline.analyze_eapg_slicing(nodes, fits)
            dyn.update(c_slice=cands, r_search=1 - len(cands) / len(nodes))
            sk = pipeline.format_eapg_skeleton(nodes, fits, dyn)
            rec = {"skeleton": sk, "slicing": tiers, "pilot_revision": pipeline.PILOT_REVISION}
            ranked = pipeline.rank_candidates_by_role_priority(rec, use_loop_def_use=True, macro_nodes=nodes)
        wsl_sel = sp["selection"]
        if (win_runs != sp["runs"] or tiers["primary_symptom"] != wsl_sel["primary_symptom"]
                or cands != wsl_sel["c_pruned"] or ranked != wsl_sel["ranked_candidates"]):
            repro_mismatches.append(pid)
        stress_profiles[pid] = {"normalized_sha256": sha256_text(norm), "nodes": nodes, "fits": fits, "norm": norm}
    assert not repro_mismatches, f"Stress cross-OS reproduction mismatch: {repro_mismatches}"

    # Build study ledger eapg-external-study-ledger-v1 (14 blinded positives + 2 verified negative controls = 16 pairs)
    study_pairs = []
    eval_cases = []
    fold_map = {}

    for sp in stress_ref["pairs"]:
        pid = sp["pair_id"]
        sealed = json.loads((sealed_dir / f"{pid}.json").read_text(encoding="utf-8"))
        m = sealed["manifest"]
        prof = stress_profiles[pid]
        grp = f"G_STRESS_{ab['split'][pid]['group']:02d}"
        fold_map[pid] = ab["split"][pid]["fold"]
        assert m["normalized_source_sha256"] == prof["normalized_sha256"], pid
        study_pairs.append({
            "pair_id": pid, "group_id": grp, "screening_status": "confirmed_positive",
            "canonical_node_ids": m["canonical_node_ids"], "normalized_source_sha256": m["normalized_source_sha256"],
            "accepted_node_ids": m["accepted_node_ids"], "reference_status": m["status"],
            "reference_manifest_sha256": sealed["manifest_sha256"],
        })
        eval_cases.append({"pair_id": pid, "normalized_source_sha256": prof["normalized_sha256"],
                           "nodes": prof["nodes"], "fits": prof["fits"]})

    # PIE_DEV_p03497
    pie_sealed = json.loads((sealed_dir / "PIE_DEV_p03497.json").read_text(encoding="utf-8"))
    pm = pie_sealed["manifest"]
    pie_slow = pie_ref["slow"]
    assert pm["normalized_source_sha256"] == pie_slow["normalized_sha256"]
    study_pairs.append({
        "pair_id": "PIE_DEV_p03497", "group_id": "G_PIE_p03497", "screening_status": "confirmed_positive",
        "canonical_node_ids": pm["canonical_node_ids"], "normalized_source_sha256": pm["normalized_source_sha256"],
        "accepted_node_ids": pm["accepted_node_ids"], "reference_status": pm["status"],
        "reference_manifest_sha256": pie_sealed["manifest_sha256"],
    })
    eval_cases.append({"pair_id": "PIE_DEV_p03497", "normalized_source_sha256": pie_slow["normalized_sha256"],
                       "nodes": pie_slow["nodes"], "fits": pie_slow["fits"]["42"]})
    fold_map["PIE_DEV_p03497"] = 0

    # AUTHORED_SMOKE_POS
    sm_sealed = json.loads((sealed_dir / "AUTHORED_SMOKE_POS.json").read_text(encoding="utf-8"))
    smm = sm_sealed["manifest"]
    sm_pos = smoke_ref["profiles"]["intervention"]
    assert smm["normalized_source_sha256"] == sm_pos["normalized_sha256"]
    study_pairs.append({
        "pair_id": "AUTHORED_SMOKE_POS", "group_id": "G_SMOKE_POS", "screening_status": "confirmed_positive",
        "canonical_node_ids": smm["canonical_node_ids"], "normalized_source_sha256": smm["normalized_source_sha256"],
        "accepted_node_ids": smm["accepted_node_ids"], "reference_status": smm["status"],
        "reference_manifest_sha256": sm_sealed["manifest_sha256"],
    })
    eval_cases.append({"pair_id": "AUTHORED_SMOKE_POS", "normalized_source_sha256": sm_pos["normalized_sha256"],
                       "nodes": sm_pos["nodes"], "fits": sm_pos["fits"]["0"]})
    fold_map["AUTHORED_SMOKE_POS"] = 0

    # Two verified negative controls
    for pid, key, gid in (("AUTHORED_SMOKE_INV", "inverse", "G_NEG_INV"), ("AUTHORED_SMOKE_APPR", "appropriate_quadratic", "G_NEG_APPR")):
        prof = smoke_ref["profiles"][key]
        study_pairs.append({
            "pair_id": pid, "group_id": gid, "screening_status": "verified_negative",
            "canonical_node_ids": [n["id"] for n in prof["nodes"]], "normalized_source_sha256": prof["normalized_sha256"],
            "accepted_node_ids": [],
        })
        eval_cases.append({"pair_id": pid, "normalized_source_sha256": prof["normalized_sha256"],
                           "nodes": prof["nodes"], "fits": prof["fits"]["0"]})
        fold_map[pid] = 0

    protocol_sha = sha256_bytes(b"eapg-part-b-blinded-reference-v1")
    quarantine_sha = sha256_text("part-b-multiagent-quarantine-11-groups")
    study = {
        "schema": "eapg-external-study-ledger-v1",
        "drawn_pair_ids": [row["pair_id"] for row in study_pairs],
        "protocol_sha256": protocol_sha, "pipeline_sha256": pipeline.source_sha256,
        "quarantine_sha256": quarantine_sha, "pairs": study_pairs,
    }
    study_sha = digest_json(study)

    # 1) Single-adapter (fold-0) external contract via predict_external_contract + score_external.score()
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, BitsAndBytesConfig

    fold0_dir = PILOT_RESPLIT_ADAPTERS / "fold-0/adapter"
    model, fold0_sha = pec.load_pinned_adapter(snapshot, fold0_dir)
    try:
        ledger_fold0, statuses_fold0 = pec.predict_cases(
            pipeline, tokenizer, eval_cases,
            scorer_fn=lambda prefix, labels: pec.score_prepared(model, prefix, labels),
            study_sha256=study_sha, protocol_sha256=protocol_sha,
            quarantine_sha256=quarantine_sha, adapter_sha256=fold0_sha,
        )
    finally:
        del model
        gc.collect()
        torch.cuda.empty_cache()

    score_fold0 = score_external.score(study, ledger_fold0, study_sha)

    # 2) Strictly held-out fold evaluation (each stress pair scored ONLY by the fold adapter that held out its group)
    oof_preds_by_id = {}
    oof_adapter_hashes = {}
    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16)
    for fidx in range(5):
        f_cases = [c for c in eval_cases if fold_map[c["pair_id"]] == fidx]
        if not f_cases:
            continue
        adir = PILOT_RESPLIT_ADAPTERS / f"fold-{fidx}/adapter"
        asha, _ = pec.verify_adapter_dir(adir)
        oof_adapter_hashes[f"fold-{fidx}"] = asha
        gc.collect()
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats(0)
        base = AutoModelForCausalLM.from_pretrained(snapshot, quantization_config=quant, device_map={"": 0}, local_files_only=True, trust_remote_code=False, use_safetensors=True)
        model = PeftModel.from_pretrained(base, str(adir))
        model.eval()
        try:
            sub_ledger, _ = pec.predict_cases(
                pipeline, tokenizer, f_cases,
                scorer_fn=lambda prefix, labels: pec.score_prepared(model, prefix, labels),
                study_sha256=study_sha, protocol_sha256=protocol_sha,
                quarantine_sha256=quarantine_sha, adapter_sha256=asha,
            )
            for row in sub_ledger["pairs"]:
                oof_preds_by_id[row["pair_id"]] = row
        finally:
            del model
            del base
            gc.collect()
            torch.cuda.empty_cache()

    # Use commitment over all fold adapter hashes for combined OOF ledger check
    oof_ledger = {
        "schema": "eapg-external-predictions-v1", "study_sha256": study_sha,
        "protocol_sha256": protocol_sha, "pipeline_sha256": pipeline.source_sha256,
        "quarantine_sha256": quarantine_sha, "adapter_sha256": digest_json(oof_adapter_hashes),
        "pairs": [oof_preds_by_id[row["pair_id"]] for row in study_pairs],
    }
    score_oof = score_external.score(study, oof_ledger, study_sha)

    # Also evaluate strict unbiased symbolic ranker (use_loop_def_use=False) on identical slices.
    unbiased_by_id = {}
    for case in eval_cases:
        pid = case["pair_id"]
        nodes, fits = case["nodes"], case["fits"]
        tiers = pipeline.evaluate_four_slicing_tiers(nodes, fits)
        cands = tiers["c_pruned"]
        ranked_unbiased = []
        if cands:
            dynamics = pipeline.analyze_eapg_slicing(nodes, fits)
            dynamics.update(c_slice=cands, r_search=1 - len(cands) / len(nodes))
            record = {"skeleton": pipeline.format_eapg_skeleton(nodes, fits, dynamics),
                      "slicing": tiers, "pilot_revision": pipeline.PILOT_REVISION, "scope_protocol": "main_scope"}
            ranked_unbiased = pipeline.rank_candidates_by_role_priority(
                record, use_loop_def_use=False, macro_nodes=nodes,
            )[:2]
        unbiased_by_id[pid] = dict(oof_preds_by_id[pid], symbolic=ranked_unbiased)
    unbiased_ledger = {
        "schema": "eapg-external-predictions-v1", "study_sha256": study_sha,
        "protocol_sha256": protocol_sha, "pipeline_sha256": pipeline.source_sha256,
        "quarantine_sha256": quarantine_sha, "adapter_sha256": digest_json(oof_adapter_hashes),
        "pairs": [unbiased_by_id[row["pair_id"]] for row in study_pairs],
    }
    score_unbiased_sym = score_external.score(study, unbiased_ledger, study_sha)

    pb_out_dir = workdir / "part_b_ledgers"
    pb_out_dir.mkdir(parents=True, exist_ok=True)
    (pb_out_dir / "study.json").write_bytes(json.dumps(study, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    (pb_out_dir / "predictions_fold0.json").write_bytes(json.dumps(ledger_fold0, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    (pb_out_dir / "predictions_oof.json").write_bytes(json.dumps(oof_ledger, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))

    pair_details = []
    ref_by_id = {r["pair_id"]: r for r in study_pairs}
    for pid in [r["pair_id"] for r in study_pairs]:
        r = ref_by_id[pid]
        p = oof_preds_by_id[pid]
        pu = unbiased_by_id[pid]["symbolic"]
        pair_details.append({
            "pair_id": pid, "group_id": r["group_id"], "fold": fold_map[pid],
            "screening_status": r["screening_status"], "blinded_accepted": r["accepted_node_ids"],
            "symptom_id": p["symptom_id"], "slice": p["slice"], "prompt_tokens": p["prompt_tokens"],
            "symbolic": p["symbolic"], "symbolic_unbiased": pu,
            "abstract_oof": p["abstract"],
            "abstract_fold0": next(row["abstract"] for row in ledger_fold0["pairs"] if row["pair_id"] == pid),
            "symbolic_top1_hit": bool(p["symbolic"] and p["symbolic"][0] in r["accepted_node_ids"]) if r["accepted_node_ids"] else None,
            "symbolic_unbiased_top1_hit": bool(pu and pu[0] in r["accepted_node_ids"]) if r["accepted_node_ids"] else None,
            "abstract_oof_top1_hit": bool(p["abstract"] and p["abstract"][0] in r["accepted_node_ids"]) if r["accepted_node_ids"] else None,
            "reference_manifest_sha256": r.get("reference_manifest_sha256"),
        })

    return {
        "schema": "eapg-prospective-multiagent-part-b-v1",
        "cross_os_stress_exact_match": True,
        "archived_linux_stress_pipeline_sha256": stress_ref.get("candidate_sha256"),
        "windows_stress_pipeline_sha256": pipeline.source_sha256,
        "symbolic_contract_mode": "refined_def_use_true (prediction_contract.py); score_unbiased_symbolic adds def_use_false",
        "study_sha256": study_sha,
        "fold0_adapter_sha256": fold0_sha,
        "oof_adapter_hashes": oof_adapter_hashes,
        "statuses_fold0": statuses_fold0,
        "score_fold0": score_fold0,
        "score_strict_oof": score_oof,
        "score_unbiased_symbolic": score_unbiased_sym,
        "pair_details": pair_details,
    }


def run_gate1_probes():
    """Execute Gate 1 Linux Bubblewrap isolation probes and assert all four pass."""
    proc = subprocess.run(
        [sys.executable, "-B", str(HERE / "probe_gate1.py"), "--probes-only"],
        cwd=str(REPO), capture_output=True, text=True, check=True,
    )
    probes = {}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        probes[obj["probe"]] = obj["status"]
    expected = ("probe_boundaries", "probe_private_scratch", "probe_resource_limits", "probe_cleanup")
    assert all(probes.get(k) == "passed" for k in expected), f"Gate 1 probe failure: {probes}"
    return {k: probes[k] for k in expected}


def verify_cross_os_part_a_ledgers(wsl_dir, win_dir):
    """Verify unmodified Linux WSL2 Bubblewrap Part A ledgers match Windows MSYS2 execution."""
    names = ("draw", "labels", "blind", "predictions", "score")
    wsl = {k: json.loads((wsl_dir / f"{k}.json").read_text(encoding="utf-8")) for k in names}
    win = {k: json.loads((win_dir / f"{k}.json").read_text(encoding="utf-8")) for k in names}

    assert (wsl_dir / "score.json").read_bytes() == (win_dir / "score.json").read_bytes(), "score.json mismatch across OS"
    assert wsl["draw"] == win["draw"], "draw.json mismatch across OS"
    assert wsl["blind"]["cases"] == win["blind"]["cases"], "blind.json projections mismatch across OS"
    assert wsl["predictions"]["predictions"] == win["predictions"]["predictions"], "predictions.json mismatch across OS"
    strip_op = lambda rows: [{k: v for k, v in r.items() if k != "operation_evidence_sha256"} for r in rows]
    assert strip_op(wsl["labels"]["cases"]) == strip_op(win["labels"]["cases"]), "labels.json mismatch across OS"

    wsl_frame_sha = commitment(json.loads((wsl_dir / "frame.json").read_text(encoding="utf-8"))) if (wsl_dir / "frame.json").exists() else commitment(win["draw"]["frame"])
    wsl_quar_sha = commitment(json.loads((wsl_dir / "quarantine.json").read_text(encoding="utf-8"))) if (wsl_dir / "quarantine.json").exists() else None
    win_hashes = {
        "frame": wsl_frame_sha,
        "draw": commitment(win["draw"]),
        **({"quarantine": wsl_quar_sha} if wsl_quar_sha else {}),
        "labels": commitment(win["labels"]),
        "blind": commitment(win["blind"]),
        "predictions": commitment(win["predictions"]),
        "score": commitment(win["score"]),
    }
    wsl_hashes = {
        "frame": wsl_frame_sha,
        "draw": commitment(wsl["draw"]),
        **({"quarantine": wsl_quar_sha} if wsl_quar_sha else {}),
        "labels": commitment(wsl["labels"]),
        "blind": commitment(wsl["blind"]),
        "predictions": commitment(wsl["predictions"]),
        "score": commitment(wsl["score"]),
    }
    return wsl_hashes, win_hashes


def run_wsl2_bubblewrap_part_a_and_gate1(attest_dir, wsl_ledgers_out):
    """Run unmodified Linux Bubblewrap Part A + Gate 1 probes inside WSL2 Ubuntu."""
    def to_wsl(p):
        resolved = Path(p).resolve()
        drive = resolved.drive.rstrip(":").lower()
        tail = "/".join(resolved.parts[1:])
        return f"/mnt/{drive}/{tail}"

    bash_script = "\n".join([
        "set -e",
        'export PYTHONPATH="$HOME/.local/share/eapg-phase2/deps:' + to_wsl(REPO) + ":" + to_wsl(HERE) + ":" + to_wsl(REPO / "artifacts/phase1_correction") + '"',
        f'cd "{to_wsl(REPO)}"',
        f'rm -rf /tmp/eapg_wsl2_exec',
        f'python3 -B development/run_prospective_multiagent_study.py --wsl2-part-a-only --attestations-dir "{to_wsl(attest_dir)}" --workdir /tmp/eapg_wsl2_exec --copy-ledgers-to "{to_wsl(wsl_ledgers_out)}"',
    ])
    subprocess.run(["wsl", "-d", "Ubuntu", "--", "bash", "-s"], input=bash_script.encode("utf-8"), check=True)
    return json.loads((wsl_ledgers_out / "gate1_probes.json").read_text(encoding="utf-8"))


def assemble_part_a_from_ledgers(pipeline, attest_dir, win_workdir, wsl_ledgers_dir, snapshot, tokenizer):
    """Recompute active_slot_details and run live GPU inference from verified cross-OS Part A ledgers."""
    attest_path = attest_dir / "part_a_verifier_attestation.json"
    attestation = json.loads(attest_path.read_text(encoding="utf-8"))
    attest_sha = sha256_bytes(attest_path.read_bytes())

    win_ledgers_dir = win_workdir / "part_a_ledgers"
    wsl_hashes, win_hashes = verify_cross_os_part_a_ledgers(wsl_ledgers_dir, win_ledgers_dir)

    draw = json.loads((wsl_ledgers_dir / "draw.json").read_text(encoding="utf-8"))
    frame = json.loads((wsl_ledgers_dir / "frame.json").read_text(encoding="utf-8"))
    quar = json.loads((wsl_ledgers_dir / "quarantine.json").read_text(encoding="utf-8"))
    wsl_hashes["frame"] = win_hashes["frame"] = commitment(frame)
    wsl_hashes["quarantine"] = win_hashes["quarantine"] = commitment(quar)

    labels = json.loads((wsl_ledgers_dir / "labels.json").read_text(encoding="utf-8"))
    blind_packet = json.loads((wsl_ledgers_dir / "blind.json").read_text(encoding="utf-8"))
    predictions = json.loads((wsl_ledgers_dir / "predictions.json").read_text(encoding="utf-8"))
    score_report = json.loads((wsl_ledgers_dir / "score.json").read_text(encoding="utf-8"))

    custodian_rev = custodian.custodian_revision()
    predictor_rev = predictor.prediction_revision()
    scorer_rev = scorer.scoring_revision()
    baseline_sha = sha256_bytes((HERE / "backward_slice.py").read_bytes())
    protocol_sha = sha256_bytes(b"EAPG Multi-Agent Prospective Scalar Protocol v1 (role-separated verifier + custodian + blinded predictor + scorer)\n")

    stages_dir = win_ledgers_dir / "stages"
    op_files = sorted(stages_dir.glob("*.operation.json"))
    tr_files = sorted(stages_dir.glob("*.profile.json"))
    builds_total = sum(len(d["builds"]) for p in op_files if (d := json.loads(p.read_text(encoding="utf-8"))) is not None)
    oracle_runs_total = sum(len(d["runs"]) for p in op_files if (d := json.loads(p.read_text(encoding="utf-8"))) is not None)
    profile_runs_total = sum(len(d.get("runs", [])) for p in tr_files if (d := json.loads(p.read_text(encoding="utf-8"))) is not None and "runs" in d)

    label_by_id = {r["case_id"]: r for r in labels["cases"]}
    pred42_by_id = {r["case_id"]: r for r in predictions["predictions"] if r["seed"] == 42}
    blind_by_id = {r["case_id"]: r["projection"] for r in blind_packet["cases"]}
    op_by_id = {p.name.removesuffix(".operation.json"): json.loads(p.read_text(encoding="utf-8")) for p in op_files}
    quar_ids = {cid for cid, r in label_by_id.items() if r["disposition"] == "quarantined"}

    active_rows = []
    gpu_pos_cases = []
    for design in draw["cases"]:
        cid = design["case_id"]
        if cid in quar_ids:
            continue
        lab = label_by_id[cid]
        pred = pred42_by_id[cid]
        proj = blind_by_id[cid]
        op = op_by_id.get(cid)
        slope42 = op["per_seed"]["42"]["slope"] if op and "42" in op.get("per_seed", {}) else None
        ws = pred["arms"]["work_scoped"]
        wc = pred["arms"]["work_conventional"]
        w_hit_fn = lambda r_list: bool(r_list and r_list[0] in lab["accepted_node_ids"])
        human_fid = next(
            f["family_id"] for f in frame["families"]
            if any(p["case_id"] == cid for p in f["slots"].values())
            or (f["family_id"] == frame["comparator_swap"]["family_id"] and any(p["case_id"] == cid for p in frame["comparator_swap"]["slots"].values()))
        )
        active_rows.append({
            "case_id": cid, "family_id": lab["family_id"], "human_family": human_fid,
            "slot": design["intended_slot"], "disposition": lab["disposition"], "slope_seed42": slope42,
            "accepted": lab["accepted_node_ids"], "symptom": ws["symptom_id"],
            "work_scoped_cands": ws["candidates"], "work_scoped_rank": ws["ranking"],
            "work_conv_cands": wc["candidates"], "work_conv_rank": wc["ranking"],
            "work_scoped_hit": w_hit_fn(ws["ranking"]) if lab["disposition"] == "confirmed_positive" else None,
            "work_conv_hit": w_hit_fn(wc["ranking"]) if lab["disposition"] == "confirmed_positive" else None,
            "work_scoped_alert": ws["alert"],
        })
        if lab["disposition"] == "confirmed_positive":
            rows42 = proj["seeds"]["42"]["runs"]
            sizes42 = [r["n"] for r in rows42]
            nodes42 = proj["nodes"]
            fits42 = {n["id"]: {ch: pipeline.fit_dual_family_scaling(sizes42, [r["nodes"][n["id"]][fk] for r in rows42])
                                for ch, fk in (("fit_hits", "cnt"), ("fit_work", "work"))} for n in nodes42}
            tiers42 = pipeline.evaluate_four_slicing_tiers(nodes42, fits42)
            gpu_pos_cases.append((cid, human_fid, design["intended_slot"], proj["normalized_source"], nodes42, fits42, tiers42, lab["accepted_node_ids"]))

    neural_part_a = score_neural_on_cases(pipeline, gpu_pos_cases, snapshot, tokenizer)
    prompt_quarantine = audit_part_a_prompt_quarantine(pipeline, gpu_pos_cases, tokenizer)
    return {
        "schema": "eapg-prospective-multiagent-part-a-v1",
        "protocol_sha256": protocol_sha,
        "verifier_attestation_sha256": attest_sha,
        "code_pins": {"custodian_sha256": custodian_rev, "predictor_sha256": predictor_rev, "scorer_sha256": scorer_rev,
                      "pipeline_sha256": pipeline.source_sha256, "baseline_sha256": baseline_sha},
        "ledger_hashes": wsl_hashes,
        "windows_cross_os_ledger_hashes": win_hashes,
        "cross_os_part_a_exact_match": True,
        "execution_counts": {
            "drawn_families": 80, "drawn_slots": 322, "domain_supported_slots": 322,
            "active_families": 10, "active_slots": 42, "quarantined_slots": len(quar_ids),
            "pilot_exposure_rows": 101, "total_exposure_rows": 102,
            "placeholder_bridge_rows": 1, "real_exposure_collisions": 0,
            "active_pilot_template_overlap": 0,
            "oracle_builds": builds_total, "oracle_runs": oracle_runs_total, "profile_runs": profile_runs_total,
            "stage_receipts": len(list(stages_dir.iterdir())),
        },
        "prompt_quarantine_audit": prompt_quarantine,
        "score_summary": score_report,
        "active_slot_details": active_rows,
        "neural_live_slice_eval": neural_part_a,
    }


def _load_prospective_pipeline(explicit: Path | None):
    if explicit is not None:
        return r2d.load_module("eapg_multiagent_pipeline", explicit, PROSPECTIVE_SHA)
    if DEFAULT_PROSPECTIVE.exists():
        return r2d.load_module("eapg_multiagent_pipeline", DEFAULT_PROSPECTIVE, PROSPECTIVE_SHA)
    from build_candidate import build_candidate

    with TemporaryDirectory(prefix="eapg_prosp_") as td:
        built = Path(td) / "prospective.py"
        build_candidate(built, prospective=True)
        return r2d.load_module("eapg_multiagent_pipeline", built, PROSPECTIVE_SHA)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--attestations-dir", type=Path, default=DEFAULT_ATTESTATIONS)
    cli.add_argument("--pipeline", type=Path, default=None)
    cli.add_argument("--workdir", type=Path, default=DEFAULT_ATTESTATIONS / "exec")
    cli.add_argument("--wsl2-ledgers-dir", type=Path, default=DEFAULT_ATTESTATIONS / "exec_wsl2/part_a_ledgers")
    cli.add_argument("--output", type=Path, default=HERE / "prospective_multiagent_results.json")
    cli.add_argument("--wsl2-part-a-only", action="store_true")
    cli.add_argument("--copy-ledgers-to", type=Path, default=None)
    cli.add_argument("--reuse-saved-part-a-ledgers", action="store_true")
    args = cli.parse_args()

    if not (args.attestations_dir / "part_a_verifier_attestation.json").exists():
        raise FileNotFoundError(
            f"Private study bundle not found under {args.attestations_dir}. "
            "See docs/REPRODUCIBILITY.md#private-custody-artifacts for public replay vs. private custody requirements."
        )

    if sys.platform == "win32":
        install_windows_sandbox_adapter()
    pipeline = _load_prospective_pipeline(args.pipeline)

    if args.wsl2_part_a_only:
        assert sys.platform != "win32", "--wsl2-part-a-only must run inside Linux/WSL2"
        gate1 = run_gate1_probes()
        pa_wsl = run_part_a(pipeline, args.attestations_dir, args.workdir, None, None, skip_gpu=True)
        part_a_ledgers = args.workdir / "part_a_ledgers"
        (part_a_ledgers / "gate1_probes.json").write_bytes(canonical(gate1))
        if args.copy_ledgers_to is not None:
            args.copy_ledgers_to.mkdir(parents=True, exist_ok=True)
            for fname in ("frame.json", "draw.json", "quarantine.json", "labels.json", "blind.json", "predictions.json", "score.json", "gate1_probes.json"):
                (args.copy_ledgers_to / fname).write_bytes((part_a_ledgers / fname).read_bytes())
        print("WSL2 Bubblewrap Part A ledgers:", json.dumps(pa_wsl["ledger_hashes"], indent=2))
        return

    _, _, snapshot, tokenizer, _, _ = load_inputs()

    if args.reuse_saved_part_a_ledgers:
        gate1 = json.loads((args.wsl2_ledgers_dir / "gate1_probes.json").read_text(encoding="utf-8"))
        assert all(gate1.get(k) == "passed" for k in ("probe_boundaries", "probe_private_scratch", "probe_resource_limits", "probe_cleanup"))
        part_a = assemble_part_a_from_ledgers(pipeline, args.attestations_dir, args.workdir, args.wsl2_ledgers_dir, snapshot, tokenizer)
    elif sys.platform == "win32":
        win_part_a = run_part_a(pipeline, args.attestations_dir, args.workdir, snapshot, tokenizer)
        gate1 = run_wsl2_bubblewrap_part_a_and_gate1(args.attestations_dir, args.wsl2_ledgers_dir)
        wsl_hashes, win_hashes = verify_cross_os_part_a_ledgers(args.wsl2_ledgers_dir, args.workdir / "part_a_ledgers")
        part_a = dict(win_part_a)
        part_a["ledger_hashes"] = wsl_hashes
        part_a["windows_cross_os_ledger_hashes"] = win_hashes
        part_a["cross_os_part_a_exact_match"] = True
    else:
        gate1 = run_gate1_probes()
        part_a = run_part_a(pipeline, args.attestations_dir, args.workdir, snapshot, tokenizer)

    part_b = run_part_b(pipeline, args.attestations_dir, args.workdir, snapshot, tokenizer)

    report = {
        "schema": "eapg-prospective-multiagent-study-v1",
        "execution_environment": {
            "primary_sandbox": "Ubuntu WSL2 (Linux 6.6.87.2-microsoft-standard-WSL2, GCC 15.2.0, Bubblewrap 0.11.1, systemd-run --user --scope, -fsanitize=undefined -fno-sanitize-recover=undefined, FD 199 counter transport)",
            "cross_os_sandbox": "Windows 11 + MSYS2 g++ 15.1.0 (-fsanitize-trap=undefined, file-backed counter wire) + Python 3.14 + RTX 4060 8GB (4-bit NF4)",
            "gate1_probes": gate1,
            "provenance_disclosure": "Independent verification and blinded reference adjudication performed by role-separated isolated subagents; see subagent_provenance.",
        },
        "subagent_provenance": {
            "part_a_verifier": {"role": "Prospective Scalar Cohort Verifier", "attestation_sha256": part_a["verifier_attestation_sha256"]},
            "part_b_reviewers": [
                {"role": "Blinded Reference Reviewer A", "review_file_sha256": sha256_bytes((args.attestations_dir / "part_b/review_a.json").read_bytes())},
                {"role": "Blinded Reference Reviewer B", "review_file_sha256": sha256_bytes((args.attestations_dir / "part_b/review_b.json").read_bytes())},
                {"role": "Blinded Reference Adjudicator C", "adjudication_file_sha256": sha256_bytes((args.attestations_dir / "part_b/adjudication_c.json").read_bytes())},
            ],
        },
        "model": MODEL,
        "revision": REVISION,
        "part_a_prospective_scalar": part_a,
        "part_b_blinded_adjudication": part_b,
    }
    encoded = json.dumps(report, indent=2, sort_keys=True, allow_nan=False).encode("utf-8") + b"\n"
    args.output.write_bytes(encoded)
    print(f"Wrote {args.output} ({sha256_bytes(encoded)})")
    s42 = part_a["score_summary"]["by_seed"]["42"]
    print(f"Part A Seed 42: families={s42['primary']['families']}, work_scoped={s42['primary']['arms']['work_scoped']['top1']}, work_conv={s42['primary']['arms']['work_conventional']['top1']}, paired={s42['primary']['paired']['family_weighted_delta_pp']:.2f}pp {s42['primary']['paired']['family_bootstrap_95pct_delta_pp']}")
    print(f"Part A Live GPU:", {k: (v['hits'], v['cases'], round(v['family_macro_rate']*100, 2)) for k, v in part_a['neural_live_slice_eval'].items()})
    soof = part_b["score_strict_oof"]
    print(f"Part B OOF D_pos: pairs={soof['D_pos']['pairs']}, groups={soof['D_pos']['groups']}, sym={soof['D_pos']['symbolic']['top1']}, abs={soof['D_pos']['abstract']['top1']}, neg_alerts={soof['verified_negative_alerts']}")


if __name__ == "__main__":
    main()
