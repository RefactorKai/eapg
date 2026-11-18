# EAPG Phase 1 correction

This release preserves the original pilot and implements the [Board of Audit Professors' findings](../board_of_audit_professors.md) in a versioned manuscript and a targeted scaling rerun.

| Item | Evidence |
|---|---|
| [Corrected paper](paper_sections_and_refs.pdf) | Recompiled from the [revised source](paper_sections_and_refs.tex), [references](references.bib), and [Table IV](table_ablation.tex) in this directory. |
| [Fast recurrence correction](scaling/README.md) | The 25 affected fast implementations use unsigned arithmetic modulo 2^64. The addendum records outputs, execution statuses, counters, and fits. |
| [Localization verification](verify_localization.py) | Checks frozen hashes, reconstructs Table IV scores, and reproduces the matched-mask and group-weighting diagnostics from saved logits and predictions. |
| [Phase 2 protocol](phase2_protocol.md) | Prospective plan for external validation with eligibility, safety, blinded reference labeling, and group-aware reporting. |

## What was rerun

The fast-side recurrence rerun replaces the A2.1 and B.3 fast work-exponent evidence. All 125 fitted runs and 75 additional checks matched a modular oracle. Mean fast work exponents round to 1.02 and 1.01, respectively. The original slow and corrected fast outputs agreed on the affected 25 pairs at sizes 16 and 24. Paired equivalence at larger sizes was outside the rerun.

Table IV is based on the original held-out predictions. The correction changes the baseline labels and explains the search-reduction convention. The post-hoc shared-mask results and equal-template-group averages are recalculations of those predictions. The six SHA-256 digests in the audit report identify the frozen source, manuscript, pilot data, and evaluation evidence. This release did not repeat GPU training or score external submissions.

The bibliography now uses the published PIE and Extra-P records. The repair board retained the EvalPerf author order after comparing it with the authors' metadata. [PIE record](https://dblp.org/rec/conf/iclr/ShypulaMZ0GYHNR24.html) · [Extra-P record](https://doi.org/10.1145/3437801.3441613) · [EvalPerf author metadata](https://arxiv.org/abs/2408.06450)

## Reproduce the checks

Run these commands from the repository root with Python 3.14. Use the pinned tokenizer option for an additional CPU-only replay of all seven prompt modes and the five-fold assignment.

```powershell
python artifacts/phase1_correction/verify_localization.py
python artifacts/phase1_correction/verify_localization.py --verify-prompts
python artifacts/phase1_correction/verify_localization.py --write-table
```

The verifier's default mode uses the Python standard library. The prompt replay loads local Qwen2.5-Coder-1.5B tokenizer revision `df3ce67c0e24480f20468b6ef2894622d69eb73b` and uses the frozen pipeline's tree-sitter parsing. This revision reproduced the stored folds and the 498-token maximum. The historical GPU log records the model family but does not record a model snapshot hash or adapter checkpoints.

The local replay environment used Python 3.14.2, tree-sitter 0.26.0, tree-sitter-cpp 0.23.4, Transformers 5.17.0, and tokenizers 0.23.2. The local GPU stack contained PyTorch 2.10.0+cu128, bitsandbytes 0.49.2, PEFT 0.19.1, and Accelerate 1.15.0. These are versions observed during verification. See the [scaling addendum](scaling/README.md) for its compiler and replay commands.

To rebuild the PDF, run LaTeX and BibTeX from this directory. Use IEEEtran and the standard packages declared in the source.

```powershell
pdflatex -halt-on-error -no-shell-escape paper_sections_and_refs.tex
bibtex paper_sections_and_refs
pdflatex -halt-on-error -no-shell-escape paper_sections_and_refs.tex
pdflatex -halt-on-error -no-shell-escape paper_sections_and_refs.tex
```
