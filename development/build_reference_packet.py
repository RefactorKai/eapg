"""Build the custodian's blinded reference packet in the pinned Linux guest.

Use --fixture --pipeline PATH for the authored test. After external custody
gates, --input expects pair_id, problem_spec, slow_code, fast_code, protocol_sha256,
independent_evidence (record_sha256 and summary), and profile (pipeline_sha256,
normalized_source_sha256, canonical_node_ids) from the actual slow-side profile.
--out writes a private packet at a fresh path. Pin the printed digest separately.
"""

import argparse
import ast
import inspect
import json
from pathlib import Path
import re
import sys
from types import FunctionType, SimpleNamespace

from gate1_sandbox import invoke
from run_phase2_development import load_module, normalize, profile_case, verify_preprocessing


DEPS = Path.home() / ".local/share/eapg-phase2/deps"
if DEPS.is_dir():
    sys.path.insert(0, str(DEPS))
from reference_adjudication import PACKET, digest, fields, json_bytes, read_json, require, sha, text, validate_packet
import phase2_custody_and_probes as custody


CUSTODY_SHA256 = "4140210dfb6c159fc9a51977ca6e40495654f15929c8b4759e5afa09f7b40749"
ARCHIVED_CANDIDATE_SHA256 = "ab43a6e4882bbba6d2f54a9dc9be99dfeb031d5d5633c265e993d53109f41563"


def marker_lines(raw, expanded):
    # A source-supplied line directive can impersonate the GCC location markers.
    logical = re.sub(r"(?:\\|\?\?/)[ \t]*\r?\n", "", raw).replace("??=", "#")
    tokens = custody.tokens(logical)
    for i, (token, following) in enumerate(zip(tokens, tokens[1:])):
        marker = token == "#" or (i > 0 and tokens[i - 1:i + 1] == ["%", ":"])
        require(not (marker and re.match(r"(?:line\Z|[0-9])", following)), "Source line directives are unsupported")

    def sandboxed_run(args, *, input, timeout, **_):
        result = verify_preprocessing(invoke(args, data=input.encode("utf-8"), timeout=timeout), "GCC marker pass")
        return SimpleNamespace(stdout=result.stdout.decode("utf-8"))

    mapper = custody.raw_line_map
    isolated = FunctionType(mapper.__code__, {**mapper.__globals__, "subprocess": SimpleNamespace(run=sandboxed_run)})
    lines, status = isolated(raw, expanded)
    require(status == "aligned", "GCC marker pass did not align with canonical Pass 0")
    return lines


def canonical_spans(pipeline, normalized, aliases):
    extract = pipeline.extract_macro_nodes
    nodes = extract(normalized, aliases)
    if all("normalized_span" in node for node in nodes):
        return nodes
    if pipeline.source_sha256 != ARCHIVED_CANDIDATE_SHA256:
        return custody.spanned_nodes(pipeline, normalized, aliases)

    # The archived candidate adds a fifth emission site inside add_call.
    class ArchivedSpans(ast.NodeTransformer):
        count = 0

        def visit_Dict(self, node):
            self.generic_visit(node)
            keys = {key.value for key in node.keys if isinstance(key, ast.Constant)}
            if {"id", "role", "insert_pos"} <= keys:
                owner = "call" if "call_span" in keys else "n"
                node.keys.append(ast.Constant("normalized_span"))
                node.values.append(ast.parse(f"({owner}.start_byte, {owner}.end_byte)", mode="eval").body)
                self.count += 1
            return node

    transformer = ArchivedSpans()
    source = transformer.visit(ast.parse(inspect.getsource(extract)))
    require(transformer.count == 5, "Unexpected archived candidate node-emission sites")
    namespace = dict(extract.__globals__)
    exec(compile(ast.fix_missing_locations(source), inspect.getfile(extract), "exec"), namespace)
    traced = namespace[extract.__name__](normalized, aliases)
    require([{k: v for k, v in node.items() if k != "normalized_span"} for node in traced] == nodes,
            "Archived candidate spans changed the scoring extractor's output")
    return traced


def build_packet(pipeline, source):
    require(sha(Path(custody.__file__).read_bytes()) == CUSTODY_SHA256, "Pinned custody exporter SHA-256 mismatch")
    fields(source, "pair_id problem_spec slow_code fast_code protocol_sha256 independent_evidence profile")
    require(all(text(source[key]) for key in ("pair_id", "problem_spec", "slow_code", "fast_code"))
            and digest(source["protocol_sha256"]), "Invalid blinded source record")
    evidence, receipt = source["independent_evidence"], source["profile"]
    fields(evidence, "record_sha256 summary")
    require(digest(evidence["record_sha256"]) and text(evidence["summary"]), "Invalid independent screening record")
    fields(receipt, "pipeline_sha256 normalized_source_sha256 canonical_node_ids")
    require(digest(receipt["pipeline_sha256"]) and pipeline.source_sha256 == receipt["pipeline_sha256"]
            and digest(receipt["normalized_source_sha256"]) and type(receipt["canonical_node_ids"]) is list,
            "Invalid or mismatched profiling receipt")
    raw = source["slow_code"]
    traced = {}

    def capture(expanded):
        normalized, origin = custody.traced_normalization(pipeline, expanded)
        traced.update(expanded=expanded, origin=origin)
        return normalized

    # Keep the profiler's checked Pass 0 and parser check. Trace only Pass 1.
    tracer = SimpleNamespace(preprocess_pass_zero=pipeline.preprocess_pass_zero, parser=pipeline.parser,
                             normalize_synthetic_braces=capture)
    normalized, aliases = normalize(tracer, raw)
    normalized_sha = sha(normalized)
    require(normalized_sha == receipt["normalized_source_sha256"], "Normalized source disagrees with the profile")
    nodes = canonical_spans(pipeline, normalized, aliases)
    require([node["id"] for node in nodes] == receipt["canonical_node_ids"], "Canonical IDs disagree with the profile")

    expanded, origin = traced["expanded"], traced["origin"]
    line_map = marker_lines(raw, expanded)
    raw_lines, expanded_lines = raw.splitlines(), expanded.splitlines()
    normalized_bytes, expanded_bytes = normalized.encode("utf-8"), expanded.encode("utf-8")
    macro_names = set(re.findall(r"^\s*#\s*define\s+([A-Za-z_]\w*)", raw, re.MULTILINE))
    rows = []
    for node in nodes:
        start, end = node["normalized_span"]
        require(0 <= start < end <= len(normalized_bytes), "Invalid normalized node span")
        positions = origin[start:end]
        originals = [offset for offset in positions if offset is not None]
        require(bool(originals), "Node has no source-backed bytes")
        first, last = originals[0], originals[-1]
        first_line = expanded_bytes.count(b"\n", 0, first) + 1
        last_line = expanded_bytes.count(b"\n", 0, last) + 1
        lines = [line for line in range(first_line, last_line + 1) if expanded_lines[line - 1].strip()]
        require(lines and all(line in line_map for line in lines), "Node has incomplete raw-line provenance")
        raw_numbers = sorted({line_map[line] for line in lines})
        require(all(1 <= number <= len(raw_lines) for number in raw_numbers), "Invalid raw node line")
        macro_evidence = macro_names & {token for number in raw_numbers for token in custody.tokens(raw_lines[number - 1])}
        rows.append({"node_id": node["id"], "role": node["role"], "normalized_byte_span": [start, end],
                     "normalized_line_span": [normalized_bytes.count(b"\n", 0, start) + 1,
                                              normalized_bytes.count(b"\n", 0, end - 1) + 1],
                     "pre_brace_byte_span": [first, last + 1], "raw_source_lines": raw_numbers,
                     "macro_invocation_evidence": sorted(macro_evidence), "has_synthetic_braces": None in positions})

    packet = {key: value for key, value in source.items() if key != "profile"}
    packet.update(schema=PACKET, pipeline_sha256=pipeline.source_sha256, slow_source_sha256=sha(raw),
                  fast_source_sha256=sha(source["fast_code"]),
                  pass2_map={"normalized_source_sha256": normalized_sha, "line_alignment": "aligned", "nodes": rows})
    validate_packet(packet, sha(json_bytes(packet)))
    return packet


def verify_fixture(pipeline):
    raw = """#define REP(i, n) for (int i = 0; i < (n); ++i)
int main() {
    int n = 5;
    int total = 0;
    REP(i, n)
        if (i > 0) total += i;
    return total - 10;
}
"""
    normalized, nodes, result, counter = profile_case(pipeline, raw, b"", 5)
    require(result.returncode == 0 and counter["status"] == "CLEAN_COMPLETION", "Authored profiling fixture failed")
    profile = {"pipeline_sha256": pipeline.source_sha256, "normalized_source_sha256": sha(normalized),
               "canonical_node_ids": [node["id"] for node in nodes]}
    source = {"pair_id": "authored-macro", "problem_spec": "Sum five positions", "slow_code": raw,
              "fast_code": "int main() { return 0; }", "protocol_sha256": sha("authored fixture protocol"),
              "independent_evidence": {"record_sha256": sha("authored fixture"), "summary": "Authored fixture only"},
              "profile": profile}
    packet = build_packet(pipeline, source)
    loop, = (row for row in packet["pass2_map"]["nodes"] if row["role"] == "LOOP")
    require(loop["macro_invocation_evidence"] == ["REP"] and loop["has_synthetic_braces"]
            and 5 in loop["raw_source_lines"], "Authored macro invocation provenance failed")
    for invalid, expansion in ((raw, "int unrelated;"), ("%:li\\\nne 5\n" + raw, normalized)):
        try:
            marker_lines(invalid, expansion)
        except ValueError:
            continue
        raise AssertionError("Marker mismatch or source directive did not fail closed")
    print(f"Authored Pass-2 packet matched profiled SHA {sha(normalized)} and IDs {profile['canonical_node_ids']}.")


def main():
    cli = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    cli.add_argument("--pipeline", required=True, type=Path)
    mode = cli.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fixture", action="store_true")
    mode.add_argument("--input", type=Path)
    cli.add_argument("--out", type=Path)
    args = cli.parse_args()
    if sys.platform != "linux" or (args.input is not None) != (args.out is not None):
        cli.error("Run in the pinned Linux guest. --input and --out are required together.")
    if args.fixture:
        verify_fixture(load_module("reference_fixture_pipeline", args.pipeline))
        return
    source = read_json(args.input)
    receipt = source.get("profile") if type(source) is dict else None
    fields(receipt, "pipeline_sha256 normalized_source_sha256 canonical_node_ids")
    require(digest(receipt["pipeline_sha256"]), "Expected a pinned pipeline SHA-256")
    pipeline = load_module("reference_packet_pipeline", args.pipeline, receipt["pipeline_sha256"])
    packet = build_packet(pipeline, source)
    with args.out.open("x", encoding="utf-8") as output:
        json.dump(packet, output, indent=2, ensure_ascii=False)
        output.write("\n")
    print(sha(json_bytes(packet)))


if __name__ == "__main__":
    main()
