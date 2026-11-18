"""Check static provenance replay against the pinned C++ parser."""

from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from build_reference_packet import custody
from run_phase2_development import ProfileFailure
import synthetic_source_fingerprints as proof


PIPELINE = SimpleNamespace(source_sha256="a" * 64, parser=custody.PARSER)


class SourceFingerprintTests(unittest.TestCase):
    def test_normalized_templates_link_across_versions(self):
        source = "int main() { int count = 5; return count + 2; }\n"
        renamed = "int main() { int accum = 9; return accum + 1; }\n"
        changed = renamed.replace(" + ", " - ")
        inventory = {"schema": proof.INVENTORY_SCHEMA, "rows": [
            {"row_id": "first", "sources": {"original": source, "restored": source}},
            {"row_id": "second", "sources": {"edited": renamed, "control": changed}},
        ]}
        with patch.object(proof, "normalize", side_effect=lambda pipeline, text: (text, {})) as normalize:
            report = proof.build_report(PIPELINE, inventory)
        self.assertEqual(normalize.call_count, 3)
        original = report["rows"][0]["sources"]["original"]
        edited, control = report["rows"][1]["sources"].values()
        self.assertEqual(original, report["rows"][0]["sources"]["restored"])
        self.assertNotEqual(original["raw_sha256"], edited["raw_sha256"])
        self.assertNotEqual(original["normalized_sha256"], edited["normalized_sha256"])
        self.assertEqual(original["template_sha256"], edited["template_sha256"])
        self.assertNotEqual(edited["template_sha256"], control["template_sha256"])

        provenance = {"schema": proof.PROVENANCE, "rows": [
            {**row, "unknown_provenance_reason": None} for row in deepcopy(report["rows"])
        ]}
        proof.verify_attestations(report, provenance)
        missing = deepcopy(provenance)
        missing["rows"].pop()
        with self.assertRaisesRegex(ValueError, "does not cover"):
            proof.verify_attestations(report, missing)
        provenance["rows"][0]["sources"]["restored"]["template_sha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "do not replay"):
            proof.verify_attestations(report, provenance)

    def test_unavailable_static_fingerprint_requires_unknown_provenance(self):
        inventory = {"schema": proof.INVENTORY_SCHEMA, "rows": [
            {"row_id": "first", "sources": {"evaluated": "int main() {}"}},
        ]}
        with patch.object(proof, "normalize", side_effect=ProfileFailure("PREPROCESS_ERROR", "authored failure")):
            report = proof.build_report(PIPELINE, inventory)
        row = {**report["rows"][0], "unknown_provenance_reason": None}
        provenance = {"schema": proof.PROVENANCE, "rows": [row]}
        self.assertEqual(row["sources"]["evaluated"]["normalized_sha256"],
                         {"unavailable_reason": "normalization_preprocess_error"})
        with self.assertRaisesRegex(ValueError, "must keep provenance unknown"):
            proof.verify_attestations(report, provenance)
        row["unknown_provenance_reason"] = "One source cannot be normalized"
        proof.verify_attestations(report, provenance)


if __name__ == "__main__":
    unittest.main()
