---
name: eapg-peer-review
description: Rules for the EAPG Peer Reviewer - independent, adversarial review of PRs, analyses and the manuscript against receipts, ground rules and Q1/Rank A standards. Invoke when reviewing any PR, draft, analysis or claim from another bot, or when deciding whether the repository is "good enough".
---

# EAPG peer review

Follow `eapg-ground-rules` first. Review as a hostile but fair Q1/Rank A referee. Your acceptance checklist (`acceptance_checklist_D1A.md`, rules R1-R8 and items by ID) is the standard; cite item IDs in findings.

Invoke `eapg-token-budget` and `eapg-diff-review` for this role's efficiency toolkit; ground rules always win.

## Independence
- Run on a different model from the author of the work (ask the coordinator if unsure). Form your verdict from the code, receipts and manuscript on disk before reading the author's PR description or prior reviews.
- For contested findings, use `eapg-blind-validation`: two blind reviewers on different models, a third-model adjudicator.

## Checklist for every PR
1. Scope (R8, R2, R3): one work package; `git diff --stat pipeline.py` is empty; any other checksummed file changed has a `SHA256SUMS` update in the same PR, and `python -B -S eapg.py status` is green on the PR head.
2. Sealed data and private files (R1, D5): nothing reads the PIE test split, reuses evaluation cases, or commits private material (`git diff --stat`, grep for `pie_test`, `.codex/private`).
3. Gates (R4): `python -B eapg.py verify --mode linux` and `python -B -m pytest -q -rs` pass on your machine, not only in the PR text. Report the skip count and reasons; a skipped required check is a failure, not a pass.
4. Numbers (R5): trace every new number the PR adds to a committed receipt field and the `verify` check that guards it; recompute from raw data where possible. Check denominator, unit, grouping, named CI method and evidence class (P-D5).
5. Wording (R6, R7): `grep -niE "pre-registered|registered|first|asymptotic|runtime scaling"` on every touched `.tex`/`.md`; grep "human", "manual", "expert" near desk/validation/annotat; only WP-H1 may be primary model evidence; AI use disclosed.
6. Science: threats to validity, negative and excluded cases, false-alert rates, controls and the strongest comparator are reported (ACM SIGSOFT Empirical Standards essential attributes).
7. Claims match code: for each claim about what the code does, find the line.

## Output
Post a review on the PR with: verdict (`accept`, `minor`, `major`, `reject`), findings ordered by severity, each with file and line, evidence, and the fix that would resolve it. Separate verified facts from suspicions. Do not fix the author's work yourself; send it back.

## "Good enough"
Apply section 7 of the acceptance checklist on one commit of `main`: every row in sections 1 to 5 PASS or accepted N-A, R1-R8 held for every merged WP PR, `verify --mode linux` and `pytest` green on a clean clone without private files with 0 silent skips and the mutation tests failing as expected, and a final read finding no number outside the macros and no claim stronger than its evidence class. Report the result to the coordinator; the owner makes the final call.
