"""Run the registered PIE development pair in a fixture-checked Linux namespace."""

import argparse
from collections import defaultdict
import ctypes
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory, TemporaryFile
import time
from types import FunctionType, SimpleNamespace


HERE = Path(__file__).resolve().parent
PIPELINE_SHA = "7c855651566c1a7dc003fdcb291d8edd3ff1a99c671f781eb595d72c492ae743"
VAL_SHA = "6608a303c5c6ab61e7936599f3aa8cbde67bc36007e1a9739d7868665c531dab"
LIMITS = ["prlimit", "--cpu=8:8", "--as=536870912:536870912",
          "--fsize=8388608:8388608", "--core=0:0", "--"]
FILE_CAP = 8 * 1024 * 1024


def sha(data):
    return hashlib.sha256(data).hexdigest()


def reap_descendants():
    deadline = time.monotonic() + 3
    children = Path(f"/proc/self/task/{os.getpid()}/children")
    while time.monotonic() < deadline:
        try:
            reaped, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if reaped:
            continue
        for pid in map(int, children.read_text().split()):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        time.sleep(0.01)
    raise RuntimeError("Could not reap the subprocess tree")


def run(args, *, data=b"", timeout=12, descriptor=None, extra_env=None):
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "TMPDIR": "/tmp"}
    env.update(extra_env or {})
    with TemporaryFile() as stdin, TemporaryFile() as stdout, TemporaryFile() as stderr:
        stdin.write(data)
        stdin.seek(0)
        child = subprocess.Popen(
            LIMITS + args, stdin=stdin, stdout=stdout, stderr=stderr, env=env,
            start_new_session=True, pass_fds=() if descriptor is None else (descriptor,),
        )
        try:
            child.wait(timeout=timeout)
            timed_out = False
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
            reap_descendants()
        stdout.seek(0)
        stderr.seek(0)
        out, err = stdout.read(FILE_CAP + 1), stderr.read(FILE_CAP + 1)
    if max(len(out), len(err)) > FILE_CAP:
        raise RuntimeError("Output exceeded the enforced file-size limit")
    return SimpleNamespace(returncode=child.returncode, stdout=out, stderr=err, timed_out=timed_out)


def check(result, label):
    if result.timed_out or result.returncode != 0:
        raise RuntimeError(f"{label}: exit={result.returncode}, timeout={result.timed_out}, "
                           f"stderr={result.stderr[:2000].decode(errors='replace')}")
    return result


def normalize(pipeline, source):
    def compiler_run(args, *, input, **_):
        completed = check(run(args, data=input.encode()), "Pass 0 preprocessing")
        return SimpleNamespace(returncode=0, stdout=completed.stdout.decode())

    preprocess = pipeline.preprocess_pass_zero
    # The frozen function catches exceptions. Record any compiler failure so
    # fallback text can never silently enter this run.
    failed = []

    def tracked_compiler(*args, **kwargs):
        try:
            return compiler_run(*args, **kwargs)
        except (RuntimeError, UnicodeError, OSError) as exc:
            failed.append(exc)
            raise

    bounded = FunctionType(preprocess.__code__, {
        **preprocess.__globals__, "subprocess": SimpleNamespace(run=tracked_compiler),
    }, argdefs=preprocess.__defaults__)
    expanded, aliases = bounded(source)
    if failed:
        raise failed[0]
    normalized = pipeline.normalize_synthetic_braces(expanded)
    if pipeline.parser.parse(normalized.encode()).root_node.has_error:
        raise RuntimeError("Normalized source contains a tree-sitter error")
    return normalized, aliases


def instrument(pipeline, source, nodes):
    tree = pipeline.parser.parse(source.encode())
    main = [n for n in tree.root_node.named_children if n.type == "function_definition"
            and n.child_by_field_name("declarator").child_by_field_name("declarator").text == b"main"]
    if len(main) != 1:
        raise ValueError("Expected one top-level main")
    position = main[0].child_by_field_name("body").start_byte + 1
    frozen = pipeline.instrument_cpp_source

    def add_main_init(code, edits):
        return pipeline.apply_reverse_byte_edits(code, edits + [(position, position, "\n__eapg_init();\n")])

    instrumenter = FunctionType(frozen.__code__, {
        **frozen.__globals__, "apply_reverse_byte_edits": add_main_init,
    })
    text = instrumenter(source, nodes)
    start = text.index("static void __eapg_dump_and_exit")
    end = text.index("#define __EAPG_TICK", start)
    text = text[:start] + f"""
static pid_t __eapg_owner = 0;
static FILE* __eapg_stream = nullptr;
static void __eapg_emit(int breached) {{
    if (getpid() != __eapg_owner || !__eapg_stream) return;
    FILE* stream = __eapg_stream;
    __eapg_stream = nullptr;
    bool ok = std::fprintf(stream, "{{\\"status\\":\\"%s\\",\\"total_ticks\\":%llu,\\"nodes\\":{{",
        breached ? "CAP_BREACHED" : "CLEAN_COMPLETION", __eapg_ticks) >= 0;
    for (int i = 0; i < {len(nodes)} && ok; ++i) {{
        ok = std::fprintf(stream, "%s\\"N%d\\":{{\\"cnt\\":%llu,\\"work\\":%llu}}",
            i ? "," : "", i + 1, __eapg_cnt[i], __eapg_work[i]) >= 0;
    }}
    if (ok) ok = std::fprintf(stream, "}}}}\\n") >= 0;
    if (std::fclose(stream) != 0 || !ok) std::_Exit(98);
}}
static void __eapg_normal_exit() {{ __eapg_emit(0); }}
static void __eapg_dump_and_exit(int breached) {{
    __eapg_emit(breached);
    std::_Exit(97);
}}
static void __eapg_init() {{
    __eapg_owner = getpid();
    const char* fd_text = std::getenv("EAPG_COUNTER_FD");
    if (!fd_text) std::_Exit(98);
    int original = std::atoi(fd_text);
    int fd = fcntl(original, F_DUPFD_CLOEXEC, 64);
    close(original);
    if (fd < 0) std::_Exit(98);
    __eapg_stream = fdopen(fd, "w");
    if (!__eapg_stream || std::atexit(__eapg_normal_exit) != 0) std::_Exit(98);
    const char* n_text = std::getenv("EAPG_N");
    if (n_text) {{
        unsigned long long n = std::strtoull(n_text, nullptr, 10);
        unsigned long long cap = 5ULL * n * n;
        if (cap > __eapg_cap) __eapg_cap = cap;
    }}
}}

""" + text[end:]
    return "#include <unistd.h>\n#include <fcntl.h>\n" + text


def compile_cpp(source, path, *flags):
    check(run(["g++", "-std=c++17", "-O2", *flags, "-x", "c++", "-", "-o", str(path)],
              data=source.encode(), timeout=25), f"Compile {path.name}")


def strict_object(items):
    result = dict(items)
    if len(result) != len(items):
        raise ValueError("Duplicate keys in the counter record")
    return result


def run_profile(path, data, n, nodes, cap):
    with TemporaryFile() as channel:
        descriptor = channel.fileno()
        result = run([str(path)], data=data, descriptor=descriptor,
                     extra_env={"EAPG_COUNTER_FD": str(descriptor), "EAPG_N": str(n)})
        channel.seek(0)
        wire = channel.read(65_537)
    if result.timed_out or result.returncode not in (0, 97):
        raise ValueError(f"Instrumented execution failed: exit={result.returncode}, timeout={result.timed_out}")
    if not wire or len(wire) > 65_536 or wire.count(b"\n") != 1 or not wire.endswith(b"\n"):
        raise ValueError("Missing, oversized, or repeated counter record")
    record = json.loads(wire, object_pairs_hook=strict_object)
    expected_status = "CLEAN_COMPLETION" if result.returncode == 0 else "CAP_BREACHED"
    if set(record) != {"status", "total_ticks", "nodes"} or record["status"] != expected_status:
        raise ValueError("Counter record and process status disagree")
    if set(record["nodes"]) != {node["id"] for node in nodes}:
        raise ValueError("Counter record does not match the macro-node set")
    for counters in record["nodes"].values():
        if set(counters) != {"cnt", "work"} or any(type(n) is not int or n < 0 for n in counters.values()):
            raise ValueError("Invalid counter values")
    total = sum(counters["work"] for counters in record["nodes"].values())
    if type(record["total_ticks"]) is not int or record["total_ticks"] != total or (total < cap) != (result.returncode == 0):
        raise ValueError("Counter totals disagree with the tick ceiling")
    return result, record


def verify_gate(pipeline, work):
    if os.getuid() == 0 or any(Path(p).exists() for p in ("/mnt/c", "/mnt/d", "/init", "/etc/shadow")):
        raise RuntimeError("Host filesystem or elevated UID exposed")
    with socket.socket() as sock:
        sock.settimeout(0.3)
        if sock.connect_ex(("198.51.100.1", 443)) == 0:
            raise RuntimeError("Unexpected external network reachability")
    interfaces = Path("/proc/net/dev").read_text().splitlines()[2:]
    if {line.split(":")[0].strip() for line in interfaces} != {"lo"}:
        raise RuntimeError("Unexpected network interface in the namespace")
    storage = os.statvfs("/tmp")
    if storage.f_blocks * storage.f_frsize > 64 * 1024**2:
        raise RuntimeError("Private scratch exceeds its size bound")
    if run(["g++", "-E", "-x", "c++", "-"], data=b'#include "/mnt/c/Windows/System32/drivers/etc/hosts"\n').returncode == 0:
        raise RuntimeError("Preprocessor reached a host path")
    if not os.statvfs("/usr").f_flag & os.ST_RDONLY:
        raise RuntimeError("Toolchain mount is writable")
    memory = run(["python3", "-c", "import mmap; mmap.mmap(-1, 600*1024**2)"])
    if memory.returncode == 0 or b"Cannot allocate memory" not in memory.stderr:
        raise RuntimeError("Address-space limit probe failed")
    flood = run(["python3", "-c", "import os; [os.write(1,b'x'*65536) for _ in range(256)]"])
    if flood.returncode == 0 or len(flood.stdout) != FILE_CAP:
        raise RuntimeError("Output-bound probe failed")
    tree = run(["python3", "-c", "import os,time\np=os.fork()\n"
                "if p: print(p,flush=True)\nelse: os.setsid()\ntime.sleep(30)"], timeout=0.5)
    if not tree.timed_out:
        raise RuntimeError("Process-tree probe did not time out")
    child = Path("/proc") / str(int(tree.stdout))
    for _ in range(30):
        if not child.exists():
            break
        time.sleep(0.05)
    if child.exists():
        raise RuntimeError("Timed-out subprocess left a child")
    return {
        "uid": os.getuid(), "network": "loopback-only", "host_mounts": "unreachable",
        "preprocessor_host_include": "denied", "toolchain": "read-only", "scratch_bytes": 64 * 1024**2,
        "per_process_address_space_probe": "denied", "output_bound_bytes": len(flood.stdout),
        "process_tree_timeout": "zero surviving child processes",
        "counter_fixtures": verify_transport(pipeline, work),
    }


def verify_transport(pipeline, work):
    fixtures = {
        "early_return": ("if (true) return 0; return 1;", "CLEAN_COMPLETION"),
        "helper_exit": ("finish();", "CLEAN_COMPLETION"),
        "fork_owner": ("if (fork() == 0) std::exit(0); int status; wait(&status); return 0;", "CLEAN_COMPLETION"),
        "tick_cap": ("for (;;) { int i = 0; i++; }", "CAP_BREACHED"),
        "closed_descriptor": ("close(64); return 0;", "reject"),
        "duplicate_record": ('write(64, "{}\\n", 3); return 0;', "reject"),
        "forged_stdout_and_stderr": ('puts("{}"); fputs("{}\\n", stderr); std::abort();', "reject"),
        "abnormal_exit": ("std::_Exit(0);", "reject"),
    }
    outcomes = {}
    for name, (body, expected) in fixtures.items():
        code = "#include <unistd.h>\n#include <sys/wait.h>\n#include <cstdlib>\n#include <cstdio>\n"
        if name == "helper_exit":
            code += "void finish() { std::exit(0); }\n"
        source, aliases = normalize(pipeline, code + "int main() {" + body + "}\n")
        nodes = pipeline.extract_macro_nodes(source, aliases)
        binary = work / name
        compile_cpp(instrument(pipeline, source, nodes), binary)
        try:
            _, record = run_profile(binary, b"", 1, nodes, pipeline.compute_tick_ceiling(1))
            outcome = record["status"]
        except ValueError:
            outcome = "reject"
        if outcome != expected:
            raise RuntimeError(f"Counter fixture {name}: expected {expected}, saw {outcome}")
        outcomes[name] = outcome
    return outcomes


def oracle_output(result, case, label):
    check(result, label)
    if result.stdout.split() != case["expected_stdout"].encode().split():
        raise RuntimeError(f"{label}: stdout differs from the independent oracle")


def profile_side(pipeline, source, cases, work):
    normalized, aliases = normalize(pipeline, source)
    nodes = pipeline.extract_macro_nodes(normalized, aliases)
    binary = work / "program"
    for mode, flags in (("original", ()), ("sanitizer", ("-fsanitize=undefined", "-fno-sanitize-recover=undefined"))):
        compile_cpp(source, binary, *flags)
        for case in cases:
            result = run([str(binary)], data=case["stdin"].encode())
            oracle_output(result, case, f"{mode}, N={case['n']}, seed={case['seed']}")
        binary.unlink()

    compile_cpp(instrument(pipeline, normalized, nodes), binary)
    traces = defaultdict(list)
    for case in cases:
        n, seed = case["n"], case["seed"]
        result, record = run_profile(binary, case["stdin"].encode(), n, nodes, pipeline.compute_tick_ceiling(n))
        if record["status"] == "CLEAN_COMPLETION":
            oracle_output(result, case, f"instrumented, N={n}, seed={seed}")
        traces[seed].append({"n": n, "returncode": result.returncode,
                             "stdout": result.stdout.decode(), **record})
    binary.unlink()

    fits = {}
    for seed, rows in traces.items():
        clean = [row for row in rows if row["status"] == "CLEAN_COMPLETION"]
        if len(clean) < 4 or clean[-1]["n"] < 8 * clean[0]["n"]:
            raise RuntimeError(f"Insufficient clean scaling sizes for seed {seed}")
        sizes = [row["n"] for row in clean]
        fits[seed] = {
            node["id"]: {
                channel: pipeline.fit_dual_family_scaling(sizes, [row["nodes"][node["id"]][key] for row in clean])
                for channel, key in (("fit_hits", "cnt"), ("fit_work", "work"))
            }
            for node in nodes
        }
    return {"nodes": nodes, "fits": fits, "runs": traces, "normalized_sha256": sha(normalized.encode()),
            "plain_oracle_checks": len(cases), "sanitizer_oracle_checks": len(cases)}


def inside(probes_only):
    import pipeline

    if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise OSError(ctypes.get_errno(), "Could not enable descendant reaping")
    with TemporaryDirectory(dir="/tmp") as directory:
        work = Path(directory)
        gate = verify_gate(pipeline, work)
        print("Linux isolation and counter fixtures passed", file=sys.stderr, flush=True)
        if probes_only:
            return {"gate": gate}
        payload = json.load(sys.stdin)
        cases = payload["workload"]["inputs"]
        slow_source, fast_source = payload["slow"], payload["fast"]
        slow = profile_side(pipeline, slow_source, cases, work)
        fast = profile_side(pipeline, fast_source, cases, work)
    slices = {}
    for seed, fits in slow["fits"].items():
        nodes = slow["nodes"]
        result = pipeline.evaluate_four_slicing_tiers(nodes, fits)
        candidates = result["c_pruned"]
        if candidates:
            dynamics = pipeline.analyze_eapg_slicing(nodes, fits)
            dynamics["c_slice"] = candidates
            dynamics["r_search"] = 1 - len(candidates) / len(nodes)
            skeleton = pipeline.format_eapg_skeleton(nodes, fits, dynamics)
            record = {"skeleton": skeleton, "slicing": result, "slow_code": slow_source,
                      "pilot_revision": pipeline.PILOT_REVISION}
            result["ranked_candidates"] = pipeline.rank_candidates_by_role_priority(record, use_loop_def_use=True)
        else:
            result["ranked_candidates"] = []
        slices[seed] = result
    return {"gate": gate, "compiler": check(run(["g++", "--version"]), "compiler version").stdout.decode().splitlines()[0],
            "python": sys.version.split()[0],
            "parser": {package: version(package) for package in ("tree-sitter", "tree-sitter-cpp")},
            "slow": slow, "fast": fast, "slices_by_seed": slices}


def development_payload():
    workload_bytes = (HERE / "development_workload.json").read_bytes()
    workload = json.loads(workload_bytes)
    raw = (HERE / "pie_val.jsonl").read_bytes()
    if sha(raw) != VAL_SHA:
        raise ValueError("PIE validation release hash mismatch")
    row, = [row for line in raw.splitlines() if line.strip() and
            (row := json.loads(line))["problem_id"] == workload["problem_id"] and
            (row["src_id"], row["tgt_id"]) == (workload["slow_submission_id"], workload["fast_submission_id"])]
    for side, key in (("slow", "src_code"), ("fast", "tgt_code")):
        if sha(row[key].encode()) != workload[f"{side}_sha256"]:
            raise ValueError(f"Registered {side} source hash mismatch")
    return workload_bytes, {"workload": workload, "slow": row["src_code"], "fast": row["tgt_code"]}


def guest_launcher(stage, deps, probes_only, data):
    env = os.environ.copy()
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    unit = f"eapg-development-{os.getpid()}.scope"
    verify_scope = (
        'set -eu; scope=$(cut -d: -f3 /proc/self/cgroup); dir=/sys/fs/cgroup$scope; '
        'test "$(cat "$dir/memory.max")" = 805306368; '
        'test "$(cat "$dir/pids.max")" = 24; '
        'read quota period < "$dir/cpu.max"; test "$quota" = "$period"; '
        'exec "$@"'
    )
    args = [
        "systemd-run", "--user", "--scope", "--quiet", f"--unit={unit}",
        "--property=MemoryMax=768M", "--property=TasksMax=24", "--property=CPUQuota=100%",
        "/bin/sh", "-c", verify_scope, "eapg-scope",
        "bwrap", "--unshare-all", "--unshare-user", "--disable-userns", "--die-with-parent", "--new-session",
        "--cap-drop", "ALL", "--clearenv",
        "--setenv", "PATH", "/usr/bin:/bin", "--setenv", "LANG", "C.UTF-8",
        "--setenv", "PYTHONPATH", "/deps:/job", "--setenv", "TMPDIR", "/tmp",
        "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib",
        "--symlink", "usr/lib64", "/lib64", "--proc", "/proc", "--dev", "/dev",
        "--size", str(64 * 1024**2), "--tmpfs", "/tmp", "--chdir", "/tmp",
        "--ro-bind", str(stage), "/job", "--ro-bind", str(deps), "/deps",
        "--", "python3", "-B", "/job/run_development.py", "--inside",
    ]
    if probes_only:
        args.append("--probes-only")
    try:
        return subprocess.run(args, input=data, stdout=subprocess.PIPE, env=env,
                              timeout=180, check=True).stdout
    finally:
        subprocess.run(["systemctl", "--user", "stop", unit], env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probes-only", action="store_true")
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.inside:
        print(json.dumps(inside(args.probes_only)))
        return
    if sys.platform != "linux" or os.getuid() == 0:
        parser.error("Run as an unprivileged Linux user")
    pipeline = HERE.parent.parent / "pipeline.py"
    if sha(pipeline.read_bytes()) != PIPELINE_SHA:
        raise ValueError("Frozen pipeline hash mismatch")
    output = HERE / "development_results.json"
    if not args.probes_only and output.exists():
        raise FileExistsError(output)
    deps = Path.home() / ".local/share/eapg-phase2/deps"
    if not all((deps / module).is_dir() for module in ("tree_sitter", "tree_sitter_cpp")):
        raise RuntimeError(f"Install the pinned Linux parser wheels under {deps}")
    workload_bytes, payload = (b"", {}) if args.probes_only else development_payload()
    with TemporaryDirectory(prefix="eapg-dev-") as directory:
        stage = Path(directory)
        shutil.copyfile(pipeline, stage / "pipeline.py")
        shutil.copyfile(__file__, stage / "run_development.py")
        result = json.loads(guest_launcher(stage, deps, args.probes_only, json.dumps(payload).encode()))
    if args.probes_only:
        print(json.dumps(result["gate"], indent=2))
        return
    result.update({
        "study": "PIE validation feasibility, development only",
        "workload_sha256": sha(workload_bytes), "validation_sha256": VAL_SHA, "pipeline_sha256": PIPELINE_SHA,
        "runner_sha256": sha(Path(__file__).read_bytes()),
        "sandbox_limits": {"cgroup_memory_bytes": 768 * 1024**2, "cgroup_tasks": 24, "cgroup_cpu_quota": "100%",
                           "run_wall_seconds": 12, "compile_wall_seconds": 25, "file_bytes": FILE_CAP},
        "case": {key: value for key, value in payload["workload"].items() if key != "inputs"},
    })
    with output.open("x", encoding="utf-8") as file:
        json.dump(result, file, indent=2)
        file.write("\n")
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
