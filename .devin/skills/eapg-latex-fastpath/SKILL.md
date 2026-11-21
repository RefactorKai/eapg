---
name: eapg-latex-fastpath
description: Paper Writer toolkit. Invoke with eapg-token-budget before locating claims, editing a manuscript section, or compiling LaTeX.
---

# EAPG LaTeX fastpath

Follow `eapg-ground-rules` and `eapg-paper-writing`. Never apply Caveman voice to manuscript or evidence.

## Locate before editing
- Patch only the affected section and direct macro dependencies; no whole-manuscript reads for a local typo and no unrelated reflow.
- Section map: `rg -n '^\\(sub)*section|^\\input|^\\include' manuscript/paired_mechanism.tex`; read only the relevant range and its referenced macros.
- Macro/claim lookup: `rg -n -F 'MacroName' manuscript development -g '*.tex' -g '*.py'`. If `development/paper_claims.json` exists, `jq 'keys' development/paper_claims.json`, then query the actual schema. If absent (as on this checkout), flag it; do not invent a registry or source.
- Check paired receipts with `python -B -S artifacts/paired_development/replay.py --verify-public`; pilot macros with `python -B eapg.py replay --stage manuscript`. Never hand-type result numbers.

## Build once per final edit
- Main paired manuscript, from `manuscript/`: `pdflatex -no-shell-escape -halt-on-error -interaction=nonstopmode paired_mechanism.tex`, `bibtex paired_mechanism`, then the same pdflatex command twice. Stop on any failure.
- EAPG development paper: `python -B eapg.py build-paper --clean` (not the paired submission).
- Capture each command's full stdout/stderr and exit status in `$HOME/eapg-agent-logs/` first. Navigate logs with `rg -n -i -A 3 '^!|error|warning|undefined|overfull' "$HOME/eapg-agent-logs/latex.log"`; no matches is not a successful-build test.
- Keep raw logs for PR evidence; require zero undefined references and no new overfull boxes. Run final ground-rule gates; a filtered log never replaces evidence.
