"""Authored custody graph tests. Run with python -B development/test_synthetic_quarantine.py."""

from copy import deepcopy
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from synthetic_frame import canonical, commitment
from synthetic_quarantine import FRAME_COHORTS, PROVENANCE, seal


REPRESENTATIONS = ["skeleton", "full"]
FINGERPRINTS = ("raw_sha256", "normalized_sha256", "template_sha256")
MISSING = {"unavailable_reason": "Authored unsupported fingerprint"}


def row(rid, cohort, *, family=None):
    versions = ("original", "evaluated", "restored") if cohort in FRAME_COHORTS else ("evaluated",)
    return {"row_id": rid, "cohort": cohort, "registered_family_id": family or (rid if cohort in FRAME_COHORTS else None),
            "attestation_sha256": commitment(["attestation", rid]), "unknown_provenance_reason": None,
            "problem_ids": [rid], "implementation_ids": [rid], "generator_ids": [rid], "scaffold_sha256": [],
            "sources": {version: {key: commitment([rid, version, key]) for key in FINGERPRINTS} for version in versions},
            "prompts": {rep: commitment([rid, rep]) for rep in REPRESENTATIONS}}


def fixture(rows):
    draw = {"schema": "eapg-synthetic-draw-v1", "draw_seed": 47, "protocol_sha256": "a" * 64, "frame_sha256": "b" * 64,
            "cases": [{"case_id": rec["row_id"], "intended_slot": "positive_at_site", "workload_sha256": "c" * 64,
                       "source_sha256": rec["sources"]["evaluated"]["raw_sha256"]}
                      for rec in rows if rec["cohort"] == "drawn"]}
    draw["allocation"] = {"positive_at_site": len(draw["cases"])}
    return draw, {"schema": PROVENANCE, "draw_sha256": commitment(draw), "representations": REPRESENTATIONS, "rows": rows}


def by_id(manifest):
    return {row["row_id"]: (group["family_id"], row) for group in manifest["components"] for row in group["rows"]}


class SyntheticQuarantine(unittest.TestCase):
    def test_transitive_edges_and_exposure_survive_excluded_bridge(self):
        first = row("first", "drawn", family="registered")
        sibling = row("sibling", "drawn", family="registered")
        same_scaffold = row("scaffold_neighbor", "drawn")
        same_normalized = row("normalized_neighbor", "drawn")
        bridge = row("bridge", "train")
        exposure = row("exposure", "exposure")
        first["sources"]["restored"]["template_sha256"] = bridge["sources"]["evaluated"]["template_sha256"]
        bridge["prompts"]["skeleton"] = exposure["prompts"]["full"]
        sibling["scaffold_sha256"] = same_scaffold["scaffold_sha256"] = [commitment(["shared scaffold"])]
        same_normalized["sources"]["original"]["normalized_sha256"] = sibling["sources"]["restored"]["normalized_sha256"]
        exposure["sources"]["evaluated"]["normalized_sha256"] = MISSING
        first["prompts"]["full"] = MISSING
        draw, provenance = fixture([first, sibling, same_scaffold, same_normalized, bridge, exposure])
        outcome = seal(draw, provenance)
        rows = by_id(outcome)
        self.assertEqual(len({family for family, _ in rows.values()}), 1)
        for rid in ("first", "sibling", "scaffold_neighbor", "normalized_neighbor"):
            self.assertEqual(rows[rid][1]["disposition"], "quarantined")
            self.assertEqual(rows[rid][1]["reasons"], ["linked_to_prior_exposure"])
        self.assertEqual(rows["bridge"][1]["disposition"], "excluded")
        self.assertEqual(rows["bridge"][1]["reasons"], ["linked_to_draw"])
        self.assertEqual(rows["exposure"][1]["disposition"], "prior_exposure")
        self.assertEqual(rows["first"][1]["unavailable_fingerprints"]["prompts.full"], MISSING["unavailable_reason"])
        provenance["rows"].reverse()
        self.assertEqual(seal(draw, provenance)["components"], outcome["components"])

    def test_unknown_origins_fitting_splits_and_typed_keys(self):
        target = row("target", "drawn")
        unknown = row("unknown", "validation")
        unknown.update(unknown_provenance_reason="Known generator ancestor only", problem_ids=[], implementation_ids=[],
                       generator_ids=["target"])
        unrelated = row("unrelated", "train")
        unrelated["problem_ids"] = ["target-generator-alias"]
        target["generator_ids"].append("target-generator-alias")
        cpu = row("cpu", "drawn")
        cpu["prompts"]["skeleton"] = MISSING
        fit = row("unused-near-cpu", "train")
        fit["implementation_ids"].append("cpu")
        val, train = row("validation", "validation"), row("train", "train")
        val["problem_ids"].append("train")
        unsupported = row("unsupported", "train")
        unsupported["prompts"]["full"] = MISSING
        incomplete = row("incomplete", "train")
        incomplete["unknown_provenance_reason"] = "Unverified lineage"
        draw, provenance = fixture([target, unknown, unrelated, cpu, fit, val, train, unsupported, incomplete])
        rows = by_id(seal(draw, provenance))
        self.assertEqual(rows["target"][0], rows["unknown"][0])
        self.assertEqual(rows["target"][1]["reasons"], ["unknown_component_provenance"])
        self.assertEqual(rows["unknown"][1]["reasons"], ["unknown_component_provenance", "linked_to_draw"])
        self.assertEqual(rows["unrelated"][1]["disposition"], "eligible")
        self.assertEqual(rows["cpu"][1]["disposition"], "eligible")
        self.assertEqual(rows["unused-near-cpu"][1]["reasons"], ["linked_to_draw"])
        self.assertEqual(rows["validation"][1]["disposition"], "eligible")
        self.assertEqual(rows["train"][1]["reasons"], ["reserved_for_validation"])
        self.assertEqual(rows["unsupported"][1]["reasons"], ["unavailable_prompt_fingerprint"])
        self.assertEqual(rows["incomplete"][1]["reasons"], ["unknown_component_provenance"])

    def test_rejects_incomplete_or_mismatched_custody_rows(self):
        draw, provenance = fixture([row("case", "drawn"), row("used", "exposure")])
        for message, mutate in (
            ("cover the drawn", lambda p: p["rows"].pop(0)),
            ("Duplicate provenance", lambda p: p["rows"].append(p["rows"][0])),
            ("bind this draw", lambda p: p.update(draw_sha256="0" * 64)),
            ("source differs from draw", lambda p: p["rows"][0]["sources"]["evaluated"].update(raw_sha256="0" * 64)),
            ("Missing drawn source version", lambda p: p["rows"][0]["sources"].pop("restored")),
            ("Incomplete prompt", lambda p: p["rows"][0]["prompts"].pop("full")),
            ("fingerprint", lambda p: p["rows"][0]["prompts"].update(full="invented")),
            ("origin provenance", lambda p: p["rows"][1].update(problem_ids=[])),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                edited = deepcopy(provenance)
                mutate(edited)
                seal(draw, edited)

    def test_cli_checks_pins_and_replays_exact_bytes(self):
        draw, provenance = fixture([row("case", "drawn"), row("used", "exposure")])
        with TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp:
            root = Path(temp)
            (root / "draw.json").write_bytes(canonical(draw))
            (root / "provenance.json").write_bytes(canonical(provenance))
            args = [sys.executable, "-B", str(Path(__file__).with_name("synthetic_quarantine.py")),
                    "--draw", "draw.json", "--draw-sha256", commitment(draw),
                    "--provenance", "provenance.json", "--provenance-sha256", commitment(provenance)]
            subprocess.run([*args, "--output", "quarantine.json"], cwd=root, check=True, capture_output=True)
            self.assertEqual((root / "quarantine.json").read_bytes(), canonical(seal(draw, provenance)))
            subprocess.run([*args, "--verify", "quarantine.json"], cwd=root, check=True, capture_output=True)
            provenance["rows"].pop()
            (root / "provenance.json").write_bytes(canonical(provenance))
            result = subprocess.run([*args, "--verify", "quarantine.json"], cwd=root, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b"Ledger digest mismatch: provenance.json", result.stderr)


if __name__ == "__main__":
    unittest.main()
