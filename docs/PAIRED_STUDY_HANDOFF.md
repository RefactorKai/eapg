# EAPG research handoff

18 November 2026

## Current status

The checkout is the repository root on `main` at `a4fe32b`. The paired-study implementation and documents are working-tree changes. The frozen release still passes all 31 SHA-256 checks. The held-out data stayed sealed.

- The pipeline runs C++17 fixtures in the existing Linux isolation launcher, validates expected outputs and operation counts independently, tests individual restorations, and produces trace, evaluation, prediction, scoring and table receipts. It also checks split overlap, commits a representative selection before scoring, and enforces the registered power and evidence gates. [Runbook](PAIRED_STUDY_RUNBOOK.md) · [Source](../development/paired_study/)
- The authored run has **12 cases from one family**, with six count-confirmed positives, four verified negative controls and two indeterminate cases. Rewind attribution found **5/6** at Top-1. Value-sensitive change impact found **6/6**. Both found all five cursor cases, and only change impact identified the unrelated slowdown. Both gave **0/4** alerts on the verified negative controls. These are descriptive results.
- A second source-to-score run on the same WSL2 host reproduced the traces, oracle, scores and paper table byte for byte. The analysis manifest SHA-256 is `eabc320f3d188b3883780210b0659c18697e10606fd69663f4ba64c0b791448a`. The previous full suite reported 118 passed and 8 Windows skips. The handoff check reran the focused suite and got 33 tests and 32 subtests passing. Local evidence is under `build/paired-study-authored-reproduction/`, which is Git-ignored. A checkout containing the paired-study changes can regenerate it using the runbook.

## Problems persisting

1. **The ranking hypothesis failed on the authored panel.** The stronger comparator matched rewind attribution on cursor cases and beat it across the panel. A standalone superiority claim needs new evidence against value-sensitive change impact. The operation accounting can still explain where excess work comes from.
2. **There is no independently adjudicated natural cohort.** The development intake selected 12 PIE validation problems and 12 CppPerf projects. Zero cases have completed independent human eligibility, correctness, count and restoration checks. The old PIE draw has at most 35 independent groups. Under the illustrative 20-point effect and 34% discordance, that is about 43% power even before exclusions. The same assumptions give about 80% power at 71 groups. [Intake and case dispositions](PAIRED_STUDY_INTAKE.md) · [Power design](RESEARCH_REWORK_PLAN.md#5-independent-labels-measurements-and-denominators)
3. **Support is narrow.** The current collector validates dependencies for an authored indexed-array template. General C++ tracing and source-mapped compiler slicing remain unvalidated. LLVM DG was unavailable on the tested host. Changes that replace the algorithm can leave no alignable scan episodes.
4. **Runtime and independent reproduction remain open.** The separately timed case `a01` passed the operation-count criterion and missed the runtime criterion. Startup contributes to the measured duration. Byte-identical regeneration has been demonstrated on one host. The confirmatory study remains unregistered.

## The idea

Given two correct versions on the same workload, identify a changed statement that explains a measured increase in work. A single target trace can identify a hotspot. A comparative regression claim depends on the reference version and workload.

For ordered rank queries on a sorted array, carrying the scan cursor preserves the same outputs as restarting it. On queries 1 through n, carrying costs n advances and restarting costs n(n+1)/2. At n=8 the reset explains exactly 28 extra advances. The method follows the scan entry back to the reaching source definition and accounts for the lost progress. A correctness-preserving restoration supplies separate evidence about the proposed cause. The most defensible paper direction is the accounting mechanism, its support boundaries, and what the human-code intake reveals. [Research design and proof](RESEARCH_REWORK_PLAN.md)

## Prompt for the next LLM

> Continue the EAPG study from the repository root. Read `docs/PAIRED_STUDY_HANDOFF.md`, `docs/PAIRED_STUDY_RUNBOOK.md`, `docs/PAIRED_STUDY_INTAKE.md`, and sections 2 through 6 of `docs/RESEARCH_REWORK_PLAN.md`. Inspect the working tree first. Preserve the checksummed release, existing working-tree changes, and the sealed evaluation. Use development material only and keep the recorded comparison with value-sensitive change impact.
>
> Start by testing the feasibility of one human-written development case on paper. Use PIE validation case `p00537` as the known alignment boundary. Audit its six-size input ladder, expected output, and predicted accumulator-write counts under the problem contract. Its reference uses a different algorithm, so record it as an alignment boundary. Then select the most plausible remaining development pair for a local-restoration case. State the exact candidate change and plausible alternative, the common cost event, output oracle, workload sizes and shapes, how the executions would align, and the smallest restoration that preserves correctness. Record a rejection with its specific cause if the pair cannot meet those requirements. Label source-based derivations as such. Independent human adjudication requires actual independent reviewers.
>
> Deliver a short evidence-backed decision about the paper. If a credible natural case can be validated, explain what new evidence could distinguish quantitative attribution from value-sensitive change impact. Otherwise develop the bounded mechanism and feasibility paper from the verified results. Keep operation counts distinct from elapsed time, report every candidate disposition, and retain the stronger comparator. Use the existing isolated launcher for any authorized C++ execution. Leave held-out data sealed until independent custody, reviewers, a powered frame, validated trace and slicing support, and a registered protocol are in place. Report exactly what you checked and any material gap.
