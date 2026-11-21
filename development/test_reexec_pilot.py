"""Unit tests for the pilot Table I re-execution receipt and its comparison rules."""

from copy import deepcopy
import json
import unittest

import reexec_pilot as reexec


class ReexecPilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gen = reexec.load_frozen_pipeline()
        cls.published = reexec.load_published()
        cls.receipt = json.loads(reexec.RECEIPT.read_text(encoding="utf-8"))

    def test_committed_receipt_recomputes_from_raw_counters(self):
        self.assertEqual(reexec.check_receipt_static(self.gen, self.receipt, self.published),
                         sum(r["v_slow"] + r["v_fast"] for r in self.published))

    def test_embedded_sources_match_generator(self):
        corpus = reexec.embedded_corpus(self.gen, self.published)
        self.assertEqual([c["slow_code"] for c in corpus], [r["slow_code"] for r in self.published])
        self.assertTrue(all(callable(c["input_gen"]) for c in corpus))

    def test_identical_records_have_no_mismatch_or_flip(self):
        result = reexec.compare_records(self.published, deepcopy(self.published))
        self.assertEqual((result["mismatches"], result["decision_flips"]), ([], []))
        self.assertEqual(result["decisions_compared"], 18 * len(self.published))

    def test_slice_change_is_a_mismatch_and_a_flip(self):
        fresh = deepcopy(self.published)
        fresh[0]["slicing"]["c_pruned"] = []
        result = reexec.compare_records(self.published, fresh)
        self.assertEqual(result["mismatches"], [f"{fresh[0]['pair_id']}:slicing.c_pruned"])
        self.assertIn(f"{fresh[0]['pair_id']}:c_pruned.retains_reference", result["decision_flips"])

    def test_r2_drift_across_gate_flips_node_decision(self):
        pairs = {"PAIR_001": deepcopy(self.receipt["pairs"]["PAIR_001"])}
        fresh = deepcopy(pairs)
        node = next(iter(fresh["PAIR_001"]["slow"]["nodes"].values()))
        node["fit_work"]["r2_exp"] = 0.0 if node["fit_work"]["r2_exp"] >= reexec.EXP_R2_GATE else 1.0
        result = reexec.compare_counters(pairs, fresh)
        self.assertEqual(len(result["mismatches"]), 1)
        self.assertTrue(any(f.endswith("fit_work.r2_exp_gate") for f in result["decision_flips"]))

    def test_tampered_counter_fails_static_check(self):
        receipt = deepcopy(self.receipt)
        node = next(iter(receipt["pairs"]["PAIR_001"]["slow"]["nodes"].values()))
        node["work"][-1] += 1
        with self.assertRaises(AssertionError):
            reexec.check_receipt_static(self.gen, receipt, self.published)


    def fake_runs(self, raw=None):
        run = {"raw": raw if raw is not None else reexec.PILOT.read_bytes(), "records": deepcopy(self.published),
               "counters": deepcopy(self.receipt["pairs"]), "weights": {}}
        return run, {**run, "records": deepcopy(self.published), "raw": reexec.PILOT.read_bytes()}

    def test_archived_outputs_evaluate_clean(self):
        self.assertEqual(reexec.evaluate(self.published, self.receipt, *self.fake_runs())[1], [])

    def test_one_byte_change_in_fresh_output_fails(self):
        raw = bytearray(reexec.PILOT.read_bytes())
        raw[raw.index(b"  ")] = ord("\t")
        self.assertEqual(json.loads(bytes(raw)), self.published)
        report, failures, *_ = reexec.evaluate(self.published, self.receipt, *self.fake_runs(bytes(raw)))
        self.assertFalse(report["byte_identical"])
        self.assertEqual(len(failures), 1)
        self.assertIn("SHA-256", failures[0])

    def test_tampered_comparison_denominators_fail_static_check(self):
        for section, key in (("vs_published", "fields_compared"), ("vs_published", "decisions_compared"),
                             ("vs_published", "pairs"), ("vs_receipt", "decisions_compared")):
            receipt = deepcopy(self.receipt)
            receipt["comparison"][section][key] = 1
            with self.subTest(section=section, key=key), self.assertRaises(AssertionError):
                reexec.check_receipt_static(self.gen, receipt, self.published)

    def test_tampered_byte_identity_or_unit_records_fail_static_check(self):
        mutations = (
            lambda r: r.update(byte_identical=False),
            lambda r: r["proxy_defaults"]["unit"]["records"][0].update(max_work_slow=-1.0),
            lambda r: r["proxy_defaults"]["unit"]["vs_linear"].update(fields_compared=1),
            lambda r: r["proxy_defaults"]["linear"]["table_i"]["rows"][0].__setitem__(1, "0"),
        )
        for i, mutate in enumerate(mutations):
            receipt = deepcopy(self.receipt)
            mutate(receipt)
            with self.subTest(mutation=i), self.assertRaises(AssertionError):
                reexec.check_receipt_static(self.gen, receipt, self.published)

    def test_unit_proxy_default_reweights_only_undeclared_receivers(self):
        src = ("struct Bag { int count(int x) const { return x; } int size() const { return 3; } };\n"
               "Bag make();\n"
               "int f(int n, std::vector<int> v) { int s = 0; for (int i = 0; i < n; ++i) "
               "{ auto q = make(); s += q.count(i); s += v.erase(v.begin()) != v.end(); } return s; }\n")
        weights = {mode: {n["id"]: n["weight_expr"] for n in reexec.load_frozen_pipeline(mode).extract_macro_nodes(src, {})}
                   for mode in reexec.PROXY_DEFAULTS}
        changed = reexec.weight_changes({"t": weights["linear"]}, {"t": weights["unit"]})
        self.assertEqual(changed, [next(f"t/{k}: {w} -> 1ULL" for k, w in weights["linear"].items() if "q.size()" in w)])
        self.assertIn("(unsigned long long)(v.size())", weights["unit"].values())

    def test_proxy_patch_leaves_pinned_source_untouched(self):
        self.assertEqual(reexec.load_frozen_pipeline().EAPG_SOURCE_SHA256, reexec.PIPELINE_SHA)
        self.assertNotEqual(reexec.load_frozen_pipeline("unit").EAPG_SOURCE_SHA256, reexec.PIPELINE_SHA)

if __name__ == "__main__":
    unittest.main()
