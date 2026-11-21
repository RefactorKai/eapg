---
name: eapg-statistics
description: Statistics and audit rules for the EAPG Data Analyst - cluster-aware tests, Clopper-Pearson intervals, denominators, evidence classes, receipts and table macros. Invoke for any analysis, table, rate, CI, power calculation, or audit of reported numbers in RefactorKai/eapg.
---

# EAPG statistics

Follow `eapg-ground-rules` first. Checklist items M3, M4, M5, B4 and P-D5 set the acceptance bar.

Invoke `eapg-token-budget` and `eapg-receipt-queries` for this role's efficiency toolkit; ground rules always win.

## Unit of analysis
- Cases cluster by problem, template group or mechanism family. The group is the independent unit. Report both the pair-weighted and the group-weighted score whenever they could differ; the audit showed the pilot's neural lead reverses under group weighting (take both scores from `artifacts/scope_isolated_pilot/node_only_ablation/evaluation_results.json`, never from memory).
- Count a family once. Seeds, renamings and extra sizes are not new samples.
- State quarantine keys (problem ID, aliases, normalized source, identifier- and numeric-literal-normalized templates, prompt tokens) and the number of cross-split collisions.

## Default methods (M3)
- Comparisons between arms: cluster-aware by default, a cluster permutation test or wild-cluster bootstrap over groups. A pair-level exact McNemar test (with discordant counts `b` vs `c`) is secondary at most.
- Proportions, especially small strata: Clopper-Pearson exact 95% intervals.
- Multiplicity: Holm correction over a declared primary set; label one primary metric per caption.
- Leave-one-out results are shown as a range, not a CI.
- Precision (M5): one-decimal intervals (or 100k bootstrap draws), canonical sorted-key ordering documented, fixed seed and replicate count in the receipt.

## Every rate
- Write `k/n = p%` with the exact denominator, the unit (pair, equal-group, macro) and what is excluded and why (abstentions, ties, unsupported, indeterminate). Never set pair-level and group-level numbers side by side unlabelled (M4).
- Ties without a unique recommendation are abstentions on Top-1 for every arm; report tie frequency and an expected score under uniform tie-breaking as secondary.
- Name the CI method in the text or caption.
- Small cohorts are feasibility evidence. Part A needs at least 60 families and at least 30 off-site cases; missing either minimum blocks directional claims. Part B needs at least 20 groups. Below a gate, give no directional claim in the abstract or conclusion (B4).

## Power
Use the design in `docs/RESEARCH_REWORK_PLAN.md` section 5 (paired discordance, groups as units). Report assumed effect, discordance, alpha and power with the group count; flag exclusions that cut power.

## Receipts, macros and evidence class
- Each analysis is a script in `development/` that reads committed inputs and writes a JSON receipt with input SHA-256s, script revision, seed and the outputs. Reruns are byte-identical.
- Table and text numbers are generated `\newcommand` macros from `development/paper_claims.json` (WP-A3), never typed. `verify` must fail when a receipt value is mutated (M2 mutation test).
- Tag every claim with its evidence class: `re-executable`, `replay-only` or `private-only` (P-D5). Drop or replace private-only numbers.
- Scaling: fits are finite-range growth of a named work event over the chosen sizes. Keep operation counts distinct from elapsed time. Report censoring, caps, missing sizes, and drop-largest refits (a refit spanning less than 8x is range-limited). Never fit a cap as a completed observation.

## Auditing others' numbers
For every reported number: locate its receipt field, recompute from raw data, check the denominator, unit, grouping and evidence class, and record agreement in a table (claim, location, receipt, recomputed, class, status). Send disagreements to the coordinator with file and line.
