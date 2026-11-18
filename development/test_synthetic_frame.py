"""Authored frame and replay checks. Run with python -B development/test_synthetic_frame.py."""

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from score_synthetic import PRIMARY, SEEDS, join
from synthetic_frame import CORE_SLOTS, FRAME, INPUTS, SWAP_SLOTS, build_draw, canonical, commitment, select


PROTOCOL = b"Authored mock protocol"
PIN = "a" * 64


def slots(fid, names, bands=()):
    result = {}
    for slot in names:
        pid = commitment([fid, slot])[:24]
        original = commitment([pid, "original"])
        evaluated = original if slot == "appropriate_superlinear" else commitment([fid, "evaluated"])
        result[slot] = {"case_id": pid, "source_hashes": {"original": original, "evaluated": evaluated, "restored": original},
                        "registration_sha256": commitment([pid, "registration"])}
    for slot, band in zip(CORE_SLOTS[:2], bands):
        result[slot]["band"] = band
    if "positive_off_site" in result:
        result["positive_off_site"].update(edit_span=[10, 12], intended_statement_span=[12, 20])
    return result


def fixture(pin=PIN):
    frame = {"schema": FRAME, "protocol_sha256": pin, "draw_seed": 1729,
             "sham_classes": {"linear": False, "quadratic": True}, "allocation": [], "families": []}
    for cell, (mechanism, sham, off, at) in enumerate((
        ("reset", "linear", "near_below", "strong"), ("reset", "quadratic", "strong", "strong"),
        ("rescan", "linear", "strong", "strong"), ("rescan", "quadratic", "strong", "near_above"),
    )):
        frame["allocation"].append({"mechanism": mechanism, "sham_class": sham, "off_site_band": off,
                                    "at_site_band": at, "count": 20})
        for ordinal in range(22):
            fid = f"mock-{cell}-{ordinal}"
            frame["families"].append({"family_id": fid, "problem_id": fid, "problem_aliases": [],
                                      "specification_sha256": PIN, "implementation_origin": fid, "generator_id": fid,
                                      "generator_ancestors": [], "mechanism": mechanism, "sham_class": sham,
                                      "workload": {"generator_sha256": PIN, "distribution": "valid mock values",
                                                   "n0": 3 + cell, "size_parameters": "length only"},
                                      "slots": slots(fid, CORE_SLOTS, (off, at))})
    frame["comparator_swap"] = {"family_id": "mock-0-0", "slots": slots("mock-swap", SWAP_SLOTS)}
    return frame


def input_fixture(selection, cases):
    return {"schema": INPUTS, "selection_sha256": commitment(selection), "families": {
        family["family_id"]: [{"seed": seed, "n": family["workload"]["n0"] << power,
                               "sha256": commitment([family["family_id"], seed, power])}
                              for seed in SEEDS for power in range(6)]
        for family, _, _ in cases}}


class SyntheticFrame(unittest.TestCase):
    def test_draw_replays_and_joins_with_scorer(self):
        frame = fixture()
        before, _ = select(frame, PIN)
        for family in frame["families"]:
            family.update(problem_aliases=None, implementation_origin=None, generator_ancestors=None)
        selection, cases = select(frame, PIN)
        self.assertEqual(selection["core_family_ids"], before["core_family_ids"])
        self.assertEqual(selection, select(deepcopy(frame), PIN)[0])
        self.assertEqual(len(set(selection["core_family_ids"])), 80)
        self.assertEqual(len(set(selection["case_ids"])), 322)
        inputs = input_fixture(selection, cases)
        draw = build_draw(selection, cases, inputs)
        self.assertEqual(draw["allocation"], dict.fromkeys(CORE_SLOTS, 80) | dict.fromkeys(SWAP_SLOTS, 1))
        self.assertEqual([row["case_id"] for row in draw["cases"]], selection["case_ids"])
        self.assertEqual(draw["cases"][-2]["source_sha256"], draw["cases"][-1]["source_sha256"])
        self.assertEqual(draw["cases"][-2]["workload_sha256"], draw["cases"][-1]["workload_sha256"])

        draw_sha = commitment(draw)
        labels = {"schema": "eapg-synthetic-labels-v1", "draw_sha256": draw_sha,
                  "source_manifest_sha256": PIN, "quarantine_sha256": PIN, "cases": [
                      {"case_id": pid, "family_id": None, "disposition": "quarantined", "operation_evidence_sha256": None,
                       "normalized_source_sha256": None, "canonical_node_ids": [], "accepted_node_ids": [],
                       "reference_status": None, "reference_reason": None} for pid in selection["case_ids"]]}
        arms = dict.fromkeys(PRIMARY, {"alert": None, "symptom_id": None, "candidates": [], "ranking": [], "status": "not_run"})
        predictions = {"schema": "eapg-synthetic-predictions-v1", "draw_sha256": draw_sha,
                       "labels_sha256": commitment(labels), "runner_sha256": PIN, "pipeline_sha256": PIN,
                       "baseline_sha256": PIN, "arm_ids": list(PRIMARY), "predictions": [
                           {"case_id": pid, "seed": seed, "normalized_source_sha256": None, "profile_status": "not_run",
                            "arms": arms} for pid in selection["case_ids"] for seed in SEEDS]}
        joined = join(draw, labels, predictions, draw_sha, commitment(labels))
        self.assertEqual([row["case_id"] for row in joined[42]], selection["case_ids"])

    def test_frame_rejects_bad_quotas_origins_slots_and_diagnostic(self):
        for message, mutate in (
            ("80 origin families", lambda f: f["allocation"][0].update(count=19)),
            ("allocation cell", lambda f: f["allocation"][0].update(count=23)),
            ("allocation cell", lambda f: f["allocation"].append(f["allocation"][0])),
            ("balance", lambda f: (f["allocation"][0].update(count=21), f["allocation"][1].update(count=19))),
            ("near-threshold bands", lambda f: self.replace_last_cell_band(f)),
            ("Shared problem", lambda f: f["families"][1].update(problem_aliases=[f["families"][0]["problem_id"]])),
            ("Shared implementation", lambda f: f["families"][1].update(implementation_origin=f["families"][0]["implementation_origin"])),
            ("Shared generator", lambda f: f["families"][1].update(generator_ancestors=[f["families"][0]["generator_id"]])),
            ("registered slots", lambda f: f["families"][0]["slots"].pop("positive_at_site")),
            ("Off-site spans", lambda f: f["families"][0]["slots"]["positive_off_site"].update(edit_span=[10, 15])),
            ("identical evaluated bytes", lambda f: f["comparator_swap"]["slots"][SWAP_SLOTS[0]]["source_hashes"].update(evaluated=PIN)),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                frame = fixture()
                mutate(frame)
                select(frame, PIN)

    @staticmethod
    def replace_last_cell_band(frame):
        frame["allocation"][-1]["at_site_band"] = "strong"
        for family in frame["families"][-22:]:
            family["slots"]["positive_at_site"]["band"] = "strong"

    def test_input_grid_rejects_substitution_missing_rows_and_wrong_order(self):
        frame = fixture()
        selection, cases = select(frame, PIN)
        inputs = input_fixture(selection, cases)
        fid = selection["core_family_ids"][0]
        frame["draw_seed"] += 1
        with self.assertRaisesRegex(ValueError, "replayed selection"):
            build_draw(*select(frame, PIN), inputs)
        for message, mutate in (
            ("cover the selected", lambda i: i["families"].pop(fid)),
            ("Incomplete input digest grid", lambda i: i["families"][fid].pop()),
            ("out-of-order input digest", lambda i: i["families"][fid].reverse()),
            ("out-of-order input digest", lambda i: i["families"][fid][0].update(sha256="unchecked")),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                edited = deepcopy(inputs)
                mutate(edited)
                build_draw(selection, cases, edited)

    def test_cli_seals_selection_and_draw_from_explicit_pins(self):
        protocol_sha = sha256(PROTOCOL).hexdigest()
        frame = fixture(protocol_sha)
        selection, cases = select(frame, protocol_sha)
        inputs = input_fixture(selection, cases)
        with TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp:
            root = Path(temp)
            (root / "protocol.md").write_bytes(PROTOCOL)
            (root / "frame.json").write_bytes(canonical(frame))
            (root / "inputs.json").write_bytes(canonical(inputs))
            args = [sys.executable, "-B", str(Path(__file__).with_name("synthetic_frame.py")),
                    "--protocol", "protocol.md", "--protocol-sha256", protocol_sha,
                    "--frame", "frame.json", "--frame-sha256", commitment(frame)]
            subprocess.run([*args, "--output", "selection.json"], cwd=root, check=True, capture_output=True)
            self.assertEqual((root / "selection.json").read_bytes(), canonical(selection))
            draw_args = [*args, "--inputs", "inputs.json", "--inputs-sha256", commitment(inputs)]
            subprocess.run([*draw_args, "--output", "draw.json"], cwd=root, check=True, capture_output=True)
            expected = canonical(build_draw(selection, cases, inputs))
            self.assertEqual((root / "draw.json").read_bytes(), expected)
            subprocess.run([*draw_args, "--verify", "draw.json"], cwd=root, check=True, capture_output=True)
            self.assertNotEqual(subprocess.run([*args, "--output", "draw.json"], cwd=root, capture_output=True).returncode, 0)
            self.assertEqual((root / "draw.json").read_bytes(), expected)

            draw = build_draw(selection, cases, inputs)
            draw["cases"][0]["source_sha256"] = PIN
            (root / "draw.json").write_bytes(canonical(draw))
            result = subprocess.run([*draw_args, "--verify", "draw.json"], cwd=root, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b"Sealed output differs", result.stderr)

            frame["draw_seed"] += 1
            (root / "frame.json").write_bytes(canonical(frame))
            result = subprocess.run([*args, "--output", "altered.json"], cwd=root, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b"Ledger digest mismatch: frame.json", result.stderr)
            self.assertFalse((root / "altered.json").exists())


if __name__ == "__main__":
    unittest.main()
