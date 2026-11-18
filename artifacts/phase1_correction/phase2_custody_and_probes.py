"""Build provisional Phase 2 custody manifests and verify local fixtures."""

import argparse
import ast
from collections import defaultdict
import ctypes
from dataclasses import dataclass
import hashlib
from importlib.metadata import version
import inspect
import json
from pathlib import Path
import random
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Event, Lock, Thread
import time
from types import FunctionType

from tree_sitter import Language, Parser
import tree_sitter_cpp


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PILOT = HERE.parent / "scope_isolated_pilot/pilot100_results.json"
PILOT_SHA = "4a3b563cdd54c471f39df95e7d40ec3ae5433259795cadcde80272955ea44cb5"
PARSER = Parser(Language(tree_sitter_cpp.language()))
SCHEMA = "phase2-static-custody-v2"
KEYWORDS = frozenset("""
alignas alignof asm auto bool break case catch char char16_t char32_t class const
constexpr const_cast continue decltype default delete do double dynamic_cast else
enum explicit export extern false float for friend goto if inline int long mutable
namespace new noexcept nullptr operator private protected public register
reinterpret_cast return short signed sizeof static static_assert static_cast
struct switch template this thread_local throw true try typedef typeid typename
union unsigned using virtual void volatile wchar_t while and or not xor bitand
bitor compl and_eq not_eq or_eq xor_eq
""".split())
STL_NAMES = frozenset("""
std cin cout cerr endl vector map set unordered_map unordered_set multiset
priority_queue queue deque stack string pair tuple array sort stable_sort lower_bound
upper_bound binary_search find count reverse accumulate min max min_element
max_element push_back emplace_back insert erase begin end size empty clear resize assign main
""".split())
# Consume string/character literals before comments. Keep unmatched symbols as tokens.
LEX = re.compile(
    r'(?P<raw>(?:u8|u|U|L)?R"(?P<delimiter>[^ ()\\\t\r\n]{0,16})\(.*?\)(?P=delimiter)")'
    r"""|(?P<quoted>(?:u8|u|U|L)?(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'))"""
    r"|(?P<comment>//(?:\\\r?\n|[^\r\n])*|/\*.*?\*/)"
    r"|(?P<num>(?:[0-9]|\.[0-9])(?:[eEpP][+-]|[\w.'])*)(?!\w)"
    r"|(?P<id>[^\W\d]\w*)"
    r"|(?P<op>::|->\*|->|<<=|>>=|<=>|<<|>>|==|!=|<=|>=|&&|\|\||\+\+|--|[+\-*/%&|^]=|\S)",
    re.DOTALL,
)
ID_NODES = {"identifier", "type_identifier", "field_identifier", "namespace_identifier"}


def sha(data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def tokens(code, normalized=False):
    result = []
    for token in LEX.finditer(code):
        kind, value = token.lastgroup, token.group()
        if kind == "comment":
            continue
        if normalized and kind == "num":
            value = "<NUM>"
        if normalized and kind == "id" and value not in KEYWORDS | STL_NAMES:
            value = "<ID>"
        result.append(value)
    return result


def source_key(code):
    # Include physical line boundaries when preprocessing can give them meaning.
    if "#" not in code:
        return sha(json_bytes(tokens(code)))
    parts, end = [], 0
    for token in LEX.finditer(code):
        if token.lastgroup == "comment":
            continue
        if "\n" in code[end:token.start()]:
            parts.append("<NEWLINE>")
        parts.append(token.group())
        end = token.end()
    return sha(json_bytes(parts))


def walk(node):
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


def fingerprints(code, pilot=False):
    raw = code.encode("utf-8")
    root = PARSER.parse(raw).root_node
    if root.has_error:
        return {"lex:" + sha(json_bytes(tokens(code, normalized=True)))}, "lexer"

    def spelling(node):
        return raw[node.start_byte:node.end_byte].decode("utf-8")

    def serialize(node, strip_guard=False):
        if node.type == "comment":
            return None
        if strip_guard and node.type == "if_statement":
            parts = tokens(spelling(node))
            if len(parts) == 11 and parts[:5] == ["if", "(", "!", "read_problem_size", "("] and parts[6:] == [")", ")", "return", "0", ";"]:
                return None
        if node.type == "number_literal":
            return [node.type, "<NUM>"]
        if node.type in ID_NODES:
            value = spelling(node)
            # Preserve all explicitly std-qualified names, including APIs outside the allowlist.
            parent = node.parent
            qualified = parent and parent.type == "qualified_identifier" and spelling(parent).startswith("std::")
            return [node.type, value if qualified or value in STL_NAMES else "<ID>"]
        if not node.child_count:
            return [node.type, spelling(node)]
        return [node.type, [part for child in node.children if (part := serialize(child, strip_guard)) is not None]]

    result = {"unit:" + sha(json_bytes(serialize(root)))}
    for node in walk(root):
        if node.type != "function_definition":
            continue
        declarator = node.child_by_field_name("declarator")
        names = tokens(spelling(declarator)) if declarator else []
        if pilot and names[:2] == ["read_problem_size", "("]:
            continue
        result.add("function:" + sha(json_bytes(serialize(node))))
        body = node.child_by_field_name("body")
        if body:
            result.add("body:" + sha(json_bytes(serialize(body))))
            if pilot and names[:2] == ["main", "("]:
                result.add("body:" + sha(json_bytes(serialize(body, strip_guard=True))))
    return result, "ast"


@dataclass(frozen=True)
class Pair:
    pair_id: str
    problem_id: str
    slow_code: str
    fast_code: str
    slow_sub_id: str = ""
    fast_sub_id: str = ""
    aliases: tuple = ()


def load_pilot():
    content = PILOT.read_bytes()
    if sha(content) != PILOT_SHA:
        raise ValueError("Frozen pilot SHA-256 mismatch")
    return [Pair(**{key: row[key] for key in ("pair_id", "problem_id", "slow_code", "fast_code")}) for row in json.loads(content)]


def draw_pairs(rows):
    rng = random.Random(42)
    by_problem = defaultdict(list)
    for row in rows:
        by_problem[row.problem_id].append(row)
    problems = sorted(by_problem)
    rng.shuffle(problems)
    selected, ledger = [], []
    for problem in problems:
        candidates = sorted(by_problem[problem], key=lambda row: row.pair_id)
        unique = {}
        for row in candidates:
            unique.setdefault(source_key(row.slow_code), row)
        draw = rng.sample(list(unique.values()), min(4, len(unique)))
        selected.extend(draw)
        ledger.append({"problem_id": problem, "available": len(candidates), "distinct_slow_sources": len(unique),
                       "drawn_pair_ids": [row.pair_id for row in draw]})
    return selected, ledger


def quarantine(test, pilot):
    records = [(row, True) for row in test] + [(row, False) for row in pilot]
    if len({row.pair_id for row, _ in records}) != len(records):
        raise ValueError("Duplicate pair IDs across the test and pilot inputs")
    parents = list(range(len(records)))
    owners, features, modes = {}, [], {}

    def find(idx):
        while parents[idx] != idx:
            parents[idx] = parents[parents[idx]]
            idx = parents[idx]
        return idx

    for idx, (row, is_test) in enumerate(records):
        keys = {f"problem:{pid}" for pid in (row.problem_id, *row.aliases) if pid}
        keys |= {f"submission:{sid}" for sid in (row.slow_sub_id, row.fast_sub_id) if sid}
        modes[row.pair_id] = {}
        for side in ("slow", "fast"):
            code = getattr(row, f"{side}_code")
            structural, mode = fingerprints(code, pilot=not is_test)
            modes[row.pair_id][side] = mode
            keys |= structural | {"source:" + source_key(code)}
        features.append(keys)
        for key in sorted(keys):
            other = find(owners.setdefault(key, idx))
            root = find(idx)
            parents[max(root, other)] = min(root, other)

    components = defaultdict(list)
    for idx in range(len(records)):
        components[find(idx)].append(idx)
    groups, removed, retained = {}, [], []
    for members in components.values():
        test_ids = sorted(records[idx][0].pair_id for idx in members if records[idx][1])
        pilot_ids = sorted(records[idx][0].pair_id for idx in members if not records[idx][1])
        if test_ids:
            groups[f"G_TEST_{len(groups) + 1:02d}"] = test_ids
            removed.extend(pilot_ids)
        else:
            retained.extend(pilot_ids)
    test_keys = set().union(*(keys for keys, (_, is_test) in zip(features, records) if is_test))
    retained_ids = set(retained)
    retained_keys = set().union(*(keys for keys, (row, _) in zip(features, records) if row.pair_id in retained_ids))
    if test_keys & retained_keys:
        raise RuntimeError("Unresolved static quarantine overlap")
    return {"test_groups": groups, "removed_pilot_pair_ids": sorted(removed),
            "retained_pilot_pair_ids": sorted(retained), "fingerprint_modes": modes,
            "verified_zero_static_overlap": True, "final_prompt_quarantine": "pending"}


def read_frame(path, expected_sha):
    content = path.read_bytes()
    if sha(content) != expected_sha:
        raise ValueError("Frame SHA-256 mismatch")
    frame = json.loads(content)
    if not all(isinstance(frame.get(key), str) and frame[key] for key in ("release", "usage_terms")):
        raise ValueError("Frame must identify the release and usage terms")
    pairs, tests = [], {}
    for row in frame["pairs"]:
        if row.get("split") != "test":
            raise ValueError("Every frame row must belong to the official test split")
        pair = Pair(**{key: row[key] for key in Pair.__dataclass_fields__ if key in row})
        for value in (pair.pair_id, pair.problem_id, pair.slow_code, pair.fast_code):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Pair IDs, problem IDs, and both sources must be nonempty strings")
        if not isinstance(pair.aliases, (list, tuple)) or not isinstance(row["test_indices"], list):
            raise ValueError("Expected arrays for aliases and test indices")
        for identifier in (pair.slow_sub_id, pair.fast_sub_id, *pair.aliases):
            if not isinstance(identifier, str):
                raise ValueError("Submission identifiers and aliases must be strings")
        if not all(type(idx) is int and idx >= 0 for idx in row["test_indices"]):
            raise ValueError("Test indices must be nonnegative integers")
        if pair.pair_id in tests:
            raise ValueError(f"Duplicate pair ID {pair.pair_id}")
        tests[pair.pair_id] = row["test_indices"]
        pairs.append(pair)
    if not pairs or len({pair.problem_id for pair in pairs}) != 41:
        raise ValueError("Expected all 41 problems from the pinned PIE test frame")
    return frame, pairs, tests


def write_manifest(path, expected_sha, destination):
    frame, pairs, tests = read_frame(path, expected_sha)
    draw, ledger = draw_pairs(pairs)
    manifest = {
        "schema": SCHEMA, "stage": "provisional static quarantine", "release": frame["release"],
        "usage_terms": frame["usage_terms"], "frame_sha256": expected_sha, "pilot_sha256": PILOT_SHA,
        "runner_sha256": sha(Path(__file__).read_bytes()), "python": sys.version.split()[0],
        "rng": "Python random.Random (MT19937)", "seed": 42,
        "parser_versions": {package: version(package) for package in ("tree-sitter", "tree-sitter-cpp")},
        "problem_ledger": ledger, "pairs": [
            {"pair_id": row.pair_id, "problem_id": row.problem_id, "slow_sub_id": row.slow_sub_id,
             "fast_sub_id": row.fast_sub_id, "aliases": row.aliases, "slow_sha256": sha(row.slow_code),
             "slow_source_key": source_key(row.slow_code),
             "fast_sha256": sha(row.fast_code), "test_indices": tests[row.pair_id]}
            for row in draw
        ],
        "quarantine": quarantine(draw, load_pilot()),
    }
    with destination.open("x", encoding="utf-8") as stream:
        json.dump({"manifest": manifest, "manifest_sha256": sha(json_bytes(manifest))}, stream, indent=2)
        stream.write("\n")


def traced_normalization(pipeline, expanded):
    """Record the actual frozen Pass-1 edit sequence and each original byte."""
    origin = list(range(len(expanded.encode("utf-8"))))

    def trace(source, edits):
        raw = source.encode("utf-8")
        for start, end, replacement in sorted(edits, key=lambda edit: edit[0], reverse=True):
            original = raw[start:end]
            wrapped = replacement.encode("utf-8")
            if wrapped != b"{\n    " + original + b"\n}":
                raise ValueError("Unexpected frozen Pass-1 edit")
            origin[start:end] = [None] * 6 + origin[start:end] + [None] * 2
        return pipeline.apply_reverse_byte_edits(source, edits)

    normalize = pipeline.normalize_synthetic_braces
    traced = FunctionType(normalize.__code__, {**normalize.__globals__, "apply_reverse_byte_edits": trace})
    normalized = traced(expanded)
    if normalized != normalize(expanded) or len(origin) != len(normalized.encode("utf-8")):
        raise ValueError("Pass-1 provenance did not match the frozen normalizer")
    return normalized, origin


def spanned_nodes(pipeline, normalized, aliases):
    """Expose byte spans at the frozen extractor's four node-emission sites."""
    fn = pipeline.extract_macro_nodes
    source = ast.parse(inspect.getsource(fn))

    class Spans(ast.NodeTransformer):
        count = 0

        def visit_Dict(self, node):
            self.generic_visit(node)
            keys = {key.value for key in node.keys if isinstance(key, ast.Constant)}
            if {"id", "role", "insert_pos"} <= keys:
                node.keys.append(ast.Constant("normalized_span"))
                node.values.append(ast.parse("(n.start_byte, n.end_byte)", mode="eval").body)
                self.count += 1
            return node

    transformer = Spans()
    transformer.visit(source)
    if transformer.count != 4:
        raise ValueError("Unexpected frozen Pass-2 node-emission sites")
    namespace = dict(fn.__globals__)
    exec(compile(ast.fix_missing_locations(source), str(ROOT / "pipeline.py"), "exec"), namespace)
    with_spans = namespace[fn.__name__](normalized, aliases)
    base = [{key: value for key, value in row.items() if key != "normalized_span"} for row in with_spans]
    if base != fn(normalized, aliases):
        raise ValueError("Pass-2 map did not match the scoring extractor")
    return with_spans


def raw_line_map(raw, expanded):
    # Match the frozen Pass-0 include split exactly, then align the marker pass
    # only when its nonblank lines match the authoritative expansion.
    if re.search(r"^\s*#\s*(?:line\b|\d)", raw, re.MULTILINE):
        return {}, "unresolved"
    includes, other = [], []
    for number, line in enumerate(raw.splitlines(), 1):
        (includes if re.match(r"^\s*#\s*include\b", line) else other).append((number, line))
    marked = subprocess.run(
        ["g++", "-E", "-x", "c++", "-"], input="\n".join(line for _, line in other),
        text=True, capture_output=True, timeout=10, check=True,
    ).stdout
    line_number, file_name = 1, "<stdin>"
    matched = [(line, number) for number, line in includes if line.strip()]
    for line in marked.splitlines():
        marker = re.match(r'^#\s+(\d+)\s+"([^"]+)"', line)
        if marker:
            line_number, file_name = int(marker[1]), marker[2]
            continue
        if line.strip():
            original = other[line_number - 1][0] if file_name == "<stdin>" and 1 <= line_number <= len(other) else None
            matched.append((line, original))
        line_number += 1
    lines = [(i, line) for i, line in enumerate(expanded.splitlines(), 1) if line.strip()]
    if [line for _, line in lines] != [line for line, _ in matched]:
        return {}, "unresolved"
    return {i: original for (i, _), (_, original) in zip(lines, matched) if original is not None}, "aligned"


def local_pass2_map():
    """Run the exact frozen path on the built-in fixture only."""
    raw = """#include <iostream>
#define REP(i, n) for (int i = 0; i < (n); ++i)
int main() {
    int n = 10;
    int total = 0;
    REP(i, n)
        if (i > 0) total += i;
        else total -= i;
    return total;
}
"""
    sys.path.insert(0, str(ROOT))
    import pipeline

    expanded, aliases = pipeline.preprocess_pass_zero(raw)
    normalized, origin = traced_normalization(pipeline, expanded)
    if not pipeline.verify_cpp_syntax(normalized):
        raise ValueError("Normalized fixture failed C++ syntax validation")
    normalized_bytes, expanded_bytes = normalized.encode("utf-8"), expanded.encode("utf-8")
    line_map, alignment = raw_line_map(raw, expanded)
    raw_lines = raw.splitlines()
    macro_names = set(re.findall(r"^\s*#\s*define\s+([A-Za-z_]\w*)", raw, re.MULTILINE))
    rows = []
    for row in spanned_nodes(pipeline, normalized, aliases):
        start, end = row["normalized_span"]
        span = origin[start:end]
        originals = [offset for offset in span if offset is not None]
        first, last = originals[0], originals[-1]
        pre_brace_lines = range(expanded_bytes.count(b"\n", 0, first) + 1,
                                expanded_bytes.count(b"\n", 0, last) + 2)
        raw_numbers = sorted({line_map[number] for number in pre_brace_lines if number in line_map})
        # GCC line markers locate source lines. Identifiers on those lines
        # provide invocation evidence, not a nested token-level expansion trace.
        macro_evidence = macro_names & {token for number in raw_numbers for token in tokens(raw_lines[number - 1])}
        rows.append({
            "node_id": row["id"], "role": row["role"], "normalized_byte_span": [start, end],
            "normalized_line_span": [normalized_bytes.count(b"\n", 0, start) + 1,
                                     normalized_bytes.count(b"\n", 0, end - 1) + 1],
            "pre_brace_byte_span": [first, last + 1], "raw_source_lines": raw_numbers,
            "macro_invocation_evidence": sorted(macro_evidence), "has_synthetic_braces": None in span,
        })
    return {"normalized_source_sha256": sha(normalized_bytes), "line_alignment": alignment, "nodes": rows}


class WindowsProbeJob:
    """A Windows Job Object for the built-in fixtures, not an external sandbox."""

    def __init__(self):
        from ctypes import wintypes

        dword, size, ticks = wintypes.DWORD, ctypes.c_size_t, ctypes.c_longlong

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("process_time", ticks), ("job_time", ticks), ("flags", dword),
                ("min_working_set", size), ("max_working_set", size), ("processes", dword),
                ("affinity", size), ("priority", dword), ("scheduling", dword),
            ]

        class Limits(ctypes.Structure):
            _fields_ = [
                ("basic", BasicLimits), ("io_counters", ctypes.c_uint64 * 6),
                ("process_memory", size), ("job_memory", size),
                ("peak_process_memory", size), ("peak_job_memory", size),
            ]

        class Accounting(ctypes.Structure):
            _fields_ = [
                ("time", ticks * 4), ("page_faults", dword), ("total", dword),
                ("active", dword), ("terminated", dword),
            ]

        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        handle, boolean, pointer = wintypes.HANDLE, wintypes.BOOL, ctypes.c_void_p
        signatures = {
            "CreateJobObjectW": (handle, [pointer, wintypes.LPCWSTR]),
            "SetInformationJobObject": (boolean, [handle, ctypes.c_int, pointer, dword]),
            "QueryInformationJobObject": (boolean, [handle, ctypes.c_int, pointer, dword, pointer]),
            "OpenProcess": (handle, [dword, boolean, dword]),
            "AssignProcessToJobObject": (boolean, [handle, handle]),
            "TerminateJobObject": (boolean, [handle, ctypes.c_uint]),
            "CloseHandle": (boolean, [handle]),
        }
        for name, (restype, argtypes) in signatures.items():
            function = getattr(self.api, name)
            function.restype, function.argtypes = restype, argtypes
        self.accounting = Accounting()
        self.handle = self.checked(self.api.CreateJobObjectW(None, None))
        limits = Limits()
        limits.basic.flags = 0x4 | 0x8 | 0x200 | 0x2000  # CPU, process count, memory, kill-on-close
        limits.basic.job_time = 30_000_000  # three seconds in 100 ns ticks
        limits.basic.processes = 4
        limits.job_memory = 256 * 1024**2
        try:
            self.checked(self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
        except OSError:
            self.api.CloseHandle(self.handle)
            raise

    @staticmethod
    def checked(result):
        if not result:
            raise ctypes.WinError(ctypes.get_last_error())
        return result

    def assign(self, pid):
        process = self.checked(self.api.OpenProcess(0x0101, False, pid))  # SET_QUOTA | TERMINATE
        try:
            self.checked(self.api.AssignProcessToJobObject(self.handle, process))
        finally:
            self.api.CloseHandle(process)

    def terminate(self):
        self.checked(self.api.TerminateJobObject(self.handle, 1))

    def counts(self):
        self.checked(self.api.QueryInformationJobObject(
            self.handle, 1, ctypes.byref(self.accounting), ctypes.sizeof(self.accounting), None,
        ))
        return self.accounting.total, self.accounting.active

    def close(self):
        self.api.CloseHandle(self.handle)


QUOTA_PROBES = {
    "tree_timeout": (
        r'''
        #include <windows.h>
        #include <cstdio>
        #include <string>
        int main(int argc, char**) {
            if (argc > 1) { Sleep(INFINITE); return 0; }
            char path[MAX_PATH] = {};
            if (!GetModuleFileNameA(nullptr, path, MAX_PATH)) return 2;
            std::string cmd = std::string("\"") + path + "\" child";
            STARTUPINFOA info = {}; info.cb = sizeof(info);
            PROCESS_INFORMATION child = {};
            if (!CreateProcessA(nullptr, cmd.data(), nullptr, nullptr, FALSE, 0,
                                nullptr, nullptr, &info, &child)) return 3;
            std::puts("child spawned"); std::fflush(stdout);
            CloseHandle(child.hThread); CloseHandle(child.hProcess);
            Sleep(INFINITE);
        }
        ''', "TIMEOUT",
    ),
    "output_flood": (
        '#include <cstdio>\nint main(){while(true){std::putchar(65);std::fputc(66,stderr);}}',
        "OUTPUT_LIMIT",
    ),
    "signed_overflow": (
        '#include <climits>\nint main(){volatile int x=INT_MAX; return x+1;}',
        "SANITIZER_UB",
    ),
    "forged_marker": (
        '#include <cstdio>\n#include <windows.h>\nint main(){std::puts("__EAPG_TERMINAL_OK__");'
        'std::fflush(stdout);std::fputs("__EAPG_TERMINAL_OK__",stderr); ExitProcess(23);}',
        "CRASH_NO_TERMINAL_RECORD",
    ),
    "clean_control": ('int main(){return 0;}', "CLEAN_COMPLETION"),
}


def run_local_probe(directory, name, source):
    executable = directory / f"{name}.exe"
    status_file = directory / f"{name}.status.json"
    flags = ["-fsanitize=signed-integer-overflow", "-fsanitize-trap=signed-integer-overflow"] if name == "signed_overflow" else []
    subprocess.run(
        ["g++", "-std=c++17", "-O2", *flags, "-x", "c++", "-", "-o", str(executable)],
        input=source, text=True, capture_output=True, timeout=30, check=True,
    )
    job = WindowsProbeJob()
    proc = None
    drains = []
    output = {"stdout": bytearray(), "stderr": bytearray()}
    lock, overflow = Lock(), Event()
    cap = 65_536

    def capture(name, pipe):
        with pipe:
            for chunk in iter(lambda: pipe.read1(4096), b""):
                with lock:
                    remaining = cap - sum(map(len, output.values()))
                    output[name].extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        overflow.set()

    # The worker waits until it is in the job before it can spawn the fixture.
    gate = (
        "import ctypes,os,subprocess,sys\n"
        "if sys.stdin.buffer.read(1) != b'1': sys.exit(125)\n"
        "status=subprocess.call([sys.argv[1]],stdin=subprocess.DEVNULL)\n"
        "os._exit(ctypes.c_int32(status).value)\n"
    )
    timed_out = False
    try:
        proc = subprocess.Popen(
            [sys.executable, "-I", "-c", gate, str(executable)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        job.assign(proc.pid)
        for key in output:
            drain = Thread(target=capture, args=(key, getattr(proc, key)), daemon=True)
            drain.start()
            drains.append(drain)
        proc.stdin.write(b"1")
        proc.stdin.close()
        deadline = time.monotonic() + 1.5
        while proc.poll() is None and not overflow.is_set():
            if time.monotonic() >= deadline:
                timed_out = True
                break
            overflow.wait(0.01)
        observed_status = proc.poll()
        job.terminate()
        proc.wait(timeout=3)
        for drain in drains:
            drain.join(timeout=3)
            if drain.is_alive():
                raise RuntimeError("A probe output pipe remained open after job termination")
        deadline = time.monotonic() + 3
        total, active = job.counts()
        while active and time.monotonic() < deadline:
            time.sleep(0.01)
            total, active = job.counts()
        if active:
            raise RuntimeError("Probe left processes in its job")
    finally:
        job.close()
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait(timeout=3)
    if overflow.is_set():
        classification = "OUTPUT_LIMIT"
    elif timed_out:
        classification = "TIMEOUT"
    elif name == "signed_overflow" and observed_status is not None and observed_status & 0xFFFFFFFF == 0xC000001D:
        classification = "SANITIZER_UB"
    elif observed_status == 0:
        classification = "CLEAN_COMPLETION"
        # Only the outside supervisor writes this positive-control record.
        status_file.write_text(json.dumps({"status": classification, "exit_code": 0}), encoding="utf-8")
    else:
        classification = "CRASH_NO_TERMINAL_RECORD"
    if name == "tree_timeout" and (total < 3 or b"child spawned" not in output["stdout"]):
        raise RuntimeError("Tree timeout probe did not create a child")
    if name == "forged_marker" and not all(b"__EAPG_TERMINAL_OK__" in data for data in output.values()):
        raise RuntimeError("Forgery probe did not write both forged markers")
    return {"status": classification, "exit_code": observed_status, "job_processes": total,
            "surviving_processes": active, "captured_bytes": sum(map(len, output.values())),
            "supervisor_record": status_file.exists()}


def verify_custody():
    broken = "int main(){int counter=17; for( ; }"
    renamed = "int main(){int tally=24; for( ; }"
    assert fingerprints(broken) == fingerprints(renamed)
    assert fingerprints(broken)[1] == "lexer"
    assert source_key('int main(){return sizeof("a // b");}') != source_key('int main(){return sizeof("a // c");}')
    sort = "int main(){ std::sort(a,b); }"
    assert not (fingerprints(sort)[0] & fingerprints(sort.replace("sort", "find"))[0])
    human = "int main(){ int k=999; int acc=0; for(int j=0;j<k;++j) acc+=j; return acc; }"
    pilot = [
        Pair("PILOT_001", "P1",
             "static bool read_problem_size(int& n){return true;}\n"
             "int main(){ int n=16; if (!read_problem_size(n)) return 0;"
             "int s=0; for(int i=0;i<n;++i) s+=i; return s; }",
             "int main(){int k=3; return k*k;}", aliases=("bridge",)),
        Pair("PILOT_002", "P2", "int main(){while(true){break;} return 0;}",
             "int main(){return sizeof(int);}", aliases=("bridge",)),
        Pair("PILOT_003", "P3", "int main(){return 0;}", "int main(){return 2*4;}"),
    ]
    test = [Pair("TEST_001", "H1", "int main(){return 1^2;}", human)]
    report = quarantine(test, pilot)
    assert report["removed_pilot_pair_ids"] == ["PILOT_001", "PILOT_002"]
    assert report["retained_pilot_pair_ids"] == ["PILOT_003"]
    frozen = load_pilot()
    assert len(frozen) == 100
    probe = Pair("FIXTURE_REPEATED_SOURCE", "test", frozen[0].fast_code, "int main(){return 3.4;}")
    assert frozen[0].pair_id in quarantine([probe], frozen)["removed_pilot_pair_ids"]
    frame_rows = [
        {"split": "test", "pair_id": f"FIXTURE_{i:02d}_{j}", "problem_id": f"T{i:02d}",
         "slow_code": f"int main(){{return {j % 5};}}", "fast_code": f"int main(){{return {j};}}",
         "test_indices": [0]}
        for i in range(41) for j in range(6)
    ]
    with TemporaryDirectory(prefix="custody-fixture-", dir=HERE) as scratch:
        frame, manifest = Path(scratch) / "frame.json", Path(scratch) / "manifest.json"
        frame.write_bytes(json_bytes({"release": "local fixture", "usage_terms": "local only", "pairs": frame_rows}))
        digest = sha(frame.read_bytes())
        _, records, _ = read_frame(frame, digest)
        assert draw_pairs(records) == draw_pairs(list(reversed(records)))
        write_manifest(frame, digest, manifest)
        payload = json.loads(manifest.read_bytes())
        assert payload["manifest_sha256"] == sha(json_bytes(payload["manifest"]))
        assert len(payload["manifest"]["pairs"]) == 164
        assert all(row["distinct_slow_sources"] == 5 for row in payload["manifest"]["problem_ledger"])
        assert all(not row["pair_id"].endswith("_5") for row in payload["manifest"]["pairs"])
        assert len({(row["problem_id"], row["slow_source_key"]) for row in payload["manifest"]["pairs"]}) == 164
        assert "slow_code" not in payload["manifest"]["pairs"][0]
        assert payload["manifest"]["quarantine"]["final_prompt_quarantine"] == "pending"
    print("Custody PASS: seed-42 draw, sealed manifest, lexer fallback, STL distinctions, and transitive pilot precedence.", flush=True)


def verify_map():
    result = local_pass2_map()
    loop, = (node for node in result["nodes"] if node["role"] == "LOOP")
    assert result["line_alignment"] == "aligned", result
    assert loop["has_synthetic_braces"] and loop["macro_invocation_evidence"] == ["REP"], loop
    assert 6 in loop["raw_source_lines"], loop
    assert len(loop["pre_brace_byte_span"]) == 2
    assert all(set(row) == set(loop) for row in result["nodes"])
    assert not any({"a_work", "a_hits", "c_pruned", "rank", "count"} & set(row) for row in result["nodes"])
    import pipeline

    unicode_source = 'int main(){ const char* s="λ"; while (*s) break; }'
    normalized, origin = traced_normalization(pipeline, unicode_source)
    recovered = bytes(normalized.encode("utf-8")[i] for i, offset in enumerate(origin) if offset is not None)
    assert recovered == unicode_source.encode("utf-8")
    print("Pass-2 map PASS:", json.dumps(loop), flush=True)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--static-only", action="store_true", help="Run custody fixtures without invoking GCC")
    cli.add_argument("--frame", type=Path, help="Local pinned official-test frame in the documented JSON schema")
    cli.add_argument("--frame-sha256", help="Expected SHA-256 of the local frame file")
    cli.add_argument("--manifest", type=Path, help="New path for the sealed provisional manifest")
    args = cli.parse_args()
    if args.frame or args.frame_sha256 or args.manifest:
        if args.static_only or not all((args.frame, args.frame_sha256, args.manifest)):
            cli.error("--frame, --frame-sha256 and --manifest are required together")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", args.frame_sha256):
            cli.error("--frame-sha256 must be a 64-digit SHA-256 digest")
        write_manifest(args.frame, args.frame_sha256.lower(), args.manifest)
        print(f"Provisional static manifest written to {args.manifest}")
        return
    if not __debug__:
        cli.error("Fixture verification requires Python assertions")
    verify_custody()
    if args.static_only:
        return
    if sys.platform != "win32":
        cli.error("Local quota fixtures use Windows Job Objects. Run --static-only on other hosts.")
    verify_map()
    with TemporaryDirectory(prefix="quota-fixtures-", dir=HERE) as scratch:
        for name, (source, expected) in QUOTA_PROBES.items():
            result = run_local_probe(Path(scratch), name, source)
            assert result["status"] == expected, (name, result)
            assert result["supervisor_record"] == (expected == "CLEAN_COMPLETION"), (name, result)
            print(f"{name} PASS: {json.dumps(result)}", flush=True)


if __name__ == "__main__":
    main()
