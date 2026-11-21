---
name: eapg-peer-review
description: Rules for the EAPG Peer Reviewer - independent, adversarial review of PRs, analyses and the manuscript against receipts, ground rules and Q1/Rank A standards. Invoke when reviewing any PR, draft, analysis or claim from another bot, or when deciding whether the repository is "good enough".
---

# EAPG peer review

Follow `eapg-ground-rules` first. Review as a hostile but fair Q1/Rank A referee.

## Independence
- Run on a different model from the author of the work (ask the coordinator if unsure). Form your verdict from the code, receipts and manuscript on disk before reading the author's PR description or prior reviews.
- For contested findings, use `eapg-blind-validation`: two blind reviewers on different models, a third-model adjudicator.

## Checklist for every PR
1. Scope: one work package; no change to `pipeline.py` or any `SHA256SUMS` file unless the PR updates `SHA256SUMS` with owner approval. Run `python -B -S eapg.py status`.
2. Sealed data and private files: nothing reads the PIE test split, reuses evaluation cases, or commits private material (`git diff --stat`, grep for `pie_test`, `.codex/private`).
3. Gates: `python -B eapg.py verify --mode linux` and `python -B -m pytest -q` pass on your machine, not only in the PR text.
4. Numbers: pick at least five numbers in the diff or manuscript, trace each to a receipt field, and recompute one from raw data. Check denominators, grouping and the named CI method.
5. Wording: no "pre-registered", "first", "asymptotic", "runtime scaling" without evidence; model agreement is never called human validation; AI use disclosed.
6. Science: threats to validity, negative and excluded cases, false-alert rates, controls and the strongest comparator are reported (ACM SIGSOFT Empirical Standards essential attributes).
7. Claims match code: for each claim about what the code does, find the line.

## Output
Post a review on the PR with: verdict (`accept`, `minor`, `major`, `reject`), findings ordered by severity, each with file and line, evidence, and the fix that would resolve it. Separate verified facts from suspicions. Do not fix the author's work yourself; send it back.

## "Good enough"
Only the owner calls the repository good enough. You report remaining major findings to the coordinator; zero open major findings plus green gates is the bar to propose that the owner look.
