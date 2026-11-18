"""Capture custodian-only execution receipts and project blind prediction inputs.

Pass `capture_case` the evaluated source, committed oracle grid, and verified
`synthetic_oracle.verify_case` report from the private ledger. Seal the first
return value privately. Only the second return value is a prediction packet.
Pin that packet externally before handing it to `predict_case`.
"""

from base64 import b64encode
from hashlib import sha256
import json
from time import perf_counter_ns

from gate1_sandbox import MAX_SCALE, execute
from run_phase2_development import ProfileFailure, compile_instrumented, normalize, process_status, validate_counter
from score_synthetic import CONFIRMED, SEEDS
from synthetic_arms import ARM_IDS, arm, predict_seed
from synthetic_oracle import utf8, valid_grid


SCHEMA = "eapg-synthetic-trace-projection-v1"
NODE_FIELDS = frozenset(("id", "role", "parent", "normalized_span", "defs", "uses", "source_preview",
                         "direct_call_targets", "control_uses", "is_state_reset", "is_unidirectional_step",
                         "in_nested_branch"))
EARLY_STATUSES = {"invalid_input", "oracle_unverified", "normalization_failure", "canonical_map_failure",
                  "instrumentation_failure"}


def complete_grid(sizes):
    return len(sizes) >= 4 and sizes[-1] >= 8 * sizes[0]


def capture_case(pipeline, source, grid, operation_evidence):
    """Return the private profile receipt and separate blind projection.

    A resource or transport failure in one sandbox receipt cannot censor other
    sizes. Missing isolation receipts raise in the launcher and stop the study.
    """
    receipt = {"schema": "eapg-synthetic-profile-evidence-v1", "normalization": None, "build": None, "runs": []}
    packet = {"schema": SCHEMA, "normalized_source": None, "normalized_source_sha256": None, "nodes": [],
              "seeds": {str(seed): {"status": "not_run", "runs": []} for seed in SEEDS}}

    def stop(status, stage, details):
        receipt["status"] = status
        receipt[stage] = details
        for seed in packet["seeds"].values():
            seed["status"] = status
        return receipt, packet

    if not valid_grid(grid) or not utf8(source) or not source:
        return stop("invalid_input", "input", {"reason": "invalid_evaluated_source_or_grid"})
    source_digest = sha256(source.encode("utf-8")).hexdigest()
    grid_digest = sha256(json.dumps(grid, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()
    receipt.update(evaluated_source_sha256=source_digest, grid_sha256=grid_digest)
    if (not isinstance(operation_evidence, dict)
            or operation_evidence.get("schema") != "eapg-synthetic-operation-evidence-v1"
            or type(disposition := operation_evidence.get("disposition")) is not str or disposition not in CONFIRMED
            or operation_evidence.get("grid_sha256") != grid_digest
            or not isinstance(sources := operation_evidence.get("source_sha256"), dict)
            or sources.get("edited") != source_digest):
        return stop("oracle_unverified", "input", {"reason": "unconfirmed_or_mismatched_oracle_evidence"})

    try:
        normalized, aliases = normalize(pipeline, source)
    except ProfileFailure as error:
        return stop("normalization_failure", "normalization", error.details)
    except (ValueError, RecursionError) as error:
        return stop("normalization_failure", "normalization", {"message": str(error)})
    except RuntimeError as error:
        # Older normalize() reports a parser error with the same exception class as the launcher.
        if str(error) != "Normalized source contains a tree-sitter error":
            raise
        return stop("normalization_failure", "normalization", {"message": str(error)})

    digest = sha256(normalized.encode("utf-8")).hexdigest()
    receipt["normalization"] = {"status": "CLEAN_COMPLETION", "normalized_source_sha256": digest}
    try:
        nodes = pipeline.extract_macro_nodes(normalized, aliases)
        ids = [node["id"] for node in nodes]
        if ids != [f"N{i}" for i in range(1, len(nodes) + 1)]:
            raise ValueError("Invalid canonical node order")
    except (KeyError, ValueError, RecursionError) as error:
        return stop("canonical_map_failure", "canonical_map", {"message": str(error)})
    receipt["canonical_node_ids"] = ids
    packet.update(normalized_source=normalized, normalized_source_sha256=digest,
                  nodes=[{key: value for key, value in node.items() if key in NODE_FIELDS} for node in nodes])
    try:
        binary = compile_instrumented(pipeline, normalized, nodes)
    except ProfileFailure as error:
        return stop("instrumentation_failure", "build", error.details)
    except (ValueError, RecursionError) as error:
        return stop("instrumentation_failure", "build", {"message": str(error)})
    receipt["build"] = {"status": "CLEAN_COMPLETION", "executable_sha256": sha256(binary).hexdigest()}

    for row in grid:
        seed, n = row["seed"], row["n"]
        data = row["stdin"].encode("utf-8")
        expected = row["expected_stdout"].encode("utf-8")
        started = perf_counter_ns()
        result = execute(binary, data, counter_scale=n)
        elapsed = perf_counter_ns() - started
        execution = {"seed": seed, "n": n, "launcher_elapsed_ns": elapsed, "input_sha256": sha256(data).hexdigest(),
                     "expected_stdout_sha256": sha256(expected).hexdigest(), "process_status": process_status(result),
                     "returncode": result.returncode, "timed_out": result.timed_out, "events": result.events,
                     "stdout_b64": b64encode(result.stdout).decode("ascii"),
                     "stderr_b64": b64encode(result.stderr).decode("ascii"),
                     "counter_wire_b64": b64encode(result.counter_wire).decode("ascii")}
        try:
            counters = validate_counter(result, nodes, pipeline.compute_tick_ceiling(n))
        except ProfileFailure as error:
            execution.update(status=error.details["status"], message=error.details["message"])
        else:
            execution.update(status=counters["status"], total_ticks=counters["total_ticks"])
            if counters["status"] == "CLEAN_COMPLETION":
                if result.stdout != expected:
                    execution["status"] = "OUTPUT_MISMATCH"
                else:
                    packet["seeds"][str(seed)]["runs"].append(
                        {"n": n, "status": "CLEAN_COMPLETION", "nodes": counters["nodes"]}
                    )
        receipt["runs"].append(execution)

    receipt["status"] = "profiled"
    for seed in packet["seeds"].values():
        sizes = [row["n"] for row in seed["runs"]]
        seed["status"] = "eligible" if complete_grid(sizes) else "insufficient_clean_rows"
    return receipt, packet


def prediction_rows(packet):
    """Validate the projection's boundary and return the committed seed rows."""
    if (type(packet) is not dict
            or packet.keys() != {"schema", "normalized_source", "normalized_source_sha256", "nodes", "seeds"}
            or packet["schema"] != SCHEMA):
        raise ValueError("Invalid prediction projection schema")
    source, digest, nodes = (packet[key] for key in ("normalized_source", "normalized_source_sha256", "nodes"))
    if type(nodes) is not list or any(type(node) is not dict or "id" not in node or node.keys() - NODE_FIELDS
                                     for node in nodes):
        raise ValueError("Invalid canonical nodes in prediction projection")
    ids = [node["id"] for node in nodes]
    if ids != [f"N{i}" for i in range(1, len(nodes) + 1)]:
        raise ValueError("Invalid canonical node order in prediction projection")
    if source is None:
        if digest is not None or nodes:
            raise ValueError("Unavailable source cannot have canonical evidence")
    elif not utf8(source) or not source or digest != sha256(source.encode("utf-8")).hexdigest():
        raise ValueError("Normalized source digest mismatch in prediction projection")
    seeds = packet["seeds"]
    if type(seeds) is not dict or seeds.keys() != {str(seed) for seed in SEEDS}:
        raise ValueError("Wrong seed coverage in prediction projection")
    for seed in seeds.values():
        if type(seed) is not dict or seed.keys() != {"status", "runs"} or type(seed["runs"]) is not list:
            raise ValueError("Invalid seed evidence in prediction projection")
        status, rows = seed["status"], seed["runs"]
        sizes = []
        for row in rows:
            if (type(row) is not dict or row.keys() != {"n", "status", "nodes"} or row["status"] != "CLEAN_COMPLETION"
                    or type(row["n"]) is not int or not 0 < row["n"] <= MAX_SCALE
                    or type(row["nodes"]) is not dict or row["nodes"].keys() != set(ids)
                    or any(type(count) is not dict or count.keys() != {"cnt", "work"}
                           or any(type(n) is not int or n < 0 for n in count.values())
                           for count in row["nodes"].values())):
                raise ValueError("Invalid clean counter row in prediction projection")
            sizes.append(row["n"])
        if sizes != sorted(set(sizes)):
            raise ValueError("Duplicate or unordered clean sizes in prediction projection")
        tested = digest is not None and status == ("eligible" if complete_grid(sizes) else "insufficient_clean_rows")
        if not tested and (rows or type(status) is not str or status not in EARLY_STATUSES):
            raise ValueError("Invalid seed disposition in prediction projection")
    return seeds


def predict_case(pipeline, projection):
    """Produce scorer rows from a sealed projection, without launching programs."""
    seeds = prediction_rows(projection)
    digest, nodes = projection["normalized_source_sha256"], projection["nodes"]
    predictions = []
    for seed in SEEDS:
        key = str(seed)
        status, rows = seeds[key]["status"], seeds[key]["runs"]
        if status != "eligible":
            predictions.append({"seed": seed, "normalized_source_sha256": digest, "profile_status": status,
                                "arms": {name: arm(None, [], [], status=status) for name in ARM_IDS}})
            continue
        sizes = [row["n"] for row in rows]
        fits = {node["id"]: {
            channel: pipeline.fit_dual_family_scaling(sizes, [row["nodes"][node["id"]][field] for row in rows])
            for channel, field in (("fit_hits", "cnt"), ("fit_work", "work"))
        } for node in nodes}
        profile = {"normalized_sha256": digest, "nodes": nodes, "runs": {key: rows}, "fits": {key: fits}}
        predictions.append(predict_seed(pipeline, projection["normalized_source"], profile, seed))
    return predictions
