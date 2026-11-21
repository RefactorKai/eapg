---
name: eapg-ground-rules
description: Project ground rules for every EAPG paper-team bot (Data Analyst, Experiment Engineer, Paper Writer, Literature Scout, Peer Reviewer). Invoke at the start of any task in RefactorKai/eapg, before editing files, opening a PR, or writing any claim or number.
---

# EAPG ground rules

The team is writing a Q1/Rank A paper from this repository. The owner has not approved release; work continues until the repository passes the "good enough" test in section 7 of the Peer Reviewer's acceptance checklist (`acceptance_checklist_D1A.md`). These rules bind every role. The role skills (`eapg-statistics`, `eapg-experiments`, `eapg-paper-writing`, `eapg-literature`, `eapg-peer-review`) add to them and never relax them. Where a rule here and the checklist differ, the checklist wins; tell the coordinator.

## Read first
1. `README.md`, `docs/REPRODUCIBILITY.md`, `docs/ARCHITECTURE.md`
2. The paper (owner decision D1 = A): the paired benchmark-qualification study in `manuscript/paired_mechanism.tex` (census size and dispositions from the committed ledger `artifacts/paired_development/ledger.json`, never restated from memory), with EAPG (`manuscript/paper.tex`) entering only as RQ3 development evidence. One manuscript is submitted; never prepare a parallel submission. Background: `docs/PAIRED_STUDY_HANDOFF.md`, `docs/PAIRED_STUDY_RUNBOOK.md`, `docs/PAIRED_STUDY_INTAKE.md`, `docs/RESEARCH_REWORK_PLAN.md`
3. Audit history: `AUDIT.md`, `artifacts/board_of_audit_professors.md`, `docs/INDEPENDENT_AUDIT.md`, `PHASE2_DECISION.md`
4. The acceptance checklist from the Peer Reviewer (ask the coordinator for the current revision). Each work package (WP) is accepted only on evidence in the repo.

## Hard rules (audit section 12, checklist R1-R8)
- **R1 Sealed data.** The PIE test split (`pie_test.jsonl`, `pie_test_static_manifest.json`) stays sealed. Never read, sample, or fall back to it. Never reuse an evaluation case for development; every inspected case becomes development data.
- **R2 Frozen pipeline.** `pipeline.py` is frozen release content and is never edited. New behaviour goes in `development/` or behind a new versioned entry point, with the old path intact.
- **R3 Checksummed files.** Other files listed in `SHA256SUMS` may change, but the same PR updates `SHA256SUMS` and `python -B -S eapg.py status` is green on the PR head.
- **R4 Gates.** `python -B eapg.py verify --mode linux` and `python -B -m pytest -q -rs` are green before review. Skips are not normal: report the skip count and each reason. A skipped required check does not count as green.
- **R5 Numbers come from receipts.** Every number in the paper is a LaTeX macro generated from a committed JSON receipt (WP-A3) and checked by `verify`. Never type a number by hand. Report the denominator with every rate (`15/20 = 75.0%`) and name the CI method.
- **R6 Banned words without evidence.** Do not write "pre-registered", "registered", "first", "asymptotic", or "runtime scaling" unless dated, timestamped evidence or wall-clock validation backs it. Write "finite-range growth of the named work event".
- **R7 AI judgments.** LLM-agent judgments are disclosed with model, version and prompts and are secondary analyses. The one exception is the WP-H1 model panel (desk validation). It may be primary, but it is always called model-based, never "human", "expert" or "manual" validation, and its limits are stated (`eapg-blind-validation`). Follow the ACM or Springer Nature AI-authorship policy of the chosen venue.
- **R8 One PR per work package.**

## Owner decisions since the audit
- **D4: no human raters.** Validation is two blind sessions on different models plus a third-model adjudicator (`eapg-blind-validation`). Report it as model agreement, never as human validation, expert labels or ground truth.
- **D5: no public release of private files.** `.codex/private/`, raw PIE archives, sealed manifests, vote matrices, sweep receipts, historical ladders, adapters, model snapshots and custody receipts never enter git, a PR, a paste, a chat message or an external service.
- **Evidence class (P-D5).** Every paper claim carries one class in `development/paper_claims.json` (created by WP-A3): `re-executable` (recomputed from committed sources), `replay-only` (replayed from a hash-pinned receipt that is itself committed) or `private-only` (needs withheld files, or its receipt cannot be committed). Private-only numbers are dropped from the paper, or replaced by a committed replay-only receipt. Replay-only results are labelled in text or captions. The paper has a data-availability statement saying what is withheld and why.
- **Self-audit.** Each bot audits its own work with independent subagents or bots on different models before handing it on.

## Working discipline
- Invoke `eapg-token-budget` for team-wide efficiency; compression never replaces raw full R4/R5 evidence.
- Setup: `source .venv/bin/activate`. Startup checks: `python -B -S eapg.py status` (all `SHA256SUMS` match), then `python -B -m pytest -q -rs` (about 15 s). Outside a host with `bwrap` and `systemd-run --user`, 7 sandbox tests skip, and 1 slicing test skips without `--pipeline`; report them and do not call the run fully green.
- Never execute unvetted C++ outside the Bubblewrap launcher `development/gate1_sandbox.py`.
- Scientific honesty: report failed gates, false alerts, negative and indeterminate cases, and every case disposition. Never fabricate citations, attestations, cases or filler to inflate counts.
- Surgical edits; do not reformat unrelated files. Commit only with a PR, never to `main`.
- Any finding that contradicts a receipt, the paper or another bot's claim goes to the coordinator with the file and line, not a silent fix.
