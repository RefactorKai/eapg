"""Check that ranking resolves expanded macro-node IDs against the canonical node set."""

import json
from pathlib import Path
import shutil
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "development"))

import pipeline  # noqa: E402
from canonical_ranking import rank_canonical  # noqa: E402

SCALES = (4, 8, 16, 32)
MACRO_SOURCE = """#define SET_OFFSET(x) int x = 0; x += 0
int main(int n, char**) {
    for (int i = 0; i < n; ++i) {
        SET_OFFSET(start);
        for (int j = start; j < n; ++j) {}
    }
}"""


def canonical_nodes(source):
    expanded, aliases = pipeline.preprocess_pass_zero(source)
    return pipeline.extract_macro_nodes(pipeline.normalize_synthetic_braces(expanded), aliases)


@unittest.skipUnless(shutil.which("g++"), "g++ is required for macro expansion")
class CanonicalRankingTests(unittest.TestCase):
    def macro_record(self):
        nodes = canonical_nodes(MACRO_SOURCE)
        counts = {"N1": SCALES, "N2": SCALES, "N3": SCALES, "N4": [n * n for n in SCALES]}
        fits = {}
        for node in nodes:
            fit = pipeline.fit_dual_family_scaling(list(SCALES), list(counts[node["id"]]))
            fits[node["id"]] = {"fit_hits": fit, "fit_work": fit}
        tiers = pipeline.evaluate_four_slicing_tiers(nodes, fits)
        dynamics = pipeline.analyze_eapg_slicing(nodes, fits)
        dynamics.update(c_slice=tiers["c_pruned"], r_search=1 - len(tiers["c_pruned"]) / len(nodes))
        record = {"skeleton": pipeline.format_eapg_skeleton(nodes, fits, dynamics), "slicing": tiers,
                  "slow_code": MACRO_SOURCE, "pilot_revision": pipeline.PILOT_REVISION}
        return record, nodes

    def test_raw_reparse_lacks_expanded_id(self):
        record, nodes = self.macro_record()
        raw = pipeline.extract_macro_nodes(pipeline.normalize_synthetic_braces(MACRO_SOURCE), {})
        self.assertIn("N4", {node["id"] for node in nodes})
        self.assertNotIn("N4", {node["id"] for node in raw})
        self.assertEqual(record["slicing"]["c_pruned"], ["N2", "N3", "N4"])
        with self.assertRaises(KeyError):
            pipeline.rank_candidates_by_role_priority(record, use_loop_def_use=True)

    def test_frozen_ranker_uses_canonical_nodes(self):
        record, nodes = self.macro_record()
        for def_use in (False, True):
            with self.subTest(use_loop_def_use=def_use):
                ranked = rank_canonical(pipeline, record, nodes, use_loop_def_use=def_use)
                self.assertEqual(sorted(ranked), record["slicing"]["c_pruned"])
                label_blind = {k: v for k, v in record.items() if k != "slow_code"}
                self.assertEqual(rank_canonical(pipeline, label_blind, nodes, use_loop_def_use=def_use), ranked)

    def test_candidate_ranker_receives_macro_nodes(self):
        seen = {}

        def rank(rec, *, use_loop_def_use=False, macro_nodes=None):
            seen.update(rec=rec, def_use=use_loop_def_use, nodes=macro_nodes)
            return ["N1"]

        class Candidate:
            rank_candidates_by_role_priority = staticmethod(rank)

        nodes, record = [{"id": "N1"}], {"slow_code": "unused"}
        self.assertEqual(rank_canonical(Candidate, record, nodes, use_loop_def_use=True), ["N1"])
        self.assertEqual(seen, {"rec": record, "def_use": True, "nodes": nodes})

    def test_frozen_pilot_rankings_unchanged(self):
        rows = json.loads((ROOT / "artifacts/scope_isolated_pilot/pilot100_results.json").read_text("utf-8"))
        compared = 0
        for row in rows:
            if not row["slicing"]["c_pruned"]:
                continue
            nodes = canonical_nodes(row["slow_code"])
            for def_use in (False, True):
                expected = pipeline.rank_candidates_by_role_priority(row, use_loop_def_use=def_use)
                self.assertEqual(rank_canonical(pipeline, row, nodes, use_loop_def_use=def_use), expected,
                                 row["pair_id"])
            compared += 1
        self.assertGreater(compared, 0)


if __name__ == "__main__":
    unittest.main()
