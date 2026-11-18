# Synthetic study runbook

The CPU workflow uses three separate commands. The custodian verifies the precommitted cases and seals the label ledger. The prediction operator sees the blinded packet. The scorer checks both sealed ledgers and the precommitted software pins before joining. Use the [prospective protocol](PROSPECTIVE_SYNTHETIC_PROTOCOL.md) for the scientific design, role assignments, and lock requirements.

## Before evaluation

Record and sign the protocol, frame, approvals, and software pins through the study's registration process. Generate independent opaque case IDs as 24 to 64 lowercase hexadecimal characters. Define which analyst can access each file and the pinned sandbox environment. [Frame schema](synthetic_frame.py) · [Provenance schema](synthetic_quarantine.py)

Compile the prospective pipeline and record the hash emitted by the builder. Run these commands in the pinned Ubuntu sandbox environment to derive the local software and runtime commitments. The runtime pin records the observed compiler, parser packages, Bubblewrap and systemd client versions, kernel, flags, and configured limits. Keep the registered image and host configuration alongside the pin.

```sh
python3 -B development/build_candidate.py --prospective "$PIPELINE"
python3 -B development/synthetic_study_custodian.py --print-revision
python3 -B development/synthetic_study_custodian.py --print-runtime \
  --pipeline "$PIPELINE" --pipeline-sha256 "$PIPELINE_SHA"
python3 -B development/synthetic_study_predict.py --print-revision
python3 -B development/synthetic_study_score.py --print-revision
sha256sum development/backward_slice.py
```

Before the draw, prepare a private canonical `eapg-synthetic-source-inventory-v1` object for the entire proposed frame including both comparator-swap cases. Use `rows` with `row_id` and a `sources` object keyed by `original`, `evaluated`, and `restored`. Each source value is the exact UTF-8 text whose hash appears in the frame. Run the preflight in the pinned Ubuntu sandbox on independently pinned inputs.

```sh
python3 -B development/audit_synthetic_frame_domain.py \
  --frame "$FRAME" --frame-sha256 "$FRAME_SHA" \
  --inventory "$FRAME_INVENTORY" --inventory-sha256 "$FRAME_INVENTORY_SHA" \
  --pipeline "$PIPELINE" --pipeline-sha256 "$PIPELINE_SHA" \
  --output "$DOMAIN_REPORT"
```

Keep every proposed slot in this report. Review compiler, normalization, and comparator failures before locking the frame. The script checks syntax and static CFG support. Semantic equivalence, oracle growth, reference mapping, and coverage for the realized symptom are checked in later stages. The registered draw validator checks quotas and workload bindings separately.

The source manifest uses canonical JSON with sorted keys, fixed separators, ASCII escapes, and no trailing newline. It has schema `eapg-synthetic-sources-v1`, the draw digest, and the complete ordered list of cases. Each case contains its opaque ID, preregistration, oracle grid, and the digest of the independent review. The preregistration contains the three program variants, three separately implemented counting builds, the analytic growth specification, the raw splice and equivalent edited intervals, and the operation inventory digest. Its exact hash is recorded in the frame. Use `original`, `edited`, and `restored` in the source manifest. The frame calls the edited side `evaluated`. For the appropriate-superlinear control, use identical raw source variants and a null edit. The source manifest goes to the custodian. The review and inventory digests link to separately signed material the custodian retains. [Oracle grid and program schemas](synthetic_oracle.py) · [Raw splice schema](synthetic_intervention.py)

## Custodian

Replay the draw from the pinned frame and input manifest. Prepare a private canonical `eapg-synthetic-source-inventory-v1` manifest with `rows`, each containing `row_id` and `sources`. The sources object maps the version names used by each provenance row to its exact UTF-8 source text. Run the fingerprint tool without the provenance flags to compute fields for a new manifest. To certify the attested fields against the exact bytes, replay with both provenance flags before sealing the graph.

```sh
python3 -B development/synthetic_source_fingerprints.py \
  --inventory "$INVENTORY" --inventory-sha256 "$INVENTORY_SHA" \
  --pipeline "$PIPELINE" --pipeline-sha256 "$PIPELINE_SHA" \
  --provenance "$PROVENANCE" --provenance-sha256 "$PROVENANCE_SHA" \
  --output "$FINGERPRINT_REPORT"
```

Seal the provenance graph with the complete exposure history. After reviewing the registrations and oracle expectations, record the source manifest pin before any evaluation execution. Use a fresh private output directory with access restricted to the custodian. Supply independently recorded pins in the commands below.

```sh
python3 -B development/synthetic_study_custodian.py \
  --protocol "$PROTOCOL" --protocol-sha256 "$PROTOCOL_SHA" \
  --frame "$FRAME" --frame-sha256 "$FRAME_SHA" \
  --inputs "$INPUTS" --inputs-sha256 "$INPUTS_SHA" \
  --draw "$DRAW" --draw-sha256 "$DRAW_SHA" \
  --provenance "$PROVENANCE" --provenance-sha256 "$PROVENANCE_SHA" \
  --quarantine "$QUARANTINE" --quarantine-sha256 "$QUARANTINE_SHA" \
  --sources "$SOURCES" --sources-sha256 "$SOURCES_SHA" \
  --pipeline "$PIPELINE" --pipeline-sha256 "$PIPELINE_SHA" \
  --runner-sha256 "$CUSTODIAN_SHA" --runtime-sha256 "$RUNTIME_SHA" \
  --output "$PRIVATE_RESULTS"
```

The preflight checks every row before executing any evaluation program and preserves the exact input bytes. The source and prediction universes use the same canonical IDs. The custodian gets `evidence.json`, `labels.json`, and `blind.json`. The private `stages/` directory preserves each completed operation, mapping, and profile receipt as it finishes. Treat an interrupted directory without all final files as an incomplete run. Seal the label ledger before sending an independently pinned copy of `blind.json` to the operator. The packet orders opaque IDs separately from the draw, supplies generic nulls for unavailable profiles, and contains only the clean evaluated-side projections. For a comparator swap with two confirmed cases, both projections come from the same evaluated execution. Keep the other files under custody.

## Prediction and scoring

The operator needs the blind packet, registered software, and their independent pins.

```sh
python3 -B development/synthetic_study_predict.py \
  --packet "$BLIND" --packet-sha256 "$BLIND_SHA" \
  --pipeline "$PIPELINE" --pipeline-sha256 "$PIPELINE_SHA" \
  --runner-sha256 "$PREDICTOR_SHA" --output "$PREDICTIONS"
```

Seal the predictions before the scorer receives the three ledger files. The registered scorer verifies the prediction bundle, candidate, and baseline pins as well as each file digest.

```sh
python3 -B development/synthetic_study_score.py \
  --draw "$DRAW" --draw-sha256 "$DRAW_SHA" \
  --labels "$LABELS" --labels-sha256 "$LABELS_SHA" \
  --predictions "$PREDICTIONS" --predictions-sha256 "$PREDICTIONS_SHA" \
  --scorer-sha256 "$SCORER_SHA" --runner-sha256 "$PREDICTOR_SHA" \
  --pipeline-sha256 "$PIPELINE_SHA" --baseline-sha256 "$BASELINE_SHA" \
  --output "$SCORES"
```

## Authored dry run

The dry run constructs a mock 322-slot roster with one active authored family and 316 provenance exclusions. It runs real isolated C++ builds and executions for the six active slots, seals all rows, and invokes the operator and scorer separately. The active family and its comparison inputs were designed for development. This fixture leaves the real study unregistered and under custody.

```sh
PYTHONPATH="$HOME/.local/share/eapg-phase2/deps" python3 -B development/probe_synthetic_study_runner.py \
  --pipeline "$PIPELINE" --pipeline-sha256 "$PIPELINE_SHA" \
  --output .codex/private/integrated-smoke
```

The asserted outcome is 322 label rows, 966 prediction rows, 54 oracle builds, 972 oracle executions, 90 evaluated profile executions, and 15 private stage receipts. The same-program comparator-swap pair must verify on every seed. The scorer must report an under-sized primary cohort. Runtime and CPU-accounting fields in the private receipt can differ across reproductions.
