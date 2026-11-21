"""Build a label-blind prediction row and the exact tokens for custody and inference."""

from math import isfinite

from canonical_ranking import rank_canonical


def prepare_prediction(pipeline, pair_id, normalized_sha256, nodes, fits, tokenizer):
    if (not isinstance(pair_id, str) or not pair_id or not isinstance(normalized_sha256, str)
            or len(normalized_sha256) != 64 or any(c not in "0123456789abcdef" for c in normalized_sha256)):
        raise ValueError("Expected an opaque case ID and normalized-source SHA-256")
    ids = [node["id"] for node in nodes]
    if ids != [f"N{i}" for i in range(1, len(ids) + 1)] or set(fits) != set(ids):
        raise ValueError("Canonical node IDs and fitted profiles disagree")
    tiers = pipeline.evaluate_four_slicing_tiers(nodes, fits)
    symptom, candidates = tiers["primary_symptom"], tiers["c_pruned"]
    if ((symptom is not None and symptom not in ids)
            or len(candidates) != len(set(candidates)) or not set(candidates) <= set(ids)
            or (symptom is None and candidates)):
        raise ValueError("Selector emitted invalid nodes")
    row = {"pair_id": pair_id, "normalized_source_sha256": normalized_sha256, "symptom_id": symptom,
           "slice": candidates, "prompt_tokens": None, "symbolic": [], "abstract": [],
           "abstract_status": "NO_SYMPTOM" if symptom is None else "EMPTY_SLICE"}
    if not candidates:
        return row, [], {}

    dynamics = pipeline.analyze_eapg_slicing(nodes, fits)
    dynamics.update(c_slice=candidates, r_search=1 - len(candidates) / len(nodes))
    record = {"skeleton": pipeline.format_eapg_skeleton(nodes, fits, dynamics),
              "slicing": tiers, "pilot_revision": pipeline.PILOT_REVISION, "scope_protocol": "main_scope"}
    symbolic = rank_canonical(pipeline, record, nodes, use_loop_def_use=True)
    if len(symbolic) != len(candidates) or set(symbolic) != set(candidates):
        raise ValueError("Symbolic ranking changed the emitted candidate set")
    row["symbolic"] = symbolic[:2]
    if len(nodes) > 26:
        row["abstract_status"] = "NODE_LIMIT"
        return row, [], {}

    prompt, prompt_nodes, prompt_candidates = pipeline.build_variant_prompt_and_cands(
        record, "abstract_graph", tag_mode="slice", node_only=True,
    )
    if prompt_nodes != ids or prompt_candidates != candidates:
        raise ValueError("Serialized prompt disagrees with the canonical slice")
    prefix = tokenizer.encode(prompt, add_special_tokens=False)
    if not prefix:
        raise ValueError("Serialized prompt has no tokens")
    row["prompt_tokens"] = len(prefix)
    if len(prefix) + 1 > 512:
        row["abstract_status"] = "CONTEXT_LIMIT"
        return row, prefix, {}

    labels = {}
    for node in candidates:
        suffix = " " + pipeline._nid_to_code(node)
        label = tokenizer.encode(suffix, add_special_tokens=False)
        if (len(label) != 1 or label[0] in labels.values()
                or tokenizer.encode(prompt + suffix, add_special_tokens=False) != prefix + label):
            row["abstract_status"] = "UNSUPPORTED_NODE_TOKEN"
            return row, prefix, {}
        labels[node] = label[0]
    row["abstract_status"] = "READY"
    return row, prefix, labels


def rank_abstract(row, scores):
    """Finish a prepared row with one finite next-token score per candidate node."""
    if (row["abstract_status"] != "READY" or set(scores) != set(row["slice"])
            or not all(isfinite(score) for score in scores.values())):
        raise ValueError("Neural scores do not match an eligible candidate set")
    return dict(row, abstract=sorted(row["slice"], key=scores.__getitem__, reverse=True)[:2],
                abstract_status="RANKED")
