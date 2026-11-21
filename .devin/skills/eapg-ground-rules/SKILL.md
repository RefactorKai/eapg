---
name: eapg-ground-rules
description: Project ground rules for every EAPG paper-team bot (Data Analyst, Experiment Engineer, Paper Writer, Literature Scout, Peer Reviewer). Invoke at the start of any task in RefactorKai/eapg, before editing files, opening a PR, or writing any claim or number.
---

# EAPG ground rules

The team is writing a Q1/Rank A paper from this repository. The owner has not approved release; work continues until the repository is "good enough". These rules bind every role. The role skills (`eapg-statistics`, `eapg-experiments`, `eapg-paper-writing`, `eapg-literature`, `eapg-peer-review`) add to them and never relax them.

## Read first
1. `README.md`, `docs/REPRODUCIBILITY.md`, `docs/ARCHITECTURE.md`
2. The current direction: `docs/PAIRED_STUDY_HANDOFF.md`, `docs/PAIRED_STUDY_RUNBOOK.md`, `docs/PAIRED_STUDY_INTAKE.md`, `docs/RESEARCH_REWORK_PLAN.md`
3. Audit history: `AUDIT.md`, `artifacts/board_of_audit_professors.md`, `docs/INDEPENDENT_AUDIT.md`, `PHASE2_DECISION.md`
4. Two manuscripts exist: `manuscript/paper.tex` (EAPG localization, built by `eapg.py build-paper`) and `manuscript/paired_mechanism.tex` (paired-pair audit, latest direction). Confirm with the coordinator which one a task targets before editing.

## Hard rules (audit section 12)
- **Sealed data.** The PIE test split (`pie_test.jsonl`, `pie_test_static_manifest.json`) stays sealed. Never read, sample, or fall back to it. Never reuse an evaluation case for development; every inspected case becomes development data.
- **Frozen release.** `pipeline.py` and every file listed in `SHA256SUMS` are frozen release content. Changes go in `development/` or behind a new versioned entry point. A PR that changes any checksummed file updates `SHA256SUMS` in the same PR, and only with the owner's explicit approval of a new release version. Do not touch modules hashed by `custodian_revision()`, `prediction_revision()`, `scoring_revision()` without re-sealing the custody chain.
- **Numbers come from receipts.** Every number in the paper is a LaTeX macro generated from a committed JSON receipt (work package WP-A3). Never type a number by hand. Report the denominator with every rate (`15/20 = 75.0%`) and name the CI method.
- **AI judgments are secondary.** LLM-agent judgments are reported only as secondary analyses, with model, version and prompts disclosed. Follow the ACM or Springer Nature AI-authorship policy of the chosen venue (see `eapg-paper-writing`).
- **Banned words without evidence.** Do not write "pre-registered", "first", "asymptotic", or "runtime scaling" unless dated evidence or wall-clock validation backs it. Write "finite-range growth of the named work event".
- **One PR per work package.** `python -B eapg.py verify --mode linux` and `python -B -m pytest -q` are green before review.

## Owner decisions since the audit
- **No human raters.** Validation is two blind sessions on different models plus a third-model adjudicator (`eapg-blind-validation`). Report it as model agreement, never as human validation, expert labels or ground truth.
- **No public release of private files.** `.codex/private/`, raw PIE archives, sealed manifests, adapters, model snapshots and custody receipts never enter git, a PR, a paste, a chat message or an external service.
- **Self-audit.** Each bot audits its own work with independent subagents or bots on different models before handing it on.

## Working discipline
- Setup: `source .venv/bin/activate`. Startup checks: `python -B -S eapg.py status` (all `SHA256SUMS` match), then `python -B -m pytest -q` (about 15 s; 8 Linux sandbox skips are expected outside user-systemd hosts).
- Never execute unvetted C++ outside the Bubblewrap launcher `development/gate1_sandbox.py`.
- Scientific honesty: report failed gates, false alerts, negative and indeterminate cases, and every case disposition. Never fabricate citations, attestations, cases or filler to inflate counts.
- Surgical edits; do not reformat unrelated files. Commit only with a PR, never to `main`.
- Any finding that contradicts a receipt, the paper or another bot's claim goes to the coordinator with the file and line, not a silent fix.
