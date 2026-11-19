# `development/` Module Index

To preserve cryptographic digests pinned in [`custodian_revision()`](synthetic_study_custodian.py), [`prediction_revision()`](synthetic_study_predict.py), [`scoring_revision()`](synthetic_study_score.py), and sealed study JSONs, source modules remain at their flat canonical paths under `development/` and are categorized here by role.

For top-level verification and replay commands, prefer [`../eapg.py`](../eapg.py) from the repository root.

The [paired-study runbook](../docs/PAIRED_STUDY_RUNBOOK.md) covers the new C++ repeated-work panel, independent timing, source-attributed predictions, and blinded scoring. Its development intake and results use a separate study namespace.

---

## 1. Core Candidate, Slicing & Custody Contracts
- [`build_candidate.py`](build_candidate.py) — Applies [`phase2_pipeline.patch`](phase2_pipeline.patch) (and optionally [`phase2_prospective.patch`](phase2_prospective.patch)) onto pinned [`../pipeline.py`](../pipeline.py).
- [`backward_slice.py`](backward_slice.py) — Conventional single-`main()` integral scalar CFG reaching-definitions and control-dependence slicer comparator.
- [`prediction_contract.py`](prediction_contract.py) — Deterministic prompt assembly, 512-token / 26-node eligibility enforcement, and abstention status logic (`RANKED`, `NO_SYMPTOM`, `EMPTY_SLICE`, `NODE_LIMIT`, `CONTEXT_LIMIT`, `UNSUPPORTED_NODE_TOKEN`, `NORMALIZATION_FAILURE`).
- [`prompt_quarantine.py`](prompt_quarantine.py) — Exact prompt-token and numeric-literal template transitive quarantine checks.
- [`build_reference_packet.py`](build_reference_packet.py), [`reference_adjudication.py`](reference_adjudication.py) — Pass-2-free blinded packet export, two-reviewer consensus, and third-adjudicator resolution manifest generator.

## 2. Sandbox, Runtime Screen & Calibration
- [`gate1_sandbox.py`](gate1_sandbox.py) — Bubblewrap (`0.11.1`) + `systemd-run` per-invocation C++ sandbox with FD `199` counter wire (`-fsanitize=undefined -fno-sanitize-recover=undefined`).
- [`run_phase2_development.py`](run_phase2_development.py) — Native Phase 2 normalization, compilation, and execution runner over [`gate1_sandbox.py`](gate1_sandbox.py).
- [`runtime_screen.py`](runtime_screen.py), [`summarize_validation.py`](summarize_validation.py) — Independent monotonic wall-clock timing screen and validation summary checks on PIE `p03497`.
- [`run_weighted_panel.py`](run_weighted_panel.py), [`weighted_panel_sources.py`](weighted_panel_sources.py), [`verify_weighted_panel.py`](verify_weighted_panel.py) — Container-size operation proxy calibration across `std::find`, `std::count`, and `std::reverse` (`-O0/-O2/-O3`).

## 3. Prospective Scalar Study Harness
- [`synthetic_frame.py`](synthetic_frame.py) — 80-family synthetic frame specification, draw builder, and canonical JSON SHA-256 commitments.
- [`synthetic_arms.py`](synthetic_arms.py) — 7 evaluation arms (`hit_growth`, `work_symptom`, `work_scoped`, `work_conventional`, `hits_scoped`, `hits_conventional`, `work_scoped_symbolic`).
- [`synthetic_intervention.py`](synthetic_intervention.py) — Single-site reversible intervention verification and token alignment.
- [`synthetic_oracle.py`](synthetic_oracle.py) — Closed-form plain, UBSan, and operation-counting C++17 oracle runner across seed/size grids.
- [`synthetic_trace.py`](synthetic_trace.py) — Instrumented profiling & scaling fit extraction across `42..44`.
- [`synthetic_source_fingerprints.py`](synthetic_source_fingerprints.py), [`synthetic_quarantine.py`](synthetic_quarantine.py) — Exposure template hashing and transitive quarantine sealing (`280` quarantined slots).
- [`synthetic_study_custodian.py`](synthetic_study_custodian.py), [`synthetic_study_predict.py`](synthetic_study_predict.py), [`synthetic_study_score.py`](synthetic_study_score.py), [`score_synthetic.py`](score_synthetic.py), [`score_external.py`](score_external.py) — Separately hash-locked custodian, blinded predictor, and equal-family statistical scorers.
- [`plan_synthetic_power.py`](plan_synthetic_power.py), [`SYNTHETIC_STUDY_RUNBOOK.md`](SYNTHETIC_STUDY_RUNBOOK.md) — Sample-size planning and CPU custodian runbook.

## 4. Training, GPU Contract, Ablation & Study Orchestration
- [`assemble_pilot_resplit.py`](assemble_pilot_resplit.py), [`train_pilot_resplit.py`](train_pilot_resplit.py), [`replay_pilot_resplit.py`](replay_pilot_resplit.py) — Strict 13-group 5-fold pilot refit and CPU contrast replay.
- [`train_phase2_adapter.py`](train_phase2_adapter.py) — 4-bit NF4 QLoRA adapter trainer (`Qwen2.5-Coder-1.5B`).
- [`train_resplit_ablation.py`](train_resplit_ablation.py), [`replay_resplit_ablation.py`](replay_resplit_ablation.py) — Six-representation ablation trainer and offline logit verifier (`tab:eapg-resplit-ablation`).
- [`predict_external_contract.py`](predict_external_contract.py) — Live 4-bit NF4 adapter executor enforcing [`prediction_contract.py`](prediction_contract.py) into [`score_external.py`](score_external.py).
- [`run_prospective_multiagent_study.py`](run_prospective_multiagent_study.py) — Dual-OS Part A (`10` unseen scalar families, `322` slots, live GPU) + Part B (`14+2` blinded-adjudicated pairs, strict OOF vs. fold-0) orchestrator.
- [`replay_pilot_contrast.py`](replay_pilot_contrast.py), [`replay_pilot_outputs.py`](replay_pilot_outputs.py), [`verify_manuscript_pilot.py`](verify_manuscript_pilot.py) — Offline replay and manuscript table integrity verifiers.

## 5. Domain Audits & Diagnostic Probes
- **Domain Audits:** [`audit_comparator_bottlenecks.py`](audit_comparator_bottlenecks.py), [`audit_pilot_baseline_domain.py`](audit_pilot_baseline_domain.py), [`audit_scalar_intake.py`](audit_scalar_intake.py), [`audit_synthetic_frame_domain.py`](audit_synthetic_frame_domain.py), [`audit_uoj_source_availability.py`](audit_uoj_source_availability.py).
- **Probes:** [`probe_adapter_objective.py`](probe_adapter_objective.py), [`probe_comparator_swap.py`](probe_comparator_swap.py), [`probe_gate1.py`](probe_gate1.py), [`probe_gate2_ast.py`](probe_gate2_ast.py), [`probe_gate2_pilot.py`](probe_gate2_pilot.py), [`probe_prediction_contract.py`](probe_prediction_contract.py), [`probe_runtime_controls.py`](probe_runtime_controls.py), [`probe_scope_boundary.py`](probe_scope_boundary.py), [`probe_synthetic_comparison.py`](probe_synthetic_comparison.py), [`probe_synthetic_intervention.py`](probe_synthetic_intervention.py), [`probe_synthetic_study_runner.py`](probe_synthetic_study_runner.py), [`probe_transitive_edit.py`](probe_transitive_edit.py), [`probe_weighted_find.py`](probe_weighted_find.py).

## 6. Automated Test Suites (`test_*.py`)
All 19 unit and integration test modules under `development/` (note: most modules assume `development/` on `sys.path` when invoked via `eapg.py`, `unittest`, or `pytest`): [`test_assemble_pilot_resplit.py`](test_assemble_pilot_resplit.py), [`test_audit_scalar_intake.py`](test_audit_scalar_intake.py), [`test_audit_synthetic_frame_domain.py`](test_audit_synthetic_frame_domain.py), [`test_backward_slice.py`](test_backward_slice.py), [`test_predict_external_contract.py`](test_predict_external_contract.py), [`test_prediction_contract.py`](test_prediction_contract.py), [`test_prospective_multiagent_study.py`](test_prospective_multiagent_study.py), [`test_resplit_ablation.py`](test_resplit_ablation.py), [`test_score_synthetic.py`](test_score_synthetic.py), [`test_synthetic_arms.py`](test_synthetic_arms.py), [`test_synthetic_frame.py`](test_synthetic_frame.py), [`test_synthetic_intervention.py`](test_synthetic_intervention.py), [`test_synthetic_oracle.py`](test_synthetic_oracle.py), [`test_synthetic_quarantine.py`](test_synthetic_quarantine.py), [`test_synthetic_source_fingerprints.py`](test_synthetic_source_fingerprints.py), [`test_synthetic_study_custodian.py`](test_synthetic_study_custodian.py), [`test_synthetic_study_predict.py`](test_synthetic_study_predict.py), [`test_synthetic_study_score.py`](test_synthetic_study_score.py), [`test_synthetic_trace.py`](test_synthetic_trace.py). (`eapg.py verify --mode common` runs the 18 zero-external-dep replay and unit checks; `--mode linux` adds `test_phase2_{ast,selection}.py`, `test_backward_slice.py`, `test_synthetic_intervention.py`, and the 6 `tree-sitter`/custodian/intake checks.)

## 7. Protocols, Decision Logs & JSON Receipts
- **Docs:** [`RESEARCH_RECORD.md`](RESEARCH_RECORD.md), [`PROSPECTIVE_SYNTHETIC_PROTOCOL.md`](PROSPECTIVE_SYNTHETIC_PROTOCOL.md), [`EXTERNAL_STUDY_HANDOFF.md`](EXTERNAL_STUDY_HANDOFF.md), [`SCALAR_FRAME_FEASIBILITY.md`](SCALAR_FRAME_FEASIBILITY.md), [`SYNTHETIC_STUDY_RUNBOOK.md`](SYNTHETIC_STUDY_RUNBOOK.md), [`WEIGHTED_PANEL_PROTOCOL.md`](WEIGHTED_PANEL_PROTOCOL.md).
- **Receipts:** [`comparator_bottlenecks.json`](comparator_bottlenecks.json), [`comparator_swap_results.json`](comparator_swap_results.json), [`pilot_output_agreement.json`](pilot_output_agreement.json), [`prospective_multiagent_results.json`](prospective_multiagent_results.json), [`registered_validation_summary.json`](registered_validation_summary.json), [`runtime_validation_timing.json`](runtime_validation_timing.json), [`scalar_intake_feasibility.json`](scalar_intake_feasibility.json), [`scope_boundary_results.json`](scope_boundary_results.json), [`transitive_edit_results.json`](transitive_edit_results.json), [`uoj_source_availability.json`](uoj_source_availability.json).
