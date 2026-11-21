# Frozen analysis protocol: paired benchmark expansion (500–1,000 new public C++ pairs)

Status: frozen before any new pair is executed or opened. The commit date of this file in RefactorKai/eapg is its freeze date. Until that commit exists, call it a "frozen protocol", never "pre-registered" (ground rule §12).
Drafted on 2026-11-21 from committed sources only. The author opened no newly scraped pair, read no scrape output and saw no count of scraped pairs.

## 0. Sources of every fixed value

| Source | What it fixes |
|---|---|
| `artifacts/paired_development/ledger.json` (schema `eapg.path-b.ledger.v2`), `tables.md` | Disposition labels, desk reasons, stage order, 147-pair reference rates |
| `manuscript/paired_mechanism.tex` §Growth screen; `development/paired_study/path_b_close.py:54-69` | Growth screen: slope ≥ 0.50, largest-size ratio ≥ 1.50, ≥ 4 common uncapped sizes spanning ≥ 8×, all-stream rule |
| `docs/RESEARCH_REWORK_PLAN.md` §5 | Six geometric sizes, three streams, cap censoring, ≥ 80% restoration recovery, representative-pair rule, stable-hash selection |
| PR #10 `development/GROUPED_STATISTICS.md`, `replay_grouped_statistics.py`, `grouped_statistics.json` | Cluster key, equal-cluster weighting, exact whole-cluster sign-flip test, Clopper–Pearson, Holm, bootstrap recipe, 1-decimal reporting |

No threshold below was chosen after looking at new data. None may be tuned on the new set. A changed threshold needs a dated protocol amendment, made before execution and justified on disjoint development data (§11).

### 147-pair reference values (all from the receipts above; pair counts)

| Quantity | 147-pair value | 95% CP |
|---|---|---|
| R1 Desk stops / selected | 103/147 = 70.1% | 62.0–77.3% |
| R2 Reached isolated execution / selected | 14/147 = 9.5% | 5.3–15.5% |
| R3 All-stream alerts / fitted | 4/13 = 30.8% | 9.1–61.4% |
| R4 All-stream alerts / selected | 4/147 = 2.7% | 0.7–6.8% |
| R5 Single-TU preprocessing stops / attempted after desk (12 + 14) | 12/26 = 46.2% | 26.6–66.6% |
| R6 Output-oracle failures / executed | 1/14 = 7.1% | 0.2–33.9% |
| R7 Desk stop − execution, equal-cluster (119 clusters) | +58.6 pp, Holm p = 4.94×10⁻¹⁴ | bootstrap 46.4–70.1 pp |
| R8 Alert − no alert among fits, equal-cluster (12 clusters) | −33.3 pp, Holm p = 0.388 | bootstrap −83.3–16.7 pp |

The 147 rows mix one pair per PIE problem with a project census and inherited controls. They are development evidence, not a probability sample. They serve here only as fixed reference values, never as pooled data.

## 1. Population, frames and unit of analysis

- **Population.** New public C++ performance pairs (target = slower version, reference = faster version) from the scrape, up to 1,000 pairs. Before execution, the scrape manifest is frozen: source URL, pinned revision or submission IDs, SHA-256 of both sides, corpus, cluster key. Its SHA-256 goes in the analysis receipt. No pair is added after the freeze.
- **Frames.** Report two frames separately, plus their distinct union: **Contest** (single-submission judge pairs) and **Repository** (project commit pairs). A pair in both frames counts once in the union.
- **Observation unit.** One pair.
- **Independent unit (cluster).** Contest: judge + problem ID. Repository: case-folded `owner/repo`, with forks merged into the upstream root. Clusters connected by a shared alias, a shared normalized source, or the identifier- and literal-normalized template hash are merged (connected components). Clusters are the test units. Pairs within a cluster are not independent.
- **Representative pair (primary).** In each cluster, choose one pair before inspection: the lowest SHA-256 of the compact UTF-8 JSON `["eapg-expansion-v1", corpus, cluster_id, pair_id]`, with lexical ties. The primary rates (P1, P3) use representative pairs only, so their units are independent. All pairs are still executed and reported (S-analyses).
- **Quarantine.** A cluster that overlaps the 147-pair study (its 77 PIE problem IDs, its 42 CppPerf projects, and their aliases or templates) is development-exposed. It is dropped from the confirmatory frame and reported as its own stratum. PIE test-split material is never used. Report the number of cross-set collisions for each quarantine key.

## 2. Qualification stages and stop labels (frozen set)

Each pair enters once and stops at the **first** relevant stage. The label set is closed: these are the 147-pair ledger labels plus three new labels marked †.

| Stage | Pass condition | Terminal labels |
|---|---|---|
| S0 Intake | Both sides retrieved at pin, C++, licence allows use, not a duplicate | `intake_unretrievable`†, `intake_duplicate`† (counted once, kept in the flow table, left out of every denominator) |
| S1 Desk | Legal six-size geometric ladder, independent output oracle, common work event, isolatable edit with restoration and sham | `desk_excluded` / `desk_blocked`, bucket **source** (`source_derived_oracle_failure`, `source_derived_numeric_oracle_failure`, `source_derived_undefined_behavior`, `forced_avx`, `forced_x86_native`, `isa_or_arch_locked`, `concurrency_or_cache_layout`, `graphics_driver_or_host_api`, `unsupported_dependencies`), **contract** (`fixed_contract`, `insufficient_workload_ladder`, `alignment_boundary`, `no_common_calibrated_work`, `no_common_restoring_event`, `no_executable_work_delta`, `no_matching_work_delta`, `no_isolated_restoration`), **route** (`missing_pinned_dependency`, `missing_pinned_dependency_and_calibration`, `unverified_assertion_configuration`, `unverified_cache_cutoff_alignment`, `unverified_calibrated_cache_work`) |
| S2 Single-TU preprocessing | Dependency-only preprocessing succeeds under the Gate 1 runner | `support_boundary_closed` |
| S3 Isolated execution | Target, reference, restoration and sham build and run in the Bubblewrap launcher (`development/gate1_sandbox.py`, never `pipeline.py`); plain and UBSan outputs agree with the oracle; counts agree exactly at O0/O2/O3 | `execution_oracle_failure`, `execution_infrastructure_failure`† |
| S4 Fit admission | Every registered stream has ≥ 4 common uncapped sizes spanning ≥ 8×; capped points are censored, never fitted | `insufficient_fit` (fitted = no) |
| S5 Screen | — | `alert` (all streams pass) / `no_alert` |

- **Desk labels** come from the D4 blind model protocol (`eapg-blind-validation`): two raters from different model families, blind to each other and to all outcomes, record their labels before any comparison; a third family adjudicates disagreements. The S1 label is the adjudicated label. Report κ (exact and bucket labels) with CIs and their method. Call this "model-based validation", never human.
- **No deferral.** Every pair that passes desk goes to S2 in stable-hash order, not in order of likely growth. A pair not executed when the study closes is `not_executed` and counts as not reaching execution in P1.
- **Infrastructure failures.** Retry at most twice with the same pins. Then label the pair `execution_infrastructure_failure`. It counts as not executed in P1 and is dropped only in sensitivity S6.
- **Restoration validity.** A restoration must recover ≥ 80% of the positive excess count at the two largest common sizes on every stream (RESEARCH_REWORK_PLAN §5). The sham must preserve the measured work. A failed restoration is recorded as a property of the restoration and is not by itself a stop; the screen verdict still comes from target versus reference.

## 3. Outcomes

**Primary (confirmatory, Holm family of three).**
- **P1 Execution yield.** Representative clusters reaching S3 with valid outputs or `execution_oracle_failure` (the R2 definition), divided by all confirmatory representative clusters past S0.
- **P2 Desk stop − execution contrast.** The R7 replication: all confirmatory pairs past S0, within-pair difference (desk stop) − (reached execution), averaged within cluster, then equal-weight across clusters.
- **P3 Alert rate among fits.** Representative clusters with an all-stream `alert`, divided by representative clusters with a fit (S4 passed).

**Secondary (nominal p, labelled exploratory).**
- S1 Desk-stop rate (vs R1) and the source/contract/route split.
- S2 Alerts per selected cluster (vs R4).
- S3 Preprocessing stops per attempted cluster (vs R5).
- S4 Oracle failures per executed cluster (vs R6).
- S5 The R8 contrast replicated.
- S6 P1 without infrastructure failures.
- S7 Any-stream alert rule.
- S8 Drop-largest refit (admitted only when the reduced ladder still has ≥ 4 sizes spanning ≥ 8×; otherwise "range-limited", not negative).
- S9 All-pair equal-cluster versions of P1 and P3.
- S10 Per-frame rates.
- S11 Desk κ.
- S12 Quarantined-overlap stratum.

## 4. Tests and intervals (M3)

- **Rates.** Report `k/n = p%` with a two-sided 95% Clopper–Pearson interval and the unit named. For P1, P3 and S1–S4 the unit is representative clusters, so CP is exact under independent clusters. All-pair rates (S9) carry CP only as a descriptive working-independence reference, plus the cluster bootstrap below.
- **P1, P3 test.** Two-sided exact binomial test of the representative-cluster rate against the fixed 147 value (P1: 14/147; P3: 4/13), using representative pairs only.
- **P2, S5 test.** Two-sided exact whole-cluster sign-flip test (`replay_grouped_statistics.py:sign_flip_p`, including ties in the tail; zero-effect clusters are not permuted).
- **Descriptive interval for contrasts.** Whole-cluster percentile bootstrap: sort cluster IDs ascending; Python `random` with seed 42; 10,000 draws of the original cluster count with replacement; sort the replicates and take nearest ranks 250 and 9,750. This is a sensitivity interval, not the test. Leave-one-cluster-out results are a **range**, never a CI.
- **Pair-level McNemar** is secondary at most. Never report pair-level and cluster-level numbers side by side unlabelled (M4).
- **Precision (M5).** Interval endpoints to one decimal in pp. Compute tests before rounding. Record the seed, draws and ordering in the receipt.

## 5. Multiplicity

Holm at family-wise α = 0.05 over exactly {P1, P2, P3}. Secondary p-values are nominal and labelled so. Frame-level and stratum-level results are never added to the family. Report adjusted and unadjusted p for the family.

## 6. Sample-size gates (frozen)

| Outcome | Gate (confirmatory representative clusters) | Basis |
|---|---|---|
| P1, P2 | ≥ 200 clusters past S0 | Exact binomial at α = 0.05/3: power 0.94 to detect 19.0% (2× R2) and 0.92 to detect 3.0% against 9.5%; CP half-width ≈ 4.3 pp at 9.5% |
| P3 | ≥ 30 fitted clusters | Power 0.83 to detect 60% and 0.94 to detect 5% against 30.8% at α = 0.05/3; half-width ≈ 17 pp |
| Per-frame secondary | ≥ 30 clusters in the frame | Below this, counts and CP only |

Below a gate, give counts and CP only, with no directional claim in the abstract or conclusion (B4). The gates use cluster counts after quarantine and S0. The analysis runs **once**, after every pair has a terminal label. There are no interim looks at P1–P3 (the WP-P1 rule in §9 uses the same final data).

## 7. Exclusions

- **Before the denominator (reported in the flow, outside every denominator):** S0 labels; PIE test split; quarantined clusters (analysed only as S12).
- **Never excluded:** any S1–S5 outcome, including oracle failures, censoring, timeouts, infrastructure failures (P1 counts them as not executed) and pairs not executed when the study closes.
- **Caps.** A capped point is right-censored and left out of the fit; cap coverage is reported. A timeout is not a negative.
- **Post-hoc removal** of a pair or cluster for any reason not listed here is forbidden. A found error (wrong pin, duplicate found late) is fixed by relabelling under §2 and logged in an errata list with its date.

## 8. Confirming or contradicting the 147-pair findings

| 147 finding | Confirmed | Contradicted | Otherwise |
|---|---|---|---|
| F1 Qualification usually stops before execution (R7) | P2 > 0 and Holm p < 0.05 | P2 < 0 and Holm p < 0.05 | Inconclusive |
| F2 Single-TU execution yield is low, about 9.5% (R2) | Gate met, P1 Holm p ≥ 0.05 and the P1 CP half-width ≤ 5.0 pp | P1 Holm p < 0.05 (direction stated) | Inconclusive (below gate or too imprecise) |
| F3 Fitted alerts are a minority, about 30.8% (R3) | Gate met, P3 Holm p ≥ 0.05 and the P3 CP upper limit < 50% | P3 Holm p < 0.05 (direction stated) | Inconclusive |
| F4 Alerts per selected pair are rare (R4), secondary | Nominal binomial p ≥ 0.05 vs 4/147 and CP upper < 10% | Nominal p < 0.05 | Inconclusive; exploratory |
| F5 Accepted references can fail an independent oracle (R6), secondary | ≥ 1 `execution_oracle_failure` with a committed witness | — | Not observed (report the CP upper bound) |

"Consistent with" is the only wording allowed when a test does not reject. A non-rejection never establishes equivalence.

## 9. Go/no-go rule for WP-P1 (native-build contrast)

Evaluated once, on the final single-TU dispositions, before any native build is attempted. Native-build results never enter P1–P3.

- **E:** the P1 execution yield (representative clusters, CP).
- **R:** route-attributable stops in the Repository frame: S1 route-bucket stops plus `support_boundary_closed`, in representative clusters.
- **X:** executed Repository-frame representative clusters.

| Condition | Decision |
|---|---|
| E's CP lower limit > 15.5% (above the R2 upper limit) | **NO-GO, single-TU adequate.** Report the yield and keep WP-P1 out of scope. |
| E's CP lower limit ≤ 15.5%, and R ≥ 12 and R ≥ X | **GO.** Run WP-P1 on all R clusters plus fixed controls (hash-chosen executed and contract-stop clusters), as specified in WP-P1. |
| E's CP lower limit ≤ 15.5%, and R < 12 or R < X | **NO-GO, narrow the paper.** Losses are not mainly due to the build route; narrow the paper to the single-TU route. |

The 15.5% anchor is the R2 CP upper limit. The 12 is the 147-pair preprocessing stop count (R5 numerator). R ≥ X matches the 147 repository-patch union (R = 7 route + 12 preprocessing = 19 vs X = 4 executed), applied at the weaker ratio of 1. Report E, R and X with CPs next to the decision.

## 10. Receipts and evidence class

- One script in `development/` reads the frozen manifest and the final ledger and writes a JSON receipt. The receipt holds input SHA-256s, the script revision, the seed, the draws and every P/S value. It is checked by `eapg.py verify`.
- Every number is tagged `re-executable`, `replay-only` or `private-only`. Private-only numbers are dropped from the paper.
- Both the per-pair ledger and the representative-pair list are committed before P1–P3 are computed.

## 11. Amendments

Only before the first S3 execution, by a dated commit that states the change, the reason and the disjoint evidence. Any change after that is reported as a deviation, and both analyses are shown.

## 12. Known limitations

- The 147 reference values come from a non-probability, partly inherited sample.
- Comparisons against them test consistency with fixed numbers, not a two-sample difference.
- Desk labels are model-based, not human.
- Fits are finite-range growth of a named work event; no runtime or asymptotic claim is made.
