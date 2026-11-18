"""CPU and optional live-adapter tests for the external prediction contract."""

import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

import predict_external_contract as contract
from score_external import score


HASH = "a" * 64


def fake_pipeline(meta_by_id):
    def format_prompt(record, *_args, **_kwargs):
        nodes = [f"N{i}" for i in range(1, len(record["skeleton"].split("|")) + 1)]
        return "Locate bottleneck node.\nAnswer:", nodes, record["slicing"]["c_pruned"]

    def slicing_for(nodes, _fits):
        return meta_by_id[len(nodes)]

    return SimpleNamespace(
        source_sha256=HASH,
        PILOT_REVISION="validated-input-pilot-v2",
        evaluate_four_slicing_tiers=slicing_for,
        analyze_eapg_slicing=lambda *_: {},
        format_eapg_skeleton=lambda _nodes, _fits, dyn: dyn.get("skeleton", "skeleton"),
        rank_candidates_by_role_priority=lambda rec, **_kw: list(rec["slicing"]["c_pruned"]),
        build_variant_prompt_and_cands=format_prompt,
        _nid_to_code=lambda nid: chr(64 + int(nid[1:])),
    )


def fake_tokenizer(long_prompt=False, bad_token=False):
    def encode(text, *, add_special_tokens=False):
        assert not add_special_tokens
        if text.startswith(" "):
            return [999, 1000] if bad_token else [100 + ord(text[1])]
        if text.endswith(" A") or text.endswith(" B") or text.endswith(" C"):
            prefix = [1] * (512 if long_prompt else 10)
            return prefix + ([999, 1000] if bad_token else [100 + ord(text[-1])])
        return [1] * (512 if long_prompt else 10)

    return SimpleNamespace(encode=encode)


class ExternalContractTests(unittest.TestCase):
    def test_end_to_end_abstentions_and_external_scorer_join(self):
        meta = {
            2: {"primary_symptom": "N2", "c_pruned": ["N1", "N2"]},
            3: {"primary_symptom": None, "c_pruned": []},
            4: {"primary_symptom": "N2", "c_pruned": []},
            27: {"primary_symptom": "N2", "c_pruned": ["N1", "N2"]},
        }
        pipeline = fake_pipeline(meta)
        tok = fake_tokenizer()

        def make_case(pid, n_nodes, *, norm_sha=HASH):
            if norm_sha is None:
                return {"pair_id": pid, "normalized_source_sha256": None, "nodes": [], "fits": None,
                        "unavailable_reason": "NORMALIZATION_FAILURE"}
            nodes = [{"id": f"N{i}"} for i in range(1, n_nodes + 1)]
            fits = {f"N{i}": {} for i in range(1, n_nodes + 1)}
            return {"pair_id": pid, "normalized_source_sha256": norm_sha, "nodes": nodes, "fits": fits}

        def custom_prompt(record, *_args, **_kwargs):
            n = 27 if len(record["slicing"]["c_pruned"]) == 2 and record["slicing"].get("_n") == 27 else 2
            return "Locate bottleneck node.\nAnswer:", [f"N{i}" for i in range(1, n + 1)], record["slicing"]["c_pruned"]

        # Map exact node count into meta via skeleton text.
        pipeline.format_eapg_skeleton = lambda nodes, _fits, _dyn: "|".join(n["id"] for n in nodes)
        pipeline.build_variant_prompt_and_cands = lambda rec, *a, **kw: (
            "Locate bottleneck node.\nAnswer:",
            rec["skeleton"].split("|"),
            rec["slicing"]["c_pruned"],
        )

        cases = [
            make_case("ready_pos", 2),
            make_case("no_sym", 3),
            make_case("empty_slice", 4),
            make_case("node_limit", 27),
            make_case("norm_fail", 0, norm_sha=None),
        ]

        ledger, statuses = contract.predict_cases(
            pipeline, tok, cases,
            scorer_fn=lambda _p, labels: {k: (10.0 if k == "N1" else 1.0) for k in labels},
            study_sha256=HASH, protocol_sha256=HASH, quarantine_sha256=HASH, adapter_sha256=HASH,
        )
        self.assertEqual([s["abstract_status"] for s in statuses], [
            "RANKED", "NO_SYMPTOM", "EMPTY_SLICE", "NODE_LIMIT", "NORMALIZATION_FAILURE",
        ])

        ctx_ledger, ctx_stat = contract.predict_cases(
            pipeline, fake_tokenizer(long_prompt=True), [make_case("ctx", 2)],
            scorer_fn=lambda *_: (_ for _ in ()).throw(AssertionError("Must not score overflow")),
            study_sha256=HASH, protocol_sha256=HASH, quarantine_sha256=HASH, adapter_sha256=HASH,
        )
        self.assertEqual(ctx_stat[0]["abstract_status"], "CONTEXT_LIMIT")
        self.assertEqual(ctx_ledger["pairs"][0]["abstract"], [])
        self.assertEqual(ctx_ledger["pairs"][0]["symbolic"], ["N1", "N2"])

        bad_ledger, bad_stat = contract.predict_cases(
            pipeline, fake_tokenizer(bad_token=True), [make_case("badtok", 2)],
            scorer_fn=lambda *_: (_ for _ in ()).throw(AssertionError("Must not score bad target token")),
            study_sha256=HASH, protocol_sha256=HASH, quarantine_sha256=HASH, adapter_sha256=HASH,
        )
        self.assertEqual(bad_stat[0]["abstract_status"], "UNSUPPORTED_NODE_TOKEN")
        self.assertEqual(bad_ledger["pairs"][0]["abstract"], [])

        study = {
            "schema": "eapg-external-study-ledger-v1",
            "protocol_sha256": HASH,
            "pipeline_sha256": HASH,
            "quarantine_sha256": HASH,
            "drawn_pair_ids": [c["pair_id"] for c in cases],
            "pairs": [
                {
                    "pair_id": "ready_pos", "group_id": "g0", "screening_status": "confirmed_positive",
                    "canonical_node_ids": ["N1", "N2"], "normalized_source_sha256": HASH,
                    "accepted_node_ids": ["N1"], "reference_status": "resolved", "reference_manifest_sha256": HASH,
                },
                {
                    "pair_id": "no_sym", "group_id": "g1", "screening_status": "verified_negative",
                    "canonical_node_ids": ["N1", "N2", "N3"], "normalized_source_sha256": HASH,
                    "accepted_node_ids": [],
                },
                {
                    "pair_id": "empty_slice", "group_id": "g2", "screening_status": "confirmed_positive",
                    "canonical_node_ids": ["N1", "N2", "N3", "N4"], "normalized_source_sha256": HASH,
                    "accepted_node_ids": ["N1"], "reference_status": "resolved", "reference_manifest_sha256": HASH,
                },
                {
                    "pair_id": "node_limit", "group_id": "g3", "screening_status": "confirmed_positive",
                    "canonical_node_ids": [f"N{i}" for i in range(1, 28)], "normalized_source_sha256": HASH,
                    "accepted_node_ids": ["N1"], "reference_status": "resolved", "reference_manifest_sha256": HASH,
                },
                {
                    "pair_id": "norm_fail", "group_id": "g4", "screening_status": "compile_failure",
                    "canonical_node_ids": [], "normalized_source_sha256": None,
                    "accepted_node_ids": [],
                },
            ],
        }
        result = score(study, ledger, HASH)
        self.assertEqual(result["D_pos"]["pairs"], 3)
        self.assertEqual(result["D_elig"]["pairs"], 1)
        self.assertEqual(result["D_rank"]["pairs"], 1)
        self.assertEqual(result["D_pos"]["abstract"]["top1"]["count"], 1)
        self.assertEqual(result["D_pos"]["symbolic"]["top1"]["count"], 2)
        self.assertEqual(result["verified_negative_alerts"]["count"], 0)

    def test_adapter_manifest_verification_detects_missing_or_tampered_files(self):
        with TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            adapter = Path(tmp)
            (adapter / "adapter_config.json").write_text("{}", encoding="utf-8")
            (adapter / "adapter_model.safetensors").write_bytes(b"weights")
            digest, _ = contract.verify_adapter_dir(adapter)
            self.assertEqual(len(digest), 64)
            with self.assertRaises(ValueError):
                contract.verify_adapter_dir(adapter, "0" * 64)


def run_live_dry_run(pipeline_path, adapter_dir, smoke_profile_path):
    """Exercise the full GPU 4-bit adapter + prospective pipeline + external scorer."""
    import gc
    import torch
    from run_phase2_development import load_pipeline
    from train_phase2_adapter import load_inputs

    pipeline = load_pipeline(pipeline_path)
    smoke = json.loads(smoke_profile_path.read_text(encoding="utf-8"))
    _, _, snapshot, tokenizer, _, _ = load_inputs()
    model, adapter_sha = contract.load_pinned_adapter(snapshot, adapter_dir)
    try:
        intv = smoke["profiles"]["intervention"]
        inv = smoke["profiles"]["inverse"]
        quad = smoke["profiles"]["appropriate_quadratic"]
        overflow_nodes = list(intv["nodes"])
        overflow_fits = dict(intv["fits"]["0"])
        for idx in range(len(overflow_nodes) + 1, 28):
            nid = f"N{idx}"
            overflow_nodes.append({
                "id": nid, "role": "STATE_UPD", "parent": "MAIN_SCOPE", "insert_pos": 0,
                "defs": [f"pad_{idx}"], "uses": [], "weight_expr": "1ULL",
                "is_state_reset": False, "is_unidirectional_step": False,
                "in_nested_branch": False, "source_preview": f"int pad_{idx} = 0;",
            })
            overflow_fits[nid] = intv["fits"]["0"]["N1"]

        cases = [
            {
                "pair_id": "authored_reset_pos",
                "normalized_source_sha256": intv["normalized_sha256"],
                "nodes": intv["nodes"],
                "fits": intv["fits"]["0"],
            },
            {
                "pair_id": "authored_inverse_neg",
                "normalized_source_sha256": inv["normalized_sha256"],
                "nodes": inv["nodes"],
                "fits": inv["fits"]["0"],
            },
            {
                "pair_id": "authored_appropriate_ctrl",
                "normalized_source_sha256": quad["normalized_sha256"],
                "nodes": quad["nodes"],
                "fits": quad["fits"]["0"],
            },
            {
                "pair_id": "authored_node_limit",
                "normalized_source_sha256": intv["normalized_sha256"],
                "nodes": overflow_nodes,
                "fits": overflow_fits,
            },
            {
                "pair_id": "authored_norm_failure",
                "normalized_source_sha256": None,
                "nodes": [],
                "fits": None,
                "unavailable_reason": "NORMALIZATION_FAILURE",
            },
        ]
        study_pins = {
            "study_sha256": HASH,
            "protocol_sha256": HASH,
            "quarantine_sha256": HASH,
        }
        ledger, statuses = contract.predict_cases(
            pipeline, tokenizer, cases,
            scorer_fn=lambda prefix, labels: contract.score_prepared(model, prefix, labels),
            adapter_sha256=adapter_sha,
            **study_pins,
        )
        study = {
            "schema": "eapg-external-study-ledger-v1",
            "protocol_sha256": HASH,
            "pipeline_sha256": pipeline.source_sha256,
            "quarantine_sha256": HASH,
            "drawn_pair_ids": [c["pair_id"] for c in cases],
            "pairs": [
                {
                    "pair_id": "authored_reset_pos", "group_id": "g_reset", "screening_status": "confirmed_positive",
                    "canonical_node_ids": [n["id"] for n in intv["nodes"]],
                    "normalized_source_sha256": intv["normalized_sha256"],
                    "accepted_node_ids": [smoke["intervention"]["reference"]],
                    "reference_status": "resolved", "reference_manifest_sha256": HASH,
                },
                {
                    "pair_id": "authored_inverse_neg", "group_id": "g_reset", "screening_status": "verified_negative",
                    "canonical_node_ids": [n["id"] for n in inv["nodes"]],
                    "normalized_source_sha256": inv["normalized_sha256"],
                    "accepted_node_ids": [],
                },
                {
                    "pair_id": "authored_appropriate_ctrl", "group_id": "g_quad", "screening_status": "verified_negative",
                    "canonical_node_ids": [n["id"] for n in quad["nodes"]],
                    "normalized_source_sha256": quad["normalized_sha256"],
                    "accepted_node_ids": [],
                },
                {
                    "pair_id": "authored_node_limit", "group_id": "g_lim", "screening_status": "confirmed_positive",
                    "canonical_node_ids": [n["id"] for n in overflow_nodes],
                    "normalized_source_sha256": intv["normalized_sha256"],
                    "accepted_node_ids": ["N4"],
                    "reference_status": "resolved", "reference_manifest_sha256": HASH,
                },
                {
                    "pair_id": "authored_norm_failure", "group_id": "g_fail", "screening_status": "compile_failure",
                    "canonical_node_ids": [], "normalized_source_sha256": None,
                    "accepted_node_ids": [],
                },
            ],
        }
        scored = score(study, ledger, HASH)
        print(json.dumps({
            "adapter_sha256": adapter_sha,
            "statuses": statuses,
            "ledger_pairs": ledger["pairs"],
            "scorer_summary": {
                "D_pos": scored["D_pos"],
                "D_elig": scored["D_elig"],
                "verified_negative_alerts": scored["verified_negative_alerts"],
            },
        }, indent=2))
    finally:
        del model
        gc.collect()
        torch.cuda.empty_cache()


if __name__ == "__main__":
    cli = argparse.ArgumentParser(add_help=False)
    cli.add_argument("--live", action="store_true")
    cli.add_argument("--pipeline", type=Path)
    cli.add_argument("--adapter-dir", type=Path)
    cli.add_argument("--smoke-profile", type=Path)
    opts, remaining = cli.parse_known_args()
    if opts.live:
        run_live_dry_run(opts.pipeline, opts.adapter_dir, opts.smoke_profile)
    else:
        unittest.main(argv=[sys.argv[0], *remaining])
