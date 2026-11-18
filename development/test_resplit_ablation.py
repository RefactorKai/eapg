"""Unit tests for CPU ablation matrix replay, baselines, and leak checks."""

from copy import deepcopy
import unittest
from unittest.mock import patch

import replay_resplit_ablation as replay
from train_resplit_ablation import REPRESENTATIONS, summarize_matrix


class ResplitAblationTests(unittest.TestCase):
    def _fixture(self):
        # 5 pairs, 5 groups, 5 folds so every invariant exercises real multi-fold checks.
        pilot_rows = {}
        split = {}
        pub_resplit = {"predictions": {}}
        for i in range(5):
            pid = f"PAIR_{i:03d}"
            cands = ["N2", "N3"] if i < 4 else ["N2"]
            pilot_rows[pid] = {
                "pair_id": pid,
                "problem_id": f"P{i}",
                "mechanism_id": "A1.1",
                "track_gt": "A1" if i < 3 else ("A2" if i == 3 else "B"),
                "gt_node": "N2",
                "slicing": {
                    "c_pruned": cands,
                    "c_inter_only": ["N2"],
                    "c_naive_work": ["N3"] if i == 0 else ["N2"],
                },
            }
            split[pid] = {
                "problem_id": f"P{i}",
                "group": i,
                "fold": i,
                "prompt_sha256": f"{i:064x}",
            }
            pub_resplit["predictions"][pid] = {
                "adapted": list(cands),
                "base": list(reversed(cands)),
                "symbolic": list(cands),
            }

        predictions = {}
        for r_idx, rep in enumerate(REPRESENTATIONS):
            predictions[rep] = {}
            for i in range(5):
                pid = f"PAIR_{i:03d}"
                cands = pilot_rows[pid]["slicing"]["c_pruned"]
                all_nodes = ["N1", "N2", "N3"]
                base_logits = {"N1": 3.0, "N2": 1.0, "N3": 2.0}
                if rep == "abstract_graph":
                    adapted_logits = {"N1": 0.1, "N2": 5.0, "N3": 1.0}
                else:
                    adapted_logits = {"N1": 2.0 + r_idx * 0.1, "N2": 1.0, "N3": 1.5}
                predictions[rep][pid] = {
                    "fold": i,
                    "group": i,
                    "reference": "N2",
                    "all_nodes": all_nodes,
                    "candidates": list(cands),
                    "base_unconstrained": sorted(all_nodes, key=base_logits.get, reverse=True),
                    "base_constrained": sorted(cands, key=base_logits.get, reverse=True),
                    "adapted_unconstrained": sorted(all_nodes, key=adapted_logits.get, reverse=True),
                    "adapted_constrained": sorted(cands, key=adapted_logits.get, reverse=True),
                    "base_logits": base_logits,
                    "adapted_logits": adapted_logits,
                }

        report = {
            "schema": "eapg-resplit-ablation-v1",
            "pilot_sha256": "p" * 64,
            "pipeline_sha256": "q" * 64,
            "max_tokens_by_repr": {rep: 200 + idx for idx, rep in enumerate(REPRESENTATIONS)},
            "recipe": {"max_sequence": 512},
            "split": split,
            "scores": summarize_matrix(predictions, pilot_rows),
            "predictions": predictions,
        }

        class FakePipeline:
            @staticmethod
            def rank_candidates_by_role_priority(row, *, use_loop_def_use=False):
                return list(row["slicing"]["c_pruned"])

        return report, pilot_rows, pub_resplit, FakePipeline()

    def test_verify_ablation_report_and_baselines(self):
        report, pilot_rows, pub_resplit, pipeline = self._fixture()
        sha_text = (
            f"{'p' * 64}  artifacts/scope_isolated_pilot/pilot100_results.json\n"
            f"{'q' * 64}  pipeline.py\n"
        )
        with patch.object(replay, "ROOT") as mock_root:
            mock_root.__truediv__.return_value.read_text.return_value = sha_text
            scores, baselines = replay.verify_ablation_report(report, pilot_rows, pub_resplit, pipeline)

        self.assertEqual(scores["by_representation"]["abstract_graph"]["all"]["adapted_constrained"]["top1_hits"], 5)
        self.assertAlmostEqual(baselines["all"]["uniform"]["expected_hits"], 3.0)
        self.assertEqual(baselines["all"]["raw_order"]["expected_hits"], 5.0)
        rows = replay.format_ablation_rows(scores, baselines, report["max_tokens_by_repr"])
        self.assertEqual(len(rows), 10)
        self.assertEqual(len(rows[0]), 8)

    def test_rejects_cross_fold_prompt_leak_and_logit_tampering(self):
        report, pilot_rows, pub_resplit, pipeline = self._fixture()
        sha_text = (
            f"{'p' * 64}  artifacts/scope_isolated_pilot/pilot100_results.json\n"
            f"{'q' * 64}  pipeline.py\n"
        )
        leaked = deepcopy(report)
        leaked["split"]["PAIR_001"]["prompt_sha256"] = leaked["split"]["PAIR_000"]["prompt_sha256"]
        with patch.object(replay, "ROOT") as mock_root:
            mock_root.__truediv__.return_value.read_text.return_value = sha_text
            with self.assertRaisesRegex(ValueError, "Cross-fold leak on prompt_sha256"):
                replay.verify_ablation_report(leaked, pilot_rows, pub_resplit, pipeline)

        tampered = deepcopy(report)
        tampered["predictions"]["raw_code"]["PAIR_000"]["adapted_unconstrained"].reverse()
        with patch.object(replay, "ROOT") as mock_root:
            mock_root.__truediv__.return_value.read_text.return_value = sha_text
            with self.assertRaisesRegex(ValueError, "Rank sorting mismatch"):
                replay.verify_ablation_report(tampered, pilot_rows, pub_resplit, pipeline)


if __name__ == "__main__":
    unittest.main()
