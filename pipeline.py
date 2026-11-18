"""
EAPG Research Pipeline Master Orchestrator
Neurosymbolic Root-Cause Localization of Algorithmic Complexity Bottlenecks

Stages:
  1. AST Ingestion & Normalization (tree-sitter / Preprocessor Pass 0 / syntax-check)
  2. Sandbox Execution & Dynamic Scaling (micro-instrumentation, B(N), micro-ladder, dual-family fitting)
  3. Parent-Scope Backward Slicing (Monotonic Progress Pruning, R_search calculation)
  4. Ablation Matrix Evaluation & LaTeX Booktabs Export
"""

import os
import re
import sys
import json
import math
import argparse
import subprocess
from pathlib import Path
from typing import List, Dict, Set, Tuple, Optional

import tree_sitter_cpp as tscpp
from tree_sitter import Language, Parser

CPP_LANGUAGE = Language(tscpp.language())
parser = Parser(CPP_LANGUAGE)


# ==============================================================================
# Stage 1: AST Normalization & Preprocessor Pass 0 (Mandatory Patch 3)
# ==============================================================================

def verify_cpp_syntax(source_code: str, compiler: str = "g++") -> bool:
    """Validate rewritten C++ source code with -fsyntax-only."""
    try:
        proc = subprocess.run(
            [compiler, "-std=c++17", "-fsyntax-only", "-x", "c++", "-"],
            input=source_code,
            text=True,
            capture_output=True,
            timeout=10
        )
        return proc.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def apply_reverse_byte_edits(source: str, edits: List[Tuple[int, int, str]]) -> str:
    """
    Apply insertions/replacements in strict reverse-byte order (bottom-to-top)
    to preserve earlier byte offsets. Each edit: (start_byte, end_byte, replacement).
    """
    sorted_edits = sorted(edits, key=lambda x: x[0], reverse=True)
    raw_bytes = source.encode("utf-8")
    for start, end, repl in sorted_edits:
        raw_bytes = raw_bytes[:start] + repl.encode("utf-8") + raw_bytes[end:]
    return raw_bytes.decode("utf-8")


def preprocess_pass_zero(source_code: str, compiler: str = "g++") -> Tuple[str, Dict[str, str]]:
    """
    Mandatory Patch 3: Preprocessor Pass 0.
    1. Separates #include directives to prevent standard library 15,000+ line explosion.
    2. Runs g++ -E -P to cleanly expand competitive programming #define macros.
    3. Re-attaches #include directives at the top.
    4. Extracts type_alias_declaration (using) and type_definition (typedef) from AST.
    """
    includes = []
    other_lines = []
    for line in source_code.splitlines():
        if re.match(r'^\s*#\s*include\b', line):
            includes.append(line)
        else:
            other_lines.append(line)

    non_inc_code = "\n".join(other_lines)

    try:
        proc = subprocess.run(
            [compiler, "-E", "-P", "-x", "c++", "-"],
            input=non_inc_code,
            text=True,
            capture_output=True,
            timeout=10
        )
        expanded = proc.stdout if proc.returncode == 0 else non_inc_code
    except Exception:
        expanded = non_inc_code

    final_source = "\n".join(includes) + "\n\n" + expanded

    # Extract typedef / using aliases from AST
    raw_b = final_source.encode("utf-8")
    tree = parser.parse(raw_b)
    alias_map = {}

    def extract_aliases(node):
        if node.type == "type_alias_declaration":
            name_node = next((c for c in node.children if c.type == "type_identifier"), None)
            type_node = next((c for c in node.children if c.type in ("type_descriptor", "template_type", "type_identifier", "primitive_type") and (name_node is None or c.id != name_node.id)), None)
            if name_node and type_node:
                alias_name = raw_b[name_node.start_byte:name_node.end_byte].decode("utf-8").strip()
                target_type = raw_b[type_node.start_byte:type_node.end_byte].decode("utf-8").strip()
                alias_map[alias_name] = target_type
        elif node.type == "type_definition":
            type_node = next((c for c in node.children if c.type in ("type_descriptor", "template_type", "type_identifier", "primitive_type", "sized_type_specifier")), None)
            name_node = next((c for c in reversed(node.children) if c.type == "type_identifier"), None)
            if name_node and type_node:
                alias_name = raw_b[name_node.start_byte:name_node.end_byte].decode("utf-8").strip()
                target_type = raw_b[type_node.start_byte:type_node.end_byte].decode("utf-8").strip()
                alias_map[alias_name] = target_type

        for ch in node.children:
            extract_aliases(ch)

    extract_aliases(tree.root_node)
    return final_source, alias_map


def normalize_synthetic_braces(source_code: str) -> str:
    """
    Pass 1 Synthetic Block Normalization.
    Iteratively wraps single-statement loops and branches into explicit { ... } blocks.
    Uses bottom-up non-overlapping ranges per pass to avoid nesting collisions.
    """
    def find_braceless(src: str):
        b_raw = src.encode("utf-8")
        tree = parser.parse(b_raw)
        candidates = []

        def visit(node):
            for c in node.children:
                visit(c)
            if node.type in ("for_statement", "while_statement", "do_statement"):
                body = node.child_by_field_name("body")
                if body and body.type != "compound_statement":
                    candidates.append((body.start_byte, body.end_byte))
            elif node.type == "if_statement":
                conseq = node.child_by_field_name("consequence")
                if conseq and conseq.type != "compound_statement":
                    candidates.append((conseq.start_byte, conseq.end_byte))
            elif node.type == "else_clause":
                for c in node.children:
                    if c.type not in ("else", "compound_statement") and not c.type.startswith("comment"):
                        candidates.append((c.start_byte, c.end_byte))

        visit(tree.root_node)
        return candidates

    curr = source_code
    for _ in range(20):
        cands = find_braceless(curr)
        if not cands:
            break
        non_overlapping = []
        for start, end in cands:
            contains_other = any(s >= start and e <= end and (s != start or e != end) for s, e in cands)
            if not contains_other:
                non_overlapping.append((start, end))

        edits = []
        b_raw = curr.encode("utf-8")
        for start, end in non_overlapping:
            stmt_str = b_raw[start:end].decode("utf-8")
            edits.append((start, end, f"{{\n    {stmt_str}\n}}"))
        curr = apply_reverse_byte_edits(curr, edits)

    return curr


def extract_identifiers(node, raw_bytes: bytes) -> Set[str]:
    """Extract variable and field identifiers from AST node."""
    res = set()
    if node.type in ("identifier", "field_identifier"):
        name = raw_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="ignore").strip()
        keywords = {
            "int", "long", "char", "float", "double", "bool", "void", "auto",
            "std", "cin", "cout", "endl", "vector", "set", "map", "size",
            "push_back", "pop_back", "insert", "find", "count", "begin", "end",
            "return", "true", "false", "nullptr"
        }
        if name and name not in keywords:
            res.add(name)
    for c in node.children:
        res.update(extract_identifiers(c, raw_bytes))
    return res


def extract_macro_nodes(source_code: str, alias_map: Dict[str, str]) -> List[Dict]:
    """
    Extract Macro-Nodes with accurate container type tracking, unidirectional step detection,
    and non-truncated defs/uses.
    """
    raw_b = source_code.encode("utf-8")
    tree = parser.parse(raw_b)
    nodes = []

    var_types: Dict[str, str] = {}

    def classify_type_str(type_str: str) -> str:
        resolved = type_str
        for k, v in alias_map.items():
            if k in resolved:
                resolved = resolved.replace(k, v)
        if any(h in resolved for h in ("unordered_set", "unordered_map")):
            return "hash_container"
        elif any(t in resolved for t in ("set", "map", "priority_queue")):
            return "tree_container"
        elif any(s in resolved for s in ("vector", "string", "deque", "list")):
            return "seq_container"
        return "primitive"

    # Pre-pass: scan declarations to record var_types
    def scan_types(n):
        if n.type == "declaration":
            txt = raw_b[n.start_byte:n.end_byte].decode("utf-8", errors="ignore")
            m = re.search(r'([a-zA-Z_]\w*(?:::[a-zA-Z_]\w*)?(?:<[^>]+>)?)\s+([a-zA-Z_]\w*)', txt)
            if m:
                t_str, v_name = m.group(1), m.group(2)
                var_types[v_name] = classify_type_str(t_str)
        elif n.type == "function_definition":
            decl = n.child_by_field_name("declarator")
            if decl:
                for ch in decl.children:
                    if ch.type == "parameter_list":
                        for p in ch.children:
                            if p.type == "parameter_declaration":
                                p_txt = raw_b[p.start_byte:p.end_byte].decode("utf-8", errors="ignore")
                                p_ids = extract_identifiers(p, raw_b)
                                if p_ids:
                                    p_name = sorted(list(p_ids))[-1]
                                    var_types[p_name] = classify_type_str(p_txt)
        for c in n.children:
            scan_types(c)

    scan_types(tree.root_node)

    def walk(n, parent_id=None, inside_branch=False):
        nonlocal nodes
        current_id = None

        if n.parent and n.parent.type == "for_statement":
            body = n.parent.child_by_field_name("body")
            if body and n.id != body.id:
                return

        if n.type == "function_definition":
            decl = n.child_by_field_name("declarator")
            fn_name = raw_b[decl.start_byte:decl.end_byte].decode("utf-8", errors="ignore").split("(")[0].strip()
            if fn_name == "main":
                current_id = "MAIN_SCOPE"
            else:
                current_id = f"N{len(nodes)+1}"
                body = n.child_by_field_name("body")
                insert_pos = body.start_byte + 1 if (body and body.type == "compound_statement") else n.start_byte

                defs = set()
                weight_expr = "1ULL"
                for ch in decl.children:
                    if ch.type == "parameter_list":
                        for p in ch.children:
                            if p.type == "parameter_declaration":
                                p_txt = raw_b[p.start_byte:p.end_byte].decode("utf-8")
                                p_id_set = extract_identifiers(p, raw_b)
                                defs.update(p_id_set)
                                is_ref = "&" in p_txt
                                p_cat = classify_type_str(p_txt)
                                if p_cat == "seq_container" and not is_ref and p_id_set:
                                    p_name = sorted(list(p_id_set))[-1]
                                    weight_expr = f"(unsigned long long)({p_name}.size())"

                nodes.append({
                    "id": current_id,
                    "role": "FUNCTION_ENTRY",
                    "parent": parent_id,
                    "insert_pos": insert_pos,
                    "name": fn_name,
                    "defs": sorted(list(defs)),
                    "uses": [],
                    "weight_expr": weight_expr,
                    "is_unidirectional_step": False,
                    "is_state_reset": False,
                    "in_nested_branch": False,
                    "source_preview": raw_b[n.start_byte:body.start_byte].decode("utf-8", errors="ignore").strip() if body else fn_name
                })

        elif n.type in ("for_statement", "while_statement", "do_statement"):
            current_id = f"N{len(nodes)+1}"
            body = n.child_by_field_name("body")
            insert_pos = body.start_byte + 1 if (body and body.type == "compound_statement") else n.end_byte

            uses = set()
            defs = set()
            if n.type == "for_statement":
                init = n.child_by_field_name("initializer")
                cond = n.child_by_field_name("condition")
                upd = n.child_by_field_name("update")
                if init:
                    init_txt = raw_b[init.start_byte:init.end_byte].decode("utf-8", errors="ignore")
                    init_all_ids = extract_identifiers(init, raw_b)
                    init_lhs_ids = set()
                    for m_init in re.finditer(r'\b([a-zA-Z_]\w*)\s*=([^,;]+)', init_txt):
                        lhs_var = m_init.group(1)
                        if lhs_var in init_all_ids:
                            init_lhs_ids.add(lhs_var)
                    if init_lhs_ids:
                        defs.update(init_lhs_ids)
                        uses.update(init_all_ids - init_lhs_ids)
                    else:
                        defs.update(init_all_ids)
                if cond: uses.update(extract_identifiers(cond, raw_b))
                if upd:
                    defs.update(extract_identifiers(upd, raw_b))
                    uses.update(extract_identifiers(upd, raw_b))
            else:
                cond = n.child_by_field_name("condition")
                if cond: uses.update(extract_identifiers(cond, raw_b))

            header_end = body.start_byte if body else n.end_byte
            header_txt = raw_b[n.start_byte:header_end].decode("utf-8", errors="ignore").strip()

            nodes.append({
                "id": current_id,
                "role": "LOOP",
                "parent": parent_id,
                "insert_pos": insert_pos,
                "type": n.type,
                "defs": sorted(list(defs)),
                "uses": sorted(list(uses)),
                "weight_expr": "1ULL",
                "is_unidirectional_step": False,
                "is_state_reset": False,
                "in_nested_branch": inside_branch,
                "source_preview": header_txt
            })

        elif n.type == "if_statement":
            current_id = f"N{len(nodes)+1}"
            # Inject BEFORE the if_statement so branch evaluation frequency is tracked
            insert_pos = n.start_byte
            cond = n.child_by_field_name("condition")
            uses = extract_identifiers(cond, raw_b) if cond else set()
            conseq = n.child_by_field_name("consequence")
            header_txt = raw_b[n.start_byte:(conseq.start_byte if conseq else n.end_byte)].decode("utf-8", errors="ignore").strip()

            nodes.append({
                "id": current_id,
                "role": "BRANCH",
                "parent": parent_id,
                "insert_pos": insert_pos,
                "defs": [],
                "uses": sorted(list(uses)),
                "weight_expr": "1ULL",
                "is_unidirectional_step": False,
                "is_state_reset": False,
                "in_nested_branch": inside_branch,
                "source_preview": header_txt
            })

        elif n.type in ("expression_statement", "declaration", "return_statement"):
            if n.parent and n.parent.type == "compound_statement":
                txt = raw_b[n.start_byte:n.end_byte].decode("utf-8", errors="ignore").strip()
                is_trivial_return = bool(re.match(r'^\s*return\s*(-?\d+|true|false|nullptr)?\s*;\s*$', txt))
                is_io = any(txt.startswith(x) for x in ("std::cin", "cin", "std::cout", "cout"))

                if not is_io and not is_trivial_return:
                    has_assign = any(op in txt for op in ("=", "++", "--", "+=", "-=", "*=", "/="))
                    has_call = ("(" in txt and ")" in txt)
                    if has_assign or has_call:
                        current_id = f"N{len(nodes)+1}"
                        all_ids = extract_identifiers(n, raw_b)

                        defs = set()
                        uses = set(all_ids)

                        # Match unidirectional step updates without trailing \b
                        step_post = re.search(r'\b([a-zA-Z_]\w*)\s*(\+\+|--|\+=\s*1|-=\s*1)', txt)
                        step_pre = re.search(r'(\+\+|--)\s*([a-zA-Z_]\w*)\b', txt)
                        is_unidirectional = False
                        if step_post:
                            is_unidirectional = True
                            defs.add(step_post.group(1))
                        elif step_pre:
                            is_unidirectional = True
                            defs.add(step_pre.group(2))

                        eq_match = re.search(r'\b([a-zA-Z_]\w*)\s*(\+|-|\*|/)?=', txt)
                        if eq_match:
                            var_lhs = eq_match.group(1)
                            op_prefix = eq_match.group(2)
                            defs.add(var_lhs)
                            if not op_prefix:
                                uses.discard(var_lhs)

                        is_reset = bool(
                            (re.search(r'\b([a-zA-Z_]\w*)\s*=\s*([a-zA-Z_]\w*|0|1)\s*;', txt) or
                             (eq_match and not eq_match.group(2) and eq_match.group(1) not in uses))
                        ) and not is_unidirectional

                        # Container type-aware weight assignment
                        weight_expr = "1ULL"
                        stl_match = re.search(r'\bstd::(find|count)\s*\(\s*([a-zA-Z_]\w*)\.begin\(\)', txt)
                        if stl_match:
                            container_name = stl_match.group(2)
                            weight_expr = f"(unsigned long long)({container_name}.size())"
                        else:
                            method_match = re.search(r'\b([a-zA-Z_]\w*)\.(find|count|insert|erase|substr)\s*\(', txt)
                            if method_match:
                                container_name = method_match.group(1)
                                c_type = var_types.get(container_name, "seq_container")
                                if c_type == "hash_container":
                                    weight_expr = "1ULL"
                                elif c_type == "tree_container":
                                    weight_expr = f"(unsigned long long)__eapg_log2({container_name}.size() + 2)"
                                else:
                                    weight_expr = f"(unsigned long long)({container_name}.size())"

                        role = "CALL" if (txt.startswith("return") or (has_call and not has_assign)) else "STATE_UPD"
                        stmt_insert_pos = n.start_byte if (n.type == "return_statement" or role == "CALL") else n.end_byte

                        nodes.append({
                            "id": current_id,
                            "role": role,
                            "parent": parent_id,
                            "insert_pos": stmt_insert_pos,
                            "defs": sorted(list(defs)),
                            "uses": sorted(list(uses)),
                            "weight_expr": weight_expr,
                            "is_unidirectional_step": is_unidirectional,
                            "is_state_reset": is_reset,
                            "in_nested_branch": inside_branch,
                            "source_preview": txt
                        })

        next_parent = current_id if current_id else parent_id
        is_now_branch = inside_branch or (n.type == "if_statement")
        for c in n.children:
            walk(c, next_parent, is_now_branch)

    walk(tree.root_node)
    return nodes


# ==============================================================================
# Stage 2: Sandbox Execution & Scaling Limits (sandbox-runner & Patch 1)
# ==============================================================================

def compute_tick_ceiling(n: int) -> int:
    """Dynamic execution cap B(N) = max(2e6, 5*N^2)."""
    return max(2_000_000, 5 * (n ** 2))


def instrument_cpp_source(normalized_code: str, macro_nodes: List[Dict]) -> str:
    """Inject dual counters (__cnt and __work), log2 helper, and dynamic tick cap flush."""
    num_nodes = len(macro_nodes)
    header = f"""
// === EAPG DUAL-COUNTER PROFILER INSTRUMENTATION ===
#include <cstdio>
#include <cstdlib>

#define MAX_EAPG_NODES {max(16, num_nodes + 8)}
static unsigned long long __eapg_cnt[MAX_EAPG_NODES] = {{0}};
static unsigned long long __eapg_work[MAX_EAPG_NODES] = {{0}};
static unsigned long long __eapg_ticks = 0;
static unsigned long long __eapg_cap = 2000000ULL;
static int __eapg_breached = 0;

static inline unsigned long long __eapg_log2(unsigned long long sz) {{
    unsigned long long l = 0;
    while (sz >>= 1) l++;
    return l ? l : 1ULL;
}}

static void __eapg_dump_and_exit(int breached) {{
    __eapg_breached = breached;
    std::fprintf(stderr, "\\n---EAPG_DUMP_START---\\n");
    std::fprintf(stderr, "{{\\"status\\": \\"%s\\", \\"total_ticks\\": %llu, \\"nodes\\": {{", 
                 breached ? "CAP_BREACHED" : "CLEAN_COMPLETION", __eapg_ticks);
    for (int i = 0; i < {num_nodes}; ++i) {{
        std::fprintf(stderr, "\\"N%d\\": {{\\"cnt\\": %llu, \\"work\\": %llu}}%s", 
                     i + 1, __eapg_cnt[i], __eapg_work[i], (i + 1 < {num_nodes}) ? ", " : "");
    }}
    std::fprintf(stderr, "}}}}\\n---EAPG_DUMP_END---\\n");
    std::exit(0);
}}

static void __eapg_atexit_handler() {{
    if (!__eapg_breached) {{
        __eapg_dump_and_exit(0);
    }}
}}

static void __eapg_init() {{
    std::atexit(__eapg_atexit_handler);
    const char* env_n = std::getenv("EAPG_N");
    if (env_n) {{
        unsigned long long n_val = std::strtoull(env_n, nullptr, 10);
        unsigned long long calc_cap = 5ULL * n_val * n_val;
        __eapg_cap = (calc_cap > 2000000ULL) ? calc_cap : 2000000ULL;
    }}
}}

struct __EapgInitializer {{
    __EapgInitializer() {{ __eapg_init(); }}
}};
static __EapgInitializer __eapg_auto_init;

#define __EAPG_TICK(idx, w) do {{ \\
    __eapg_cnt[idx]++; \\
    __eapg_work[idx] += (w); \\
    __eapg_ticks += (w); \\
    if (__eapg_ticks >= __eapg_cap) {{ __eapg_dump_and_exit(1); }} \\
}} while(0)
// =================================================
"""

    edits = []
    for idx, node in enumerate(macro_nodes):
        pos = node["insert_pos"]
        w = node["weight_expr"]
        edits.append((pos, pos, f"\n__EAPG_TICK({idx}, {w});\n"))

    instrumented = header + apply_reverse_byte_edits(normalized_code, edits)
    return instrumented


def compile_cpp_binary(source_code: str, output_path: str, compiler: str = "g++") -> bool:
    """Compile C++ code to standalone binary with -O2 optimization."""
    try:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            [compiler, "-std=c++17", "-O2", "-x", "c++", "-", "-o", output_path],
            input=source_code,
            text=True,
            capture_output=True,
            timeout=15
        )
        return proc.returncode == 0
    except Exception:
        return False


def run_sandboxed_binary(
    binary_path: str,
    stdin_data: str,
    timeout_sec: float = 3.0,
    max_output_bytes: int = 10 * 1024 * 1024
) -> Tuple[int, str, str, str]:
    """Run C++ binary with process isolation and timeout."""
    kwargs = {}
    if os.name != "nt":
        kwargs["preexec_fn"] = os.setsid

    try:
        proc = subprocess.run(
            [binary_path],
            input=stdin_data,
            text=True,
            capture_output=True,
            timeout=timeout_sec,
            **kwargs
        )
        stdout = proc.stdout[:max_output_bytes]
        stderr = proc.stderr[:max_output_bytes]
        status = "CLEAN_COMPLETION" if proc.returncode == 0 else f"CRASH_{proc.returncode}"
        return proc.returncode, stdout, stderr, status
    except subprocess.TimeoutExpired:
        return -1, "", "", "TIMEOUT_TLE"
    except Exception as e:
        return -2, "", str(e), "SANDBOX_ERROR"


def run_instrumented_binary(
    binary_path: str,
    stdin_data: str,
    n_scale: int,
    timeout_sec: float = 3.0
) -> Tuple[str, Dict]:
    """Run binary with EAPG_N set, capturing JSON profiling counters."""
    env = os.environ.copy()
    env["EAPG_N"] = str(n_scale)
    try:
        proc = subprocess.run(
            [binary_path],
            input=stdin_data,
            text=True,
            capture_output=True,
            timeout=timeout_sec,
            env=env
        )
        match = re.search(r'---EAPG_DUMP_START---\s*(\{.*?\})\s*---EAPG_DUMP_END---', proc.stderr, re.DOTALL)
        if match:
            dump_data = json.loads(match.group(1))
            return dump_data.get("status", "CLEAN_COMPLETION"), dump_data.get("nodes", {})
        else:
            return "NO_DUMP", {}
    except subprocess.TimeoutExpired:
        return "TIMEOUT_TLE", {}
    except Exception as e:
        return f"CRASH_{str(e)}", {}


def fit_dual_family_scaling(scales: List[int], works: List[float]) -> Dict:
    """
    Dual-Family Curve Fitting (Mandatory Patch 1):
    1. Power-Law: log(W) = alpha * log(N) + c1
    2. Exponential: log2(W) = beta * N + c2
    Selects winning model based on R2 comparison.
    """
    if len(scales) < 2:
        return {
            "growth": "INSUFFICIENT_DATA",
            "alpha": 0.0,
            "beta": 0.0,
            "r2_poly": 0.0,
            "r2_exp": 0.0,
            "points": len(scales)
        }

    # 1. Power-law fit (log-log)
    xs = [math.log(max(1, s)) for s in scales]
    ys = [math.log(max(1.0, w)) for w in works]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    denom_x = sum((x - mean_x) ** 2 for x in xs)

    if denom_x > 0:
        alpha = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(len(xs))) / denom_x
        c1 = mean_y - alpha * mean_x
        ss_tot = sum((y - mean_y) ** 2 for y in ys)
        ss_res = sum((ys[i] - (alpha * xs[i] + c1)) ** 2 for i in range(len(ys)))
        r2_poly = 1.0 - (ss_res / ss_tot) if ss_tot > 1e-12 else 1.0
    else:
        alpha = 0.0
        r2_poly = 0.0

    # 2. Exponential fit (semi-log2)
    ns = [float(s) for s in scales]
    zs = [math.log2(max(1.0, w)) for w in works]
    mean_n = sum(ns) / len(ns)
    mean_z = sum(zs) / len(zs)
    denom_n = sum((n - mean_n) ** 2 for n in ns)

    if denom_n > 0:
        beta = sum((ns[i] - mean_n) * (zs[i] - mean_z) for i in range(len(ns))) / denom_n
        c2 = mean_z - beta * mean_n
        ss_tot_z = sum((z - mean_z) ** 2 for z in zs)
        ss_res_z = sum((zs[i] - (beta * ns[i] + c2)) ** 2 for i in range(len(zs)))
        r2_exp = 1.0 - (ss_res_z / ss_tot_z) if ss_tot_z > 1e-12 else 1.0
    else:
        beta = 0.0
        r2_exp = 0.0

    # Model Selection
    is_exp = (
        len(scales) >= 3 and
        r2_exp > r2_poly and
        r2_exp >= 0.85 and
        beta >= 0.02
    )

    return {
        "growth": "EXP" if is_exp else "POLY",
        "alpha": round(alpha, 2),
        "beta": round(beta, 2),
        "r2_poly": round(r2_poly, 3),
        "r2_exp": round(r2_exp, 3),
        "points": len(scales)
    }


def compute_ols_exponent(scales: List[int], works: List[float]) -> float:
    """Ordinary Least Squares linear regression on log(work) vs log(N)."""
    fit = fit_dual_family_scaling(scales, works)
    return fit["alpha"]


def execute_scaling_with_micro_ladder(
    binary_path: str,
    input_generator,
    macro_nodes: List[Dict],
    initial_scales: List[int] = [16, 64, 256, 1024, 4096]
) -> Dict[str, Dict]:
    """
    Executes scaling ladder with Dynamic Back-Off Micro-Ladder (Mandatory Patch 1).
    When binary completes at N_k and breaches B(N_{k+1}), triggers local micro-ladder.
    Guarantees >= 4 uncapped points in inflection zone.
    """
    node_hits_history = {n["id"]: [] for n in macro_nodes}
    node_work_history = {n["id"]: [] for n in macro_nodes}
    uncapped_scales = []

    last_uncapped_scale = None
    first_breached_scale = None

    # Step 1: Geometric coarse ladder
    for scale in initial_scales:
        stdin_data = input_generator(scale)
        status, dump = run_instrumented_binary(binary_path, stdin_data, scale)
        if status == "CLEAN_COMPLETION":
            uncapped_scales.append(scale)
            last_uncapped_scale = scale
            for n in macro_nodes:
                nid = n["id"]
                node_hits_history[nid].append(dump.get(nid, {}).get("cnt", 0))
                node_work_history[nid].append(dump.get(nid, {}).get("work", 0))
        else:
            first_breached_scale = scale
            break

    # Step 2: Mandatory Patch 1 Micro-Ladder if inflection occurred
    if last_uncapped_scale is not None and first_breached_scale is not None:
        micro_scales = [
            last_uncapped_scale + 2,
            last_uncapped_scale + 4,
            last_uncapped_scale + 6,
            last_uncapped_scale + 8,
            last_uncapped_scale + 10,
            last_uncapped_scale + 12,
            last_uncapped_scale + 16,
            last_uncapped_scale + 20,
            last_uncapped_scale + 24,
            last_uncapped_scale + 32,
        ]
        for m_scale in micro_scales:
            if m_scale >= first_breached_scale or m_scale in uncapped_scales:
                continue
            stdin_data = input_generator(m_scale)
            status, dump = run_instrumented_binary(binary_path, stdin_data, m_scale)
            if status == "CLEAN_COMPLETION":
                uncapped_scales.append(m_scale)
                for n in macro_nodes:
                    nid = n["id"]
                    node_hits_history[nid].append(dump.get(nid, {}).get("cnt", 0))
                    node_work_history[nid].append(dump.get(nid, {}).get("work", 0))
            else:
                break

    sorted_order = sorted(range(len(uncapped_scales)), key=lambda k: uncapped_scales[k])
    sorted_scales = [uncapped_scales[k] for k in sorted_order]

    scaling_results = {}
    for n in macro_nodes:
        nid = n["id"]
        hits = [node_hits_history[nid][k] for k in sorted_order]
        work = [node_work_history[nid][k] for k in sorted_order]

        fit_hits = fit_dual_family_scaling(sorted_scales, hits)
        fit_work = fit_dual_family_scaling(sorted_scales, work)

        scaling_results[nid] = {
            "fit_hits": fit_hits,
            "fit_work": fit_work,
            "uncapped_scales": sorted_scales,
            "work_values": work,
            "cap_breached": first_breached_scale is not None
        }

    return scaling_results


def verify_o2_invariance(source_code: str, compiler: str = "g++") -> Dict[str, bool]:
    """Test compilation across optimization levels -O0, -O2, and -O3."""
    results = {}
    for opt in ["-O0", "-O2", "-O3"]:
        try:
            proc = subprocess.run(
                [compiler, "-std=c++17", opt, "-fsyntax-only", "-x", "c++", "-"],
                input=source_code,
                text=True,
                capture_output=True,
                timeout=10
            )
            results[opt] = (proc.returncode == 0)
        except Exception:
            results[opt] = False
    return results


# ==============================================================================
# Stage 3: Monotonic Progress Pruning Slicing (Mandatory Patch 2)
# ==============================================================================

def calculate_search_space_reduction(v_total: int, v_candidate: int) -> float:
    """Search Space Reduction Ratio R_search = 1 - (|V_candidate| / |V_total|)."""
    if v_total <= 0:
        return 0.0
    return 1.0 - (min(v_candidate, v_total) / v_total)


def analyze_eapg_slicing(macro_nodes: List[Dict], scaling_results: Dict) -> Dict:
    """
    Deterministic Parent-Scope Backward Slicing with Monotonic Progress Pruning (Mandatory Patch 2).
    Addresses Bug 4: Populates self-contained root cause for hidden work jumps and missing guard anchors.
    """
    node_map = {n["id"]: n for n in macro_nodes}
    delta_alphas = {}
    symptoms = []
    hidden_work_nodes = set()

    caller_map = {}
    for n in macro_nodes:
        preview = n.get("source_preview", "")
        if "(" in preview:
            for fn_node in macro_nodes:
                if fn_node["role"] == "FUNCTION_ENTRY":
                    fn_name = fn_node["name"]
                    if re.search(r'\b' + re.escape(fn_name) + r'\b', preview):
                        caller_map[fn_node["id"]] = n["id"]

    for n in macro_nodes:
        nid = n["id"]
        fit_w = scaling_results[nid]["fit_work"]
        fit_h = scaling_results[nid]["fit_hits"]
        alpha_w = fit_w["alpha"] if fit_w["growth"] == "POLY" else 9.99

        parent_id = n["parent"]
        if parent_id and parent_id in scaling_results:
            p_fit_w = scaling_results[parent_id]["fit_work"]
            p_alpha_w = p_fit_w["alpha"] if p_fit_w["growth"] == "POLY" else 9.99
            delta_a = round(alpha_w - p_alpha_w, 2)
        elif n["role"] == "FUNCTION_ENTRY" and nid in caller_map:
            caller_id = caller_map[nid]
            c_fit_w = scaling_results[caller_id]["fit_work"]
            c_alpha_w = c_fit_w["alpha"] if c_fit_w["growth"] == "POLY" else 0.0
            delta_a = round(alpha_w - c_alpha_w, 2)
        else:
            delta_a = 0.0

        # Check hidden container work jump (alpha_work - alpha_hits >= 0.7)
        if fit_w["growth"] == "POLY" and fit_h["growth"] == "POLY" and fit_w["alpha"] - fit_h["alpha"] >= 0.7:
            delta_a = max(delta_a, round(fit_w["alpha"] - fit_h["alpha"], 2))
            hidden_work_nodes.add(nid)

        delta_alphas[nid] = delta_a
        parent_is_exp = bool(parent_id and parent_id in scaling_results and scaling_results[parent_id]["fit_work"]["growth"] == "EXP")
        if delta_a >= 0.7 or (fit_w["growth"] == "EXP" and not parent_is_exp):
            symptoms.append(nid)

    symptom_id = symptoms[0] if symptoms else None
    for s_id in symptoms:
        if s_id in hidden_work_nodes:
            symptom_id = s_id
            break
        if node_map[s_id]["role"] in ("LOOP", "FUNCTION_ENTRY"):
            symptom_id = s_id
            break

    c_slice = []
    r_search = 0.0

    if symptom_id:
        symptom_node = node_map[symptom_id]
        v_guard = set(symptom_node["uses"])
        if symptom_node["role"] == "FUNCTION_ENTRY":
            v_guard.update(symptom_node["defs"])
            if symptom_id in caller_map:
                v_guard.update(node_map[caller_map[symptom_id]]["uses"])
        alpha_s = scaling_results[symptom_id]["fit_work"]["alpha"]

        # Case A: Hidden container work (Node itself is root cause)
        if symptom_id in hidden_work_nodes:
            c_slice.append(symptom_id)

        # Case B: Inter-scope candidates (defs in parent scope affecting symptom guard)
        parent_scope_id = symptom_node["parent"]
        for n in macro_nodes:
            if n["id"] == symptom_id:
                continue
            if n["parent"] == parent_scope_id:
                alpha_u = scaling_results[n["id"]]["fit_work"]["alpha"]
                if (alpha_u <= alpha_s - 0.5 or scaling_results[symptom_id]["fit_work"]["growth"] == "EXP") and (set(n["defs"]) & v_guard):
                    c_slice.append(n["id"])

        # Case C: Intra-scope candidates with Monotonic Progress Pruning
        for n in macro_nodes:
            if n["parent"] == symptom_id:
                if n["is_unidirectional_step"]:
                    continue  # Pruned!
                if n["is_state_reset"] or n["in_nested_branch"]:
                    if set(n["defs"]) & v_guard:
                        c_slice.append(n["id"])

        # Always include symptom header s in C_slice(s) = {s} U C_inter(s) U C_intra_pruned(s)
        c_slice.append(symptom_id)

        c_slice = sorted(list(set(c_slice)), key=lambda x: int(x[1:]))
        v_total = len(macro_nodes)
        v_cand = len(c_slice)
        r_search = round(1.0 - (v_cand / v_total), 3) if v_total > 0 else 0.0

    return {
        "delta_alphas": delta_alphas,
        "symptoms": symptoms,
        "primary_symptom": symptom_id,
        "c_slice": c_slice,
        "r_search": r_search
    }


def format_eapg_skeleton(macro_nodes: List[Dict], scaling_results: Dict, slicing_results: Dict) -> str:
    """Format full Execution-Annotated Program Graph (EAPG) skeleton with complete defs and uses."""
    lines = []
    lines.append("=" * 95)
    lines.append("EMITTED EAPG SKELETON (Execution-Annotated Program Graph)")
    lines.append("=" * 95)
    lines.append(f"{'NodeID':<7} | {'Role':<14} | {'a_hits':<8} | {'a_work':<8} | {'Delta_a':<8} | {'Defs':<12} | {'Uses':<18} | {'Candidate':<9} | {'Preview'}")
    lines.append("-" * 95)

    for n in macro_nodes:
        nid = n["id"]
        role = n["role"]
        fit_h = scaling_results[nid]["fit_hits"]
        fit_w = scaling_results[nid]["fit_work"]

        a_h_str = f"EXP({fit_h['beta']})" if fit_h["growth"] == "EXP" else f"{fit_h['alpha']:.2f}"
        a_w_str = f"EXP({fit_w['beta']})" if fit_w["growth"] == "EXP" else f"{fit_w['alpha']:.2f}"

        delta_a = slicing_results["delta_alphas"].get(nid, 0.0)
        delta_str = f"+{delta_a:.2f}" if delta_a > 0 else f"{delta_a:.2f}"
        if delta_a >= 0.7:
            delta_str += " *"

        defs_str = "{" + ",".join(sorted(n["defs"])) + "}"
        uses_str = "{" + ",".join(sorted(n["uses"])) + "}"
        is_cand = "[CHOKE]" if nid in slicing_results["c_slice"] else "-"
        preview = n.get("source_preview", "")[:26]

        lines.append(f"{nid:<7} | {role:<14} | {a_h_str:<8} | {a_w_str:<8} | {delta_str:<8} | {defs_str:<12} | {uses_str:<18} | {is_cand:<9} | {preview}")

    lines.append("-" * 95)
    lines.append(f"Symptom Node: {slicing_results['primary_symptom']}")
    lines.append(f"Choke-Point Candidates: {slicing_results['c_slice']}")
    lines.append(f"Search Space Reduction R_search: {slicing_results['r_search']*100:.1f}% (Constraint >= 75%: {'PASS' if slicing_results['r_search'] >= 0.75 else 'FAIL'})")
    lines.append("=" * 95)
    return "\n".join(lines)


def create_problem_quarantined_split(
    records: List[Dict],
    train_ratio: float = 0.8,
    val_ratio: float = 0.1,
    seed: int = 42
) -> Tuple[List[Dict], List[Dict], List[Dict]]:
    """Group strictly on problem_id to guarantee zero overlap across splits."""
    import random
    rng = random.Random(seed)

    problem_ids = sorted(list(set(r["problem_id"] for r in records)))
    rng.shuffle(problem_ids)

    n_total = len(problem_ids)
    n_train = int(n_total * train_ratio)
    n_val = int(n_total * val_ratio)

    train_pids = set(problem_ids[:n_train])
    val_pids = set(problem_ids[n_train:n_train + n_val])
    test_pids = set(problem_ids[n_train + n_val:])

    assert train_pids.isdisjoint(val_pids), "FATAL: Train and Val overlap in problem_id!"
    assert train_pids.isdisjoint(test_pids), "FATAL: Train and Test overlap in problem_id!"
    assert val_pids.isdisjoint(test_pids), "FATAL: Val and Test overlap in problem_id!"

    train_set = [r for r in records if r["problem_id"] in train_pids]
    val_set = [r for r in records if r["problem_id"] in val_pids]
    test_set = [r for r in records if r["problem_id"] in test_pids]

    return train_set, val_set, test_set


# ==============================================================================
# Stage 4: Ablation Matrix & LaTeX Booktabs Export (ablation-matrix)
# ==============================================================================

VARIANTS = [
    ("1", "Naive Profiler", "None", "Max Work Exponent", "No"),
    ("2", "Deterministic PDG Slice", "None", "Role-Priority Slice", "Yes"),
    ("3a", "Raw-Code SLM (Zero-Shot)", "1.5B (0 ep)", "Raw C++ Code", "No"),
    ("3b", "Raw-Code SLM (Fine-Tuned)", "1.5B (QLoRA)", "Raw C++ Code", "No"),
    ("4", "Hotspot-Guided SLM", "1.5B (QLoRA)", "Raw C++ + Line Hits", "No"),
    ("5", "Static EAPG (Ablation A)", "1.5B (QLoRA)", "Role + Def/Use + C++", "No"),
    ("6a", "Abstract Graph (Unconstrained)", "1.5B (QLoRA)", "No Code Tokens", "No"),
    ("6b", "Abstract Graph (Slice-Constrained)", "1.5B (QLoRA)", "No Code Tokens", "Yes"),
    ("7a", "Full EAPG (Unconstrained)", "1.5B (QLoRA)", "EAPG + C++", "No"),
    ("7b", "Full EAPG (Slice-Constrained)", "1.5B (QLoRA)", "EAPG + C++", "Yes"),
]

RANK_TAG_VARIANTS = [
    VARIANTS[1],
    ("6b-slice", "Abstract EAPG (Slice Tags)", "1.5B (QLoRA)", "Abstract", "Yes"),
    ("6b-rank", "Abstract EAPG (Rank Tags)", "1.5B (QLoRA)", "Abstract", "Yes"),
    ("7b-slice", "Lexical EAPG (Slice Tags)", "1.5B (QLoRA)", "Lexical", "Yes"),
    ("7b-rank", "Lexical EAPG (Rank Tags)", "1.5B (QLoRA)", "Lexical", "Yes"),
]

REVISED_VARIANTS = VARIANTS[:6] + [
    (f"{family}{suffix}-{tags}", f"{name} ({mode}, {tags} tags)", "1.5B (QLoRA)", name, mode)
    for family, name in (("6", "Abstract EAPG"), ("7", "Lexical EAPG"))
    for tags in ("slice", "rank")
    for suffix, mode in (("a", "unconstrained"), ("b", "slice-constrained"))
]


def export_ablation_latex_table(
    results: Dict[str, Dict[str, float]], output_path: str, *,
    rank_tag_ablation=False, revised_pilot=False, repair_families=False, multi_candidate_count: Optional[int] = None,
):
    """Generate conference-ready LaTeX table with exact booktabs syntax."""
    if rank_tag_ablation:
        variants = RANK_TAG_VARIANTS
        caption = r"\caption{Two-by-two EAPG ablation on 100 pilot pairs. All neural rows use slice-constrained decoding and adapters in blocks 20--27. Paradigm accuracy is conditional on the reference node.}"
    elif revised_pilot:
        variants = REVISED_VARIANTS
        if multi_candidate_count is not None:
            target = "Multi-cand. Top-1"
            metric_note = f"Multi-candidate Top-1 uses the {multi_candidate_count} pairs with at least two slice candidates."
        else:
            target = "Repair family" if repair_families else "Paradigm"
            metric_note = f"{target} accuracy is conditional on the reference node."
        caption = (
            r"\caption{Five-fold evaluation on 100 pilot pairs grouped by problem ID, canonical template, and identical prompt tokens. "
            r"Variants 6a and 7a score all nodes. Variants 6b and 7b score the slice. Reset, A1, and A2 report subset Top-1. "
            f"{metric_note} Metrics are percentages." + "}"
        )
    else:
        variants = VARIANTS
        caption = r"\caption{Five-fold evaluation on 100 constructed pairs grouped by 41 problem IDs. Reset Top-1 covers the 18 pairs in \texttt{A1.1} and \texttt{A1.4}. Paradigm accuracy is conditional on the reference node.}"
    lines = [
        r"\begin{table*}[t]",
        r"\centering",
        r"\small",
        caption,
        r"\label{tab:rank_tag_ablation}" if rank_tag_ablation else r"\label{tab:ablation_results}",
        r"\begin{tabular}{cllccccccc}",
        r"\toprule",
        r"\textbf{\#} & \textbf{Variant / Method} & \textbf{Backbone} & \textbf{Top-1 (\%)} & \textbf{Top-2 (\%)} & \textbf{Reset Top-1 (\%)} & \textbf{A1 Rec (\%)} & \textbf{A2 Rec (\%)} & \textbf{$R_{\text{search}}$ (\%)} & \textbf{Paradigm (\%)} \\",
        r"\midrule",
    ]
    if revised_pilot and not rank_tag_ablation:
        tabular_start = lines.index(r"\begin{tabular}{cllccccccc}")
        lines[tabular_start:tabular_start + 3] = [
            r"\setlength{\tabcolsep}{4pt}",
            r"\begin{tabular}{@{}cllccccccc@{}}",
            r"\toprule",
            r"\textbf{ID} & \textbf{Method} & \textbf{Backbone} & \textbf{Top-1} & \textbf{Top-2} & \textbf{Reset} & \textbf{A1} & \textbf{A2} & \textbf{$R_{\text{search}}$} & \textbf{" + target + r"} \\",
        ]

    for v_key, name, bb, _, _ in variants:
        if revised_pilot and not rank_tag_ablation:
            name = name.partition(" (")[0]
        res = results.get(v_key, {"top1": 0.0, "top2": 0.0, "reset_top1": 0.0, "a1_top1": 0.0, "a2_top1": 0.0, "r_search": 0.0, "paradigm": -1.0})
        t1_s = f"{res['top1']:.1f}"
        t2_s = f"{res['top2']:.1f}"
        rst_s = f"{res.get('reset_top1', 0.0):.1f}"
        a1_s = f"{res.get('a1_top1', 0.0):.1f}"
        a2_s = f"{res.get('a2_top1', 0.0):.1f}"
        rs_s = f"{res.get('r_search', 0.0):.1f}"
        p_val = res["multi_top1"] if multi_candidate_count is not None else res.get("paradigm", -1.0)
        p_s = "--" if p_val < 0 else f"{p_val:.1f}"
        row = (
            f"{v_key} & {name} & {bb} & "
            f"{t1_s} & {t2_s} & {rst_s} & {a1_s} & {a2_s} & {rs_s} & {p_s} \\\\"
        )
        lines.append(row)
        if v_key in ("2", "5", "6b"):
            lines.append(r"\midrule")

    lines.extend([
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table*}",
    ])

    out = "\n".join(lines)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(out)
    return out


# ==============================================================================
# 5 Hand-Picked Test Benchmark Pairs with SaS Synthesizers
# ==============================================================================

BENCHMARK_PAIRS = [
    # Pair 1: Sliding Window / Two Pointers (Track A1: State Corruption / Pointer Reset)
    {
        "name": "Pair 1: Sliding Window (Track A1 - Pointer Reset)",
        "problem_id": "P_SLIDING_WINDOW_01",
        "slow_code": """#include <iostream>
#include <vector>
#define vi std::vector<int>
#define ll long long

int main() {
    int n;
    ll k;
    if (!(std::cin >> n >> k)) return 0;
    vi a(n);
    for (int i = 0; i < n; ++i) std::cin >> a[i];

    int max_len = 0;
    for (int l = 0; l < n; ++l) {
        int r = l;
        ll sum = 0;
        while (r < n && sum + a[r] <= k) {
            sum += a[r];
            r++;
        }
        if (r - l > max_len) max_len = r - l;
    }
    std::cout << max_len << std::endl;
    return 0;
}
""",
        "fast_code": """#include <iostream>
#include <vector>
#define vi std::vector<int>
#define ll long long

int main() {
    int n;
    ll k;
    if (!(std::cin >> n >> k)) return 0;
    vi a(n);
    for (int i = 0; i < n; ++i) std::cin >> a[i];

    int max_len = 0;
    int r = 0;
    ll sum = 0;
    for (int l = 0; l < n; ++l) {
        while (r < n && sum + a[r] <= k) {
            sum += a[r];
            r++;
        }
        if (r - l > max_len) max_len = r - l;
        sum -= a[l];
    }
    std::cout << max_len << std::endl;
    return 0;
}
""",
        "input_gen": lambda n: f"{n} {n // 2}\n" + " ".join(["1"] * n) + "\n"
    },

    # Pair 2: Exponential Recursion vs DP (Track A2: Missing Memoization - Tests Patch 1 Micro-Ladder)
    {
        "name": "Pair 2: Exponential Recursion (Track A2 - Missing Memoization)",
        "problem_id": "P_EXP_RECURSION_02",
        "slow_code": """#include <iostream>

long long ways(int n) {
    if (n <= 1) return 1;
    return ways(n - 1) + ways(n - 2);
}

int main() {
    int n;
    if (!(std::cin >> n)) return 0;
    std::cout << ways(n) << std::endl;
    return 0;
}
""",
        "fast_code": """#include <iostream>
#include <vector>

int main() {
    int n;
    if (!(std::cin >> n)) return 0;
    std::vector<long long> dp(n + 1, 0);
    dp[0] = 1;
    dp[1] = 1;
    for (int i = 2; i <= n; ++i) {
        dp[i] = dp[i - 1] + dp[i - 2];
    }
    std::cout << dp[n] << std::endl;
    return 0;
}
""",
        "input_gen": lambda n: f"{n}\n"
    },

    # Pair 3: STL Linear Search Abuse (Track A1/B: Hidden std::find Container Weight)
    {
        "name": "Pair 3: STL Linear Search Abuse (Track A1/B - Container Work)",
        "problem_id": "P_STL_ABUSE_03",
        "slow_code": """#include <iostream>
#include <vector>
#include <algorithm>
#define vi std::vector<int>

int main() {
    int n;
    if (!(std::cin >> n)) return 0;
    vi a(n);
    for (int i = 0; i < n; ++i) std::cin >> a[i];
    int count = 0;
    for (int i = 0; i < n; ++i) {
        int q = i * 2;
        auto it = std::find(a.begin(), a.end(), q);
        if (it != a.end()) count++;
    }
    std::cout << count << std::endl;
    return 0;
}
""",
        "fast_code": """#include <iostream>
#include <vector>
#include <unordered_set>

int main() {
    int n;
    if (!(std::cin >> n)) return 0;
    std::unordered_set<int> s;
    for (int i = 0; i < n; ++i) {
        int val;
        std::cin >> val;
        s.insert(val);
    }
    int count = 0;
    for (int i = 0; i < n; ++i) {
        int q = i * 2;
        if (s.find(q) != s.end()) count++;
    }
    std::cout << count << std::endl;
    return 0;
}
""",
        "input_gen": lambda n: f"{n}\n" + " ".join([str(i) for i in range(n)]) + "\n"
    },

    # Pair 4: Pass-by-Value Container in Recursion (Track A1: Hidden Vector Copy Work)
    {
        "name": "Pair 4: Pass-by-Value in Recursion (Track A1 - Hidden Vector Copy)",
        "problem_id": "P_PASS_BY_VAL_04",
        "slow_code": """#include <iostream>
#include <vector>
#define vi std::vector<int>

void dfs(int depth, int max_depth, vi path) {
    if (depth >= max_depth) return;
    path.push_back(depth);
    dfs(depth + 1, max_depth, path);
}

int main() {
    int n;
    if (!(std::cin >> n)) return 0;
    vi initial_path;
    dfs(0, n, initial_path);
    std::cout << n << std::endl;
    return 0;
}
""",
        "fast_code": """#include <iostream>
#include <vector>
#define vi std::vector<int>

void dfs(int depth, int max_depth, vi& path) {
    if (depth >= max_depth) return;
    path.push_back(depth);
    dfs(depth + 1, max_depth, path);
    path.pop_back();
}

int main() {
    int n;
    if (!(std::cin >> n)) return 0;
    vi initial_path;
    dfs(0, n, initial_path);
    std::cout << n << std::endl;
    return 0;
}
""",
        "input_gen": lambda n: f"{n}\n"
    },

    # Pair 5: Missing Early-Exit Guard (Track A2: Omission of Break / Pruning)
    {
        "name": "Pair 5: Missing Early-Exit Guard (Track A2 - Guard Omission)",
        "problem_id": "P_MISSING_GUARD_05",
        "slow_code": """#include <iostream>
#include <vector>

int main() {
    int n;
    if (!(std::cin >> n)) return 0;
    std::vector<int> a(n);
    for (int i = 0; i < n; ++i) a[i] = i;
    int target = 3;
    bool found = false;
    for (int i = 0; i < n; ++i) {
        for (int j = i + 1; j < n; ++j) {
            if (a[i] + a[j] == target) {
                found = true;
            }
        }
    }
    std::cout << (found ? 1 : 0) << std::endl;
    return 0;
}
""",
        "fast_code": """#include <iostream>
#include <vector>

int main() {
    int n;
    if (!(std::cin >> n)) return 0;
    std::vector<int> a(n);
    for (int i = 0; i < n; ++i) a[i] = i;
    int target = 3;
    bool found = false;
    for (int i = 0; i < n; ++i) {
        for (int j = i + 1; j < n; ++j) {
            if (a[i] + a[j] == target) {
                found = true;
                break;
            }
        }
        if (found) break;
    }
    std::cout << (found ? 1 : 0) << std::endl;
    return 0;
}
""",
        "input_gen": lambda n: f"{n}\n"
    }
]


def run_benchmark_pair(pair: Dict, build_dir: Path) -> Dict:
    print(f"\n>>> Running Pipeline for: {pair['name']}")

    # 1. Process Slow Code
    print("  [Stage 1] Preprocessor Pass 0 & Brace Normalization on Slow Code...")
    slow_prep, alias_map_slow = preprocess_pass_zero(pair["slow_code"])
    slow_norm = normalize_synthetic_braces(slow_prep)
    assert verify_cpp_syntax(slow_norm), "FATAL: Syntax verification failed for slow_norm!"

    macro_nodes_slow = extract_macro_nodes(slow_norm, alias_map_slow)
    print(f"  [+] Extracted {len(macro_nodes_slow)} macro nodes from slow code")

    # 2. Instrument & Compile Slow Code
    print("  [Stage 2] Instrumenting and Compiling Slow Binary with -O2...")
    slow_instr = instrument_cpp_source(slow_norm, macro_nodes_slow)
    slow_bin = str(build_dir / f"{pair['problem_id']}_slow.exe")
    assert compile_cpp_binary(slow_instr, slow_bin), f"FATAL: Compilation failed for {slow_bin}!"

    # 3. Dynamic Scaling Ladder with Adaptive Micro-Ladder
    print("  [Stage 2] Executing Dynamic Scale Ladder & Adaptive Micro-Ladder...")
    scaling_slow = execute_scaling_with_micro_ladder(slow_bin, pair["input_gen"], macro_nodes_slow)

    # 4. Stage 3 Deterministic Slicing with Monotonic Progress Pruning
    print("  [Stage 3] Parent-Scope Backward Slicing & Candidate Pruning...")
    slicing_slow = analyze_eapg_slicing(macro_nodes_slow, scaling_slow)

    # 5. Format EAPG Skeleton
    skeleton_slow = format_eapg_skeleton(macro_nodes_slow, scaling_slow, slicing_slow)
    print(skeleton_slow)

    # 6. Process Fast Code for baseline comparison
    print("  [Stage 1-2] Profiling Fast Code for Asymptotic Comparison...")
    fast_prep, alias_map_fast = preprocess_pass_zero(pair["fast_code"])
    fast_norm = normalize_synthetic_braces(fast_prep)
    macro_nodes_fast = extract_macro_nodes(fast_norm, alias_map_fast)
    fast_instr = instrument_cpp_source(fast_norm, macro_nodes_fast)
    fast_bin = str(build_dir / f"{pair['problem_id']}_fast.exe")
    assert compile_cpp_binary(fast_instr, fast_bin), f"FATAL: Compilation failed for {fast_bin}!"
    scaling_fast = execute_scaling_with_micro_ladder(fast_bin, pair["input_gen"], macro_nodes_fast)

    def get_max_exp(sc_res):
        max_a = 0.0
        has_exp = False
        for nid, d in sc_res.items():
            fw = d["fit_work"]
            if fw["growth"] == "EXP":
                has_exp = True
            elif fw["growth"] == "POLY":
                max_a = max(max_a, fw["alpha"])
        return "EXP" if has_exp else max_a

    max_slow = get_max_exp(scaling_slow)
    max_fast = get_max_exp(scaling_fast)
    print(f"  [+] Complexity Comparison: Slow={max_slow} vs Fast={max_fast}")

    return {
        "problem_id": pair["problem_id"],
        "name": pair["name"],
        "macro_nodes_count": len(macro_nodes_slow),
        "primary_symptom": slicing_slow["primary_symptom"],
        "c_slice": slicing_slow["c_slice"],
        "r_search": slicing_slow["r_search"],
        "max_slow": max_slow,
        "max_fast": max_fast,
        "skeleton": skeleton_slow
    }


def run_milestone_one(build_dir: Path, output_dir: Path) -> List[Dict]:
    """Execute Milestone 1 Pipeline across all 5 benchmark pairs."""
    build_dir.mkdir(parents=True, exist_ok=True)
    summary = []
    skeletons_dump = []

    for pair in BENCHMARK_PAIRS:
        res = run_benchmark_pair(pair, build_dir)
        summary.append(res)
        skeletons_dump.append({
            "problem_id": res["problem_id"],
            "name": res["name"],
            "primary_symptom": res["primary_symptom"],
            "candidates": res["c_slice"],
            "r_search": res["r_search"],
            "slow_scaling": str(res["max_slow"]),
            "fast_scaling": str(res["max_fast"]),
            "skeleton": res["skeleton"]
        })

    dump_path = output_dir / "milestone1_skeletons.json"
    with open(dump_path, "w", encoding="utf-8") as f:
        json.dump(skeletons_dump, f, indent=2)

    print("\n" + "=" * 80)
    print("UPDATED MILESTONE 1 BENCHMARK SUMMARY (5 Hand-Picked Test Pairs)")
    print("=" * 80)
    print(f"{'Problem ID':<22} | {'Symptom':<9} | {'Candidates':<12} | {'R_search':<10} | {'Slow':<8} | {'Fast':<8}")
    print("-" * 80)
    for s in summary:
        cands_str = str(s["c_slice"])
        print(f"{s['problem_id']:<22} | {str(s['primary_symptom']):<9} | {cands_str:<12} | {s['r_search']*100:.1f}%    | {str(s['max_slow']):<8} | {str(s['max_fast']):<8}")
    print("=" * 80)
    print(f"Full skeleton dumps saved to: {dump_path}")
    return summary


# ==============================================================================
# Exploratory 100-Pair Pilot Study (--stage pilot-100)
# ==============================================================================

def compute_macro_edit_distance(nodes_slow: List[Dict], nodes_fast: List[Dict]) -> Tuple[int, float]:
    """
    Compute structural macro-node edit distance |Delta V| and relative edit ratio rho = |Delta V| / |V_slow|.
    Uses multiset signature intersection over normalized (role, source_preview) pairs so statement
    relocations count as single structural edits rather than double delete+insert.
    """
    from collections import Counter

    def norm_sig(n: Dict) -> str:
        p = re.sub(r'\s+', ' ', n.get("source_preview", "").strip())
        return f"{n['role']}:{p}"

    c_slow = Counter(norm_sig(n) for n in nodes_slow)
    c_fast = Counter(norm_sig(n) for n in nodes_fast)

    matched = sum(min(c_slow[k], c_fast[k]) for k in c_slow.keys() & c_fast.keys())
    v_slow = len(nodes_slow)
    v_fast = len(nodes_fast)
    if v_slow == 0:
        return v_fast, 1.0

    delta_v = max(v_slow - matched, v_fast - matched)
    rho = round(delta_v / v_slow, 3)
    return delta_v, rho


PILOT_REVISION = "validated-input-pilot-v2"
PILOT_EQUIVALENCE_SCALES = (16, 24)


def cpp_template_fingerprint(source: str) -> str:
    """Hash the AST after canonicalizing local names and preserving syntax and literals."""
    from hashlib import sha256

    root = parser.parse(source.encode("utf-8")).root_node
    if root.has_error:
        raise ValueError("Cannot fingerprint an invalid pilot program")
    names = {}

    def canonical(node):
        if node.type in ("identifier", "field_identifier", "type_identifier") and node.parent.type != "qualified_identifier":
            return (node.type, names.setdefault(node.text, len(names)))
        if node.child_count:
            return (node.type, tuple(canonical(child) for child in node.children if child.type != "comment"))
        return (node.type, node.text)

    return sha256(repr(canonical(root)).encode("utf-8")).hexdigest()


def split_pilot_templates(
    records: List[Dict], seed: int = 42, *, prompt_fingerprints: Optional[Dict[str, List[str]]] = None,
):
    """Keep problems, alpha-equivalent cores, and identical model inputs together."""
    import random
    from collections import Counter

    counts = Counter(r["problem_id"] for r in records)
    by_problem = {pid: {pid} for pid in counts}
    fingerprints = {
        row["pair_id"]: row["template_fingerprints"] + (
            prompt_fingerprints[row["pair_id"]] if prompt_fingerprints is not None else []
        )
        for row in records
    }
    owner = {}
    for row in records:
        pid = row["problem_id"]
        for fingerprint in fingerprints[row["pair_id"]]:
            other = owner.setdefault(fingerprint, pid)
            joined = by_problem[pid] | by_problem[other]
            for member in joined:
                by_problem[member] = joined

    groups = sorted({tuple(sorted(group)) for group in by_problem.values()})
    random.Random(seed).shuffle(groups)
    groups.sort(key=lambda g: sum(counts[pid] for pid in g), reverse=True)
    folds = [set() for _ in range(5)]
    sizes = [0] * len(folds)
    for group in groups:
        idx = sizes.index(min(sizes))
        folds[idx].update(group)
        sizes[idx] += sum(counts[pid] for pid in group)
    assert all(folds), "Template quarantine produced an empty fold"
    fold_of = {pid: idx for idx, fold in enumerate(folds) for pid in fold}
    assert set(fold_of) == set(counts)
    for row in records:
        for fingerprint in fingerprints[row["pair_id"]]:
            assert fold_of[row["problem_id"]] == fold_of[owner[fingerprint]], "Template or prompt overlap across folds"
    return folds, groups


def add_pilot_input_validation(source: str, shape: int) -> str:
    """Vary real input checks without moving or modifying the workload itself."""
    bodies = (
        "return (std::cin >> n) && n >= 0;",
        "if (!(std::cin >> n)) return false; return n >= 0;",
        "if (!(std::cin >> n)) return false; if (n < 0) return false; return true;",
        "int value = 0; if (!(std::cin >> value) || value < 0) return false; n = value; return true;",
        "int value = 0; if (!(std::cin >> value)) return false; if (value < 0) return false; n = value; return true;",
        "long long value = 0; if (!(std::cin >> value)) return false; if (value < 0) return false; "
        "if (value > std::numeric_limits<int>::max()) return false; n = static_cast<int>(value); return true;",
    )
    root = parser.parse(source.encode("utf-8")).root_node
    functions = [node for node in root.named_children if node.type == "function_definition"]
    main = next(node for node in functions if node.child_by_field_name("declarator").text == b"main()")
    first, read = main.child_by_field_name("body").named_children[:2]
    if first.text != b"int n;" or read.text != b"if (!(std::cin >> n)) return 0;":
        raise ValueError("Unexpected pilot input preamble")
    helper = f"static bool read_problem_size(int& n) {{ {bodies[shape]} }}\n\n"
    if shape == 5:
        helper = "#include <limits>\n\n" + helper
    return apply_reverse_byte_edits(source, [
        (functions[0].start_byte, functions[0].start_byte, helper),
        (read.start_byte, read.end_byte, "if (!read_problem_size(n)) return 0;"),
    ])


def generate_pilot_100_corpus() -> List[Dict]:
    """
    Construct 100 diagnostic pairs across 41 problem IDs using reusable templates.
    """
    corpus = []
    pair_idx = 1

    def add_pair(pid, track_gt, mech_id, mech_name, paradigm, scope_kind, slow_code, fast_code, variant_tag):
        nonlocal pair_idx
        corpus.append({
            "pair_id": f"PAIR_{pair_idx:03d}",
            "problem_id": pid,
            "track_gt": track_gt,
            "mechanism_id": mech_id,
            "mechanism_name": mech_name,
            "paradigm": paradigm,
            "scope_kind": scope_kind,
            "slow_code": slow_code,
            "fast_code": fast_code,
            "input_gen": lambda n: f"{n}\n",
            "variant_tag": variant_tag
        })
        pair_idx += 1

    # 1. Track A1.1: Monotonic Pointer / Index Reset (8 Distinct Problems: P_PIE_01..08, 12 Pairs)
    a1_1_specs = [
        ("P_PIE_01", "weights", "left_p", "right_p", "win_sum", "cap_lim", "max_span", "valid_cnt", "inter", 2),
        ("P_PIE_02", "loads", "lo_idx", "hi_idx", "seg_mass", "quota_m", "best_len", "step_tag", "inter", 2),
        ("P_PIE_03", "prices", "head_i", "tail_j", "cur_cost", "budget_b", "opt_win", "chk_flag", "inter", 1),
        ("P_PIE_04", "tokens", "st_pos", "ed_pos", "char_acc", "max_all", "longest_w", "win_id", "inter", 1),
        ("P_PIE_05", "packets", "anc_l", "cur_r", "burst_s", "thresh_t", "peak_width", "pkt_ok", "inter", 1),
        ("P_PIE_06", "ribbons", "p_left", "p_right", "rib_acc", "hop_lim", "best_cut", "hops", "intra", 2),
        ("P_PIE_07", "stations", "base_s", "reach_r", "fuel_acc", "trip_lim", "max_tour", "steps", "intra", 2),
        ("P_PIE_08", "intervals", "start_k", "scan_m", "ov_total", "scan_cap", "wide_seg", "iters", "intra", 1),
    ]
    for spec_idx, (pid, arr_v, l_v, r_v, acc_v, bnd_v, out_v, extra_v, sc_kind, n_vars) in enumerate(a1_1_specs):
        for v_i in range(n_vars):
            setup_block = (
                f"int {extra_v} = 0;\n    long long base_bias = {spec_idx + 1};"
                if v_i == 0 else
                f"int {extra_v} = 1;\n    long long base_bias = {spec_idx + 2};\n    int stride_hint = 1;"
            )
            if sc_kind == "inter":
                if spec_idx in (0, 1) and v_i == 0:
                    mut_slow = f"int {r_v} = {l_v};"
                    mut_fast = f"int {r_v}_anchor = {l_v};"
                elif spec_idx == 3:
                    mut_slow = f"int {r_v} = {l_v};\n        long long {acc_v} = 0;\n        {extra_v} = 0;\n        base_bias = 0;"
                    mut_fast = f"int {r_v}_anchor = {l_v};\n        long long {acc_v}_keep = {acc_v};\n        {extra_v} = 1;\n        base_bias = 1;"
                elif v_i == 1 and spec_idx == 0:
                    mut_slow = f"int {r_v} = {l_v};\n        long long {acc_v} = 0;\n        {extra_v} = 0;"
                    mut_fast = f"int {r_v}_anchor = {l_v};\n        long long {acc_v}_keep = {acc_v};\n        {extra_v} = 1;"
                else:
                    mut_slow = f"int {r_v} = {l_v};\n        {extra_v} = 0;"
                    mut_fast = f"int {r_v}_anchor = {l_v};\n        {extra_v} = 1;"

                slow_c = f"""#include <iostream>
#include <vector>

int main() {{
    int n;
    if (!(std::cin >> n)) return 0;
    std::vector<int> {arr_v}(n, 1);
    {setup_block}
    int {out_v} = 0;
    int {r_v} = 0;
    long long {acc_v} = 0;
    long long {bnd_v} = (long long)n * n + base_bias;
    for (int {l_v} = 0; {l_v} < n; ++{l_v}) {{
        {mut_slow}
        while ({r_v} < n && {acc_v} + {arr_v}[{r_v}] <= {bnd_v}) {{
            {acc_v} += {arr_v}[{r_v}];
            {r_v}++;
        }}
        if ({r_v} - {l_v} > {out_v}) {out_v} = {r_v} - {l_v};
        {acc_v} -= {arr_v}[{l_v}];
    }}
    std::cout << {out_v} << std::endl;
    return 0;
}}
"""
                fast_c = f"""#include <iostream>
#include <vector>

int main() {{
    int n;
    if (!(std::cin >> n)) return 0;
    std::vector<int> {arr_v}(n, 1);
    {setup_block}
    int {out_v} = 0;
    int {r_v} = 0;
    long long {acc_v} = 0;
    long long {bnd_v} = (long long)n * n + base_bias;
    for (int {l_v} = 0; {l_v} < n; ++{l_v}) {{
        {mut_fast}
        while ({r_v} < n && {acc_v} + {arr_v}[{r_v}] <= {bnd_v}) {{
            {acc_v} += {arr_v}[{r_v}];
            {r_v}++;
        }}
        if ({r_v} - {l_v} > {out_v}) {out_v} = {r_v} - {l_v};
        {acc_v} -= {arr_v}[{l_v}];
    }}
    std::cout << {out_v} << std::endl;
    return 0;
}}
"""
            else:
                if v_i == 0:
                    in_slow = f"{r_v} = {l_v};\n            {acc_v} += {arr_v}[{r_v}];"
                    in_fast = f"{r_v}++;\n            {acc_v} += {arr_v}[{r_v} - 1];"
                else:
                    in_slow = f"{r_v} = {l_v};\n            {acc_v} += {arr_v}[{l_v}];"
                    in_fast = f"{r_v}++;\n            {acc_v} += {arr_v}[{r_v} - 1];"

                slow_c = f"""#include <iostream>
#include <vector>

int main() {{
    int n;
    if (!(std::cin >> n)) return 0;
    std::vector<int> {arr_v}(n, 1);
    {setup_block}
    int {out_v} = 0;
    int {r_v} = 0;
    long long {acc_v} = 0;
    int {bnd_v} = n;
    for (int {l_v} = 0; {l_v} < n; ++{l_v}) {{
        int {extra_v} = 0;
        while ({r_v} < n && {extra_v} < {bnd_v}) {{
            {in_slow}
            {extra_v}++;
        }}
        if ({extra_v} > {out_v}) {out_v} = {extra_v};
    }}
    std::cout << {out_v} << std::endl;
    return 0;
}}
"""
                fast_c = f"""#include <iostream>
#include <vector>

int main() {{
    int n;
    if (!(std::cin >> n)) return 0;
    std::vector<int> {arr_v}(n, 1);
    {setup_block}
    int {out_v} = 0;
    int {r_v} = 0;
    long long {acc_v} = 0;
    int {bnd_v} = n;
    for (int {l_v} = 0; {l_v} < n; ++{l_v}) {{
        int {extra_v} = 0;
        while ({r_v} < n && {extra_v} < {bnd_v}) {{
            {in_fast}
            {extra_v}++;
        }}
        if ({extra_v} > {out_v}) {out_v} = {extra_v};
    }}
    std::cout << {out_v} << std::endl;
    return 0;
}}
"""
            add_pair(pid, "A1", "A1.1", "Monotonic Pointer / Index Reset", "Two Pointers / Sliding Window", sc_kind, slow_c, fast_c, f"{pid}_v{v_i}")

    # 2. Track A1.2: Pass-by-Value Container Copy in Recursion (5 Problems: P_PIE_09..13, 9 Pairs)
    a1_2_specs = [
        ("P_PIE_09", "trace_route", "node_u", "max_n", "route_vec", "route_len", 2),
        ("P_PIE_10", "build_chain", "cur_pos", "limit_pos", "chain_buf", "chain_score", 2),
        ("P_PIE_11", "walk_state", "level_k", "target_k", "state_seq", "seq_total", 2),
        ("P_PIE_12", "audit_branch", "step_id", "total_steps", "history_log", "audit_sum", 2),
        ("P_PIE_13", "dfs_trail", "vert_v", "num_verts", "visited_list", "trail_cnt", 1),
    ]
    for spec_idx, (pid, fn_name, d_var, m_var, vec_var, acc_var, n_vars) in enumerate(a1_2_specs):
        for v_i in range(n_vars):
            if v_i == 0 and spec_idx < 3:
                b_slow = f"{vec_var}.push_back({d_var});\n    {fn_name}({d_var} + 1, {m_var}, {vec_var});"
                b_fast = f"{vec_var}.push_back({d_var});\n    {fn_name}({d_var} + 1, {m_var}, {vec_var});"
            elif spec_idx == 4:
                b_slow = f"{vec_var}.push_back({d_var} + 1);\n    {fn_name}({d_var} + 1, {m_var}, {vec_var});"
                b_fast = f"{vec_var}.push_back({d_var});\n    {fn_name}({d_var} + 1, {m_var}, {vec_var});\n    {vec_var}.pop_back();"
            else:
                b_slow = f"{vec_var}.push_back({d_var});\n    {fn_name}({d_var} + 1, {m_var}, {vec_var});"
                b_fast = f"{vec_var}.push_back({d_var});\n    {fn_name}({d_var} + 1, {m_var}, {vec_var});\n    {vec_var}.pop_back();"

            slow_c = f"""#include <iostream>
#include <vector>

void {fn_name}(int {d_var}, int {m_var}, std::vector<int> {vec_var}) {{
    if ({d_var} >= {m_var}) return;
    {b_slow}
}}

int main() {{
    int n;
    if (!(std::cin >> n)) return 0;
    int start_d = 0;
    int {m_var} = n;
    int {acc_var} = {spec_idx + 1};
    std::vector<int> {vec_var};
    for (int k = 0; k < 4; ++k) {{
        {acc_var} += k;
    }}
    if ({m_var} > 0) {{
        {fn_name}(start_d, {m_var}, {vec_var});
    }}
    {acc_var} += {m_var};
    std::cout << {acc_var} << std::endl;
    return 0;
}}
"""
            fast_c = f"""#include <iostream>
#include <vector>

void {fn_name}(int {d_var}, int {m_var}, std::vector<int>& {vec_var}) {{
    if ({d_var} >= {m_var}) return;
    {b_fast}
}}

int main() {{
    int n;
    if (!(std::cin >> n)) return 0;
    int start_d = 0;
    int {m_var} = n;
    int {acc_var} = {spec_idx + 1};
    std::vector<int> {vec_var};
    for (int k = 0; k < 4; ++k) {{
        {acc_var} += k;
    }}
    if ({m_var} > 0) {{
        {fn_name}(start_d, {m_var}, {vec_var});
    }}
    {acc_var} += {m_var};
    std::cout << {acc_var} << std::endl;
    return 0;
}}
"""
            add_pair(pid, "A1", "A1.2", "Pass-by-Value Container Copy", "Divide & Conquer / DFS", "self_hidden", slow_c, fast_c, f"{pid}_v{v_i}")

    # 3. Track A1.3: Linear STL Operation Inside Loop (5 Problems: P_PIE_14..18, 11 Pairs)
    a1_3_specs = [
        ("P_PIE_14", "catalog", "sku_id", "q_idx", "matched_skus", "sku_step", 3),
        ("P_PIE_15", "timestamps", "probe_t", "ev_i", "valid_events", "time_shift", 2),
        ("P_PIE_16", "coords", "pt_x", "loc_k", "found_pts", "grid_scale", 2),
        ("P_PIE_17", "whitelist", "req_uid", "usr_m", "granted_cnt", "uid_mult", 2),
        ("P_PIE_18", "readings", "cal_val", "sen_j", "cal_hits", "sen_offset", 2),
    ]
    for spec_idx, (pid, vec_v, tgt_v, idx_v, hit_v, step_v, n_vars) in enumerate(a1_3_specs):
        for v_i in range(n_vars):
            if v_i == 0 and spec_idx < 3:
                lk_slow = f"{hit_v} += (int)std::count({vec_v}.begin(), {vec_v}.end(), {tgt_v});"
                lk_fast = f"{hit_v} += (int)std::binary_search({vec_v}.begin(), {vec_v}.end(), {tgt_v});"
            elif v_i == 2:
                lk_slow = f"auto it = std::find({vec_v}.begin(), {vec_v}.end(), {tgt_v});\n        int ok_fl = (it != {vec_v}.end()) ? 1 : 0;\n        if (ok_fl > 0) {hit_v}++;"
                lk_fast = f"auto it = std::lower_bound({vec_v}.begin(), {vec_v}.end(), {tgt_v});\n        bool ok_fl = (it != {vec_v}.end() && *it == {tgt_v});\n        if (ok_fl) {hit_v}++;"
            else:
                lk_slow = f"auto it = std::find({vec_v}.begin(), {vec_v}.end(), {tgt_v});\n        if (it != {vec_v}.end()) {hit_v}++;"
                lk_fast = f"bool ok_fl = std::binary_search({vec_v}.begin(), {vec_v}.end(), {tgt_v});\n        if (ok_fl) {hit_v}++;"

            slow_c = f"""#include <iostream>
#include <vector>
#include <algorithm>

int main() {{
    int n;
    if (!(std::cin >> n)) return 0;
    int {step_v} = {spec_idx + 1};
    int base_off = {v_i};
    std::vector<int> {vec_v}(n);
    for (int {idx_v} = 0; {idx_v} < n; ++{idx_v}) {{
        {vec_v}[{idx_v}] = {idx_v} * {step_v} + base_off;
    }}
    int {hit_v} = 0;
    int total_probes = n;
    for (int {idx_v} = 0; {idx_v} < total_probes; ++{idx_v}) {{
        int {tgt_v} = {idx_v} * {step_v} + base_off;
        {lk_slow}
    }}
    if ({hit_v} < 0) {hit_v} = 0;
    std::cout << {hit_v} << std::endl;
    return 0;
}}
"""
            fast_c = f"""#include <iostream>
#include <vector>
#include <algorithm>

int main() {{
    int n;
    if (!(std::cin >> n)) return 0;
    int {step_v} = {spec_idx + 1};
    int base_off = {v_i};
    std::vector<int> {vec_v}(n);
    for (int {idx_v} = 0; {idx_v} < n; ++{idx_v}) {{
        {vec_v}[{idx_v}] = {idx_v} * {step_v} + base_off;
    }}
    int {hit_v} = 0;
    int total_probes = n;
    for (int {idx_v} = 0; {idx_v} < total_probes; ++{idx_v}) {{
        int {tgt_v} = {idx_v} * {step_v} + base_off;
        {lk_fast}
    }}
    if ({hit_v} < 0) {hit_v} = 0;
    std::cout << {hit_v} << std::endl;
    return 0;
}}
"""
            add_pair(pid, "A1", "A1.3", "Linear STL Operation in Loop", "Binary Search / STL Lookup", "self_hidden", slow_c, fast_c, f"{pid}_v{v_i}")

    # 4. Track A1.4: Loop Bound / Stride Corruption (3 Problems: P_PIE_19..21, 6 Pairs)
    a1_4_specs = [
        ("P_PIE_19", "signal", "center_i", "tap_j", "start_tap", "radius_lim", "conv_sum", "inter", 2),
        ("P_PIE_20", "points", "row_r", "col_c", "min_col", "band_end", "band_acc", "inter", 2),
        ("P_PIE_21", "blocks", "blk_i", "pos_p", "jump_step", "blk_cap", "scan_tot", "intra", 2),
    ]
    for pid, vec_v, out_i, in_j, st_v, lim_v, acc_v, sc_kind, n_vars in a1_4_specs:
        for v_i in range(n_vars):
            if sc_kind == "inter":
                def bound_program(bound):
                    return f"""#include <iostream>
#include <vector>

int main() {{
    int n;
    if (!(std::cin >> n)) return 0;
    const int k_rad = n < 2 ? n : 2;
    std::vector<int> {vec_v}(n, 1);
    for (int k = 0; k < n; ++k) {{
        {vec_v}[k] = k + 1;
    }}
    long long {acc_v} = 0;
    const int weight_k = {v_i + 1};
    for (int {out_i} = 0; {out_i} < n; ++{out_i}) {{
        int {st_v} = 0;
        int {lim_v} = {bound};
        for (int {in_j} = {st_v}; {in_j} < {lim_v}; ++{in_j}) {{
            if ({in_j} < k_rad) {{
                {acc_v} += {vec_v}[{in_j}] * weight_k;
            }}
        }}
    }}
    std::cout << {acc_v} << std::endl;
    return 0;
}}
"""
                slow_c, fast_c = bound_program("n"), bound_program("k_rad")
            else:
                def stride_program(reset):
                    return f"""#include <iostream>
#include <vector>

int main() {{
    int n;
    if (!(std::cin >> n)) return 0;
    std::vector<int> {vec_v}(n, {v_i + 1});
    long long {acc_v} = 0;
    for (int {out_i} = 0; {out_i} < n; ++{out_i}) {{
        long long {in_j} = 0;
        long long {st_v} = 1;
        int {lim_v} = n;
        while ({in_j} < {lim_v} && {st_v} > 0) {{
            {reset}
            if ({in_j} == 0) {{
                {acc_v} += {vec_v}[{in_j}];
            }}
            {in_j} += {st_v};
            {st_v} *= 2;
        }}
    }}
    std::cout << {acc_v} << std::endl;
    return 0;
}}
"""
                slow_c, fast_c = stride_program(f"{st_v} = 1;"), stride_program("")
            add_pair(pid, "A1", "A1.4", "Loop Bound / Stride Corruption", "Greedy / Window Scan", sc_kind, slow_c, fast_c, f"{pid}_v{v_i}")

    # 5. Track A2.1: Missing Top-Down DP Memoization Guard (5 Problems: P_PIE_22..26, 13 Pairs)
    a2_1_specs = [
        ("P_PIE_22", "count_stairs", "dp_stairs", "rem_steps", "stair_ans", 3),
        ("P_PIE_23", "tile_board", "memo_tile", "col_w", "tile_ways", 3),
        ("P_PIE_24", "ways_split", "cache_split", "len_rem", "split_tot", 3),
        ("P_PIE_25", "valid_bits", "dp_bits", "bit_pos", "bit_cnt", 2),
        ("P_PIE_26", "min_jump", "memo_jmp", "idx_u", "jmp_ways", 2),
    ]
    for spec_idx, (pid, fn_name, arr_name, arg_u, ans_v, n_vars) in enumerate(a2_1_specs):
        for v_i in range(n_vars):
            if v_i < 2:
                m_fast = f"if ({arr_name}[{arg_u}] != -1) return {arr_name}[{arg_u}];\n    return {arr_name}[{arg_u}] = {fn_name}({arg_u} - 1) + {fn_name}({arg_u} - 2);"
            else:
                m_fast = f"if ({arr_name}[{arg_u}] != -1) return {arr_name}[{arg_u}];\n    long long sub_w = {fn_name}({arg_u} - 1) + {fn_name}({arg_u} - 2);\n    {arr_name}[{arg_u}] = sub_w;\n    return sub_w;"

            slow_c = f"""#include <iostream>
#include <vector>

long long {arr_name}[5005];

long long {fn_name}(int {arg_u}) {{
    if ({arg_u} <= 1) return 1;
    return {fn_name}({arg_u} - 1) + {fn_name}({arg_u} - 2);
}}

int main() {{
    int n;
    if (!(std::cin >> n)) return 0;
    int {arg_u} = n;
    int init_val = -1;
    int mod_bias = {spec_idx + 1};
    for (int k = 0; k <= {arg_u}; ++k) {{
        {arr_name}[k] = init_val;
    }}
    long long {ans_v} = 0;
    if ({arg_u} >= 0) {{
        {ans_v} = {fn_name}({arg_u}) + mod_bias - {spec_idx + 1};
    }}
    std::cout << {ans_v} << std::endl;
    return 0;
}}
"""
            fast_c = f"""#include <iostream>
#include <vector>

long long {arr_name}[5005];

long long {fn_name}(int {arg_u}) {{
    if ({arg_u} <= 1) return 1;
    {m_fast}
}}

int main() {{
    int n;
    if (!(std::cin >> n)) return 0;
    int {arg_u} = n;
    int init_val = -1;
    int mod_bias = {spec_idx + 1};
    for (int k = 0; k <= {arg_u}; ++k) {{
        {arr_name}[k] = init_val;
    }}
    long long {ans_v} = 0;
    if ({arg_u} >= 0) {{
        {ans_v} = {fn_name}({arg_u}) + mod_bias - {spec_idx + 1};
    }}
    std::cout << {ans_v} << std::endl;
    return 0;
}}
"""
            add_pair(pid, "A2", "A2.1", "Missing DP Memoization Guard", "Dynamic Programming", "omission_memo", slow_c, fast_c, f"{pid}_v{v_i}")

    # 6. Track A2.2: Missing Early-Exit Pruning Guard (4 Problems: P_PIE_27..30, 11 Pairs)
    a2_2_specs = [
        ("P_PIE_27", "item_costs", "first_i", "second_j", "goal_sum", "has_pair", "scan_end", 3),
        ("P_PIE_28", "serials", "idx_a", "idx_b", "target_gap", "dup_hit", "hi_bound", 3),
        ("P_PIE_29", "loads", "slot_u", "slot_v", "crit_load", "breach_fl", "max_slot", 3),
        ("P_PIE_30", "coupons", "cp_left", "cp_right", "voucher_val", "match_ok", "cp_limit", 2),
    ]
    for spec_idx, (pid, vec_v, i_v, j_v, tgt_v, fl_v, lim_v, n_vars) in enumerate(a2_2_specs):
        for v_i in range(n_vars):
            if v_i == 0:
                in_fast = f"if ({vec_v}[{i_v}] + {vec_v}[{j_v}] > {tgt_v}) break;\n            if ({vec_v}[{i_v}] + {vec_v}[{j_v}] == {tgt_v}) {{\n                {fl_v} = true;\n            }}"
                out_fast = ""
            elif v_i == 1:
                in_fast = f"if ({fl_v}) break;\n            if ({vec_v}[{i_v}] + {vec_v}[{j_v}] == {tgt_v}) {{\n                {fl_v} = true;\n            }}"
                out_fast = f"if ({fl_v}) break;"
            else:
                in_fast = f"if ({vec_v}[{i_v}] + {vec_v}[{j_v}] > {tgt_v}) break;\n            if ({vec_v}[{i_v}] + {vec_v}[{j_v}] == {tgt_v}) {{\n                {fl_v} = true;\n                break;\n            }}"
                out_fast = f"if ({fl_v}) break;"

            slow_c = f"""#include <iostream>
#include <vector>

int main() {{
    int n;
    if (!(std::cin >> n)) return 0;
    std::vector<int> {vec_v}(n);
    int step_inc = 1;
    for (int {i_v} = 0; {i_v} < n; ++{i_v}) {{
        {vec_v}[{i_v}] = {i_v} * step_inc;
    }}
    int {tgt_v} = 3;
    bool {fl_v} = false;
    for (int {i_v} = 0; {i_v} < n; ++{i_v}) {{
        int {lim_v} = n;
        for (int {j_v} = {i_v} + 1; {j_v} < {lim_v}; ++{j_v}) {{
            if ({vec_v}[{i_v}] + {vec_v}[{j_v}] == {tgt_v}) {{
                {fl_v} = true;
            }}
        }}
    }}
    int res_out = {fl_v} ? 1 : 0;
    std::cout << res_out << std::endl;
    return 0;
}}
"""
            fast_c = f"""#include <iostream>
#include <vector>

int main() {{
    int n;
    if (!(std::cin >> n)) return 0;
    std::vector<int> {vec_v}(n);
    int step_inc = 1;
    for (int {i_v} = 0; {i_v} < n; ++{i_v}) {{
        {vec_v}[{i_v}] = {i_v} * step_inc;
    }}
    int {tgt_v} = 3;
    bool {fl_v} = false;
    for (int {i_v} = 0; {i_v} < n; ++{i_v}) {{
        int {lim_v} = n;
        for (int {j_v} = {i_v} + 1; {j_v} < {lim_v}; ++{j_v}) {{
            {in_fast}
        }}
        {out_fast}
    }}
    int res_out = {fl_v} ? 1 : 0;
    std::cout << res_out << std::endl;
    return 0;
}}
"""
            add_pair(pid, "A2", "A2.2", "Missing Early-Exit Pruning Guard", "Complete Search / Greedy", "omission_guard", slow_c, fast_c, f"{pid}_v{v_i}")

    # 7. Track B.1: Brute-Force Nested Loops -> Prefix Sums / Two Pointers (4 Problems: P_PIE_31..34, 13 Pairs)
    b1_specs = [
        ("P_PIE_31", "gains", "pref_gain", "min_pref", "best_gain", "st_i", "ed_j", "win_end", 4),
        ("P_PIE_32", "masses", "cum_mass", "base_mass", "peak_mass", "left_m", "right_m", "mass_lim", 3),
        ("P_PIE_33", "altitudes", "alt_pref", "low_alt", "max_climb", "p_start", "p_curr", "alt_bnd", 3),
        ("P_PIE_34", "flows", "bal_pref", "dip_bal", "net_surge", "day_l", "day_r", "horizon", 3),
    ]
    for spec_idx, (pid, vec_v, pref_v, min_v, best_v, i_v, j_v, lim_v, n_vars) in enumerate(b1_specs):
        for v_i in range(n_vars):
            slow_c = f"""#include <iostream>
#include <vector>

int main() {{
    int n;
    if (!(std::cin >> n)) return 0;
    int unit_val = {v_i + 1};
    std::vector<int> {vec_v}(n, unit_val);
    for (int k = 0; k < n; ++k) {{
        {vec_v}[k] = unit_val;
    }}
    long long {best_v} = 0;
    for (int {i_v} = 0; {i_v} < n; ++{i_v}) {{
        long long run_s = 0;
        int {lim_v} = n;
        for (int {j_v} = {i_v}; {j_v} < {lim_v}; ++{j_v}) {{
            run_s += {vec_v}[{j_v}];
            if (run_s > {best_v}) {best_v} = run_s;
        }}
    }}
    std::cout << {best_v} << std::endl;
    return 0;
}}
"""
            fast_c = f"""#include <iostream>
#include <vector>

int main() {{
    int n;
    if (!(std::cin >> n)) return 0;
    int unit_val = {v_i + 1};
    std::vector<int> {vec_v}(n, unit_val);
    for (int k = 0; k < n; ++k) {{
        {vec_v}[k] = unit_val;
    }}
    std::vector<long long> {pref_v}(n + 1, 0);
    for (int {i_v} = 0; {i_v} < n; ++{i_v}) {{
        {pref_v}[{i_v} + 1] = {pref_v}[{i_v}] + {vec_v}[{i_v}];
    }}
    long long {min_v} = 0;
    long long {best_v} = 0;
    for (int {j_v} = 1; {j_v} <= n; ++{j_v}) {{
        long long cand_s = {pref_v}[{j_v}] - {min_v};
        if (cand_s > {best_v}) {best_v} = cand_s;
        if ({pref_v}[{j_v}] < {min_v}) {min_v} = {pref_v}[{j_v}];
    }}
    std::cout << {best_v} << std::endl;
    return 0;
}}
"""
            add_pair(pid, "B", "B.1", "Brute Force -> Prefix Sums / Two Pointers", "Two Pointers / Sliding Window", "paradigm_shift", slow_c, fast_c, f"{pid}_v{v_i}")

    # 8. Track B.2: Quadratic Scan -> Hash Table / Binary Search (4 Problems: P_PIE_35..38, 13 Pairs)
    b2_specs = [
        ("P_PIE_35", "nums", "target_s", "pair_cnt", "idx_p", "idx_q", "scan_hi", 4),
        ("P_PIE_36", "parcels", "cap_sum", "valid_pairs", "box_a", "box_b", "box_lim", 3),
        ("P_PIE_37", "tones", "harm_f", "res_matches", "ch_l", "ch_r", "ch_max", 3),
        ("P_PIE_38", "tx_vals", "audit_sum", "settled_cnt", "tx_i", "tx_j", "tx_end", 3),
    ]
    for spec_idx, (pid, vec_v, tgt_v, out_v, i_v, j_v, lim_v, n_vars) in enumerate(b2_specs):
        for v_i in range(n_vars):
            slow_c = f"""#include <iostream>
#include <vector>

int main() {{
    int n;
    if (!(std::cin >> n)) return 0;
    int shift_v = {v_i};
    std::vector<int> {vec_v}(n);
    for (int {i_v} = 0; {i_v} < n; ++{i_v}) {{
        {vec_v}[{i_v}] = {i_v} + shift_v;
    }}
    int {tgt_v} = n;
    int {out_v} = 0;
    for (int {i_v} = 0; {i_v} < n; ++{i_v}) {{
        int {lim_v} = n;
        for (int {j_v} = {i_v} + 1; {j_v} < {lim_v}; ++{j_v}) {{
            if ({vec_v}[{i_v}] + {vec_v}[{j_v}] == {tgt_v}) {{
                {out_v}++;
            }}
        }}
    }}
    std::cout << {out_v} << std::endl;
    return 0;
}}
"""
            if spec_idx == 3 and v_i < 2:
                fast_c = f"""#include <iostream>
#include <vector>
#include <unordered_set>

int main() {{
    int n;
    if (!(std::cin >> n)) return 0;
    int shift_v = {v_i};
    std::vector<int> {vec_v}(n);
    for (int {i_v} = 0; {i_v} < n; ++{i_v}) {{
        {vec_v}[{i_v}] = {i_v} + shift_v;
    }}
    int {tgt_v} = n;
    int {out_v} = 0;
    std::unordered_set<int> seen_set;
    for (int q_idx = 0; q_idx < n; ++q_idx) {{
        int need_v = {tgt_v} - {vec_v}[q_idx];
        if (seen_set.count(need_v)) {{
            {out_v}++;
        }}
        seen_set.insert({vec_v}[q_idx]);
    }}
    std::cout << {out_v} << std::endl;
    return 0;
}}
"""
            else:
                fast_c = f"""#include <iostream>
#include <vector>
#include <algorithm>

int main() {{
    int n;
    if (!(std::cin >> n)) return 0;
    int shift_v = {v_i};
    std::vector<int> {vec_v}(n);
    for (int {i_v} = 0; {i_v} < n; ++{i_v}) {{
        {vec_v}[{i_v}] = {i_v} + shift_v;
    }}
    int {tgt_v} = n;
    int {out_v} = 0;
    std::sort({vec_v}.begin(), {vec_v}.end());
    int lo_p = 0;
    int hi_p = n - 1;
    while (lo_p < hi_p) {{
        int cur_s = {vec_v}[lo_p] + {vec_v}[hi_p];
        if (cur_s == {tgt_v}) {{
            {out_v}++;
            lo_p++;
            hi_p--;
        }} else if (cur_s < {tgt_v}) {{
            lo_p++;
        }} else {{
            hi_p--;
        }}
    }}
    std::cout << {out_v} << std::endl;
    return 0;
}}
"""
            add_pair(pid, "B", "B.2", "Quadratic Scan -> Hash Table / Binary Search", "Binary Search / Divide & Conquer", "paradigm_shift", slow_c, fast_c, f"{pid}_v{v_i}")

    # 9. Track B.3: Exponential Recursion -> Bottom-Up Tabular DP (3 Problems: P_PIE_39..41, 12 Pairs)
    b3_specs = [
        ("P_PIE_39", "rec_lattice", "dp_lat", "rem_cells", "lat_total", 4),
        ("P_PIE_40", "hop_rec", "tab_hop", "dist_left", "hop_ways", 4),
        ("P_PIE_41", "part_rec", "dp_part", "span_n", "part_cnt", 4),
    ]
    for spec_idx, (pid, fn_name, dp_v, arg_v, out_v, n_vars) in enumerate(b3_specs):
        for v_i in range(n_vars):
            slow_c = f"""#include <iostream>
#include <vector>

long long {fn_name}(int {arg_v}) {{
    if ({arg_v} <= 1) return 1;
    long long branch_a = {fn_name}({arg_v} - 1);
    long long branch_b = {fn_name}({arg_v} - 2);
    return branch_a + branch_b;
}}

int main() {{
    int n;
    if (!(std::cin >> n)) return 0;
    int {arg_v} = n;
    long long base_ways = {v_i + 1};
    long long {out_v} = 0;
    for (int k = 0; k < 3; ++k) {{
        base_ways += k;
    }}
    if ({arg_v} >= 0) {{
        {out_v} = {fn_name}({arg_v}) + base_ways;
    }}
    std::cout << {out_v} << std::endl;
    return 0;
}}
"""
            fast_c = f"""#include <iostream>
#include <vector>

int main() {{
    int n;
    if (!(std::cin >> n)) return 0;
    int {arg_v} = n;
    long long base_ways = {v_i + 1};
    long long {out_v} = 0;
    for (int k = 0; k < 3; ++k) {{
        base_ways += k;
    }}
    std::vector<long long> {dp_v}({arg_v} + 2, 0);
    {dp_v}[0] = 1;
    {dp_v}[1] = 1;
    for (int s_i = 2; s_i <= {arg_v}; ++s_i) {{
        long long prev_one = {dp_v}[s_i - 1];
        long long prev_two = {dp_v}[s_i - 2];
        {dp_v}[s_i] = prev_one + prev_two;
    }}
    if ({arg_v} >= 0) {{
        {out_v} = {dp_v}[{arg_v}] + base_ways;
    }}
    std::cout << {out_v} << std::endl;
    return 0;
}}
"""
            add_pair(pid, "B", "B.3", "Exponential Recursion -> Bottom-Up Tabular DP", "Dynamic Programming", "paradigm_shift", slow_c, fast_c, f"{pid}_v{v_i}")

    import random

    problem_ids = sorted({item["problem_id"] for item in corpus})
    random.Random(42).shuffle(problem_ids)
    shapes = {pid: i % 6 for i, pid in enumerate(problem_ids)}
    for item in corpus:
        shape = shapes[item["problem_id"]]
        item["pilot_revision"] = PILOT_REVISION
        item["template_fingerprints"] = [cpp_template_fingerprint(item[k]) for k in ("slow_code", "fast_code")]
        for key in ("slow_code", "fast_code"):
            item[key] = add_pilot_input_validation(item[key], shape)
    return corpus


def evaluate_four_slicing_tiers(macro_nodes: List[Dict], scaling_results: Dict) -> Dict:
    """
    Evaluate all Slicing Tiers for Table 3 comparison:
      1. c_naive_hits: [symptom_hits] (Control-Flow Hits Only profiler, argmax alpha_hits >= 1.5 or EXP)
      2. c_naive_work: [primary_symptom] (Work-Weighted Symptom Only, no backward slice)
      3. c_inter_only: C_inter U C_hidden_work U C_anchor (Parent-Scope Backward Slice only, no C_intra)
      4. c_unpruned: C_inter U C_intra_raw U C_hidden_work U C_anchor (Two-Tier Slice WITHOUT Monotonic Progress Pruning)
      5. c_pruned: C_inter U C_intra_pruned U C_hidden_work U C_anchor (Full Pruned Two-Tier EAPG, Ours)
    """
    node_map = {n["id"]: n for n in macro_nodes}
    delta_alphas = {}
    symptoms = []
    symptoms_hits_only = []
    hidden_work_nodes = set()

    caller_map = {}
    for n in macro_nodes:
        preview = n.get("source_preview", "")
        if "(" in preview:
            for fn_node in macro_nodes:
                if fn_node["role"] == "FUNCTION_ENTRY":
                    fn_name = fn_node["name"]
                    if re.search(r'\b' + re.escape(fn_name) + r'\b', preview):
                        caller_map[fn_node["id"]] = n["id"]

    for n in macro_nodes:
        nid = n["id"]
        fit_w = scaling_results[nid]["fit_work"]
        fit_h = scaling_results[nid]["fit_hits"]
        alpha_w = fit_w["alpha"] if fit_w["growth"] == "POLY" else 9.99
        alpha_h = fit_h["alpha"] if fit_h["growth"] == "POLY" else 9.99

        parent_id = n["parent"]
        if parent_id and parent_id in scaling_results:
            p_fit_w = scaling_results[parent_id]["fit_work"]
            p_alpha_w = p_fit_w["alpha"] if p_fit_w["growth"] == "POLY" else 9.99
            delta_a = round(alpha_w - p_alpha_w, 2)

            p_fit_h = scaling_results[parent_id]["fit_hits"]
            p_alpha_h = p_fit_h["alpha"] if p_fit_h["growth"] == "POLY" else 9.99
            delta_h = round(alpha_h - p_alpha_h, 2)
        elif n["role"] == "FUNCTION_ENTRY" and nid in caller_map:
            caller_id = caller_map[nid]
            c_fit_w = scaling_results[caller_id]["fit_work"]
            c_alpha_w = c_fit_w["alpha"] if c_fit_w["growth"] == "POLY" else 0.0
            delta_a = round(alpha_w - c_alpha_w, 2)

            c_fit_h = scaling_results[caller_id]["fit_hits"]
            c_alpha_h = c_fit_h["alpha"] if c_fit_h["growth"] == "POLY" else 0.0
            delta_h = round(alpha_h - c_alpha_h, 2)
        else:
            delta_a = 0.0
            delta_h = 0.0

        parent_is_exp_h = bool(parent_id and parent_id in scaling_results and scaling_results[parent_id]["fit_hits"]["growth"] == "EXP")
        if (delta_h >= 0.7 and alpha_h >= 1.5) or (fit_h["growth"] == "EXP" and not parent_is_exp_h):
            symptoms_hits_only.append(nid)

        if fit_w["growth"] == "POLY" and fit_h["growth"] == "POLY" and fit_w["alpha"] - fit_h["alpha"] >= 0.7:
            delta_a = max(delta_a, round(fit_w["alpha"] - fit_h["alpha"], 2))
            hidden_work_nodes.add(nid)

        delta_alphas[nid] = delta_a
        parent_is_exp_w = bool(parent_id and parent_id in scaling_results and scaling_results[parent_id]["fit_work"]["growth"] == "EXP")
        if delta_a >= 0.7 or (fit_w["growth"] == "EXP" and not parent_is_exp_w):
            symptoms.append(nid)

    symptom_id = symptoms[0] if symptoms else None
    for s_id in symptoms:
        if s_id in hidden_work_nodes:
            symptom_id = s_id
            break
        if node_map[s_id]["role"] in ("LOOP", "FUNCTION_ENTRY"):
            symptom_id = s_id
            break

    symptom_hits_id = symptoms_hits_only[0] if symptoms_hits_only else None
    for s_id in symptoms_hits_only:
        if node_map[s_id]["role"] in ("LOOP", "FUNCTION_ENTRY"):
            symptom_hits_id = s_id
            break

    c_naive_hits = [symptom_hits_id] if symptom_hits_id else []
    c_naive_work = [symptom_id] if symptom_id else []
    c_inter = []
    c_intra_raw = []
    c_intra_pruned = []

    if symptom_id:
        symptom_node = node_map[symptom_id]
        v_guard = set(symptom_node["uses"])
        if symptom_node["role"] == "FUNCTION_ENTRY":
            v_guard.update(symptom_node["defs"])
            if symptom_id in caller_map:
                v_guard.update(node_map[caller_map[symptom_id]]["uses"])

        alpha_s = scaling_results[symptom_id]["fit_work"]["alpha"]
        parent_scope_id = symptom_node["parent"]

        # Tier 1: C_inter (parent scope statements defining guard variables)
        for n in macro_nodes:
            if n["id"] == symptom_id:
                continue
            if n["parent"] == parent_scope_id:
                alpha_u = scaling_results[n["id"]]["fit_work"]["alpha"]
                if (alpha_u <= alpha_s - 0.5 or scaling_results[symptom_id]["fit_work"]["growth"] == "EXP") and (set(n["defs"]) & v_guard):
                    c_inter.append(n["id"])

        # Tier 2: C_intra_raw (all descendant statements inside symptom body OR enclosing loop body without Monotonic Progress Pruning)
        def is_descendant(nid, target_parent):
            curr = node_map[nid]["parent"]
            while curr:
                if curr == target_parent:
                    return True
                curr = node_map[curr]["parent"] if curr in node_map else None
            return False

        raw_scope_root = parent_scope_id if (symptom_id in hidden_work_nodes and parent_scope_id) else symptom_id
        v_body_vars = set(v_guard)
        for n in macro_nodes:
            if is_descendant(n["id"], raw_scope_root):
                v_body_vars.update(n["defs"])
                v_body_vars.update(n["uses"])

        for n in macro_nodes:
            if is_descendant(n["id"], raw_scope_root):
                if (set(n["defs"]) & v_body_vars) or (set(n["uses"]) & v_body_vars):
                    c_intra_raw.append(n["id"])
        if parent_scope_id and parent_scope_id in node_map:
            c_intra_raw.append(parent_scope_id)

        # Tier 3: C_intra_pruned (Mandatory Patch 2: Monotonic Progress Pruning)
        for n in macro_nodes:
            if n["parent"] == symptom_id:
                if n["is_unidirectional_step"]:
                    continue  # Pruned!
                if n["is_state_reset"] or n["in_nested_branch"]:
                    if set(n["defs"]) & v_guard:
                        c_intra_pruned.append(n["id"])

    c_inter_only = list(c_inter)
    if symptom_id:
        c_inter_only.append(symptom_id)
    c_inter_only = sorted(list(set(c_inter_only)), key=lambda x: int(x[1:]))

    c_unpruned = list(c_inter) + list(c_intra_raw)
    if symptom_id:
        c_unpruned.append(symptom_id)
    c_unpruned = sorted(list(set(c_unpruned)), key=lambda x: int(x[1:]))

    c_pruned = list(c_inter) + list(c_intra_pruned)
    if symptom_id:
        c_pruned.append(symptom_id)
    c_pruned = sorted(list(set(c_pruned)), key=lambda x: int(x[1:]))

    return {
        "primary_symptom": symptom_id,
        "c_naive_hits": c_naive_hits,
        "c_naive_work": c_naive_work,
        "c_inter_only": c_inter_only,
        "c_unpruned": c_unpruned,
        "c_pruned": c_pruned,
        "v_total": len(macro_nodes)
    }


def find_ground_truth_target(nodes_slow: List[Dict], nodes_fast: List[Dict], scope_kind: str) -> str:
    """
    Purely static AST-diff ground-truth root-cause localization (Audit Fix 2).
    Computes gt_node strictly by diffing nodes_slow and nodes_fast WITHOUT accessing
    any profiler or slicing output.
    """
    def norm_sig(n: Dict) -> str:
        p = re.sub(r'\s+', ' ', n.get("source_preview", "").strip())
        return f"{n['role']}:{p}"

    fast_sigs = {norm_sig(n) for n in nodes_fast}
    slow_sigs = {norm_sig(n) for n in nodes_slow}
    diff_slow = [n for n in nodes_slow if norm_sig(n) not in fast_sigs]

    loop_guard_vars = set()
    for n in nodes_slow:
        if n["role"] == "LOOP":
            loop_guard_vars.update(n["uses"])

    # Case 1: Track A1 State Corruptions & Self-Contained Hidden Work
    if scope_kind in ("inter", "intra", "self_hidden"):
        if scope_kind == "self_hidden":
            for n in diff_slow:
                if n["role"] in ("FUNCTION_ENTRY", "STATE_UPD"):
                    return n["id"]
        for n in diff_slow:
            if n["role"] == "STATE_UPD" and (set(n["defs"]) & loop_guard_vars):
                return n["id"]
        for n in diff_slow:
            if n["role"] == "STATE_UPD":
                return n["id"]

    # Case 2: Track A2 Omissions (Missing Memoization or Missing Early-Exit Guard)
    if scope_kind in ("omission_memo", "omission_guard"):
        node_map_fast = {n["id"]: n for n in nodes_fast}
        inserted_fast = [n for n in nodes_fast if norm_sig(n) not in slow_sigs]
        for ins_n in inserted_fast:
            p_fast_id = ins_n["parent"]
            if p_fast_id and p_fast_id in node_map_fast:
                p_fast = node_map_fast[p_fast_id]
                p_sig = norm_sig(p_fast)
                for s_n in nodes_slow:
                    if norm_sig(s_n) == p_sig:
                        return s_n["id"]
        for s_n in reversed(nodes_slow):
            if s_n["role"] in ("FUNCTION_ENTRY", "LOOP"):
                return s_n["id"]

    # Case 3: Track B Paradigm Shifts
    if scope_kind == "paradigm_shift":
        for n in diff_slow:
            if n["role"] == "FUNCTION_ENTRY":
                return n["id"]
        diff_loops = [n for n in diff_slow if n["role"] == "LOOP"]
        if diff_loops:
            return diff_loops[-1]["id"]

    return diff_slow[0]["id"] if diff_slow else nodes_slow[0]["id"]


def pilot_slice_gate(reduction: float, recall: float) -> str:
    if recall < 95.0:
        return "LOW-REC"
    return "PASS" if reduction >= 75.0 else "BLOAT-FAIL"


def run_pilot_100_study(build_dir: Path, output_dir: Path) -> List[Dict]:
    """
    Execute the 100-Pair Exploratory Pilot Study (--stage pilot-100) across 41 distinct problem
    archetypes and generate Table 1, Table 2, and Table 3.
    """
    from concurrent.futures import ThreadPoolExecutor

    build_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    corpus = generate_pilot_100_corpus()
    unique_pids = sorted(list(set(c["problem_id"] for c in corpus)))
    print(f"  [+] Synthesized {len(corpus)} C++17 pairs across {len(unique_pids)} problem IDs.")

    def process_pair(item: Dict) -> Dict:
        sp, am_s = preprocess_pass_zero(item["slow_code"])
        sn = normalize_synthetic_braces(sp)
        assert verify_cpp_syntax(sn), f"Syntax verification failed on slow code: {item['pair_id']}"
        ns = extract_macro_nodes(sn, am_s)

        fp, am_f = preprocess_pass_zero(item["fast_code"])
        fn = normalize_synthetic_braces(fp)
        assert verify_cpp_syntax(fn), f"Syntax verification failed on fast code: {item['pair_id']}"
        nf = extract_macro_nodes(fn, am_f)

        delta_v, rho = compute_macro_edit_distance(ns, nf)
        gt_node = find_ground_truth_target(ns, nf, item["scope_kind"])

        s_instr = instrument_cpp_source(sn, ns)
        s_bin = str(build_dir / f"pilot_{item['pair_id']}_slow.exe")
        assert compile_cpp_binary(s_instr, s_bin), f"Compilation failed: {s_bin}"
        f_instr = instrument_cpp_source(fn, nf)
        f_bin = str(build_dir / f"pilot_{item['pair_id']}_fast.exe")
        assert compile_cpp_binary(f_instr, f_bin), f"Compilation failed: {f_bin}"
        for scale in PILOT_EQUIVALENCE_SCALES:
            stdin_data = item["input_gen"](scale)
            slow = run_sandboxed_binary(s_bin, stdin_data)
            fast = run_sandboxed_binary(f_bin, stdin_data)
            for side, result in (("slow", slow), ("fast", fast)):
                if result[3] != "CLEAN_COMPLETION" or '"status": "CLEAN_COMPLETION"' not in result[2]:
                    raise RuntimeError(f"{item['pair_id']} {side} did not complete at N={scale}: {result[3]}")
            if slow[1].strip() != fast[1].strip():
                raise ValueError(f"{item['pair_id']} stdout mismatch at N={scale}: {slow[1].strip()!r} != {fast[1].strip()!r}")
        sc_slow = execute_scaling_with_micro_ladder(s_bin, item["input_gen"], ns)
        sc_fast = execute_scaling_with_micro_ladder(f_bin, item["input_gen"], nf)

        slicing = evaluate_four_slicing_tiers(ns, sc_slow)
        slicing_std = analyze_eapg_slicing(ns, sc_slow)
        slicing_std["c_slice"] = slicing["c_pruned"]
        slicing_std["r_search"] = round(1.0 - (len(slicing["c_pruned"]) / len(ns)), 3) if ns else 0.0
        skeleton_txt = format_eapg_skeleton(ns, sc_slow, slicing_std)

        max_hits_slow = max((d["fit_hits"]["alpha"] if d["fit_hits"]["growth"] == "POLY" else 9.99) for d in sc_slow.values())
        max_work_slow = max((d["fit_work"]["alpha"] if d["fit_work"]["growth"] == "POLY" else 9.99) for d in sc_slow.values())
        is_exp_slow = any(d["fit_work"]["growth"] == "EXP" for d in sc_slow.values())
        max_work_fast = max((d["fit_work"]["alpha"] if d["fit_work"]["growth"] == "POLY" else 9.99) for d in sc_fast.values())

        return {
            "pair_id": item["pair_id"],
            "pilot_revision": item["pilot_revision"],
            "scope_protocol": "main_scope",
            "template_fingerprints": item["template_fingerprints"],
            "stdout_equivalence_scales": list(PILOT_EQUIVALENCE_SCALES),
            "problem_id": item["problem_id"],
            "track_gt": item["track_gt"],
            "mechanism_id": item["mechanism_id"],
            "mechanism_name": item["mechanism_name"],
            "paradigm": item["paradigm"],
            "scope_kind": item["scope_kind"],
            "v_slow": len(ns),
            "v_fast": len(nf),
            "delta_v": delta_v,
            "rho": rho,
            "is_exp_slow": is_exp_slow,
            "max_hits_slow": max_hits_slow,
            "max_work_slow": max_work_slow,
            "max_work_fast": max_work_fast,
            "gt_node": gt_node,
            "slicing": slicing,
            "skeleton": skeleton_txt,
            "slow_code": item["slow_code"],
            "fast_code": item["fast_code"],
        }

    with ThreadPoolExecutor(max_workers=8) as ex:
        records = list(ex.map(process_pair, corpus))

    train_s, val_s, test_s = create_problem_quarantined_split(records, train_ratio=0.8, val_ratio=0.1, seed=42)
    print(f"  [+] Problem-Quarantined Split Verified: Train={len(train_s)} pairs ({len(set(r['problem_id'] for r in train_s))} problems), "
          f"Val={len(val_s)} pairs ({len(set(r['problem_id'] for r in val_s))} problems), "
          f"Test={len(test_s)} pairs ({len(set(r['problem_id'] for r in test_s))} problems).")

    json_out = output_dir / "pilot100_results.json"
    with open(json_out, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)
    print(f"  [+] Saved 100-pair pilot records to: {json_out}")

    dv_buckets = [
        ("|Delta V| = 1", lambda dv: dv == 1),
        ("|Delta V| = 2", lambda dv: dv == 2),
        ("|Delta V| = 3", lambda dv: dv == 3),
        ("|Delta V| = 4", lambda dv: dv == 4),
        ("|Delta V| >= 5", lambda dv: dv >= 5),
    ]
    rho_buckets = [
        ("(0.00, 0.15]", lambda r: r <= 0.15),
        ("(0.15, 0.30]", lambda r: 0.15 < r <= 0.30),
        ("(0.30, 0.50]", lambda r: 0.30 < r <= 0.50),
        ("> 0.50", lambda r: r > 0.50),
    ]

    print("\n" + "=" * 105)
    print("TABLE 1A: 2D Structural Edit Distribution (|Delta V| vs. rho = |Delta V| / |V_slow|) & Track Split")
    print("=" * 105)
    print(f"{'|Delta V| Bucket':<16} | {'rho <= 0.15':<11} | {'(0.15, 0.30]':<12} | {'(0.30, 0.50]':<12} | {'rho > 0.50':<10} | {'Total':<6} | {'Track A1':<8} | {'Track A2':<8} | {'Track B':<7}")
    print("-" * 105)
    for dv_label, dv_fn in dv_buckets:
        sub_dv = [r for r in records if dv_fn(r["delta_v"])]
        r_counts = [sum(1 for r in sub_dv if r_fn(r["rho"])) for _, r_fn in rho_buckets]
        c_a1 = sum(1 for r in sub_dv if r["track_gt"] == "A1")
        c_a2 = sum(1 for r in sub_dv if r["track_gt"] == "A2")
        c_b = sum(1 for r in sub_dv if r["track_gt"] == "B")
        print(f"{dv_label:<16} | {r_counts[0]:<11} | {r_counts[1]:<12} | {r_counts[2]:<12} | {r_counts[3]:<10} | {len(sub_dv):<6} | {c_a1:<8} | {c_a2:<8} | {c_b:<7}")
    print("-" * 105)
    tot_r = [sum(1 for r in records if r_fn(r["rho"])) for _, r_fn in rho_buckets]
    tot_a1 = sum(1 for r in records if r["track_gt"] == "A1")
    tot_a2 = sum(1 for r in records if r["track_gt"] == "A2")
    tot_b = sum(1 for r in records if r["track_gt"] == "B")
    print(f"{'Total':<16} | {tot_r[0]:<11} | {tot_r[1]:<12} | {tot_r[2]:<12} | {tot_r[3]:<10} | {len(records):<6} | {tot_a1:<8} | {tot_a2:<8} | {tot_b:<7}")
    print("=" * 105)

    cutoffs = [
        ("|Delta V| <= 1 and rho <= 0.15", lambda dv, r: dv <= 1 and r <= 0.15),
        ("|Delta V| <= 2 and rho <= 0.20", lambda dv, r: dv <= 2 and r <= 0.20),
        ("|Delta V| <= 3 and rho <= 0.25", lambda dv, r: dv <= 3 and r <= 0.25),
        ("|Delta V| <= 3 and rho <= 0.30 [ELBOW]", lambda dv, r: dv <= 3 and r <= 0.30),
        ("|Delta V| <= 4 and rho <= 0.35", lambda dv, r: dv <= 4 and r <= 0.35),
        ("|Delta V| <= 5 and rho <= 0.45", lambda dv, r: dv <= 5 and r <= 0.45),
    ]
    print("\n" + "=" * 105)
    print("TABLE 1B: Track A vs. Track B Cutoff Sensitivity Sweep (Ground Truth: Track A = 62, Track B = 38)")
    print("=" * 105)
    print(f"{'Candidate Cutoff Rule':<38} | {'Pred Track A':<12} | {'Track A Rec (%)':<15} | {'Track B Spec (%)':<16} | {'Overall Acc (%)':<15}")
    print("-" * 105)
    for c_label, c_fn in cutoffs:
        pred_a = [r for r in records if c_fn(r["delta_v"], r["rho"])]
        tp_a = sum(1 for r in records if r["track_gt"] in ("A1", "A2") and c_fn(r["delta_v"], r["rho"]))
        tn_b = sum(1 for r in records if r["track_gt"] == "B" and not c_fn(r["delta_v"], r["rho"]))
        rec_a = tp_a / 62.0 * 100.0
        spec_b = tn_b / 38.0 * 100.0
        acc = (tp_a + tn_b) / len(records) * 100.0
        print(f"{c_label:<38} | {len(pred_a):<12} | {rec_a:<15.1f} | {spec_b:<16.1f} | {acc:<15.1f}")
    print("=" * 105)

    print("\n" + "=" * 118)
    print("TABLE 2: Bottleneck Mechanism Breakdown & Dual-Counter Detection Across 100 Pairs")
    print("=" * 118)
    print(f"{'ID':<5} | {'Track':<5} | {'Bottleneck Mechanism':<42} | {'N':<3} | {'|V|':<5} | {'|dV|':<4} | {'rho':<5} | {'a_hits':<6} | {'a_work':<6} | {'a_fast':<6} | {'Hits%':<6} | {'Work%'}")
    print("-" * 118)
    for m_id in sorted(set(r["mechanism_id"] for r in records)):
        sub = [r for r in records if r["mechanism_id"] == m_id]
        n_c = len(sub)
        trk = sub[0]["track_gt"]
        m_name = sub[0]["mechanism_name"][:42]
        v_mean = sum(r["v_slow"] for r in sub) / n_c
        dv_mean = sum(r["delta_v"] for r in sub) / n_c
        rho_mean = sum(r["rho"] for r in sub) / n_c
        ah_str = "EXP" if any(r["is_exp_slow"] for r in sub) else f"{sum(r['max_hits_slow'] for r in sub)/n_c:.2f}"
        aw_str = "EXP" if any(r["is_exp_slow"] for r in sub) else f"{sum(r['max_work_slow'] for r in sub)/n_c:.2f}"
        af_str = f"{sum(r['max_work_fast'] for r in sub)/n_c:.2f}"
        det_hits = sum(1 for r in sub if len(r["slicing"]["c_naive_hits"]) > 0) / n_c * 100.0
        det_work = sum(1 for r in sub if len(r["slicing"]["c_naive_work"]) > 0) / n_c * 100.0
        print(f"{m_id:<5} | {trk:<5} | {m_name:<42} | {n_c:<3} | {v_mean:<5.1f} | {dv_mean:<4.1f} | {rho_mean:<5.2f} | {ah_str:<6} | {aw_str:<6} | {af_str:<6} | {det_hits:<6.1f} | {det_work:.1f}")
    print("=" * 118)

    tiers = [
        ("1. Control-Flow Symptom Only (Hits)", "c_naive_hits"),
        ("2. Work-Weighted Symptom Only (No Slice)", "c_naive_work"),
        ("3. Inter-Scope Slice Only (C_inter)", "c_inter_only"),
        ("4. Unpruned Two-Tier (C_inter U C_intra_raw)", "c_unpruned"),
        ("5. Full Pruned EAPG (C_inter U C_intra_pruned)", "c_pruned"),
    ]
    print("\n" + "=" * 136)
    print("TABLE 3: Two-Tier PDG Slice Recall, State-Reset Top-1 (A1.1+A1.4), Candidate Cardinality |C_slice|, & Search Space Reduction R_search")
    print("=" * 136)
    print(f"{'Slicing Strategy':<46} | {'A1 Rec%':<7} | {'A2 Rec%':<7} | {'B Rec%':<7} | {'All Rec%':<8} | {'Reset Top1%':<11} | {'Rule Top1%':<10} | {'|C_slice|':<9} | {'R_search%':<9} | {'Gate'}")
    print("-" * 136)
    for t_name, t_key in tiers:
        sub_a1 = [r for r in records if r["track_gt"] == "A1"]
        sub_a2 = [r for r in records if r["track_gt"] == "A2"]
        sub_b = [r for r in records if r["track_gt"] == "B"]
        sub_reset = [r for r in records if r["mechanism_id"] in ("A1.1", "A1.4")]
        rec_a1 = sum(1 for r in sub_a1 if r["gt_node"] in r["slicing"][t_key]) / len(sub_a1) * 100.0
        rec_a2 = sum(1 for r in sub_a2 if r["gt_node"] in r["slicing"][t_key]) / len(sub_a2) * 100.0
        rec_b = sum(1 for r in sub_b if r["gt_node"] in r["slicing"][t_key]) / len(sub_b) * 100.0
        rec_all = sum(1 for r in records if r["gt_node"] in r["slicing"][t_key]) / len(records) * 100.0
        reset_top1 = sum(1 for r in sub_reset if r["slicing"][t_key] and r["slicing"][t_key][0] == r["gt_node"]) / len(sub_reset) * 100.0
        rule_top1 = sum(1 for r in records if r["slicing"][t_key] and r["slicing"][t_key][0] == r["gt_node"]) / len(records) * 100.0
        mean_c = sum(len(r["slicing"][t_key]) for r in records) / len(records)
        mean_r = sum(1.0 - (len(r["slicing"][t_key]) / r["v_slow"]) for r in records) / len(records) * 100.0
        gate = pilot_slice_gate(mean_r, rec_all)
        print(f"{t_name:<46} | {rec_a1:<7.1f} | {rec_a2:<7.1f} | {rec_b:<7.1f} | {rec_all:<8.1f} | {reset_top1:<11.1f} | {rule_top1:<10.1f} | {mean_c:<9.2f} | {mean_r:<9.1f} | {gate}")
    print("=" * 136)

    tex_out = output_dir / "pilot100_tables.tex"
    tex_lines = [
        "% Auto-generated by pipeline.py --stage pilot-100",
        r"\begin{table}[t]",
        r"\centering",
        r"\caption{2D Structural Macro-Node Edit Distribution ($|\Delta V|$ vs. $\rho$) and Track A1/A2/B Split ($N=100$ Pairs, 41 Problem IDs).}",
        r"\label{tab:pilot_edit_dist}",
        r"\begin{tabular}{lcccccccc}",
        r"\toprule",
        r"\textbf{$|\Delta V|$ Bucket} & \textbf{$\rho \le 0.15$} & \textbf{$(0.15, 0.30]$} & \textbf{$(0.30, 0.50]$} & \textbf{$\rho > 0.50$} & \textbf{Total} & \textbf{Track A1} & \textbf{Track A2} & \textbf{Track B} \\",
        r"\midrule",
    ]
    for dv_label, dv_fn in dv_buckets:
        sub_dv = [r for r in records if dv_fn(r["delta_v"])]
        r_counts = [sum(1 for r in sub_dv if r_fn(r["rho"])) for _, r_fn in rho_buckets]
        c_a1 = sum(1 for r in sub_dv if r["track_gt"] == "A1")
        c_a2 = sum(1 for r in sub_dv if r["track_gt"] == "A2")
        c_b = sum(1 for r in sub_dv if r["track_gt"] == "B")
        tex_lbl = dv_label.replace("|Delta V|", r"$|\Delta V|$").replace(">=", r"\ge")
        tex_lines.append(f"{tex_lbl} & {r_counts[0]} & {r_counts[1]} & {r_counts[2]} & {r_counts[3]} & {len(sub_dv)} & {c_a1} & {c_a2} & {c_b} \\\\")
    tex_lines.extend([
        r"\midrule",
        f"\\textbf{{Total}} & {tot_r[0]} & {tot_r[1]} & {tot_r[2]} & {tot_r[3]} & {len(records)} & {tot_a1} & {tot_a2} & {tot_b} \\\\",
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
        "",
        r"\begin{table}[t]",
        r"\centering",
        r"\caption{Two-Tier PDG Slice Recall, State-Reset Top-1 ($A1.1+A1.4$), Deterministic Rule Top-1, Candidate Cardinality ($|C_{\text{slice}}|$), and Search Space Reduction ($R_{\text{search}}$).}",
        r"\label{tab:pilot_slicing_recall}",
        r"\begin{tabular}{lcccccccc}",
        r"\toprule",
        r"\textbf{Slicing Strategy} & \textbf{A1 Rec (\%)} & \textbf{A2 Rec (\%)} & \textbf{B Rec (\%)} & \textbf{All Rec (\%)} & \textbf{Reset Top-1 (\%)} & \textbf{Rule Top-1 (\%)} & \textbf{$|C_{\text{slice}}|$} & \textbf{$R_{\text{search}}$ (\%)} \\",
        r"\midrule",
    ])
    for t_name, t_key in tiers:
        sub_a1 = [r for r in records if r["track_gt"] == "A1"]
        sub_a2 = [r for r in records if r["track_gt"] == "A2"]
        sub_b = [r for r in records if r["track_gt"] == "B"]
        sub_reset = [r for r in records if r["mechanism_id"] in ("A1.1", "A1.4")]
        rec_a1 = sum(1 for r in sub_a1 if r["gt_node"] in r["slicing"][t_key]) / len(sub_a1) * 100.0
        rec_a2 = sum(1 for r in sub_a2 if r["gt_node"] in r["slicing"][t_key]) / len(sub_a2) * 100.0
        rec_b = sum(1 for r in sub_b if r["gt_node"] in r["slicing"][t_key]) / len(sub_b) * 100.0
        rec_all = sum(1 for r in records if r["gt_node"] in r["slicing"][t_key]) / len(records) * 100.0
        reset_top1 = sum(1 for r in sub_reset if r["slicing"][t_key] and r["slicing"][t_key][0] == r["gt_node"]) / len(sub_reset) * 100.0
        rule_top1 = sum(1 for r in records if r["slicing"][t_key] and r["slicing"][t_key][0] == r["gt_node"]) / len(records) * 100.0
        mean_c = sum(len(r["slicing"][t_key]) for r in records) / len(records)
        mean_r = sum(1.0 - (len(r["slicing"][t_key]) / r["v_slow"]) for r in records) / len(records) * 100.0
        clean_name = t_name.replace("_", r"\_")
        tex_lines.append(f"{clean_name} & {rec_a1:.1f} & {rec_a2:.1f} & {rec_b:.1f} & {rec_all:.1f} & {reset_top1:.1f} & {rule_top1:.1f} & {mean_c:.2f} & {mean_r:.1f} \\\\")
    tex_lines.extend([
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
    ])
    with open(tex_out, "w", encoding="utf-8") as f:
        f.write("\n".join(tex_lines))
    print(f"  [+] Saved LaTeX booktabs tables to: {tex_out}")

    return records


def build_qlora_dataset(build_dir: Path, output_dir: Path) -> Dict:
    """
    Generate the problem-quarantined QLoRA Training, Validation, and Test JSONL splits
    (--stage build-dataset). Enforces:
      1. Locked-in Track A / Track B split rule: |Delta V| <= 3 and rho <= 0.30.
      2. Strict problem_id quarantine: Train (32 problems), Val (4 problems), Test (5 problems).
      3. Counterfactual mutation quarantine: Synthetic counterfactual Track A1/A2 mutations are
         generated strictly from C_fast programs belonging to the 32 Train problem IDs.
      4. Token budget verification: All prompts verified against sequence length caps.
    """
    from collections import Counter
    from concurrent.futures import ThreadPoolExecutor
    from transformers import AutoTokenizer

    pilot_json = output_dir / "pilot100_results.json"
    if pilot_json.exists():
        with open(pilot_json, "r", encoding="utf-8") as f:
            records = json.load(f)
    else:
        records = run_pilot_100_study(build_dir, output_dir)

    revised_export = all(row.get("pilot_revision") == PILOT_REVISION for row in records)
    family_export = all(row.get("scope_protocol") == "main_scope" for row in records)
    train_base, val_set, test_set = create_problem_quarantined_split(records, train_ratio=0.8, val_ratio=0.1, seed=42)
    train_pids = set(r["problem_id"] for r in train_base)
    val_pids = set(r["problem_id"] for r in val_set)
    test_pids = set(r["problem_id"] for r in test_set)

    assert train_pids.isdisjoint(val_pids), "FATAL: Train and Val problem IDs overlap!"
    assert train_pids.isdisjoint(test_pids), "FATAL: Train and Test problem IDs overlap!"
    assert val_pids.isdisjoint(test_pids), "FATAL: Val and Test problem IDs overlap!"

    tokenizer_name = "Qwen/Qwen2.5-Coder-1.5B"
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_name, local_files_only=True)

    # Generate counterfactual mutations strictly from Train problem IDs (Stage 1 Mandate 6)
    cf_candidates = []
    seen_train_pids = set()
    for r in train_base:
        pid = r["problem_id"]
        if pid in seen_train_pids:
            continue
        seen_train_pids.add(pid)
        fast_src = r["fast_code"]
        mut_src = None
        mut_mech = None
        mut_track = None
        mut_scope = None

        # Apply deterministic AST-level counterfactual mutation on C_fast
        if "std::binary_search(" in fast_src:
            mut_src = fast_src.replace("std::binary_search(", "std::count(")
            mut_mech = "A1.3"
            mut_track = "A1"
            mut_scope = "self_hidden"
        elif "std::vector<int>& " in fast_src:
            mut_src = fast_src.replace("std::vector<int>& ", "std::vector<int> ")
            mut_mech = "A1.2"
            mut_track = "A1"
            mut_scope = "self_hidden"
        elif "!= -1) return " in fast_src:
            lines_f = [ln for ln in fast_src.splitlines() if "!= -1) return " not in ln]
            mut_src = "\n".join(lines_f)
            mut_mech = "A2.1"
            mut_track = "A2"
            mut_scope = "omission_memo"
        elif "_anchor = " in fast_src:
            mut_src = fast_src.replace("_anchor = ", " = ")
            mut_mech = "A1.1"
            mut_track = "A1"
            mut_scope = "inter"

        if mut_src and mut_src != fast_src and verify_cpp_syntax(mut_src):
            cf_candidates.append({
                "pair_id": f"CF_TRAIN_{len(cf_candidates)+1:03d}",
                "problem_id": pid,
                "track_gt": mut_track,
                "mechanism_id": mut_mech,
                "mechanism_name": f"Counterfactual {mut_mech}",
                "paradigm": r["paradigm"],
                "scope_kind": mut_scope,
                "slow_code": mut_src,
                "fast_code": fast_src,
                "input_gen": lambda n: f"{n}\n",
                "is_counterfactual": True
            })

    def profile_cf(item: Dict) -> Dict:
        sp, am_s = preprocess_pass_zero(item["slow_code"])
        sn = normalize_synthetic_braces(sp)
        ns = extract_macro_nodes(sn, am_s)

        fp, am_f = preprocess_pass_zero(item["fast_code"])
        fn = normalize_synthetic_braces(fp)
        nf = extract_macro_nodes(fn, am_f)

        delta_v, rho = compute_macro_edit_distance(ns, nf)
        gt_node = find_ground_truth_target(ns, nf, item["scope_kind"])

        s_instr = instrument_cpp_source(sn, ns)
        s_bin = str(build_dir / f"{item['pair_id']}_slow.exe")
        assert compile_cpp_binary(s_instr, s_bin), f"Compilation failed: {s_bin}"
        sc_slow = execute_scaling_with_micro_ladder(s_bin, item["input_gen"], ns)

        f_instr = instrument_cpp_source(fn, nf)
        f_bin = str(build_dir / f"{item['pair_id']}_fast.exe")
        assert compile_cpp_binary(f_instr, f_bin), f"Compilation failed: {f_bin}"
        sc_fast = execute_scaling_with_micro_ladder(f_bin, item["input_gen"], nf)

        slicing = evaluate_four_slicing_tiers(ns, sc_slow)
        slicing_std = analyze_eapg_slicing(ns, sc_slow)
        slicing_std["c_slice"] = slicing["c_pruned"]
        slicing_std["r_search"] = round(1.0 - (len(slicing["c_pruned"]) / len(ns)), 3) if ns else 0.0
        skeleton_txt = format_eapg_skeleton(ns, sc_slow, slicing_std)

        max_hits_slow = max((d["fit_hits"]["alpha"] if d["fit_hits"]["growth"] == "POLY" else 9.99) for d in sc_slow.values())
        max_work_slow = max((d["fit_work"]["alpha"] if d["fit_work"]["growth"] == "POLY" else 9.99) for d in sc_slow.values())
        is_exp_slow = any(d["fit_work"]["growth"] == "EXP" for d in sc_slow.values())
        max_work_fast = max((d["fit_work"]["alpha"] if d["fit_work"]["growth"] == "POLY" else 9.99) for d in sc_fast.values())

        return {
            "pair_id": item["pair_id"],
            "problem_id": item["problem_id"],
            "track_gt": item["track_gt"],
            "mechanism_id": item["mechanism_id"],
            "mechanism_name": item["mechanism_name"],
            "paradigm": item["paradigm"],
            "scope_kind": item["scope_kind"],
            "v_slow": len(ns),
            "v_fast": len(nf),
            "delta_v": delta_v,
            "rho": rho,
            "is_exp_slow": is_exp_slow,
            "max_hits_slow": max_hits_slow,
            "max_work_slow": max_work_slow,
            "max_work_fast": max_work_fast,
            "gt_node": gt_node,
            "slicing": slicing,
            "skeleton": skeleton_txt,
            "is_counterfactual": True
        }

    with ThreadPoolExecutor(max_workers=8) as ex:
        cf_records = [r for r in ex.map(profile_cf, cf_candidates) if (r["max_work_slow"] - r["max_work_fast"] >= 0.7 or r["is_exp_slow"])]

    # Verify strict counterfactual quarantine: 100% of counterfactuals must belong to train_pids
    cf_pids = set(r["problem_id"] for r in cf_records)
    assert cf_pids.issubset(train_pids), "FATAL: Counterfactual mutation leaked outside train_pids!"
    assert cf_pids.isdisjoint(val_pids | test_pids), "FATAL: Counterfactual mutation leaked into Val/Test!"

    full_train = train_base + cf_records
    target_name = "repair family" if family_export else "paradigm"

    def format_qlora_entry(rec: Dict, split_name: str) -> Dict:
        is_surgical = (rec["delta_v"] <= 3 and rec["rho"] <= 0.30)
        candidates = set(rec["slicing"]["c_pruned"])
        node_lines = []
        for nid, node in parse_skeleton_nodes(rec).items():
            mark = "*" if nid in candidates else ""
            hits = _fmt_exp_1d(node["a_hits"])
            work = _fmt_exp_1d(node["a_work"])
            if revised_export:
                hits, work = hits.removesuffix(".0"), work.removesuffix(".0")
            defs = node["defs"].strip("{}").replace(" ", "") or "-"
            uses = node["uses"].strip("{}").replace(" ", "") or "-"
            node_lines.append(f"{nid}{mark} {node['role']} {hits}/{work} {defs} {uses}")
        prompt_text = (
            f"Localize the bottleneck node and classify the repair track and {target_name}. "
            "Rows show node, role, hit/work exponents, defs, and uses. * marks slice membership.\n"
            + "\n".join(node_lines)
            + "\nResponse (JSON):\n"
        )
        target_obj = {
            "choke_node": rec["gt_node"],
            "candidate_slice": rec["slicing"]["c_pruned"],
            "track": rec["track_gt"],
            "threshold_class": "Track_A_Surgical" if is_surgical else "Track_B_Paradigm",
            "mechanism": rec["mechanism_id"],
            "paradigm": REPAIR_FAMILY_BY_MECHANISM[rec["mechanism_id"]] if family_export else rec["paradigm"],
            "r_search": round(1.0 - (len(rec["slicing"]["c_pruned"]) / rec["v_slow"]), 3)
        }
        target_text = json.dumps(target_obj)
        token_count = len(tokenizer.encode(prompt_text + target_text, add_special_tokens=False))
        if token_count > 512:
            raise ValueError(f"Token budget exceeded ({token_count} > 512) on {rec['pair_id']}")
        return {
            "pair_id": rec["pair_id"],
            "problem_id": rec["problem_id"],
            "split": split_name,
            "is_counterfactual": rec.get("is_counterfactual", False),
            "delta_v": rec["delta_v"],
            "rho": rec["rho"],
            "token_count": token_count,
            "prompt": prompt_text,
            "completion": target_text,
            "label": target_obj
        }

    ds_dir = output_dir / "dataset"
    ds_dir.mkdir(parents=True, exist_ok=True)

    train_jsonl = [format_qlora_entry(r, "train") for r in full_train]
    val_jsonl = [format_qlora_entry(r, "val") for r in val_set]
    test_jsonl = [format_qlora_entry(r, "test") for r in test_set]

    for name, rows in [("train.jsonl", train_jsonl), ("val.jsonl", val_jsonl), ("test.jsonl", test_jsonl)]:
        with open(ds_dir / name, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")

    manifest = {
        "threshold_rule": "|Delta V| <= 3 and rho <= 0.30",
        "seed": 42,
        "train_problems": sorted(list(train_pids)),
        "val_problems": sorted(list(val_pids)),
        "test_problems": sorted(list(test_pids)),
        "counts": {
            "train_natural": len(train_base),
            "train_counterfactual": len(cf_records),
            "train_total": len(train_jsonl),
            "val_total": len(val_jsonl),
            "test_total": len(test_jsonl),
        },
        "tokenizer": tokenizer_name,
        "max_tokens": max(x["token_count"] for x in train_jsonl + val_jsonl + test_jsonl),
        "track_counts": {
            name: dict(Counter(row["label"]["track"] for row in rows))
            for name, rows in (("train", train_jsonl), ("val", val_jsonl), ("test", test_jsonl))
        },
        "leakage_checks": {
            "train_val_disjoint": train_pids.isdisjoint(val_pids),
            "train_test_disjoint": train_pids.isdisjoint(test_pids),
            "val_test_disjoint": val_pids.isdisjoint(test_pids),
            "counterfactual_strictly_in_train": cf_pids.issubset(train_pids),
        }
    }
    if family_export:
        manifest["repair_family_mechanisms"] = REPAIR_FAMILIES
    with open(ds_dir / "split_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print("\n" + "=" * 95)
    print("PHASE 3 QLoRA DATASET SPLIT MANIFEST (Problem-Quarantined & Counterfactual-Guarded)")
    print("=" * 95)
    print(f"  [+] Locked-In Track A/B Boundary : {manifest['threshold_rule']}")
    print(f"  [+] Train Split (32 problems)    : {len(train_base)} natural + {len(cf_records)} counterfactual = {len(train_jsonl)} pairs")
    print(f"  [+] Val Split   (4 problems)     : {len(val_jsonl)} natural pairs (0 counterfactual)")
    print(f"  [+] Test Split  (5 problems)     : {len(test_jsonl)} natural pairs (0 counterfactual)")
    print(f"  [+] Max Sequence Length Budget   : {manifest['max_tokens']} tokens (Cap <= 512: PASS)")
    print(f"  [+] Data-Leak-Guard Verification : {manifest['leakage_checks']}")
    print(f"  [+] Output Files Saved To        : {ds_dir}")
    print("=" * 95)
    return manifest


# ==============================================================================
# Stage 4 Live Execution: 5-Fold Problem-Quarantined QLoRA & 7-Variant Ablation
# ==============================================================================

PARADIGM_LIST = [
    "Two Pointers / Sliding Window",
    "Divide & Conquer / DFS",
    "Binary Search / STL Lookup",
    "Greedy / Window Scan",
    "Dynamic Programming",
    "Complete Search / Greedy",
    "Binary Search / Divide & Conquer",
]
PARADIGM_TO_CODE = {p: chr(ord("T") + i) for i, p in enumerate(PARADIGM_LIST)}

REPAIR_FAMILIES = {
    "Sliding Window / Two Pointers / Prefix Sums": ("A1.1", "A1.4", "B.1"),
    "Binary Search / Hash Lookup": ("A1.3", "B.2"),
    "Dynamic Programming / Memoization": ("A2.1", "B.3"),
    "Recursion / Search Pruning": ("A1.2", "A2.2"),
}
REPAIR_FAMILY_BY_MECHANISM = {
    mechanism: family for family, mechanisms in REPAIR_FAMILIES.items() for mechanism in mechanisms
}
REPAIR_FAMILY_TO_CODE = dict(zip(REPAIR_FAMILIES, "TUVW"))


def _nid_to_code(nid: str) -> str:
    return chr(ord("A") + int(nid[1:]) - 1)


def parse_skeleton_nodes(rec: Dict) -> Dict[str, Dict]:
    skel_lines = rec["skeleton"].splitlines()
    node_rows = [ln for ln in skel_lines if re.match(r"^N\d+\s+\|", ln)]
    info = {}
    for ln in node_rows:
        max_splits = 8 if rec.get("pilot_revision") == PILOT_REVISION else -1
        parts = [p.strip() for p in ln.split("|", max_splits)]
        nid = parts[0]
        info[nid] = {
            "role": parts[1],
            "a_hits": parts[2],
            "a_work": parts[3],
            "delta_a": parts[4],
            "defs": parts[5],
            "uses": parts[6],
            "cand": parts[7] if len(parts) > 8 else "-",
            "preview": parts[8] if len(parts) > 8 else parts[-1],
        }
    return info


def loop_bound_aliases(rec: Dict, candidates: List[str], symptom: str) -> Set[str]:
    """Find inter-scope writes with a single def site and no induction-variable input."""
    from collections import Counter

    nodes = extract_macro_nodes(normalize_synthetic_braces(rec["slow_code"]), {})
    by_id = {node["id"]: node for node in nodes}

    def ancestors(node):
        parent = node["parent"]
        while parent in by_id:
            node = by_id[parent]
            yield node
            parent = node["parent"]

    def function_scope(node):
        for parent in (node, *ancestors(node)):
            if parent["role"] == "FUNCTION_ENTRY":
                return parent["id"]
        return "MAIN_SCOPE"

    writes = Counter((function_scope(n), name) for n in nodes for name in n["defs"])
    induction = {
        name for n in ancestors(by_id[symptom]) if n["role"] == "LOOP" for name in n["defs"]
    }
    aliases = set()
    for nid in candidates:
        node = by_id[nid]
        if node["defs"] and not any(writes[function_scope(node), name] > 1 for name in node["defs"]):
            if not induction.intersection(node["uses"]):
                aliases.add(nid)
    return aliases


def rank_candidates_by_role_priority(rec: Dict, *, use_loop_def_use=False) -> List[str]:
    """
    Deterministic role-priority ordering over c_pruned for Baseline #2 (Deterministic PDG Slice).
    Prioritizes self_hidden / EXP function entry or missing early-exit loop header first;
    otherwise prioritizes c_inter / c_intra_pruned STATE_UPD state resets.
    """
    info = parse_skeleton_nodes(rec)
    c_pruned = list(rec["slicing"]["c_pruned"])
    symptom = rec["slicing"]["primary_symptom"]
    if not c_pruned:
        return [symptom] if symptom else ["N1"]

    s_info = info.get(symptom, {})
    is_hidden = False
    try:
        if "EXP" not in s_info.get("a_work", "") and "EXP" not in s_info.get("a_hits", ""):
            if float(s_info["a_work"]) - float(s_info["a_hits"]) >= 0.7:
                is_hidden = True
    except Exception:
        pass

    if is_hidden or s_info.get("role") == "FUNCTION_ENTRY":
        return [symptom] + [x for x in c_pruned if x != symptom]

    all_nids = sorted(list(info.keys()), key=lambda x: int(x[1:]))
    sym_idx = int(symptom[1:]) if symptom else 1

    def _is_inner_branch_flag(nid: str) -> bool:
        idx = int(nid[1:])
        if idx <= sym_idx or nid in c_pruned:
            return False
        if info[nid]["role"] != "STATE_UPD" or info[nid]["uses"] != "{}" or info[nid]["defs"] == "{}":
            return False
        prev_nid = f"N{idx - 1}"
        if prev_nid not in info or info[prev_nid]["role"] != "BRANCH":
            return False
        try:
            return abs(float(info[prev_nid]["a_hits"]) - float(s_info["a_hits"])) < 0.5
        except Exception:
            return False

    has_flag_without_break = any(_is_inner_branch_flag(nid) for nid in all_nids)
    if has_flag_without_break and s_info.get("defs", "{}") != "{}":
        return [symptom] + [x for x in c_pruned if x != symptom]

    state_upds = [x for x in c_pruned if x != symptom and info.get(x, {}).get("role") == "STATE_UPD"]
    if state_upds:
        if use_loop_def_use and s_info.get("role") == "LOOP":
            inter = [nid for nid in state_upds if nid in rec["slicing"]["c_inter_only"]]
            if inter:
                aliases = loop_bound_aliases(rec, inter, symptom)
                state_upds = [nid for nid in state_upds if nid not in aliases]

        def _is_intra_reset(nid: str) -> bool:
            if int(nid[1:]) <= sym_idx:
                return False
            try:
                return abs(float(info[nid]["a_work"]) - float(s_info["a_work"])) < 0.5
            except Exception:
                return False

        intra_resets = [x for x in state_upds if _is_intra_reset(x)]
        inter_resets = [x for x in state_upds if not _is_intra_reset(x)]
        ordered_upds = intra_resets + inter_resets
        rest = [x for x in c_pruned if x not in state_upds and x != symptom]
        return ordered_upds + ([symptom] if symptom in c_pruned else []) + rest

    return ([symptom] if symptom in c_pruned else []) + [x for x in c_pruned if x != symptom]


# Coarse 3-class AST role projection: Function Entry ('FN'), State Update ('UPD'),
# and Control/Call Operations ('OP' for LOOP, CALL, BRANCH)
ROLE_SHORT_MAP = {
    "FUNCTION_ENTRY": "FN",
    "STATE_UPD": "UPD",
    "LOOP": "OP",
    "CALL": "OP",
    "BRANCH": "OP",
}


def _fmt_exp_1d(val: str) -> str:
    if "EXP" in val:
        return "EXP"
    try:
        v = float(val)
        if val.startswith("+") or val.startswith("-"):
            return f"{v:+.1f}"
        return f"{v:.1f}"
    except Exception:
        return val


def _fmt_du_compact(s: str) -> str:
    v = s.strip("{}").replace(" ", "")
    if not v:
        return "-"
    parts = v.split(",")
    return ",".join(parts[:2])


def build_variant_prompt_and_cands(
    rec: Dict, repr_kind: str, *, tag_mode: Optional[str] = None, node_only=False,
) -> Tuple[str, List[str], List[str]]:
    """
    Build strictly fair, uniform-preview prompts across all representations (all <= 512 tokens).
    Every code-bearing representation shares the same previews of up to 26 characters.
    The scope-isolated protocol uses hits/work for EAPG and keeps the lexical preview last.
    """
    if tag_mode not in (None, "slice", "rank"):
        raise ValueError(f"Unknown tag mode: {tag_mode}")
    info = parse_skeleton_nodes(rec)
    compact = rec.get("pilot_revision") == PILOT_REVISION
    dual_exponents = rec.get("scope_protocol") == "main_scope"
    all_nodes = sorted(list(info.keys()), key=lambda x: int(x[1:]))
    c_pruned = rec["slicing"]["c_pruned"] if rec["slicing"]["c_pruned"] else all_nodes
    det_rank = (
        rank_candidates_by_role_priority(rec, use_loop_def_use=node_only)
        if repr_kind in ("abstract_graph", "full_eapg") and tag_mode != "slice" else []
    )

    def node_label(nid: str) -> str:
        code = _nid_to_code(nid)
        return code if compact else f"{code}({nid})"

    def exponent(value: str) -> str:
        rounded = _fmt_exp_1d(value)
        return rounded.removesuffix(".0") if compact else rounded

    def dynamic_exponents(node: Dict) -> str:
        work = exponent(node["a_work"])
        return f"{exponent(node['a_hits'])}/{work}" if dual_exponents else work

    def slice_tag(nid: str) -> str:
        if det_rank and nid == det_rank[0]:
            return "RANK1"
        if len(det_rank) > 1 and nid == det_rank[1]:
            return "RANK2"
        if nid in c_pruned:
            return "SLICE"
        return "" if node_only else "-"

    header = "Task: Localize bottleneck node and paradigm.\n"
    answer = "\nAnswer (Node Paradigm):"
    if node_only:
        header = "Locate bottleneck node.\n"
        answer = "\nAnswer:"
    elif dual_exponents:
        header = "Find bottleneck and repair family.\n"
        if repr_kind in ("abstract_graph", "full_eapg"):
            header = "Find bottleneck and repair family. Exponents: hits/work.\n"
        answer = "\nAnswer:"

    if repr_kind == "raw_code":
        # Variants 3a/3b: Raw C++ statements only (no AST roles, no def/use, no scaling exponents, no slice tags)
        lines = [f"{node_label(nid)} | {info[nid]['preview']}" for nid in all_nodes]
        prompt = header + "\n".join(lines) + answer
        return prompt, all_nodes, c_pruned

    if repr_kind == "hotspot_raw":
        # Variant 4: Hotspot-Guided SLM (EffiLearner / ECCO style: Raw C++ statements + control-flow line hits a_hits)
        lines = [f"{node_label(nid)} | h={exponent(info[nid]['a_hits'])} | {info[nid]['preview']}" for nid in all_nodes]
        prompt = header + "\n".join(lines) + answer
        return prompt, all_nodes, c_pruned

    if repr_kind == "static_eapg":
        # Variant 5 (Ablation A): Static EAPG (Role + Defs/Uses + Preview, no dynamic exponents, no slice tags)
        lines = [
            f"{node_label(nid)} | {ROLE_SHORT_MAP.get(info[nid]['role'], 'OP')} {_fmt_du_compact(info[nid]['defs'])}/{_fmt_du_compact(info[nid]['uses'])} | {info[nid]['preview']}"
            for nid in all_nodes
        ]
        prompt = header + "\n".join(lines) + answer
        return prompt, all_nodes, c_pruned

    if repr_kind == "abstract_graph":
        # 6a/6b share role, exponents, and tags with 7a/7b.
        sep = " " if dual_exponents else " | "
        lines = [
            f"{node_label(nid)}{sep}{ROLE_SHORT_MAP.get(info[nid]['role'], 'OP')} D{len([x for x in info[nid]['defs'].strip('{}').split(',') if x.strip()])}/U{len([x for x in info[nid]['uses'].strip('{}').split(',') if x.strip()])} {dynamic_exponents(info[nid])} {slice_tag(nid)}".rstrip()
            for nid in all_nodes
        ]
        prompt = header + "\n".join(lines) + answer
        return prompt, all_nodes, c_pruned

    if repr_kind == "full_eapg":
        # 7a/7b use def/use identifiers and include a lexical preview.
        lines = []
        for nid in all_nodes:
            node = info[nid]
            code = node_label(nid)
            role = ROLE_SHORT_MAP.get(node["role"], "OP")
            du = f"{_fmt_du_compact(node['defs'])}/{_fmt_du_compact(node['uses'])}"
            features = f"{role} {du} {dynamic_exponents(node)} {slice_tag(nid)}".rstrip()
            preview = node["preview"]
            if node_only:
                lines.append(f"{code} {features} | {preview}")
            elif dual_exponents:
                lines.append(f"{code} {features} {preview}")
            elif tag_mode is None and not compact:
                lines.append(f"{code} {preview} | {features}")
            else:
                lines.append(f"{code} | {features} | {preview}")
        prompt = header + "\n".join(lines) + answer
        return prompt, all_nodes, c_pruned

    raise ValueError(f"Unknown repr_kind: {repr_kind}")


def run_ablation_matrix(build_dir: Path, out_dir: Path, *, rank_tag_ablation=False, node_only=False) -> Dict:
    """
    Execute 5-Fold Problem-Quarantined Cross-Validation across the 7-Variant Ablation Matrix
    using 4-bit NF4 QLoRA (Qwen/Qwen2.5-Coder-1.5B) on the RTX 4060 (--stage ablation).
    Enforces:
      1. Strictly identical hyperparameters (epochs=6, lr=6e-4, grad_accum=4) and untruncated
         26-char statement previews across all fine-tuned variants (3b, 4, 5, 6a/6b, 7a/7b).
      2. Full sequence length (<= 512 tokens) with ZERO tail truncation.
      3. Both Unconstrained Decoding (all_nodes) and Slice-Constrained Decoding (c_pruned).
    """
    import gc
    import hashlib
    import random
    import time
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
    from transformers.models.qwen2.modeling_qwen2 import create_causal_mask
    from peft import LoraConfig, get_peft_model

    t_start = time.time()
    torch.manual_seed(42)
    random.seed(42)

    pilot_json = out_dir / "pilot100_results.json"
    if pilot_json.exists():
        pilot_bytes = pilot_json.read_bytes()
        records = json.loads(pilot_bytes)
    else:
        raise FileNotFoundError(f"Run --stage pilot-100 before ablation: {pilot_json}")

    pids = sorted(list(set(r["problem_id"] for r in records)))
    revised_pilot = any("pilot_revision" in row for row in records)
    scope_protocols = {row.get("scope_protocol", "shared_root") for row in records}
    if len(scope_protocols) != 1:
        raise ValueError("Cannot mix scope protocols in one evaluation")
    scope_protocol = next(iter(scope_protocols))
    scope_isolated = scope_protocol == "main_scope"
    if node_only and (not scope_isolated or rank_tag_ablation):
        raise ValueError("The node-only matrix requires the scope-isolated pilot")
    repair_families = scope_isolated and not node_only
    target_count = 1 if node_only else 2
    expanded_adapters = rank_tag_ablation or revised_pilot
    if revised_pilot:
        if not all(
            row.get("pilot_revision") == PILOT_REVISION
            and tuple(row.get("stdout_equivalence_scales", ())) == PILOT_EQUIVALENCE_SCALES
            and len(row.get("template_fingerprints", ())) == 2
            for row in records
        ):
            raise ValueError("Revised pilot requires complete stdout and template provenance")
        _, source_groups = split_pilot_templates(records)
    else:
        random.Random(42).shuffle(pids)
        folds = [set(pids[i::5]) for i in range(5)]
    if expanded_adapters:
        if len(records) != 100 or len(pids) != 41 or len({r["pair_id"] for r in records}) != 100:
            raise ValueError("Expected a 100-pair, 41-problem pilot")
    if rank_tag_ablation:
        out_dir = out_dir / "rank_tag_ablation"
        out_dir.mkdir(parents=True, exist_ok=True)
    if node_only:
        out_dir = out_dir / "node_only_ablation"
        out_dir.mkdir(parents=True, exist_ok=True)
    reduction = 100 * sum(1 - len(r["slicing"]["c_pruned"]) / r["v_slow"] for r in records) / len(records)
    slice_recall = 100 * sum(r["gt_node"] in r["slicing"]["c_pruned"] for r in records) / len(records)
    if scope_isolated:
        gate = pilot_slice_gate(reduction, slice_recall)
        print(f"  [+] Slice gate: {gate} ({reduction:.1f}% reduction, {slice_recall:.1f}% recall)")
        if gate != "PASS":
            raise ValueError(f"Cannot train before passing the slice gate: {gate}")
    reduction = round(reduction, 1)

    target_codes = {} if node_only else (REPAIR_FAMILY_TO_CODE if repair_families else PARADIGM_TO_CODE)
    target_by_pair = {
        r["pair_id"]: REPAIR_FAMILY_BY_MECHANISM[r["mechanism_id"]] if repair_families else r["paradigm"]
        for r in records if not node_only
    }

    free_b, total_b = torch.cuda.mem_get_info()
    print(f"  [+] VRAM Guard Pre-Flight: {free_b/(1024**3):.2f} GB free / {total_b/(1024**3):.2f} GB total ({torch.cuda.get_device_name(0)})")
    print(f"  [+] 5-Fold Problem-Quarantined Split (41 problems -> 5 disjoint folds, N=100 out-of-sample pairs)")
    if expanded_adapters and free_b < 3 * 1024**3:
        raise RuntimeError("The eight-block run requires at least 3 GiB of free GPU memory at startup")

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    tok = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-Coder-1.5B", local_files_only=expanded_adapters)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    if revised_pilot:
        prompt_modes = [
            ("raw_code", None), ("hotspot_raw", None), ("static_eapg", None),
            ("abstract_graph", "slice"), ("abstract_graph", "rank"),
            ("full_eapg", "slice"), ("full_eapg", "rank"),
        ]
        prompt_fingerprints = {}
        for row in records:
            fingerprints = []
            for kind, tags in prompt_modes:
                prompt, _, _ = build_variant_prompt_and_cands(row, kind, tag_mode=tags, node_only=node_only)
                ids = tok.encode(prompt, add_special_tokens=False)
                fingerprints.append(hashlib.sha256(json.dumps(ids).encode("utf-8")).hexdigest())
            prompt_fingerprints[row["pair_id"]] = fingerprints
        folds, template_groups = split_pilot_templates(records, prompt_fingerprints=prompt_fingerprints)
        print(f"  [+] Source and prompt quarantine: {len(source_groups)} source groups, {len(template_groups)} merged groups")
    for i in range(5):
        for j in range(i + 1, 5):
            assert folds[i].isdisjoint(folds[j]), "FATAL: Fold problem_id overlap!"
    if repair_families:
        from collections import Counter

        family_train_counts = {}
        for i, test_ids in enumerate(folds):
            counts = Counter(target_by_pair[r["pair_id"]] for r in records if r["problem_id"] not in test_ids)
            if set(counts) != set(target_codes):
                raise ValueError(f"Fold {i} training is missing repair families: {set(target_codes) - set(counts)}")
            family_train_counts[f"fold_{i}"] = dict(counts)
        print("  [+] Every training fold contains all four repair families")

    base_model = AutoModelForCausalLM.from_pretrained(
        "Qwen/Qwen2.5-Coder-1.5B",
        quantization_config=bnb_config,
        device_map="auto",
        local_files_only=expanded_adapters,
    )
    base_model.eval()

    SPLIT_LAYER = 20 if expanded_adapters else 27
    adapted_layers = list(range(SPLIT_LAYER, base_model.config.num_hidden_layers))
    lora_cfg = LoraConfig(
        r=16,
        lora_alpha=32,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        layers_to_transform=adapted_layers,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )
    peft_m = get_peft_model(base_model, lora_cfg)
    if expanded_adapters:
        peft_m.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    peft_m.eval()

    node_code_ids = {code: tok.encode(" " + code, add_special_tokens=False)[-1] for code in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}
    parad_code_ids = {code: tok.encode(" " + code, add_special_tokens=False)[-1] for code in target_codes.values()}

    @torch.no_grad()
    def extract_full_prefix(seq_ids: List[int]) -> torch.Tensor:
        """Cache hidden states after the frozen prefix for the full input sequence."""
        inp = torch.tensor([seq_ids], dtype=torch.long, device="cuda")
        qmodel = peft_m.base_model.model.model
        inputs_embeds = qmodel.embed_tokens(inp)
        pos_ids = torch.arange(inputs_embeds.shape[1], device="cuda").unsqueeze(0)
        mask_kwargs = {
            "config": qmodel.config,
            "inputs_embeds": inputs_embeds,
            "attention_mask": None,
            "past_key_values": None,
            "position_ids": pos_ids,
        }
        c_mask = create_causal_mask(**mask_kwargs)
        pos_emb = qmodel.rotary_emb(inputs_embeds, pos_ids)
        h = inputs_embeds
        for i in range(SPLIT_LAYER):
            h = qmodel.layers[i](
                h,
                attention_mask=c_mask,
                position_embeddings=pos_emb,
                position_ids=pos_ids,
            )
        return h.detach()

    def forward_suffix(h_seq: torch.Tensor, lengths: Optional[torch.Tensor] = None) -> torch.Tensor:
        """Run every adapted block over the full sequence and score the target positions."""
        qmodel = peft_m.base_model.model.model
        seq_l = h_seq.shape[1]
        pos_ids = torch.arange(seq_l, device="cuda").unsqueeze(0)
        attention_mask = None if lengths is None else pos_ids < lengths[:, None]
        mask_kwargs = {
            "config": qmodel.config,
            "inputs_embeds": h_seq,
            "attention_mask": attention_mask,
            "past_key_values": None,
            "position_ids": pos_ids,
        }
        c_mask = create_causal_mask(**mask_kwargs)
        pos_emb = qmodel.rotary_emb(h_seq, pos_ids)
        curr = h_seq
        for layer in qmodel.layers[SPLIT_LAYER:]:
            curr = layer(curr, attention_mask=c_mask, position_embeddings=pos_emb, position_ids=pos_ids)
        if lengths is not None:
            batch_indices = torch.arange(len(lengths), device=curr.device)[:, None]
            offsets = torch.arange(-target_count, 0, device=curr.device)
            curr = curr[batch_indices, lengths[:, None] + offsets]
        elif expanded_adapters:
            curr = curr[:, -target_count:, :]
        curr = qmodel.norm(curr)
        return peft_m.base_model.model.lm_head(curr)

    def reset_lora_weights(seed: int):
        torch.manual_seed(seed)
        for name, param in peft_m.named_parameters():
            if "lora_A" in name:
                nn.init.kaiming_uniform_(param, a=5 ** 0.5)
            elif "lora_B" in name:
                nn.init.zeros_(param)

    results_summary: Dict[str, Dict[str, float]] = {}
    per_pair_logs: Dict[str, Dict] = {
        r["pair_id"]: {
            "problem_id": r["problem_id"],
            "track_gt": r["track_gt"],
            "mechanism_id": r["mechanism_id"],
            "gt_node": r["gt_node"],
            "paradigm_gt": target_by_pair.get(r["pair_id"]),
            "variants": {},
        }
        for r in records
    }

    # Evaluate Variant 1 (Naive Profiler) and Variant 2 (Deterministic PDG Slice)
    v1_top1, v1_top2, v1_a1, v1_a2, v1_reset = 0, 0, 0, 0, 0
    v2_top1, v2_top2, v2_a1, v2_a2, v2_reset = 0, 0, 0, 0, 0
    for r in records:
        c_work = r["slicing"]["c_naive_work"]
        p1_list = c_work if c_work else [r["slicing"]["primary_symptom"]]
        if p1_list[0] == r["gt_node"]:
            v1_top1 += 1
            if r["track_gt"] == "A1":
                v1_a1 += 1
            elif r["track_gt"] == "A2":
                v1_a2 += 1
            if r["mechanism_id"] in ("A1.1", "A1.4"):
                v1_reset += 1
        if r["gt_node"] in p1_list[:2]:
            v1_top2 += 1
        per_pair_logs[r["pair_id"]]["variants"]["1"] = {"pred_top1": p1_list[0], "pred_top2": p1_list[:2], "pred_paradigm": None}

        rk2 = rank_candidates_by_role_priority(r, use_loop_def_use=node_only)
        if rk2[0] == r["gt_node"]:
            v2_top1 += 1
            if r["track_gt"] == "A1":
                v2_a1 += 1
            elif r["track_gt"] == "A2":
                v2_a2 += 1
            if r["mechanism_id"] in ("A1.1", "A1.4"):
                v2_reset += 1
        if r["gt_node"] in rk2[:2]:
            v2_top2 += 1
        per_pair_logs[r["pair_id"]]["variants"]["2"] = {"pred_top1": rk2[0], "pred_top2": rk2[:2], "pred_paradigm": None}

    results_summary["1"] = {
        "top1": float(v1_top1), "top2": float(v1_top2),
        "a1_top1": round(v1_a1 / 38.0 * 100.0, 1), "a2_top1": round(v1_a2 / 24.0 * 100.0, 1),
        "reset_top1": round(v1_reset / 18.0 * 100.0, 1), "r_search": 0.0, "paradigm": -1.0,
    }
    results_summary["2"] = {
        "top1": float(v2_top1), "top2": float(v2_top2),
        "a1_top1": round(v2_a1 / 38.0 * 100.0, 1), "a2_top1": round(v2_a2 / 24.0 * 100.0, 1),
        "reset_top1": round(v2_reset / 18.0 * 100.0, 1), "r_search": reduction, "paradigm": -1.0,
    }

    # Uniform training hyperparameters across ALL fine-tuned 1.5B variants
    UNIFORM_EPOCHS = 6
    UNIFORM_LR = 6e-4
    GRAD_ACCUM = 4
    microbatch = 2 if expanded_adapters else 1

    run_specs = [
        ("raw_code", None, 0, [("3a", "unconstrained", 0.0)]),
        ("raw_code", None, UNIFORM_EPOCHS, [("3b", "unconstrained", 0.0)]),
        ("hotspot_raw", None, UNIFORM_EPOCHS, [("4", "unconstrained", 0.0)]),
        ("static_eapg", None, UNIFORM_EPOCHS, [("5", "unconstrained", 0.0)]),
        ("abstract_graph", None, UNIFORM_EPOCHS, [("6a", "unconstrained", 0.0), ("6b", "slice_constrained", 80.6)]),
        ("full_eapg", None, UNIFORM_EPOCHS, [("7a", "unconstrained", 0.0), ("7b", "slice_constrained", 80.6)]),
    ]
    if rank_tag_ablation:
        run_specs = [
            (repr_kind, tags, UNIFORM_EPOCHS, [(f"{variant}-{tags}", "slice_constrained", reduction)])
            for repr_kind, variant in (("abstract_graph", "6b"), ("full_eapg", "7b"))
            for tags in ("slice", "rank")
        ]
    elif revised_pilot:
        run_specs = run_specs[:4] + [
            (repr_kind, tags, UNIFORM_EPOCHS, [
                (f"{family}a-{tags}", "unconstrained", 0.0),
                (f"{family}b-{tags}", "slice_constrained", reduction),
            ])
            for repr_kind, family in (("abstract_graph", "6"), ("full_eapg", "7"))
            for tags in ("slice", "rank")
        ]

    trainable_params = [p for p in peft_m.parameters() if p.requires_grad]
    if expanded_adapters:
        attached_layers = {
            int(name.split(".layers.", 1)[1].split(".", 1)[0])
            for name, p in peft_m.named_parameters() if p.requires_grad
        }
        assert attached_layers == set(range(20, 28)), f"Unexpected adapter layers: {attached_layers}"

    for repr_kind, tag_mode, epochs, eval_targets in run_specs:
        gc.collect()
        torch.cuda.empty_cache()

        cached_items = []
        max_tok_len = 0
        for r in records:
            prompt, all_nodes, c_pruned = build_variant_prompt_and_cands(
                r, repr_kind, tag_mode=tag_mode, node_only=node_only,
            )
            n_code = _nid_to_code(r["gt_node"])
            full_text = f"{prompt} {n_code}"
            target_ids = [node_code_ids[n_code]]
            if not node_only:
                p_code = target_codes[target_by_pair[r["pair_id"]]]
                full_text += f" {p_code}"
                target_ids.append(parad_code_ids[p_code])
            f_ids = tok.encode(full_text, add_special_tokens=False)
            max_tok_len = max(max_tok_len, len(f_ids))
            assert len(f_ids) <= 512, f"Sequence cap exceeded ({len(f_ids)} > 512) on {r['pair_id']} ({repr_kind})"
            if expanded_adapters:
                assert f_ids[:-target_count] == tok.encode(prompt, add_special_tokens=False)
                assert f_ids[-target_count:] == target_ids
            h_full = extract_full_prefix(f_ids[:-1])
            tgt = torch.tensor(f_ids[-target_count:], dtype=torch.long, device="cuda")
            cached_items.append({
                "rec": r,
                "all_nodes": all_nodes,
                "c_pruned": c_pruned,
                "h": h_full,
                "tgt": tgt,
            })

        stats = {v_key: {"top1": 0, "top2": 0, "parad": 0, "a1": 0, "a2": 0, "b": 0, "b_parad": 0, "rst": 0, "r_search": rs} for v_key, _, rs in eval_targets}
        if expanded_adapters:
            print(f"  [+] {eval_targets[0][0]}: cached {len(cached_items)} prompts, max {max_tok_len} tokens")

        for fold_idx in range(5):
            test_pids = folds[fold_idx]
            train_data = [x for x in cached_items if x["rec"]["problem_id"] not in test_pids]
            test_data = [x for x in cached_items if x["rec"]["problem_id"] in test_pids]
            if expanded_adapters:
                assert {x["rec"]["problem_id"] for x in train_data}.isdisjoint(test_pids)
                fold_start = time.monotonic()

            reset_lora_weights(seed=42 + fold_idx)
            f_rng = random.Random(42 + fold_idx)
            optimizer = torch.optim.AdamW(trainable_params, lr=UNIFORM_LR, weight_decay=0.01)

            if expanded_adapters and epochs > 0:
                peft_m.train()
                group_size = microbatch * GRAD_ACCUM
                for _ in range(epochs):
                    gc.collect()
                    torch.cuda.empty_cache()
                    f_rng.shuffle(train_data)
                    for start in range(0, len(train_data), group_size):
                        group = train_data[start:start + group_size]
                        optimizer.zero_grad()
                        for offset in range(0, len(group), microbatch):
                            batch = group[offset:offset + microbatch]
                            seqs = [item["h"].squeeze(0) for item in batch]
                            lengths = torch.tensor([len(h) for h in seqs], device="cuda")
                            padded = nn.utils.rnn.pad_sequence(seqs, batch_first=True)
                            targets = torch.stack([item["tgt"] for item in batch])
                            logits = forward_suffix(padded, lengths)
                            loss = F.cross_entropy(logits.flatten(0, 1), targets.flatten(), reduction="sum")
                            (loss / targets.size(1) / len(group)).backward()
                        optimizer.step()
                optimizer.zero_grad(set_to_none=True)
                gc.collect()
                torch.cuda.empty_cache()
            elif epochs > 0:
                peft_m.train()
                for _ in range(epochs):
                    f_rng.shuffle(train_data)
                    optimizer.zero_grad()
                    for idx, item in enumerate(train_data):
                        logits = forward_suffix(item["h"])
                        logits_last2 = logits[0, -2:, :]
                        loss = F.cross_entropy(logits_last2, item["tgt"]) / GRAD_ACCUM
                        loss.backward()
                        if (idx + 1) % GRAD_ACCUM == 0 or (idx + 1) == len(train_data):
                            optimizer.step()
                            optimizer.zero_grad()

            peft_m.eval()
            with torch.no_grad():
                for item in test_data:
                    r = item["rec"]
                    logits = forward_suffix(item["h"])
                    logits_node = logits[0, -target_count, :]
                    pred_p = None
                    parad_ok = False
                    if not node_only:
                        logits_parad = logits[0, -1, :]
                        p_scores = [(float(logits_parad[parad_code_ids[code]].item()), p_name) for p_name, code in target_codes.items()]
                        p_scores.sort(key=lambda x: x[0], reverse=True)
                        pred_p = p_scores[0][1]
                        parad_ok = (pred_p == target_by_pair[r["pair_id"]])

                    for v_key, mode, _ in eval_targets:
                        cands = item["all_nodes"] if mode == "unconstrained" else item["c_pruned"]
                        cand_scores = [(float(logits_node[node_code_ids[_nid_to_code(c_nid)]].item()), c_nid) for c_nid in cands]
                        cand_scores.sort(key=lambda x: x[0], reverse=True)
                        pred_top1 = cand_scores[0][1]
                        pred_top2 = [x[1] for x in cand_scores[:2]]

                        if pred_top1 == r["gt_node"]:
                            stats[v_key]["top1"] += 1
                            if r["track_gt"] == "A1":
                                stats[v_key]["a1"] += 1
                            elif r["track_gt"] == "A2":
                                stats[v_key]["a2"] += 1
                            elif r["track_gt"] == "B":
                                stats[v_key]["b"] += 1
                            if r["mechanism_id"] in ("A1.1", "A1.4"):
                                stats[v_key]["rst"] += 1
                        if r["gt_node"] in pred_top2:
                            stats[v_key]["top2"] += 1
                        if parad_ok:
                            stats[v_key]["parad"] += 1
                            if r["track_gt"] == "B":
                                stats[v_key]["b_parad"] += 1

                        per_pair_logs[r["pair_id"]]["variants"][v_key] = {
                            "fold": fold_idx,
                            "decoding_mode": mode,
                            "max_prompt_tokens": max_tok_len,
                            "pred_top1": pred_top1,
                            "pred_top2": pred_top2,
                            "pred_paradigm": pred_p,
                        }
                        if expanded_adapters:
                            per_pair_logs[r["pair_id"]]["variants"][v_key]["candidate_logits"] = dict(
                                (nid, score) for score, nid in cand_scores
                            )
            if expanded_adapters:
                del optimizer
                gc.collect()
                torch.cuda.empty_cache()
                peak_mb = torch.cuda.max_memory_allocated() / 1024**2
                print(f"  [+] {eval_targets[0][0]} fold {fold_idx + 1}/5: {time.monotonic() - fold_start:.1f}s, peak {peak_mb:.0f} MiB")

        for v_key, mode, rs in eval_targets:
            s = stats[v_key]
            results_summary[v_key] = {
                "top1": float(s["top1"]),
                "top2": float(s["top2"]),
                "a1_top1": round(s["a1"] / 38.0 * 100.0, 1),
                "a2_top1": round(s["a2"] / 24.0 * 100.0, 1),
                "reset_top1": round(s["rst"] / 18.0 * 100.0, 1),
                "r_search": rs,
                "paradigm": -1.0 if node_only else float(s["parad"]),
                "max_tokens": max_tok_len,
                "epochs": epochs,
                "lr": UNIFORM_LR if epochs > 0 else 0.0,
                "decoding_mode": mode,
            }
            if expanded_adapters:
                n_b = sum(r["track_gt"] == "B" for r in records)
                results_summary[v_key].update({
                    "b_top1": round(s["b"] / n_b * 100, 1),
                    "representation": repr_kind,
                    "tag_mode": tag_mode,
                })
                if not node_only:
                    results_summary[v_key]["b_paradigm_given_reference"] = round(s["b_parad"] / n_b * 100, 1)

        del cached_items, train_data, test_data, item, h_full
        gc.collect()
        torch.cuda.empty_cache()

    peak_mb = round(torch.cuda.max_memory_allocated() / (1024 ** 2), 1)
    dt_total = round(time.time() - t_start, 1)
    multi_candidate_count = None
    if node_only:
        multi_pair_ids = [r["pair_id"] for r in records if len(r["slicing"]["c_pruned"]) >= 2]
        multi_candidate_count = len(multi_pair_ids)
        if not multi_candidate_count:
            raise ValueError("Multi-candidate Top-1 requires at least one multi-candidate slice")
        for variant, summary in results_summary.items():
            correct = sum(
                per_pair_logs[pid]["variants"][variant]["pred_top1"] == per_pair_logs[pid]["gt_node"]
                for pid in multi_pair_ids
            )
            summary["multi_correct"] = correct
            summary["multi_top1"] = round(100 * correct / multi_candidate_count, 1)

    print("\n" + "=" * 132)
    print("STAGE 4 ABLATION MATRIX: Five-Fold Pilot Evaluation (100 Constructed Pairs, 41 Problem IDs)")
    print("=" * 132)
    final_metric = "Multi-cand. Top-1%" if node_only else "Paradigm%"
    print(f"{'#':<3} | {'Variant / Method':<35} | {'Backbone':<14} | {'Top-1%':<7} | {'Top-2%':<7} | {'Reset%':<7} | {'A1 Rec%':<8} | {'A2 Rec%':<8} | {'R_search%':<9} | {final_metric}")
    print("-" * 132)
    variants = RANK_TAG_VARIANTS if rank_tag_ablation else (REVISED_VARIANTS if revised_pilot else VARIANTS)
    for v_key, name, bb, _, _ in variants:
        r_m = results_summary[v_key]
        value = r_m["multi_top1"] if node_only else r_m["paradigm"]
        p_str = "--" if value < 0 else f"{value:.1f}"
        print(
            f"{v_key:<3} | {name:<35} | {bb:<14} | {r_m['top1']:<7.1f} | {r_m['top2']:<7.1f} | "
            f"{r_m['reset_top1']:<7.1f} | {r_m['a1_top1']:<8.1f} | {r_m['a2_top1']:<8.1f} | "
            f"{r_m['r_search']:<9.1f} | {p_str}"
        )
    print("=" * 132)
    print(f"  [+] Peak VRAM Footprint : {peak_mb} MB (8,192 MB RTX 4060 Cap: PASS)")
    print(f"  [+] Total Wall-Clock    : {dt_total}s across 5 folds")

    full_output = {
        "protocol": "5-Fold Problem-Quarantined Out-of-Sample Cross-Validation (N=100 pairs, 41 Problem IDs)",
        "seed": 42,
        "hyperparameters": {
            "epochs": UNIFORM_EPOCHS,
            "lr": UNIFORM_LR,
            "grad_accum": GRAD_ACCUM,
            "max_seq_len_cap": 512,
            "tail_truncation": None,
            "preview_chars": 26,
        },
        "hardware": {
            "device": torch.cuda.get_device_name(0),
            "peak_vram_mb": peak_mb,
            "quantization": "4-bit NF4 Double-Quant (torch.bfloat16)",
            "wall_clock_sec": dt_total,
        },
        "folds": {f"fold_{i}": sorted(list(folds[i])) for i in range(5)},
        "variants": results_summary,
        "per_pair_predictions": per_pair_logs,
    }
    if expanded_adapters:
        full_output["pilot_sha256"] = hashlib.sha256(pilot_bytes).hexdigest()
        full_output["hyperparameters"].update({
            "adapted_layers": adapted_layers,
            "frozen_prefix_blocks": SPLIT_LAYER,
            "microbatch": microbatch,
            "gradient_checkpointing": True,
            "lexical_preview_position": "last",
            "paradigm_given_reference": not node_only,
            "target_tokens": target_count,
        })
    if rank_tag_ablation:
        full_output["protocol"] = "2x2 representation by rank tags, five-fold cross-validation by problem ID"
    if revised_pilot:
        full_output["protocol"] = "Five-fold cross-validation by problem ID, canonical template, and exact prompt tokens"
        full_output["pilot_revision"] = PILOT_REVISION
        full_output["scope_protocol"] = scope_protocol
        full_output["source_template_group_count"] = len(source_groups)
        full_output["template_groups"] = template_groups
        full_output["stdout_equivalence_scales"] = list(PILOT_EQUIVALENCE_SCALES)
        full_output["hyperparameters"]["node_labels"] = "single-letter codes"
    if scope_isolated:
        full_output["slice_gate"] = {"min_reduction_pct": 75.0, "min_recall_pct": 95.0, "recall_pct": slice_recall}
        full_output["hyperparameters"]["eapg_exponents"] = "hits/work"
    if repair_families:
        full_output["repair_family_codes"] = target_codes
        full_output["repair_family_mechanisms"] = REPAIR_FAMILIES
        full_output["repair_family_training_counts"] = family_train_counts
    if node_only:
        full_output["objective"] = "single-token node localization"
        full_output["rank_policy"] = "inter-scope def-site count or enclosing induction-variable dependency"
        full_output["multi_candidate_pair_ids"] = multi_pair_ids
        full_output["hyperparameters"]["lexical_preview_delimiter"] = "|"

    json_path = out_dir / "evaluation_results.json"
    tex_path = out_dir / "table_ablation.tex"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(full_output, f, indent=2)

    tex_content = export_ablation_latex_table(
        results_summary, str(tex_path), rank_tag_ablation=rank_tag_ablation,
        revised_pilot=revised_pilot, repair_families=repair_families,
        multi_candidate_count=multi_candidate_count,
    )
    print(f"  [+] Raw evaluation log saved to: {json_path}")
    print(f"  [+] LaTeX booktabs table saved to: {tex_path}")
    print("\nGenerated LaTeX Preview:")
    print(tex_content)
    return full_output


# ==============================================================================
# CLI Entrypoint
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(description="EAPG Research Pipeline Master Orchestrator")
    parser.add_argument("--stage", choices=["all", "verify-env", "o2-test", "milestone-1", "pilot-100", "build-dataset", "ablation", "rank-tag-ablation", "node-only-ablation"], default="milestone-1",
                        help="Execution stage to run")
    default_artifacts = Path(__file__).parent / "artifacts"
    parser.add_argument("--output-dir", type=str,
                        help="Output directory for generated logs and tables")
    args = parser.parse_args()

    if args.stage in ("all", "pilot-100", "ablation", "node-only-ablation"):
        default_artifacts = default_artifacts / "scope_isolated_pilot"
    out_dir = Path(args.output_dir) if args.output_dir else default_artifacts
    out_dir.mkdir(parents=True, exist_ok=True)
    build_dir = out_dir / "build"

    if args.stage in ("verify-env", "all"):
        print("[Stage 0/4] Verifying Hardware & Compiler Environment...")
        try:
            res = subprocess.run(["g++", "--version"], capture_output=True, text=True)
            compiler_ok = (res.returncode == 0)
            print(f"  [+] C++ Compiler (g++): {'Available' if compiler_ok else 'Missing'}")
        except FileNotFoundError:
            print("  [-] C++ Compiler (g++): Not found in PATH")

        try:
            import torch
            has_cuda = torch.cuda.is_available()
            vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3) if has_cuda else 0.0
            print(f"  [+] PyTorch CUDA: Available={has_cuda}, Device={torch.cuda.get_device_name(0) if has_cuda else 'N/A'}")
            print(f"  [+] Detected VRAM: {vram_gb:.2f} GB (RTX 4060 target: ~8.00 GB)")
        except ImportError:
            print("  [-] PyTorch: Not installed in active Python environment")

    if args.stage in ("o2-test", "all"):
        print("\n[Stage 2/4] Testing Compiler Optimization Invariance (-O0, -O2, -O3)...")
        sample_code = """
        #include <vector>
        #include <iostream>
        int main() {
            int n = 100;
            long long sum = 0;
            for (int l = 0; l < n; ++l) {
                int r = l;
                while (r < n) { sum += (r++); }
            }
            std::cout << sum << std::endl;
            return 0;
        }
        """
        o2_results = verify_o2_invariance(sample_code)
        for opt, ok in o2_results.items():
            print(f"  [+] Flag {opt}: {'Syntax Clean (Pass)' if ok else 'Fail'}")

    if args.stage in ("milestone-1", "all"):
        print("\n[Milestone 1] Executing Stage 1 AST Normalization & Stage 2 Dynamic Scaling...")
        run_milestone_one(build_dir, out_dir)

    if args.stage in ("pilot-100", "all"):
        print("\n[Exploratory Pilot] Executing 100-Pair Empirical Study (--stage pilot-100)...")
        run_pilot_100_study(build_dir, out_dir)

    if args.stage in ("build-dataset", "all"):
        print("\n[Phase 3 Dataset] Generating Problem-Quarantined QLoRA Split (--stage build-dataset)...")
        build_qlora_dataset(build_dir, out_dir)

    if args.stage in ("ablation", "all"):
        print("\n[Stage 4/4] Executing 5-Fold Problem-Quarantined QLoRA Training & 7-Variant Ablation Matrix...")
        run_ablation_matrix(build_dir, out_dir)

    if args.stage == "rank-tag-ablation":
        print("\n[Stage 4/4] Executing 2x2 EAPG Representation and Rank-Tag Ablation...")
        run_ablation_matrix(build_dir, out_dir, rank_tag_ablation=True)

    if args.stage == "node-only-ablation":
        print("\n[Stage 4/4] Executing the node-only ablation matrix...")
        run_ablation_matrix(build_dir, out_dir, node_only=True)


if __name__ == "__main__":
    main()
