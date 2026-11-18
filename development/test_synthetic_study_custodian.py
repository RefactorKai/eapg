"""Exercise the integrated custodian with an authored 322-row draw and mocked C++ runs."""

from copy import deepcopy
from hashlib import sha256
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from score_synthetic import EXPECTED, SEEDS, join
from synthetic_arms import ARM_IDS, arm
from synthetic_frame import CORE_SLOTS, INPUTS, SWAP_SLOTS, build_draw, commitment, select
from synthetic_quarantine import PROVENANCE, seal
from synthetic_trace import SCHEMA as PROJECTION_SCHEMA, predict_case
from test_synthetic_frame import PIN, fixture as frame_fixture
from test_synthetic_quarantine import row as provenance_row

import synthetic_study_custodian as custodian


PRIVATE_OUTPUT = "authored private oracle output é\n"


def digest(text):
    return sha256(text.encode("utf-8")).hexdigest()


def make_registration(family, slot, plan):
    identity = commitment([family["family_id"], "shared evaluated source"])[:24] if slot in SWAP_SLOTS else plan["case_id"]
    template = f"// authored fixture source {identity}\nint main() {{ int cursor = VALUE; cursor += 1; return 0; }}\n"
    edited = template.replace("VALUE", "0")
    original_token = "2" if slot == "comparator_swap_sham" else "1"
    original = template.replace("VALUE", original_token)
    edit = {"start_byte": template.encode().index(b"VALUE"), "removed": original_token, "inserted": "0"}
    order = 2 if slot == "comparator_swap_sham" or family["sham_class"] == "quadratic" else 1
    disposition = EXPECTED[slot]
    if disposition == "confirmed_appropriate":
        original, edit = edited, None
        before, after, band = 2, 2, "appropriate"
    elif disposition == "confirmed_sham":
        before, after, band = order, order, "same"
    else:
        band = plan.get("band", "strong")
        before, after = 1, {"strong": 2, "near_below": 1.63, "near_above": 1.76}[band]

    sources = {"original": original, "edited": edited, "restored": original}
    registration = {"sources": sources, "counting_sources": {key: "// counting fixture\n" + value
                     for key, value in sources.items()},
                    "growth": {"original_order": [before, 0], "edited_order": [after, 0], "band": band},
                    "edit": edit, "equivalent_edited_intervals": [],
                    "operation_inventory_sha256": commitment(["authored inventory", identity])}
    if slot == "positive_off_site":
        statement = edited.encode().index(b"cursor += 1;")
        plan["intended_statement_span"] = [statement, statement + len(b"cursor += 1;")]
    return registration


def make_grid(family, slot, registration):
    before, after = (registration["growth"][name][0] for name in ("original_order", "edited_order"))
    sizes = [family["workload"]["n0"] << power for power in range(6)]
    return [{"seed": seed, "n": n, "stdin": f"{n}\n", "expected_stdout": PRIVATE_OUTPUT,
             "expected_counts": {"original": round(n**before), "edited": round(n**after), "restored": round(n**before)}}
            for seed in SEEDS for n in sizes]


def fixture(pin=PIN, *, eligible_registration=make_registration, eligible_grid=make_grid):
    frame = frame_fixture(pin)
    drawn = set(select(frame, pin)[0]["core_family_ids"])
    eligible_family = next(family for family in frame["families"]
                           if family["family_id"] in drawn and family["sham_class"] == "linear"
                           and all(family["slots"][slot]["band"] == "strong" for slot in CORE_SLOTS[:2]))
    eligible = eligible_family["family_id"]
    frame["comparator_swap"]["family_id"] = eligible
    eligible_family.update(problem_aliases=["authored-problem-alias"], generator_ancestors=["authored-generator-parent"])
    registrations = {}
    groups = [(family, family["slots"]) for family in frame["families"]]
    groups.append((eligible_family, frame["comparator_swap"]["slots"]))
    for family, slots in groups:
        factory = eligible_registration if family["family_id"] == eligible else make_registration
        for slot, plan in slots.items():
            registration = factory(family, slot, plan)
            source = registration["sources"]
            plan["source_hashes"] = {"original": digest(source["original"]), "evaluated": digest(source["edited"]),
                                     "restored": digest(source["restored"])}
            plan["registration_sha256"] = commitment(registration)
            if slot == "positive_off_site":
                edit = registration["edit"]
                start = edit["start_byte"]
                plan["edit_span"] = [start, start + len(edit["inserted"].encode())]
            registrations[plan["case_id"]] = registration

    selection, cases = select(frame, pin)
    grids, records, attestations, eligible_ids = {}, [], [], {}
    drawn_cases = set(selection["case_ids"])
    for family, slots in groups:
        for plan in slots.values():
            case_id, fid = plan["case_id"], family["family_id"]
            cohort = "drawn" if case_id in drawn_cases else "undrawn"
            attestation = provenance_row(case_id, cohort, family=fid)
            attestation.update(problem_ids=[family["problem_id"], *family["problem_aliases"]],
                               implementation_ids=[family["implementation_origin"]],
                               generator_ids=[family["generator_id"], *family["generator_ancestors"]], prompts={})
            for version, source_pin in plan["source_hashes"].items():
                attestation["sources"][version]["raw_sha256"] = source_pin
            attestations.append(attestation)
    exposed = []
    for family, slot, plan in cases:
        case_id, fid = plan["case_id"], family["family_id"]
        registration = registrations[case_id]
        factory = eligible_grid if fid == eligible else make_grid
        grid = factory(family, slot, registration)
        grids[fid] = [{"seed": r["seed"], "n": r["n"], "sha256": digest(r["stdin"])} for r in grid]
        records.append({"case_id": case_id, "registration": registration, "grid": grid,
                        "review_sha256": commitment(["authored reviewer", case_id])})
        if fid == eligible:
            eligible_ids[slot] = case_id
        elif family["problem_id"] not in exposed:
            exposed.append(family["problem_id"])

    inputs = {"schema": INPUTS, "selection_sha256": commitment(selection), "families": grids}
    draw = build_draw(selection, cases, inputs)
    prior = provenance_row("authored-prior-exposure", "exposure")
    prior.update(problem_ids=exposed, prompts={})
    provenance = {"schema": PROVENANCE, "draw_sha256": commitment(draw), "representations": [],
                  "rows": [*attestations, prior]}
    quarantine = seal(draw, provenance)
    sources = {"schema": "eapg-synthetic-sources-v1", "draw_sha256": commitment(draw), "cases": records}
    return (pin, frame, inputs, draw, provenance, quarantine, sources), eligible_ids


def oracle_report(slot, sources, counting_sources, grid, growth, *, fail=False):
    return {"schema": "eapg-synthetic-operation-evidence-v1", "intended_slot": slot,
            "disposition": "output_failure" if fail else EXPECTED[slot],
            "source_sha256": {key: digest(text) for key, text in sources.items()},
            "counting_source_sha256": {key: digest(text) for key, text in counting_sources.items()},
            "grid_sha256": digest(json.dumps(grid, ensure_ascii=False, sort_keys=True, separators=(",", ":"))),
            "growth": growth, "per_seed": {}, "failures": [], "runs": [{"oracle_output": PRIVATE_OUTPUT}]}


def mock_profile(pipeline, source, grid, evidence, *, fail=False):
    if fail:
        return {"status": "normalization_failure"}, {
            "schema": PROJECTION_SCHEMA, "normalized_source": None, "normalized_source_sha256": None,
            "nodes": [], "seeds": {str(seed): {"status": "normalization_failure", "runs": []} for seed in SEEDS}}
    source_hash = digest(source)
    nodes = ["N1"]
    receipt = {"schema": "eapg-synthetic-profile-evidence-v1", "status": "profiled", "canonical_node_ids": nodes,
               "normalization": {"status": "CLEAN_COMPLETION", "normalized_source_sha256": source_hash}}
    projection = {"schema": PROJECTION_SCHEMA, "normalized_source": source, "normalized_source_sha256": source_hash,
                  "nodes": [{"id": "N1"}], "seeds": {str(seed): {"status": "eligible", "runs": [
                      {"n": r["n"], "status": "CLEAN_COMPLETION", "nodes": {"N1": {"cnt": r["n"], "work": r["n"]}}}
                      for r in grid if r["seed"] == seed]} for seed in SEEDS}}
    return receipt, projection


def mock_reference(pipeline, record):
    normalized = digest(record["edited"])
    return {"normalized_source_sha256": normalized, "canonical_nodes": [{"node_id": "N1"}],
            "accepted_node_ids": ["N1"], "reference_status": "resolved", "reference_reason": None}


class SyntheticStudyCustodianTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs, cls.eligible_ids = fixture()

    def test_undrawn_cases_are_required_for_provenance(self):
        for message, remove in (("Provenance must cover every frame case", True),
                                ("Provenance source version differs from frame", False)):
            with self.subTest(message=message):
                data = deepcopy(self.inputs)
                rows = data[4]["rows"]
                undrawn = next(row for row in rows if row["cohort"] == "undrawn")
                if remove:
                    rows.remove(undrawn)
                else:
                    undrawn["sources"]["original"]["raw_sha256"] = PIN
                data[5].clear()
                data[5].update(seal(data[3], data[4]))
                with self.assertRaisesRegex(ValueError, message):
                    custodian.validate_study(*data)

    def test_undrawn_bridge_quarantines_connected_drawn_family(self):
        data = deepcopy(self.inputs)
        rows = data[4]["rows"]
        eligible_id = self.eligible_ids["positive_at_site"]
        eligible = next(row for row in rows if row["row_id"] == eligible_id)
        exposure = next(row for row in rows if row["cohort"] == "exposure")
        bridge = next(row for row in rows if row["cohort"] == "undrawn")
        bridge["sources"]["original"]["template_sha256"] = eligible["sources"]["evaluated"]["template_sha256"]
        bridge["generator_ids"].extend(exposure["generator_ids"])
        data[5].clear()
        data[5].update(seal(data[3], data[4]))
        study = custodian.validate_study(*data)
        self.assertEqual(len(study.cases), 322)
        self.assertEqual(sum(not case.quarantined for case in study.cases), 0)
        component, = [component for component in data[5]["components"]
                      if any(row["row_id"] == bridge["row_id"] for row in component["rows"])]
        dispositions = {row["row_id"]: row["disposition"] for row in component["rows"]}
        self.assertEqual(dispositions[eligible_id], "quarantined")
        self.assertEqual(dispositions[bridge["row_id"]], "not_selected")

    def test_pinned_draw_rejects_invalid_late_rows_before_execution(self):
        self.assertEqual(len(self.inputs[3]["cases"]), 322)

        def change_provenance(data, mutation):
            mutation(data[4]["rows"][-2])
            updated = seal(data[3], data[4])
            data[5].clear()
            data[5].update(updated)

        for message, change in (
            ("Pinned draw", lambda data: data[3]["cases"][-1].update(workload_sha256=PIN)),
            ("Pinned quarantine", lambda data: data[5].update(provenance_sha256=PIN)),
            ("Registration differs", lambda data: data[6]["cases"][-1]["registration"].update(operation_inventory_sha256=PIN)),
            ("Input bytes", lambda data: data[6]["cases"][-1]["grid"][-1].update(stdin="17\r\n")),
            ("Input bytes", lambda data: data[6]["cases"][-3]["grid"][-1].update(stdin="17\r\n")),
            ("ordered draw", lambda data: data[6]["cases"].pop()),
            ("Provenance source version", lambda data: change_provenance(
                data, lambda r: r["sources"]["restored"].update(raw_sha256=PIN))),
            ("omits frame generator_ids", lambda data: change_provenance(data, lambda r: r["generator_ids"].pop())),
        ):
            with self.subTest(message=message):
                data = deepcopy(self.inputs)
                change(data)
                with patch.object(custodian, "verify_case") as verify, patch.object(custodian, "capture_case") as capture:
                    with self.assertRaisesRegex(ValueError, message):
                        custodian.validate_study(*data)
                verify.assert_not_called()
                capture.assert_not_called()

    def test_shared_trace_quarantine_failures_and_scoring(self):
        pipeline = SimpleNamespace(source_sha256=PIN, fit_dual_family_scaling=lambda sizes, counts: {})
        source_rows = {r["case_id"]: r for r in self.inputs[6]["cases"]}
        events = []

        def edited(slot):
            return source_rows[self.eligible_ids[slot]]["registration"]["sources"]["edited"]

        swap_source = edited(SWAP_SLOTS[0])
        appropriate = edited("appropriate_superlinear")

        def verify(slot, sources, counting_sources, grid, growth):
            events.append("verify")
            return oracle_report(slot, sources, counting_sources, grid, growth, fail=slot == "positive_at_site")

        def capture(candidate, source, grid, evidence):
            events.append("capture")
            return mock_profile(candidate, source, grid, evidence, fail=source == appropriate)

        def reference(candidate, record):
            events.append("reference")
            if record["edited"] == edited("positive_off_site"):
                raise ValueError("fixture reference cannot be resolved")
            return mock_reference(candidate, record)

        with patch.object(custodian, "verify_case", side_effect=verify) as verified, \
                patch.object(custodian, "capture_case", side_effect=capture) as captured, \
                patch.object(custodian, "resolve_intervention", side_effect=reference), \
                patch.object(custodian, "validate_single_statement"), \
                patch("builtins.open", side_effect=AssertionError("unexpected source or dataset read")), \
                patch("pathlib.Path.open", side_effect=AssertionError("unexpected source or dataset read")):
            validated = custodian.validate_study(*self.inputs)
            labels, receipts, blind = custodian.run_study(pipeline, validated)

        self.assertCountEqual([call.args[0] for call in verified.call_args_list], [*CORE_SLOTS, *SWAP_SLOTS])
        self.assertEqual(sum(call.args[1] == swap_source for call in captured.call_args_list), 1)
        self.assertEqual(captured.call_count, 4)
        self.assertEqual(events, ["verify"] * 6 + ["reference"] * 2 + ["capture"] * 4)
        self.assertIn("authored private oracle output", json.dumps(receipts))

        expected_ids = [r["case_id"] for r in self.inputs[3]["cases"]]
        by_id = {r["case_id"]: r for r in labels["cases"]}
        self.assertEqual(list(by_id), expected_ids)
        self.assertEqual(sum(r["disposition"] == "quarantined" for r in by_id.values()), 316)
        at_site, off_site = (self.eligible_ids[slot] for slot in ("positive_at_site", "positive_off_site"))
        self.assertEqual(by_id[at_site]["disposition"], "output_failure")
        self.assertEqual(by_id[off_site]["disposition"], "confirmed_positive")
        self.assertEqual(by_id[off_site]["reference_status"], "unresolved")
        self.assertTrue(by_id[off_site]["reference_reason"])

        self.assertEqual(set(blind), {"schema", "draw_sha256", "labels_sha256", "pipeline_sha256", "cases"})
        self.assertEqual(blind["schema"], "eapg-synthetic-blind-packet-v1")
        self.assertEqual(blind["labels_sha256"], commitment(labels))
        self.assertEqual([r["case_id"] for r in blind["cases"]], sorted(expected_ids))
        self.assertTrue(all(set(r) == {"case_id", "projection"} for r in blind["cases"]))
        projections = {r["case_id"]: r["projection"] for r in blind["cases"]}
        swap_positive, swap_sham = (self.eligible_ids[slot] for slot in SWAP_SLOTS)
        self.assertEqual(projections[swap_positive], projections[swap_sham])
        self.assertIsNotNone(projections[swap_positive])
        self.assertIsNone(projections[self.eligible_ids["appropriate_superlinear"]])
        receipts_by_id = {r["case_id"]: r for r in receipts}
        self.assertEqual(receipts_by_id[swap_sham]["trace"], {"reused_from_case_id": swap_positive})
        for pid, row in by_id.items():
            if row["disposition"] == "quarantined" or pid == at_site:
                self.assertIsNone(projections[pid])
        serialized = json.dumps(blind)
        for private in ("authored private oracle output", "expected_counts", "family_id", "disposition",
                        "accepted_node_ids", "reference_status", "restored", "source_manifest_sha256",
                        "cursor = 1;", "cursor = 2;"):
            self.assertNotIn(private, serialized)

        def rank(candidate, normalized, profile, seed):
            arms = {name: arm("N1", ["N1"], ["N1"], alert=True) for name in ARM_IDS}
            arms["hit_growth"] = arm(None, ["N1"], ["N1"])
            return {"seed": seed, "normalized_source_sha256": digest(normalized), "profile_status": "complete", "arms": arms}

        predictions = []
        with patch("synthetic_trace.predict_seed", side_effect=rank):
            for pid, projection in projections.items():
                rows = predict_case(pipeline, projection) if projection else [
                    {"seed": seed, "normalized_source_sha256": None, "profile_status": "not_run",
                     "arms": {name: arm(None, [], [], status="not_run") for name in ARM_IDS}} for seed in SEEDS]
                predictions.extend(dict(row, case_id=pid) for row in rows)
        ledger = {"schema": "eapg-synthetic-predictions-v1", "draw_sha256": blind["draw_sha256"],
                  "labels_sha256": blind["labels_sha256"], "runner_sha256": PIN, "pipeline_sha256": PIN,
                  "baseline_sha256": PIN, "arm_ids": list(ARM_IDS), "predictions": predictions}
        joined = join(self.inputs[3], labels, ledger, blind["draw_sha256"], blind["labels_sha256"])
        for rows in joined.values():
            self.assertEqual([r["case_id"] for r in rows], expected_ids)
            rows_by_id = {r["case_id"]: r for r in rows}
            self.assertEqual(rows_by_id[swap_positive]["arms"], rows_by_id[swap_sham]["arms"])
            self.assertEqual(rows_by_id[swap_positive]["disposition"], "confirmed_positive")
            self.assertEqual(rows_by_id[swap_sham]["disposition"], "confirmed_sham")


if __name__ == "__main__":
    unittest.main()
