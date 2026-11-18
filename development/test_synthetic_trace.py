"""Authored counter and isolation receipts. Run with python -B development/test_synthetic_trace.py."""

from base64 import b64decode
from copy import deepcopy
from hashlib import sha256
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from run_phase2_development import ProfileFailure
from synthetic_arms import ARM_IDS
from synthetic_trace import SEEDS, capture_case, predict_case, prediction_rows


SOURCE = "int main() {}"
NODES = [{"id": "N1", "reference_id": "custodian-only", "source_preview": "fixture"}]
CAP = 2_000_000
GRID = [{"seed": seed, "n": 8 * 2**size, "stdin": f"{seed}:{8 * 2**size}\n",
         "expected_stdout": "résultat\n", "expected_counts": {"original": 1, "edited": 2, "restored": 1}}
        for seed in SEEDS for size in range(6)]
ORACLE = {"schema": "eapg-synthetic-operation-evidence-v1", "disposition": "confirmed_positive",
          "source_sha256": {"edited": sha256(SOURCE.encode()).hexdigest()},
          "grid_sha256": sha256(json.dumps(GRID, ensure_ascii=False, sort_keys=True,
                                           separators=(",", ":")).encode()).hexdigest()}


def execute_fixture(binary, data, *, counter_scale):
    assert binary == b"binary"
    seed, n = map(int, data.decode().split(":"))
    assert n == counter_scale
    cap = (seed, n) in {(42, 16), (43, 256)}
    action = "CAP_BREACHED" if cap else "CLEAN_COMPLETION"
    work = CAP if cap else n * n
    counter = {"status": action, "total_ticks": work, "nodes": {"N1": {"cnt": n, "work": work}}}
    counter_wire = (json.dumps(counter) + "\n").encode()
    output = "résultat\n".encode()
    if seed == 42 and n == 32:
        output += b"\n"
    if seed == 43 and n == 8:
        counter_wire = b'{"status": "truncated"'
    return SimpleNamespace(stdout=output, stderr=b"", counter_wire=counter_wire, events={},
                           returncode=97 if cap else 0, timed_out=(seed, n) == (43, 16))


class SyntheticTraceTests(unittest.TestCase):
    def setUp(self):
        self.pipeline = SimpleNamespace(extract_macro_nodes=lambda *_: deepcopy(NODES),
                                        compute_tick_ceiling=lambda _: CAP)

    def capture(self):
        with patch("synthetic_trace.normalize", return_value=(SOURCE, {})), \
                patch("synthetic_trace.compile_instrumented", return_value=b"binary"), \
                patch("synthetic_trace.execute", side_effect=execute_fixture) as executor:
            receipt, packet = capture_case(self.pipeline, SOURCE, GRID, ORACLE)
        self.assertEqual(executor.call_count, 18)
        return receipt, json.loads(json.dumps(packet))

    def test_local_failures_preserve_other_runs_and_boundaries(self):
        receipt, packet = self.capture()
        status = {(row["seed"], row["n"]): row for row in receipt["runs"]}
        self.assertEqual(status[42, 16]["status"], "CAP_BREACHED")
        self.assertEqual(status[42, 16]["total_ticks"], CAP)
        self.assertEqual(status[42, 32]["status"], "OUTPUT_MISMATCH")
        self.assertEqual(status[43, 8]["status"], "INVALID_COUNTER")
        self.assertEqual(b64decode(status[43, 8]["counter_wire_b64"]), b'{"status": "truncated"')
        self.assertEqual(status[43, 16]["status"], "TIMEOUT_TLE")
        self.assertEqual(status[44, 256]["status"], "CLEAN_COMPLETION")
        seeds = prediction_rows(packet)
        self.assertEqual([row["n"] for row in seeds["42"]["runs"]], [8, 64, 128, 256])
        self.assertEqual(seeds["43"]["status"], "insufficient_clean_rows")
        self.assertEqual(seeds["44"]["status"], "eligible")
        public = json.dumps(packet)
        for private in ("reference", "stdout", "elapsed", "expected_count", "disposition", "grid_sha256"):
            self.assertNotIn(private, public)

    def test_fit_and_prediction_receive_the_same_eligible_rows(self):
        _, packet = self.capture()
        fits = []

        def fit(sizes, counts):
            fits.append((sizes, counts))
            return {"growth": "POLY", "alpha": 1.0, "r2_poly": 1.0}

        def predict(pipeline, normalized, profile, seed):
            self.assertIs(pipeline, self.pipeline)
            self.assertEqual(normalized, SOURCE)
            self.assertEqual(set(profile["fits"][str(seed)]["N1"]), {"fit_work", "fit_hits"})
            return {"seed": seed, "profile_status": "complete"}

        self.pipeline.fit_dual_family_scaling = fit
        with patch("synthetic_trace.predict_seed", side_effect=predict):
            preds = predict_case(self.pipeline, packet)
        self.assertEqual([row["profile_status"] for row in preds], ["complete", "insufficient_clean_rows", "complete"])
        self.assertEqual(set(preds[1]["arms"]), set(ARM_IDS))
        self.assertTrue(all(arm["alert"] is None and not arm["ranking"] for arm in preds[1]["arms"].values()))
        self.assertEqual(fits[:2], [([8, 64, 128, 256], [8, 64, 128, 256]),
                                   ([8, 64, 128, 256], [64, 4096, 16384, 65536])])

    def test_mismatched_oracle_evidence_blocks_execution(self):
        for batch, oracle in ((GRID, dict(ORACLE, disposition="growth_failure")),
                              ([dict(GRID[0], expected_stdout="changed")] + GRID[1:], ORACLE)):
            with patch("synthetic_trace.normalize") as normalize:
                receipt, packet = capture_case(self.pipeline, SOURCE, batch, oracle)
                normalize.assert_not_called()
            self.assertEqual(receipt["status"], "oracle_unverified")
            self.assertTrue(all(row["profile_status"] == "oracle_unverified" for row in predict_case(self.pipeline, packet)))
            self.assertIsNone(packet["normalized_source"])

    def test_build_failures_abstain_and_isolation_failures_propagate(self):
        with patch("synthetic_trace.normalize", return_value=(SOURCE, {})), \
                patch("synthetic_trace.compile_instrumented", side_effect=ProfileFailure("COMPILE_ERROR", "fixture")), \
                patch("synthetic_trace.execute") as execute:
            receipt, packet = capture_case(self.pipeline, SOURCE, GRID, ORACLE)
            execute.assert_not_called()
        self.assertEqual(receipt["build"]["status"], "COMPILE_ERROR")
        self.assertTrue(all(row["profile_status"] == "instrumentation_failure"
                            for row in predict_case(self.pipeline, packet)))
        with patch("synthetic_trace.normalize", side_effect=RuntimeError("Sandbox scope did not start")):
            with self.assertRaisesRegex(RuntimeError, "Sandbox scope did not start"):
                capture_case(self.pipeline, SOURCE, GRID, ORACLE)

    def test_prediction_rejects_capped_or_malformed_rows_and_source_mismatch(self):
        _, packet = self.capture()
        corrupted = deepcopy(packet)
        corrupted["seeds"]["42"]["runs"][0]["status"] = "CAP_BREACHED"
        with self.assertRaisesRegex(ValueError, "Invalid clean counter row"):
            predict_case(self.pipeline, corrupted)
        corrupted = deepcopy(packet)
        corrupted["seeds"]["42"]["runs"].pop()
        with self.assertRaisesRegex(ValueError, "Invalid seed disposition"):
            predict_case(self.pipeline, corrupted)
        corrupted = deepcopy(packet)
        corrupted["normalized_source"] += " "
        with self.assertRaisesRegex(ValueError, "source digest mismatch"):
            predict_case(self.pipeline, corrupted)


if __name__ == "__main__":
    unittest.main()
