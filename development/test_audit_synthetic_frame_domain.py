"""Authored tests for whole-frame source binding and pre-draw admission."""

from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import audit_synthetic_frame_domain as audit
from build_reference_packet import custody
from synthetic_frame import CORE_SLOTS, FRAME, SWAP_SLOTS
from synthetic_source_fingerprints import INVENTORY_SCHEMA


def fixture():
    mark = "a" * 64
    frame = {"schema": FRAME, "protocol_sha256": mark, "draw_seed": 42, "sham_classes": {},
             "allocation": [], "families": [], "comparator_swap": None}
    inventory = {"schema": INVENTORY_SCHEMA, "rows": []}
    for family, keys in (("first", CORE_SLOTS), ("second", CORE_SLOTS), ("first", SWAP_SLOTS)):
        slots = {}
        for slot in keys:
            case_id = f"{family}-{slot}"
            original = "int main() { return 0; }"
            edited = "int main() { return 1; }" if slot != "appropriate_superlinear" else original
            if (family, slot) == ("second", "positive_at_site"):
                edited = "int main() { int unsupported[2]; return 1; }"
            sources = {"original": original, "evaluated": edited, "restored": original}
            plan = {"case_id": case_id, "source_hashes": {name: sha256(text.encode()).hexdigest()
                                                       for name, text in sources.items()},
                    "registration_sha256": mark}
            if slot in CORE_SLOTS[:2]:
                plan["band"] = "strong"
            if slot == "positive_off_site":
                plan.update(edit_span=[15, 16], intended_statement_span=[11, 14])
            slots[slot] = plan
            inventory["rows"].append({"row_id": case_id, "sources": sources})
        if keys == CORE_SLOTS:
            frame["families"].append({"family_id": family, "slots": slots})
        else:
            frame["comparator_swap"] = {"family_id": family, "slots": slots}
    return frame, inventory


class FrameDomainTests(unittest.TestCase):
    def test_checks_complete_inventory_before_any_compiler_call(self):
        frame, inventory = fixture()
        for change in ("missing", "late_hash"):
            with self.subTest(change=change), patch.object(audit, "inspect_source") as inspect:
                invalid = deepcopy(inventory)
                if change == "missing":
                    invalid["rows"].pop()
                else:
                    invalid["rows"][-1]["sources"]["evaluated"] += "\r\n"
                with self.assertRaisesRegex(ValueError, "complete frame|differ from the plan"):
                    audit.audit_frame(SimpleNamespace(), frame, invalid)
                inspect.assert_not_called()

    def test_counts_support_per_case_and_family_with_actual_cfg(self):
        frame, inventory = fixture()
        pipeline = SimpleNamespace(source_sha256="b" * 64, parser=custody.PARSER,
                                   extract_macro_nodes=lambda *_: [])
        with patch.object(audit, "syntax_only") as syntax, \
                patch.object(audit, "normalize", side_effect=lambda _, text: (text, {})):
            report = audit.audit_frame(pipeline, frame, inventory)
        self.assertEqual(syntax.call_count, 3)
        self.assertEqual((report["authored_cases"], report["supported_cases"]), (10, 9))
        self.assertEqual((report["core_families"], report["supported_core_families"]), (2, 1))
        bad, = [case for case in report["cases"] if not case["supported"]]
        self.assertEqual(bad["sources"]["evaluated"]["status"], "unsupported_comparator")
        self.assertEqual(bad["sources"]["original"]["status"], "supported")

    def test_counts_only_canonical_spans_owned_by_reachable_operations(self):
        text = "int main() { int count=0; while (count < 4) { ++count; } return count; }"
        root = custody.PARSER.parse(text.encode()).root_node
        loop, = [node for node in root.named_children[0].child_by_field_name("body").named_children
                 if node.type == "while_statement"]
        nodes = [{"role": "LOOP", "normalized_span": (loop.start_byte, loop.end_byte)},
                 {"role": "CALL", "normalized_span": (1, 2)}]
        pipeline = SimpleNamespace(parser=custody.PARSER, extract_macro_nodes=lambda *_: nodes)
        with patch.object(audit, "syntax_only"), patch.object(audit, "normalize", return_value=(text, {})):
            result = audit.inspect_source(pipeline, text)
        self.assertEqual(result["canonical_roles"], {"LOOP": 1, "CALL": 1})
        self.assertEqual(result["reachable_cfg_owner_roles"], {"LOOP": 1})


if __name__ == "__main__":
    unittest.main()
