---
name: eapg-token-budget
description: Team-wide efficiency rules for every EAPG bot. Invoke after ground rules at task start, before searches, commands, or status notes.
---

# EAPG token budget

Follow `eapg-ground-rules` first. Efficiency never relaxes R1-R8.

## Read less, keep evidence
- Activate `source .venv/bin/activate`. Use `command -v rtk` before wrapping Git, ls, tests or builds; otherwise use the plain command. Install optional tools with `bash development/tools/install_agent_tools.sh`.
- Exploration: `rtk git status`, `rtk ls`, `rtk pytest development/test_verify.py -x`; fallback: `git status`, `ls`, `python -B -m pytest development/test_verify.py -x`.
- Find paths with `rg --files development`; search with `rg -n 'symbol' path`; read `sed -n '20,70p' path`. Use `ast-grep run --lang python --pattern 'def $F($$$): $$$' development/example.py` only on an existing, in-scope file.
- Batch independent commands, not dependent edits/checks. Reuse recent observations; do not re-read files just written unless reviewing the final diff or resolving uncertainty.
- Run affected tests first while iterating; full required gates once on final inputs before review: `python -B -S eapg.py status`, `python -B eapg.py verify --mode linux --verbose`, `python -B -m pytest -q -rs`. Changes to their inputs require rechecking.

## Evidence is not a summary
- Never compress or truncate receipts, audit evidence, gate logs, manuscript data, PR evidence or review findings. R4/R5 require raw full output, exit status, skips and reasons; retain it locally before showing a short navigation summary.
- For evidence, run plain commands into a persistent log under `$HOME/eapg-agent-logs/`; capture exit status before filtering. RTK summaries are exploration only, never gate evidence. Respect D5: private logs stay local and never enter git or external tools.
- For exploratory build logs only: `rtk err python -B eapg.py build-paper --clean` shows errors/warnings; evidence builds remain plain.

## Surgical work
- Locate a local bug from its stack trace or a targeted symbol/error search first. Read only relevant ranges and direct callers/tests; no whole-repo reads or broad exploration for a local fix.
- Make the smallest complete diff. No drive-by refactors, reformatting or unrelated fixes. Widen scope only when a traced dependency requires it; explain why.

## Choose by role
- Invoke `ponytail` for code changes: smallest complete change, validation intact.
- Invoke `caveman` only for chat and transient status notes; default lite means concise grammatical prose, no forced broken grammar. Never apply it to manuscripts, receipts, persisted audit notes, PR evidence or review findings.
- Load only the current role's toolkit: Analyst `eapg-receipt-queries`; Engineer `eapg-targeted-testing`; Writer `eapg-latex-fastpath`; Scout `eapg-citation-lookup`; Reviewer `eapg-diff-review`. Do not load every toolkit.
