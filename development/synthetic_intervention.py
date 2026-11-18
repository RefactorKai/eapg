"""Verify a committed reversible edit and its exact canonical token mapping."""

import argparse
from pathlib import Path
from types import SimpleNamespace

from build_reference_packet import custody
from gate1_sandbox import invoke
from reference_adjudication import fields, json_bytes, require, sha
from run_phase2_development import load_module, normalize, verify_preprocessing
from score_synthetic import read_pinned


class UnresolvedOrigin(ValueError):
    """The raw source cannot be projected through the supported origin map."""


def verify_splice(record):
    fields(record, "schema original edited restored source_sha256 edit equivalent_edited_intervals")
    require(record["schema"] == "eapg-synthetic-intervention-v1", "Wrong intervention schema")
    versions = ("original", "edited", "restored")
    fields(record["source_sha256"], " ".join(versions))
    require(all(type(record[name]) is str and record[name] for name in versions), "Expected three UTF-8 sources")
    sources = {name: record[name].encode("utf-8") for name in versions}
    require({name: sha(source) for name, source in sources.items()} == record["source_sha256"],
            "Intervention source digest mismatch")
    patch = record["edit"]
    fields(patch, "start_byte removed inserted")
    start = patch["start_byte"]
    original, edited, restored = (sources[name] for name in versions)
    require(type(start) is int and 0 <= start <= len(original)
            and all(type(patch[key]) is str for key in ("removed", "inserted")), "Invalid UTF-8 byte splice")
    removed, inserted = (patch[key].encode("utf-8") for key in ("removed", "inserted"))
    orig_end, edit_end = start + len(removed), start + len(inserted)
    require(inserted and (removed != inserted), "Expected a nonempty edited-side change")
    require(original[start:orig_end] == removed and original[:start] + inserted + original[orig_end:] == edited,
            "Forward splice does not reproduce the edited source")
    require(edited[start:edit_end] == inserted and edited[:start] + removed + edited[edit_end:] == original == restored,
            "Inverse splice does not restore the original bytes")
    intervals = record["equivalent_edited_intervals"]
    require(type(intervals) is list and all(type(span) is list and len(span) == 2
            and all(type(offset) is int for offset in span)
            and 0 <= span[0] < span[1] <= len(edited) for span in intervals)
            and len({tuple(span) for span in intervals}) == len(intervals), "Invalid equivalent raw intervals")
    return original, edited, (start, orig_end), (start, edit_end)


def code_tokens(parser, source):
    root = parser.parse(source).root_node
    require(not root.has_error, "Edit source does not parse as C++")
    pending = [root]
    tokens = []
    while pending:
        node = pending.pop()
        if node.type == "comment":
            continue
        if node.child_count and not node.type.startswith("preproc_"):
            pending.extend(reversed(node.children))
        else:
            tokens.append(node)
    return tokens


def covered(tokens, span):
    start, end = span
    return [token for token in tokens if token.start_byte < end and start < token.end_byte]


def changed_tokens(before, after):
    first = 0
    while first < min(len(before), len(after)) and before[first].text == after[first].text:
        first += 1
    before_end, after_end = len(before), len(after)
    while before_end > first and after_end > first and before[before_end - 1].text == after[after_end - 1].text:
        before_end -= 1
        after_end -= 1
    return before[first:before_end], after[first:after_end]


def single_owner(tokens):
    if not tokens:
        return True
    start, end = tokens[0].start_byte, tokens[-1].end_byte
    node = tokens[0]
    while node is not None:
        if node.start_byte <= start and end <= node.end_byte and (
            node.type.endswith("_expression") or node.type == "declaration"
            or (node.type.endswith("_statement") and node.type != "compound_statement")
        ):
            return True
        node = node.parent
    return False


def traced_source(pipeline, edited):
    tracing = {}

    def capture(expanded):
        normalized, origins = custody.traced_normalization(pipeline, expanded)
        tracing.update(expanded=expanded.encode("utf-8"), origins=origins)
        return normalized

    tracer = SimpleNamespace(preprocess_pass_zero=pipeline.preprocess_pass_zero, parser=pipeline.parser,
                             normalize_synthetic_braces=capture)
    normalized, aliases = normalize(tracer, edited.decode("utf-8"))
    return normalized, aliases, tracing


def exact_origins(parser, normalized, tracing, raw_tokens, selected):
    # Includes and trivia can move. All other tokens must retain text and order.
    expanded_tokens = code_tokens(parser, tracing["expanded"])
    raw_tokens = [node for node in raw_tokens if node.type != "preproc_include"]
    expanded_tokens = [node for node in expanded_tokens if node.type != "preproc_include"]
    if any(node.type.startswith("preproc_") for node in raw_tokens):
        raise UnresolvedOrigin("unsupported_preprocessor_directive")
    if [token.text for token in raw_tokens] != [token.text for token in expanded_tokens]:
        raise UnresolvedOrigin("pass_zero_changed_token_stream")
    selected_starts = {token.start_byte for token in selected}
    normalized_bytes = normalized.encode("utf-8")
    inverse = {expanded: i for i, expanded in enumerate(tracing["origins"]) if expanded is not None}
    mappings = []
    for raw, expanded in zip(raw_tokens, expanded_tokens, strict=True):
        if raw.start_byte not in selected_starts:
            continue
        mapped = [inverse[byte] for byte in range(expanded.start_byte, expanded.end_byte)]
        start, end = mapped[0], mapped[-1] + 1
        if mapped != list(range(start, end)) or normalized_bytes[start:end] != raw.text:
            raise UnresolvedOrigin("noncontiguous_normalized_token")
        mappings.append({"raw": [raw.start_byte, raw.end_byte], "pass_zero": [expanded.start_byte, expanded.end_byte],
                         "normalized": [start, end]})
    return mappings


def resolve_intervention(pipeline, record):
    original, edited, orig_span, edit_span = verify_splice(record)
    normalized, aliases, tracing = traced_source(pipeline, edited)
    nodes = pipeline.extract_macro_nodes(normalized, aliases)
    require(all("normalized_span" in node for node in nodes), "Require the prospective canonical extractor")
    node_spans = [{"node_id": node["id"], "role": node["role"], "span": node["normalized_span"]} for node in nodes]
    result = {"schema": "eapg-synthetic-token-reference-v1", "pipeline_sha256": pipeline.source_sha256,
              "source_sha256": record["source_sha256"], "reference_status": "unresolved", "reference_reason": None,
              "accepted_node_ids": [], "canonical_nodes": node_spans, "normalized_source_sha256": sha(normalized),
              "token_origins": []}
    try:
        original_tokens, raw_tokens = (code_tokens(pipeline.parser, source) for source in (original, edited))
        before, changed = changed_tokens(covered(original_tokens, orig_span), covered(raw_tokens, edit_span))
        require(changed and single_owner(before) and single_owner(changed),
                "Expected a nontrivia change within one expression or statement")
        for span in record["equivalent_edited_intervals"]:
            require(span[0] <= changed[0].start_byte and changed[-1].end_byte <= span[1]
                    and covered(raw_tokens, span) == changed, "Equivalent raw interval identifies different tokens")
        mappings = exact_origins(pipeline.parser, normalized, tracing, raw_tokens, changed)
    except UnresolvedOrigin as exc:
        result["reference_reason"] = str(exc)
        return result

    result["token_origins"] = mappings
    lo, hi = mappings[0]["normalized"][0], mappings[-1]["normalized"][1]
    covering = [row for row in node_spans if row["span"][0] <= lo and hi <= row["span"][1]]
    if not covering:
        result["reference_reason"] = "no_covering_canonical_node"
        return result
    shortest = min(end - start for start, end in (row["span"] for row in covering))
    owners = [row["node_id"] for row in covering if row["span"][1] - row["span"][0] == shortest]
    if len(owners) != 1:
        result["reference_reason"] = "ambiguous_canonical_owner"
        return result
    result.update(reference_status="resolved", accepted_node_ids=owners)
    return result


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--pipeline", required=True, type=Path)
    cli.add_argument("--pipeline-sha256", required=True)
    cli.add_argument("--input", required=True, type=Path)
    cli.add_argument("--input-sha256", required=True)
    cli.add_argument("--out", required=True, type=Path)
    args = cli.parse_args()
    try:
        pipeline = load_module("synthetic_reference_pipeline", args.pipeline, args.pipeline_sha256)
        record = read_pinned(args.input, args.input_sha256)
        verify_splice(record)
        for name in ("original", "edited"):
            command = ["g++", "-std=c++17", "-fsyntax-only", "-x", "c++", "-"]
            verify_preprocessing(invoke(command, data=record[name].encode("utf-8")), f"Syntax validation of {name}")
        resolved = resolve_intervention(pipeline, record)
        with args.out.open("xb") as stream:
            raw = json_bytes(resolved)
            stream.write(raw)
    except (ValueError, OSError, RuntimeError) as error:
        cli.error(str(error))
    print(f"{sha(raw)}  {args.out.name}")


if __name__ == "__main__":
    main()
