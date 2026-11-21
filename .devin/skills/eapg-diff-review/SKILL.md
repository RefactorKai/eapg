---
name: eapg-diff-review
description: Peer Reviewer toolkit. Invoke with eapg-token-budget before reviewing a diff or choosing independent validation checks.
---

# EAPG diff review

Follow `eapg-ground-rules` and `eapg-peer-review`; retain reviewer independence.

## Narrow by diff, not by trust
- Resolve the PR's actual base branch from its metadata (do not assume local `main` is current). Set `base` to that branch, run `git fetch origin "$base"`, then `git diff --stat "origin/$base...HEAD"` and `git diff --name-only "origin/$base...HEAD"`. Alternatively, use `gh pr diff <number> --name-only` for the PR's file list.
- Read each relevant file: `git diff --unified=5 "origin/$base...HEAD" -- path/to/file`; inspect callers and `nl -ba path/to/file | sed -n '20,65p'` for precise findings. Include uncommitted changes separately if reviewing a working tree.
- Follow concrete changed-symbol dependencies rather than reading the whole repository; widen only for a specific risk. Request surgical remedies, not drive-by refactors.
- Review in checklist order: scope/frozen pipeline/checksums; sealed/private data; gates; receipt-backed numbers; wording/AI disclosure; scientific validity; claims versus code. Cite acceptance checklist IDs.
- During investigation rerun only affected checks, not unrelated suites; reuse outputs only when inputs are unchanged. Before final review run all required R4 gates, including `python -B eapg.py verify --mode linux` and `python -B -m pytest -q -rs`, plus checksum status. Skips and unavailable tools are blockers, not passes.

## Evidence and findings
- Use plain Git and gate commands for audit evidence, retain full logs and exit status. RTK may navigate exploratory output, never replace the evidence.
- Order findings by severity, with `file:line`, observed behavior, causal evidence, checklist ID and concrete remedy. Distinguish verified facts from suspicions.
- Never Caveman-compress findings, PR evidence or audit conclusions. Report negative checks and unverified links; never call a claim confirmed from merely plausible code.
