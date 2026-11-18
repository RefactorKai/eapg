"""Authored CPU checks for abstention, prompt eligibility and score binding."""

from types import SimpleNamespace
import unittest

from prediction_contract import prepare_prediction, rank_abstract


class PredictionContractTests(unittest.TestCase):
    def prepare(self, symptom="N1", candidates=("N2", "N1"), length=2, *, merged_label=False,
                node_count=2, source_sha="f" * 64):
        def format_prompt(record, *_args, **_kwargs):
            self.assertEqual(record["scope_protocol"], "main_scope")
            return "prompt", ["N1", "N2"], list(candidates)

        def encode(text, *, add_special_tokens):
            self.assertFalse(add_special_tokens)
            if text.startswith("prompt"):
                prefix = [1] * length
                return prefix + ([9 if merged_label else ord(text[-1])] if text != "prompt" else [])
            return [ord(text[-1])]

        pipeline = SimpleNamespace(
            PILOT_REVISION="fixture",
            evaluate_four_slicing_tiers=lambda *_: {"primary_symptom": symptom, "c_pruned": list(candidates)},
            analyze_eapg_slicing=lambda *_: {},
            format_eapg_skeleton=lambda *_: "skeleton",
            rank_candidates_by_role_priority=lambda *_args, **_kwargs: list(candidates),
            build_variant_prompt_and_cands=format_prompt,
            _nid_to_code=lambda nid: {"N1": "A", "N2": "B"}[nid],
        )
        nodes = [{"id": f"N{i}"} for i in range(1, node_count + 1)]
        return prepare_prediction(pipeline, "authored", source_sha, nodes, {n["id"]: {} for n in nodes},
                                  SimpleNamespace(encode=encode))

    def test_abstention_preserves_empty_slices(self):
        for symptom, status in ((None, "NO_SYMPTOM"), ("N1", "EMPTY_SLICE")):
            with self.subTest(status=status):
                row, tokens, labels = self.prepare(symptom, ())
                self.assertEqual((row["slice"], row["symbolic"], row["abstract"]), ([], [], []))
                self.assertEqual((row["abstract_status"], row["prompt_tokens"], tokens, labels),
                                 (status, None, [], {}))

    def test_exact_token_budget_and_candidate_scores(self):
        row, tokens, labels = self.prepare(length=511)
        self.assertEqual(row["prompt_tokens"], len(tokens))
        self.assertEqual(labels, {"N1": 65, "N2": 66})
        ranked = rank_abstract(row, {"N1": 0.5, "N2": 0.5})
        self.assertEqual(ranked["abstract"], ["N2", "N1"])
        for invalid in ({"N1": 0.5}, {"N1": 0.5, "N2": float("nan")}):
            with self.assertRaises(ValueError):
                rank_abstract(row, invalid)
        row, tokens, labels = self.prepare(length=512)
        self.assertEqual((row["abstract_status"], row["prompt_tokens"], len(tokens), labels),
                         ("CONTEXT_LIMIT", 512, 512, {}))
        self.assertEqual(row["symbolic"], ["N2", "N1"])

    def test_incompatible_target_encoding_abstains(self):
        row, tokens, labels = self.prepare(merged_label=True)
        self.assertEqual((row["abstract_status"], len(tokens), labels), ("UNSUPPORTED_NODE_TOKEN", 2, {}))

    def test_slice_without_symptom_is_invalid(self):
        with self.assertRaises(ValueError):
            self.prepare(symptom=None)

    def test_node_limit_preserves_symbolic_rank_and_requires_source_binding(self):
        row, tokens, labels = self.prepare(node_count=27)
        self.assertEqual((row["abstract_status"], row["symbolic"], tokens, labels),
                         ("NODE_LIMIT", ["N2", "N1"], [], {}))
        with self.assertRaises(ValueError):
            self.prepare(source_sha="invalid")


if __name__ == "__main__":
    unittest.main()
