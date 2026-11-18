"""Score blind trace projections using a preregistered local prediction bundle.

Run with --print-revision before registration. At prediction time, provide the
independently recorded bundle, pipeline, and packet pins. Pass only the blind
packet to this operator. The draw and label hashes are opaque ledger links.
"""

import argparse
from hashlib import sha256
from pathlib import Path
import re

from run_phase2_development import load_module
from score_synthetic import SEEDS, digest, exact_keys, require
from synthetic_arms import ARM_IDS, arm
from synthetic_frame import canonical, commitment, read_canonical
from synthetic_trace import predict_case, prediction_rows


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "eapg-synthetic-blind-packet-v1"
BASELINE = "development/backward_slice.py"
CODE = (
    f"development/{Path(__file__).name}", BASELINE,
    *(f"development/{name}.py" for name in (
        "gate1_sandbox", "probe_gate1", "replay_pilot_contrast", "run_phase2_development",
        "score_external", "score_synthetic", "synthetic_arms", "synthetic_frame", "synthetic_oracle", "synthetic_trace",
    )),
    "artifacts/phase2_data/run_development.py",
)
CASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
NODE_ROLES = {"FUNCTION_ENTRY", "CALL", "STATE_UPD", "BRANCH", "LOOP"}


def code_manifest():
    return {name: sha256((ROOT / name).read_bytes()).hexdigest() for name in CODE}


def prediction_revision():
    """Compute the local operator bundle digest without an input packet."""
    return commitment(code_manifest())


def validate_projection(projection):
    seeds = prediction_rows(projection)
    require(all(seed["status"] != "oracle_unverified" for seed in seeds.values()),
            "Private oracle disposition in blind projection; use null")
    nodes = projection["nodes"]
    parents = {node["id"] for node in nodes} | {"MAIN_SCOPE", None}
    source_size = len((projection["normalized_source"] or "").encode("utf-8"))
    for node in nodes:
        if "role" in node:
            require(type(node["role"]) is str and node["role"] in NODE_ROLES, "Invalid canonical node role")
        if "parent" in node:
            parent = node["parent"]
            require((parent is None or type(parent) is str) and parent in parents, "Invalid canonical node parent")
        if "source_preview" in node:
            require(type(node["source_preview"]) is str, "Invalid canonical node preview")
        for key in ("defs", "uses", "control_uses"):
            if key in node:
                require(type(node[key]) is list and all(type(name) is str for name in node[key]),
                        "Invalid canonical node binding names")
        for key in ("is_state_reset", "is_unidirectional_step", "in_nested_branch"):
            if key in node:
                require(type(node[key]) is bool, "Invalid canonical node flag")
        if "direct_call_targets" in node:
            targets = node["direct_call_targets"]
            require(type(targets) is list and all(type(value) is int and 0 <= value < source_size for value in targets),
                    "Invalid canonical direct call targets")
        if "normalized_span" in node:
            span = node["normalized_span"]
            require(type(span) in (list, tuple) and len(span) == 2 and all(type(value) is int for value in span)
                    and 0 <= span[0] < span[1] <= source_size, "Invalid canonical node span")


def validate_packet(packet, pipeline_sha256):
    exact_keys(packet, "schema draw_sha256 labels_sha256 pipeline_sha256 cases", "blind packet")
    require(packet["schema"] == SCHEMA, "Wrong blind packet schema")
    require(all(digest(packet[key]) for key in ("draw_sha256", "labels_sha256", "pipeline_sha256")),
            "Invalid blind packet ledger link")
    require(packet["pipeline_sha256"] == pipeline_sha256, "Blind packet pipeline pin mismatch")
    require(type(packet["cases"]) is list and packet["cases"], "Expected an ordered blind packet case list")
    seen = set()
    for row in packet["cases"]:
        exact_keys(row, "case_id projection", "blind case")
        case_id = row["case_id"]
        require(type(case_id) is str and CASE_ID.fullmatch(case_id), "Invalid blind case ID")
        require(case_id not in seen, "Duplicate blind case ID")
        seen.add(case_id)
        if row["projection"] is not None:
            validate_projection(row["projection"])


def predict_study(pipeline, packet, runner_sha256):
    """Build the scorer ledger in packet order using the preregistered runner."""
    manifest = code_manifest()
    require(digest(runner_sha256) and commitment(manifest) == runner_sha256, "Prediction runner digest mismatch")
    validate_packet(packet, getattr(pipeline, "source_sha256", None))
    rows = []
    for case in packet["cases"]:
        projection = case["projection"]
        if projection is None:
            predictions = [{"seed": seed, "normalized_source_sha256": None, "profile_status": "unavailable",
                            "arms": {name: arm(None, [], [], status="unavailable") for name in ARM_IDS}}
                           for seed in SEEDS]
        else:
            predictions = predict_case(pipeline, projection)
        rows.extend({"case_id": case["case_id"], **pred} for pred in predictions)
    return {"schema": "eapg-synthetic-predictions-v1", "draw_sha256": packet["draw_sha256"],
            "labels_sha256": packet["labels_sha256"], "runner_sha256": runner_sha256,
            "pipeline_sha256": packet["pipeline_sha256"], "baseline_sha256": manifest[BASELINE],
            "arm_ids": list(ARM_IDS), "predictions": rows}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--print-revision", action="store_true", help="print this local operator's bundle SHA-256")
    cli.add_argument("--packet", type=Path)
    cli.add_argument("--packet-sha256")
    cli.add_argument("--pipeline", type=Path)
    cli.add_argument("--pipeline-sha256")
    cli.add_argument("--runner-sha256")
    cli.add_argument("--output", type=Path)
    args = cli.parse_args()
    options = (args.packet, args.packet_sha256, args.pipeline, args.pipeline_sha256, args.runner_sha256, args.output)
    try:
        if args.print_revision:
            require(not any(value is not None for value in options), "Use --print-revision on its own")
            print(prediction_revision())
            return
        require(all(value is not None for value in options), "Provide packet, pipeline, all three pins, and output")
        require(digest(args.runner_sha256) and prediction_revision() == args.runner_sha256,
                "Prediction runner digest mismatch")
        require(digest(args.pipeline_sha256), "Invalid registered pipeline digest")
        require(not args.output.exists(), "Prediction output already exists")
        packet = read_canonical(args.packet, args.packet_sha256)
        validate_packet(packet, args.pipeline_sha256)
        pipeline = load_module("eapg_synthetic_prediction_pipeline", args.pipeline, expected=args.pipeline_sha256)
        raw = canonical(predict_study(pipeline, packet, args.runner_sha256))
        with args.output.open("xb") as stream:
            stream.write(raw)
    except (OSError, ValueError) as error:
        cli.error(str(error))
    print(f"{sha256(raw).hexdigest()}  {args.output.name}")


if __name__ == "__main__":
    main()
