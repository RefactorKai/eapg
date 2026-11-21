---
name: eapg-statistics
description: Statistics and audit rules for the EAPG Data Analyst - group-level paired analysis, denominators, confidence intervals, power, receipts and table macros. Invoke for any analysis, table, rate, CI, power calculation, or audit of reported numbers in RefactorKai/eapg.
---

# EAPG statistics

Follow `eapg-ground-rules` first.

## Unit of analysis
- Cases cluster by problem, template group or mechanism family. The group is the independent unit. Report both the pair-weighted and the group-weighted score whenever they could differ; the audit showed the neural lead reverses under group weighting (98/100 vs 96/100 by pair, 93.48% vs 95.65% by group).
- Count a family once. Seeds, renamings and extra sizes are not new samples.
- State quarantine keys (problem ID, aliases, normalized source, identifier- and numeric-literal-normalized templates, prompt tokens) and the number of cross-split collisions.

## Every rate
- Write `k/n = p%` with the exact denominator, and say what is excluded and why (abstentions, ties, unsupported, indeterminate).
- Ties without a unique recommendation are abstentions on Top-1 for every arm; report tie frequency and an expected score under uniform tie-breaking as secondary.
- Name the CI method in the text or caption:
  - paired binary arms: exact McNemar test with the discordant counts (`b` vs `c`), plus a cluster (group) bootstrap CI for the difference;
  - single proportions: Wilson or Clopper-Pearson interval;
  - group-weighted scores: percentile bootstrap over groups, fixed seed and replicate count recorded in the receipt.
- Small cohorts are feasibility evidence. Below the registered gates (Part A `< 60` families, Part B `< 20` groups) say so and give no confirmatory claim.

## Power
Use the design in `docs/RESEARCH_REWORK_PLAN.md` section 5 (paired discordance, groups as units). Report assumed effect, discordance, alpha and power with the group count; flag exclusions that cut power.

## Receipts and macros
- Each analysis is a script in `development/` that reads committed inputs and writes a JSON receipt with input SHA-256s, script revision, seed and the outputs. Reruns are byte-identical.
- Table and text numbers are generated LaTeX macros from that receipt (WP-A3), never typed. Add a verifier check (see `development/verify_manuscript_pilot.py`) that fails when the paper and receipt disagree.
- Scaling: fits are finite-range growth of a named work event over registered sizes. Keep operation counts distinct from elapsed time. Report censoring, caps, missing sizes, and sensitivity to dropping the largest size. Never fit a cap as a completed observation.

## Auditing others' numbers
For each reported number: locate its receipt field, recompute from raw data, check the denominator and grouping, and record agreement in a table (claim, location, receipt, recomputed, status). Send disagreements to the coordinator with file and line.
