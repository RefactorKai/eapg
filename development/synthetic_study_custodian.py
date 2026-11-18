"""Replay registrations, verify cases, and seal blinded synthetic study inputs."""

import argparse
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
import subprocess

from run_phase2_development import ProfileFailure, load_module, provenance as runtime_provenance
from score_synthetic import CONFIRMED, digest, exact_keys, index, require, validate_label
from synthetic_frame import SWAP_SLOTS, build_draw, canonical, commitment, read_canonical, select
from synthetic_intervention import changed_tokens, code_tokens, covered, resolve_intervention, single_owner, verify_splice
from synthetic_oracle import SIDES, text_map, valid_grid, verify_case
from synthetic_quarantine import FRAME_COHORTS, seal
from synthetic_trace import EARLY_STATUSES, capture_case, prediction_rows


HERE = Path(__file__).resolve().parent
SOURCE_SCHEMA = "eapg-synthetic-sources-v1"
PACKET_SCHEMA = "eapg-synthetic-blind-packet-v1"
IDENTITY_FIELDS = (
    ("problem_ids", "problem_id", "problem_aliases"),
    ("implementation_ids", "implementation_origin", None),
    ("generator_ids", "generator_id", "generator_ancestors"),
)


@dataclass(frozen=True, slots=True)
class Case:
    design: dict
    family_id: str
    quarantined: bool
    registration: dict
    grid: list
    edit: dict | None
    review_sha256: str


@dataclass(frozen=True, slots=True)
class Study:
    draw_sha256: str
    source_sha256: str
    quarantine_sha256: str
    cases: tuple[Case, ...]


def raw_digest(text):
    return sha256(text.encode("utf-8")).hexdigest()


def validate_frame_attestation(family, plan, attestation):
    case_id = plan["case_id"]
    require(attestation["registered_family_id"] == family["family_id"], f"Provenance family differs from frame for {case_id}")
    for field, main_key, related_key in IDENTITY_FIELDS:
        primary = family[main_key]
        related = family[related_key] if related_key else []
        known = {value for value in [primary, *(related or [])] if value is not None}
        require(known <= set(attestation[field]), f"Provenance omits frame {field} for {case_id}")
        require((primary is not None and related is not None) or attestation["unknown_provenance_reason"],
                f"Unknown frame {field} must remain explicit for {case_id}")
    for version, expected in plan["source_hashes"].items():
        require(attestation["sources"][version]["raw_sha256"] == expected,
                f"Provenance source version differs from frame for {case_id}")


def validate_registration(family, slot, plan, row, planned_grid):
    case_id = row["case_id"]
    registration, grid = row["registration"], row["grid"]
    exact_keys(registration, "sources counting_sources growth edit equivalent_edited_intervals operation_inventory_sha256",
               f"registration for {case_id}")
    require(commitment(registration) == plan["registration_sha256"], f"Registration differs from frame for {case_id}")
    require(digest(row["review_sha256"]) and digest(registration["operation_inventory_sha256"]),
            f"Missing independent review or operation inventory pin for {case_id}")
    require(text_map(registration["sources"]) and text_map(registration["counting_sources"]),
            f"Missing UTF-8 source variants for {case_id}")
    sources = registration["sources"]
    source_digests = {side: raw_digest(sources[side]) for side in SIDES}
    frame_digests = dict(plan["source_hashes"])
    frame_digests["edited"] = frame_digests.pop("evaluated")
    require(source_digests == frame_digests, f"Raw source versions differ from frame for {case_id}")

    require(valid_grid(grid), f"Invalid committed input grid for {case_id}")
    input_pins = [{"seed": item["seed"], "n": item["n"], "sha256": raw_digest(item["stdin"])} for item in grid]
    require(input_pins == planned_grid, f"Input bytes or coordinates differ from input manifest for {case_id}")
    expected_band = {"same_growth_sham": "same", "comparator_swap_sham": "same",
                     "appropriate_superlinear": "appropriate"}.get(slot, plan.get("band", "strong"))
    growth = registration["growth"]
    require(isinstance(growth, dict) and growth.get("band") == expected_band, f"Growth band differs from frame for {case_id}")
    intervals = registration["equivalent_edited_intervals"]
    if slot == "appropriate_superlinear":
        require(registration["edit"] is None and intervals == [], f"Appropriate control contains an edit for {case_id}")
        return None
    edit = {"schema": "eapg-synthetic-intervention-v1", **sources, "source_sha256": source_digests,
            "edit": registration["edit"], "equivalent_edited_intervals": intervals}
    if slot == "positive_off_site":
        patch = registration["edit"]
        exact_keys(patch, "start_byte removed inserted", f"off-site edit for {case_id}")
        start, inserted = patch["start_byte"], patch["inserted"]
        require(type(start) is int and type(inserted) is str and start >= 0, f"Invalid off-site edit span for {case_id}")
        edited_size = len(sources["edited"].encode("utf-8"))
        require([start, start + len(inserted.encode("utf-8"))] == plan["edit_span"]
                and plan["intended_statement_span"][1] <= edited_size and plan["edit_span"][1] <= edited_size,
                f"Off-site edit or intended statement span differs from frame for {case_id}")
    return edit


def validate_study(protocol_sha256, frame, inputs, draw, provenance, quarantine, sources):
    """Verify the entire committed draw before returning executable inputs."""
    selection, planned = select(frame, protocol_sha256)
    require(build_draw(selection, planned, inputs) == draw, "Pinned draw does not replay from the frame and inputs")
    draw_sha = commitment(draw)
    require(seal(draw, provenance) == quarantine, "Pinned quarantine does not replay from the draw and provenance")
    require(quarantine["representations"] == [], "This runner implements the registered CPU arms")
    exact_keys(sources, "schema draw_sha256 cases", "source manifest")
    require(sources["schema"] == SOURCE_SCHEMA and sources["draw_sha256"] == draw_sha, "Source manifest draw mismatch")
    rows = index(sources["cases"], "case_id registration grid review_sha256", "source manifest")
    require(list(rows) == selection["case_ids"], "Source manifest must cover the ordered draw exactly")
    attestations = {row["row_id"]: row for row in provenance["rows"] if row["cohort"] in FRAME_COHORTS}
    frame_plans = {plan["case_id"]: (family, plan) for family in frame["families"] for plan in family["slots"].values()}
    frame_plans.update({plan["case_id"]: (family, plan) for family, _, plan in planned})
    require(attestations.keys() == frame_plans.keys(), "Provenance must cover every frame case and both swap cases exactly")
    for case_id, (family, plan) in frame_plans.items():
        validate_frame_attestation(family, plan, attestations[case_id])
    membership = {row["row_id"]: (component["family_id"], row["disposition"])
                  for component in quarantine["components"] for row in component["rows"] if row["cohort"] == "drawn"}

    cases = []
    for (family, slot, plan), design in zip(planned, draw["cases"], strict=True):
        case_id = design["case_id"]
        require(re.fullmatch(r"[0-9a-f]{24,64}", case_id), f"Expected an opaque hexadecimal case ID for {case_id}")
        row = rows[case_id]
        edit = validate_registration(family, slot, plan, row, inputs["families"][family["family_id"]])
        family_id, disposition = membership[case_id]
        cases.append(Case(design, family_id, disposition == "quarantined", row["registration"], row["grid"],
                          edit, row["review_sha256"]))
    swap = [case for case in cases if case.design["intended_slot"] in SWAP_SLOTS]
    require(len(swap) == 2 and swap[0].family_id == swap[1].family_id, "Comparator swap must share a final family")
    grid_keys = ("seed", "n", "stdin", "expected_stdout")
    common = [[tuple(row[key] for key in grid_keys) for row in case.grid] for case in swap]
    require(common[0] == common[1], "Comparator swap has different inputs or task outputs")
    return Study(draw_sha, commitment(sources), commitment(quarantine), tuple(deepcopy(cases)))


def validate_single_statement(pipeline, edit):
    original, evaluated, orig_span, edit_span = verify_splice(edit)
    original_tokens, evaluated_tokens = (code_tokens(pipeline.parser, source) for source in (original, evaluated))
    before, changed = changed_tokens(covered(original_tokens, orig_span), covered(evaluated_tokens, edit_span))
    require(changed and single_owner(before) and single_owner(changed),
            "Expected a nontrivia change within one expression or statement")
    for span in edit["equivalent_edited_intervals"]:
        require(span[0] <= changed[0].start_byte and changed[-1].end_byte <= span[1]
                and covered(evaluated_tokens, span) == changed, "Equivalent raw interval identifies different tokens")


def verify_operation(pipeline, case):
    if case.edit is not None:
        try:
            validate_single_statement(pipeline, case.edit)
        except ValueError as error:
            return {"disposition": "invalid_source", "reason": str(error)}
    registration = case.registration
    return verify_case(case.design["intended_slot"], registration["sources"], registration["counting_sources"],
                       case.grid, registration["growth"])


def map_reference(pipeline, case):
    try:
        return resolve_intervention(pipeline, case.edit)
    except ProfileFailure as error:
        return {"reference_status": "unresolved", "reference_reason": "reference_preprocessing_failure",
                "details": error.details}
    except ValueError as error:
        return {"reference_status": "unresolved", "reference_reason": "reference_mapping_failure", "details": str(error)}
    except RuntimeError as error:
        if str(error) != "Normalized source contains a tree-sitter error":
            raise
        return {"reference_status": "unresolved", "reference_reason": "reference_parser_failure"}


def canonical_binding(reference, projection):
    normalized = reference.get("normalized_source_sha256")
    ids = [node["node_id"] for node in reference.get("canonical_nodes", [])]
    if projection is not None and projection["normalized_source_sha256"] is not None:
        trace_sha = projection["normalized_source_sha256"]
        trace_ids = [node["id"] for node in projection["nodes"]]
        require(normalized is None or (normalized == trace_sha and ids == trace_ids), "Reference and trace disagree on canonical source")
        normalized, ids = trace_sha, trace_ids
    return normalized, ids


def run_study(pipeline, validated, *, observe=None):
    """Return private labels and receipts plus an independently sealable blind packet."""
    labels, receipts, blind = [], [], []
    operations, references = {}, {}
    for case in validated.cases:
        if case.quarantined:
            continue
        case_id = case.design["case_id"]
        operations[case_id] = verify_operation(pipeline, case)
        if observe is not None:
            observe(case_id, "operation", operations[case_id])
    for case in validated.cases:
        case_id = case.design["case_id"]
        if operations.get(case_id, {}).get("disposition") != "confirmed_positive":
            continue
        references[case_id] = map_reference(pipeline, case)
        if observe is not None:
            observe(case_id, "reference", references[case_id])
    swap_capture = None
    for case in validated.cases:
        design = case.design
        case_id, slot = design["case_id"], design["intended_slot"]
        operation = operations.get(case_id, {})
        disposition = operation.get("disposition", "quarantined")
        reference = references.get(case_id, {})
        private_trace, projection = None, None
        if disposition in CONFIRMED:
            if slot in SWAP_SLOTS and swap_capture is not None:
                owner, projection = swap_capture
                private_trace = {"reused_from_case_id": owner}
            else:
                private_trace, projection = capture_case(pipeline, case.registration["sources"]["edited"], case.grid, operation)
                prediction_rows(projection)
                if slot in SWAP_SLOTS:
                    swap_capture = case_id, projection
            if observe is not None:
                observe(case_id, "profile", private_trace)
        normalized, canonical_ids = canonical_binding(reference, projection)
        label = {"case_id": case_id, "family_id": case.family_id, "disposition": disposition,
                 "normalized_source_sha256": normalized, "canonical_node_ids": canonical_ids,
                 "accepted_node_ids": reference.get("accepted_node_ids", []),
                 "reference_status": reference.get("reference_status"), "reference_reason": reference.get("reference_reason"),
                 "operation_evidence_sha256": commitment(operation) if operation else None}
        validate_label(design, label)
        labels.append(label)
        receipts.append({"case_id": case_id, "review_sha256": case.review_sha256,
                         "operation": operation or None, "reference": reference or None, "trace": private_trace})
        if projection is not None and all(seed["status"] in EARLY_STATUSES for seed in projection["seeds"].values()):
            projection = None
        blind.append({"case_id": case_id, "projection": projection})

    label_ledger = {"schema": "eapg-synthetic-labels-v1", "draw_sha256": validated.draw_sha256,
                    "source_manifest_sha256": validated.source_sha256, "quarantine_sha256": validated.quarantine_sha256,
                    "cases": labels}
    packet = {"schema": PACKET_SCHEMA, "draw_sha256": validated.draw_sha256, "labels_sha256": commitment(label_ledger),
              "pipeline_sha256": pipeline.source_sha256, "cases": sorted(blind, key=lambda row: row["case_id"])}
    return label_ledger, receipts, packet


def custodian_revision():
    files = (
        "synthetic_study_custodian.py", "synthetic_frame.py", "synthetic_quarantine.py", "synthetic_intervention.py",
        "synthetic_oracle.py", "synthetic_trace.py", "synthetic_arms.py", "backward_slice.py", "score_synthetic.py",
        "score_external.py", "replay_pilot_contrast.py", "run_phase2_development.py", "gate1_sandbox.py",
        "probe_gate1.py", "build_reference_packet.py", "reference_adjudication.py",
        "../artifacts/phase2_data/run_development.py", "../artifacts/phase1_correction/phase2_custody_and_probes.py",
    )
    return commitment({name: sha256((HERE / name).read_bytes()).hexdigest() for name in files})


def runtime_receipt(pipeline):
    runtime = runtime_provenance(pipeline)
    for command in ("bwrap", "systemctl"):
        result = subprocess.run([command, "--version"], capture_output=True, check=True, text=True, timeout=5)
        runtime[command] = result.stdout.splitlines()[0]
    return runtime


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    mode = cli.add_mutually_exclusive_group()
    mode.add_argument("--print-revision", action="store_true")
    mode.add_argument("--print-runtime", action="store_true")
    manifests = ("frame", "inputs", "draw", "provenance", "quarantine", "sources")
    for name in (*manifests, "protocol", "pipeline"):
        cli.add_argument(f"--{name}", type=Path)
        cli.add_argument(f"--{name}-sha256")
    cli.add_argument("--runner-sha256")
    cli.add_argument("--runtime-sha256")
    cli.add_argument("--output", type=Path, help="fresh private directory")
    args = cli.parse_args()
    try:
        revision = custodian_revision()
        if args.print_revision:
            print(revision)
            return
        require(args.pipeline is not None and digest(args.pipeline_sha256), "Require pinned candidate pipeline")
        if args.print_runtime:
            pipeline = load_module("custodian_pipeline", args.pipeline, args.pipeline_sha256)
            print(commitment(runtime_receipt(pipeline)))
            return
        require(revision == args.runner_sha256, "Custodian runner revision mismatch")
        require(args.output is not None and not args.output.exists() and args.output.parent.is_dir(),
                "Require a new private output directory")
        pins = vars(args)
        require(all(pins[name] is not None and digest(pins[f"{name}_sha256"]) for name in (*manifests, "protocol")),
                "Require paths and out-of-band pins for the protocol and all manifests")
        require(sha256(args.protocol.read_bytes()).hexdigest() == args.protocol_sha256, "Protocol digest mismatch")
        validated = validate_study(args.protocol_sha256, *(read_canonical(pins[name], pins[f"{name}_sha256"]) for name in manifests))
        pipeline = load_module("custodian_pipeline", args.pipeline, args.pipeline_sha256)
        runtime = runtime_receipt(pipeline)
        require(commitment(runtime) == args.runtime_sha256, "Custodian runtime revision mismatch")
        args.output.mkdir(mode=0o700)
        stages = args.output / "stages"
        stages.mkdir(mode=0o700)

        def archive_stage(case_id, stage, value):
            with (stages / f"{case_id}.{stage}.json").open("xb") as stream:
                stream.write(canonical(value))

        labels, receipts, packet = run_study(pipeline, validated, observe=archive_stage)
        private = {"schema": "eapg-synthetic-private-evidence-v1", "draw_sha256": validated.draw_sha256,
                   "source_manifest_sha256": validated.source_sha256, "runner_sha256": revision,
                   "runtime": runtime, "cases": receipts}
        for name, value in (("evidence.json", private), ("labels.json", labels), ("blind.json", packet)):
            with (args.output / name).open("xb") as stream:
                stream.write(canonical(value))
            print(f"{commitment(value)}  {name}")
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        cli.error(str(error))


if __name__ == "__main__":
    main()
