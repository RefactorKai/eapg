"""Verify the published 6b-slice objective and pinned local snapshot on CPU."""

import ast
from hashlib import file_digest, sha256
import json
import os
from pathlib import Path
from string import ascii_uppercase
import sys


ROOT = Path(__file__).resolve().parents[1]
MODEL = "Qwen/Qwen2.5-Coder-1.5B"
REVISION = "df3ce67c0e24480f20468b6ef2894622d69eb73b"
PIPELINE_SHA = "7c855651566c1a7dc003fdcb291d8edd3ff1a99c671f781eb595d72c492ae743"
PILOT_SHA = "4a3b563cdd54c471f39df95e7d40ec3ae5433259795cadcde80272955ea44cb5"
SNAPSHOT_FILES = ("config.json", "generation_config.json", "merges.txt", "model.safetensors",
                  "tokenizer.json", "tokenizer_config.json", "vocab.json")


def checked_bytes(path, expected):
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != expected:
        raise ValueError(f"Frozen input hash mismatch for {path.name}")
    return raw


def recipe_hashes(raw):
    source = raw.decode("utf-8").replace("\r\n", "\n")
    names = {"run_ablation_matrix", "build_variant_prompt_and_cands", "_nid_to_code"}
    return {node.name: sha256(ast.get_source_segment(source, node).encode()).hexdigest()
            for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name in names}


def snapshot_hashes(snapshot):
    files = {}
    for name in SNAPSHOT_FILES:
        path = snapshot / name
        if not path.is_file():
            raise FileNotFoundError(f"Pinned revision {REVISION} is missing {name}")
        with path.open("rb") as handle:
            files[name] = {"bytes": path.stat().st_size, "sha256": file_digest(handle, "sha256").hexdigest()}
    return files


def verify_objective(tokenizer, pipeline, rows):
    def encode(text):
        return tokenizer.encode(text, add_special_tokens=False)

    node_tokens = {code: encode(" " + code) for code in ascii_uppercase}
    if any(len(ids) != 1 for ids in node_tokens.values()) or len({tuple(ids) for ids in node_tokens.values()}) != 26:
        raise ValueError("Node labels A–Z must have distinct, single-token encodings")
    longest = (0, "")
    for row in rows:
        prompt, nodes, candidates = pipeline.build_variant_prompt_and_cands(
            row, "abstract_graph", tag_mode="slice", node_only=True,
        )
        pair_id = row["pair_id"]
        if not 1 <= len(nodes) <= 26 or row["gt_node"] not in nodes:
            raise ValueError(f"{pair_id} has an unencodable node set or target")
        if candidates != row["slicing"]["c_pruned"] or "RANK1" in prompt or "RANK2" in prompt:
            raise ValueError(f"{pair_id} does not use the published binary slice tags")
        prefix = encode(prompt)
        if len(prefix) + 1 > 512:
            raise ValueError(f"{pair_id} exceeds 512 tokens with the target reserved")
        for nid in nodes:
            label = pipeline._nid_to_code(nid)
            if encode(f"{prompt} {label}") != prefix + node_tokens[label]:
                raise ValueError(f"{pair_id} node {nid} is not a single next token after the prompt")
        longest = max(longest, (len(prefix) + 1, pair_id))
    return {"rows": len(rows), "single_token_labels": len(node_tokens),
            "max_prompt_plus_target_tokens": longest[0], "example_at_max": longest[1]}


def main():
    os.environ["HF_HUB_OFFLINE"] = "1"
    from huggingface_hub.constants import HF_HUB_CACHE
    from transformers import AutoTokenizer
    import tokenizers
    import transformers

    pipeline_raw = checked_bytes(ROOT / "pipeline.py", PIPELINE_SHA)
    pilot_raw = checked_bytes(ROOT / "artifacts/scope_isolated_pilot/pilot100_results.json", PILOT_SHA)
    sys.path.insert(0, str(ROOT))
    import pipeline

    snapshot = Path(HF_HUB_CACHE) / f"models--{MODEL.replace('/', '--')}" / "snapshots" / REVISION
    files = snapshot_hashes(snapshot)
    tokenizer = AutoTokenizer.from_pretrained(snapshot, local_files_only=True, trust_remote_code=False)
    result = verify_objective(tokenizer, pipeline, json.loads(pilot_raw))
    print(json.dumps({"model": MODEL, "revision": REVISION, "snapshot_files": files,
                      "pipeline_sha256": PIPELINE_SHA, "pilot_sha256": PILOT_SHA,
                      "recipe_sha256_lf": recipe_hashes(pipeline_raw),
                      "runtime": {"python": sys.version.split()[0], "tokenizers": tokenizers.__version__,
                                  "transformers": transformers.__version__},
                      "objective": result}, indent=2))


if __name__ == "__main__":
    main()
