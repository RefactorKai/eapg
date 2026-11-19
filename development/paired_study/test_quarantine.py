from copy import deepcopy
from hashlib import sha256
import unittest

from development.paired_study import quarantine, score


DEV_SHA = "a" * 64
PROSPECTIVE_SHA = "b" * 64


def key(value):
    return sha256(value.encode()).hexdigest()


def row(case, group, *, projects=None, problems=None, submissions=None):
    return {
        "id": case,
        "group": group,
        "projects": projects or [],
        "problems": problems or [case],
        "submission_ids": submissions or [case],
        "sources": {
            side: {"source_sha256": key(f"{case}-{side}"), "template_sha256": key(f"{case}-{side}-template")}
            for side in ("target", "reference")
        },
    }


def fixture():
    development = {
        "schema": quarantine.METADATA_SCHEMA, "split": "development", "drawn_ids": [],
        "fingerprint_revision_sha256": key("extractor"), "rows": [row("dev", "dev-family")],
    }
    prospective = {
        "schema": quarantine.METADATA_SCHEMA, "split": "prospective", "drawn_ids": ["a", "b", "c"],
        "fingerprint_revision_sha256": key("extractor"),
        "rows": [row("a", "ab-family"), row("b", "ab-family"), row("c", "c-family"), row("bridge", "ab-family")],
    }
    cases = {item["id"]: item for item in prospective["rows"]}
    cases["bridge"]["sources"]["reference"]["source_sha256"] = key("a-target")
    cases["bridge"]["sources"]["target"]["template_sha256"] = key("b-reference-template")
    return development, prospective


class QuarantineTests(unittest.TestCase):
    def test_cross_version_and_undrawn_bridge_preserve_claimed_groups(self):
        ledgers = fixture()
        result = quarantine.audit(*ledgers, DEV_SHA, PROSPECTIVE_SHA, 2)
        self.assertEqual(result["drawn_groups"], {"a": "ab-family", "b": "ab-family", "c": "c-family"})
        self.assertEqual(result["groups_sha256"], sha256(score.json_bytes(result["drawn_groups"])).hexdigest())
        self.assertEqual(result["prospective_components"], [["a", "b", "bridge"], ["c"]])
        ledgers[1]["rows"].reverse()
        self.assertEqual(result, quarantine.audit(*ledgers, DEV_SHA, PROSPECTIVE_SHA, 2))

    def test_bridge_from_prior_exposure_blocks_clean_candidate(self):
        development, prospective = fixture()
        prospective["rows"][3]["problems"].append("dev")
        with self.assertRaisesRegex(ValueError, r"Cross-split.*\ba\b.*\bb\b.*\bbridge\b.*\bdev\b"):
            quarantine.audit(development, prospective, DEV_SHA, PROSPECTIVE_SHA, 2)

    def test_key_namespaces_do_not_merge_homonyms(self):
        development, prospective = fixture()
        prospective["rows"][2]["submission_ids"].append("dev")
        development["rows"][0]["submission_ids"] = ["other"]
        development["rows"][0]["sources"]["reference"]["template_sha256"] = key("c-reference")
        result = quarantine.audit(development, prospective, DEV_SHA, PROSPECTIVE_SHA, 2)
        self.assertEqual(result["prospective_group_count"], 2)

    def test_missing_inventory_wrong_count_and_relabeling_are_rejected(self):
        cases = (
            ("expected count", lambda d, p: None, 3, "group count"),
            ("split family", lambda d, p: p["rows"][1].update(group="new"), 2, "splits a component"),
            ("merged group", lambda d, p: p["rows"][2].update(group="ab-family"), 2, "spans disconnected"),
            ("missing source", lambda d, p: p["rows"][0]["sources"].pop("reference"), 2, "source versions"),
            ("unknown draw", lambda d, p: p["drawn_ids"].append("unknown"), 2, "Invalid draw"),
            ("wrong extractor", lambda d, p: p.update(fingerprint_revision_sha256=key("other")), 2, "revision"),
        )
        for label, modify, count, error in cases:
            with self.subTest(label), self.assertRaisesRegex(ValueError, error):
                ledgers = fixture()
                modify(*ledgers)
                quarantine.audit(*ledgers, DEV_SHA, PROSPECTIVE_SHA, count)

    def test_registration_binding_checks_every_case_and_claimed_group(self):
        audit = quarantine.audit(*fixture(), DEV_SHA, PROSPECTIVE_SHA, 2)
        registration = {
            "pins": {"groups": audit["groups_sha256"]},
            "cases": [{"id": case, "group": group} for case, group in audit["drawn_groups"].items()],
        }
        quarantine.check_registration(audit, registration)
        wrong = deepcopy(registration)
        wrong["cases"][0]["group"] = "wrong"
        with self.assertRaisesRegex(ValueError, "audited draw"):
            quarantine.check_registration(audit, wrong)
        wrong = deepcopy(audit)
        wrong["groups_sha256"] = key("bad")
        with self.assertRaisesRegex(ValueError, "group digest"):
            quarantine.check_registration(wrong, registration)


if __name__ == "__main__":
    unittest.main()
