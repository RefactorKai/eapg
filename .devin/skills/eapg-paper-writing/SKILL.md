---
name: eapg-paper-writing
description: Rules for the EAPG Paper Writer - claim discipline, receipt macros, banned wording, limitations, AI-use disclosure and the LaTeX build. Invoke before drafting or editing anything under manuscript/, an abstract, a caption, a cover letter or a response to reviewers.
---

# EAPG paper writing

Follow `eapg-ground-rules` first.

## Claims
- Write only what a committed receipt or cited source supports. For each claim keep its source: receipt field, script, or BibTeX key.
- Scope: a controlled study of finite-range growth of the named work event over registered sizes. Not asymptotic complexity, not runtime scaling, not general algorithm discovery, not natural-code performance.
- Banned without dated evidence or wall-clock validation: "pre-registered", "first", "asymptotic", "runtime scaling", "state of the art", "proves", "ground truth". Use "registered before the run (receipt dated YYYY-MM-DD)" only when a dated, committed receipt exists.
- Model-rater results are "model agreement" (see `eapg-blind-validation`), never human or expert validation.

## Numbers
- Every number is a macro from a generated receipt file (WP-A3); never type digits for results. Write rates as `k/n` with the percentage and name the CI method nearby.
- Report the limitations that hold today: Part A is not primary-sized (`primary_sized=false`), Part B shows no positive transfer (`positive_transfer_evidence=false`), and false alerts (5/10 quadratic shams, 10/10 appropriate controls in the pilot). Check the current receipts before restating them.
- Negative, indeterminate and excluded cases appear with counts and reasons.

## Structure (empirical SE paper)
Use the ACM SIGSOFT Empirical Standards (General Standard plus the experiment or benchmarking standard) as the checklist: research questions, motivation, methodology named and justified, data collection, analysis, threats to validity (construct, internal, external, conclusion), and an availability statement that says which files stay private and why.

## AI-use disclosure
- AI tools are never authors (ACM and Springer Nature both hold that they cannot take responsibility for the work).
- Disclose generative-AI use as the venue requires: ACM asks for disclosure in the acknowledgements or the body where AI generated text, tables, code or analysis; Springer Nature asks for documentation in the Methods (or a suitable section) and does not require declaring AI-assisted copy editing. Check the live policy of the chosen venue before submission.
- LLM-agent judgments in results are secondary analyses with model, version and prompts disclosed (prompts in an appendix or artifact).

## Build
- `python -B eapg.py build-paper --clean` builds `manuscript/paper.tex` with zero undefined references and no new overfull boxes. For `manuscript/paired_mechanism.tex`, run `pdflatex`/`bibtex` with `-no-shell-escape -halt-on-error` in `manuscript/`.
- Every BibTeX entry comes from the Literature Scout with a verified DOI or URL; no invented entries.
- Edit sentences surgically and keep the macro names stable so the verifier still matches.
