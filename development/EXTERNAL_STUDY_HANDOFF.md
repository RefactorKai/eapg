# External study handoff

> **Execution Status (17 November 2026):** Bounded 3-agent blinded execution completed in [`prospective_multiagent_results.json`](prospective_multiagent_results.json) (`14+2` pairs across `11` positive groups; `positive_transfer_evidence = false`, `< 20` groups; full unsealed PIE test split remains external). See [`../docs/INDEPENDENT_AUDIT.md`](../docs/INDEPENDENT_AUDIT.md).

## Current evidence

The [development record](RESEARCH_RECORD.md) supports an engineering claim about the repaired selector and ranker. The only human-written development pair reproduced the counter-based traversal result but failed the independent timing-slope screen. The 12-pair synthetic stress cohort contains known repairs and related templates. A comparison on previously unseen human-written programs still requires separate reference labels and predictions.

## Before the custodian profiles any test code

1. Pin the candidate pipeline, sandbox and compiler image, timing rule, and final study protocol. The proposed primary uses the repaired selector. The archived Phase 1 selector is a separate diagnostic. Seal the frame, per-problem workload generators and output oracles, workload seed and size grids, and negative control selection before measuring any test outcome. Keep the registered draw intact and retain a reason for every ineligible or failed pair. [Candidate policy](phase2_pipeline.patch) · [Frozen study design](../artifacts/phase1_correction/phase2_protocol.md)
2. Run the authored isolation and transport probes on the pinned image. Only the custodian should access test sources, map canonical nodes, and record isolated eligibility and counter features before the split is finalized. The inference side receives only allowed slow-side inputs and features. Use the same canonical normalization for profiling, prompt construction, references, and scoring. [Development runner](run_phase2_development.py) · [Timing screen](runtime_screen.py)
3. Register the final prompt serializer and model revision before processing the cohort. Include the actual development cohort and all proposed training rows when grouping sources and prompt tokens. Seal the `prompt_quarantine.seal_splits` output and record its canonical SHA-256 independently. Track unsupported serializations with explicit reasons so their static keys still affect quarantine. The transfer adapter uses the frozen published Phase 1 `6b-slice` prompts and labels for retained synthetic training rows. The repaired pipeline produces external inference prompts. The training-side prompt hashes must match the exact frozen prompt tokens submitted to quarantine. [Quarantine helper](prompt_quarantine.py) · [Offline objective probe](probe_adapter_objective.py)

The [prediction contract](prediction_contract.py) has authored tests for canonical candidates, exact tokenization, and abstentions. Before external scoring, connect it to the pinned adapter and the prediction-ledger writer and test that complete path with authored inputs. The [synthetic protocol draft](PROSPECTIVE_SYNTHETIC_PROTOCOL.md) uses separate intervention ledgers.

## Blinded reference collection

Use the protocol's timing criteria and independent algorithmic review to confirm positives. Give two independent reviewers the problem, paired sources and independent screening evidence. Collect and hash their raw slow-source causal spans before showing the static Pass-2 map. Keep candidate sets and model predictions hidden throughout. Require a distinct third reviewer to resolve conflicts or ambiguous mappings. Preserve an explicit unresolved disposition when no reference node can be accepted.

The custodian supplies a blinded packet with the normalized source digest and static node map, and records its canonical packet hash out of band. Inspect each pair with the two original review records, then add `--adjudication` if needed. Add `--out` to seal the disposition to a new path. [Packet and review format](reference_adjudication.py)

```sh
python -B development/reference_adjudication.py
python -B development/reference_adjudication.py --packet packet.json --packet-sha256 "$PACKET_SHA" \
  --reviews review-a.json review-b.json --adjudication review-c.json --out reference.json
```

## Separately sealed ledgers and scoring

Use the frozen draw as the outer join. Assign every pair a final quarantine group and screening status, even if no prediction can be produced. Keep the following ledgers separately and record each file's SHA-256 before scoring. The prediction side receives the study ledger's digest without its reference contents.

| Ledger | Required content |
|---|---|
| `eapg-external-study-ledger-v1` | `drawn_pair_ids`, `pairs`, `protocol_sha256`, `pipeline_sha256`, `quarantine_sha256`. Each pair records `pair_id`, `group_id`, `screening_status`, `canonical_node_ids`, `normalized_source_sha256`, and `accepted_node_ids`. For a confirmed positive also record `reference_status` and `reference_manifest_sha256` from the sealed adjudication. |
| `eapg-external-predictions-v1` | `study_sha256`, `protocol_sha256`, `pipeline_sha256`, `quarantine_sha256`, `adapter_sha256`, and `pairs`. Each pair records `pair_id`, `normalized_source_sha256`, `symptom_id`, the emitted `slice`, `prompt_tokens` excluding the answer, and `symbolic` and `abstract` ranked node lists. Use an empty list for abstentions and `null` for unavailable digests, symptoms, or token counts. Return up to the first two unique ranked nodes from the shared emitted slice. |

Report the end-to-end paired Top-1 contrast in `D_pos` with each quarantine group weighted equally. Report `D_elig` and `D_rank` separately, including coverage and candidate recall. Report unresolved confirmed positives as misses in the conservative lower bound. The scorer enforces a shared slice, exact draw coverage and normalized-source binding, one reserved target token, and the 26-node and 512-token eligibility limits. Its seed-42 cluster bootstrap uses 10,000 draws. A positive transfer result requires at least 20 represented primary groups and a lower 95% interval endpoint above zero. [Scorer](score_external.py)

```sh
python -B development/score_external.py --self-check
python -B development/score_external.py --study study.json --study-sha256 "$STUDY_SHA" \
  --predictions predictions.json --predictions-sha256 "$PREDICTIONS_SHA"
```
