---
name: eapg-paper-writing
description: Rules for the EAPG Paper Writer - claim discipline, receipt macros, banned wording, limitations, AI-use disclosure and the LaTeX build. Invoke before drafting or editing anything under manuscript/, an abstract, a caption, a cover letter or a response to reviewers.
---

# EAPG paper writing

Follow `eapg-ground-rules` first.

## Claims
- Write only what a committed receipt or cited source supports. For each claim keep its source: receipt field, script, or BibTeX key.
- Scope: a controlled study of finite-range growth of the named work event over the chosen sizes. Not asymptotic complexity, not runtime scaling, not general algorithm discovery, not natural-code performance.
- Banned without dated, timestamped evidence or wall-clock validation: "pre-registered", "registered", "first", "asymptotic", "runtime scaling". Also avoid "novel", "state of the art", "proves" and "ground truth". Repository history starts 2026-11-18, so no pre-registration claim is possible for the paired study (m11).
- Model-rater results are "model agreement" or "model-based validation" (see `eapg-blind-validation`), never "human", "expert" or "manual" validation. Only the WP-H1 panel may be primary; every other LLM judgment is secondary.
- Every claim's evidence class (`re-executable`, `replay-only`, `private-only`) is in `development/paper_claims.json`. No private-only claim appears anywhere; replay-only results are labelled in the text or caption (P-D5).

## Numbers
- Every number is a macro from a generated receipt file (WP-A3); never type digits for results. Write rates as `k/n` with the percentage and name the CI method nearby.
- Report the limitations that hold today: Part A is not primary-sized (`primary_sized=false`), Part B shows no positive transfer (`positive_transfer_evidence=false`), and Part A false alerts (5/5 quadratic shams, 0/5 linear shams, 10/10 appropriate controls). Check the current receipts before restating them.
- Name the unit of every rate (pair, equal-group, macro) and never mix them unlabelled.
- Negative, indeterminate and excluded cases appear with counts and reasons.

## Structure (empirical SE paper)
Use the ACM SIGSOFT Empirical Standards (General Standard plus the experiment or benchmarking standard) as the checklist: research questions, motivation, methodology named and justified, data collection, analysis, threats to validity (construct, internal, external, conclusion), and a data-availability statement that says which files are withheld and why (D5). The paper is the 147-pair paired study with EAPG as RQ3 development evidence (D1 = A); contributions follow checklist N2.

## AI-use disclosure
- AI tools are never authors (ACM and Springer Nature both hold that they cannot take responsibility for the work).
- Disclose generative-AI use as the venue requires: ACM asks for disclosure in the acknowledgements or the body where AI generated text, tables, code or analysis; Springer Nature asks for documentation in the Methods (or a suitable section) and does not require declaring AI-assisted copy editing. Check the live policy of the chosen venue before submission.
- LLM-agent judgments in results are secondary analyses with model, version and prompts disclosed (prompts in an appendix or artifact).

## Build
- Build `manuscript/paired_mechanism.tex` with `pdflatex`/`bibtex` and `-no-shell-escape -halt-on-error` in `manuscript/`; `python -B eapg.py build-paper --clean` builds the EAPG development paper. Zero undefined references, no new overfull boxes. Switch to the venue template (EASE ACM or EMSE Springer) before the rewrite (m13).
- Every BibTeX entry comes from the Literature Scout with a verified DOI or URL; no invented entries.
- Edit sentences surgically and keep the macro names stable so the verifier still matches.
