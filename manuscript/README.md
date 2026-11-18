# Localizing Growth-Changing Edits in C++17 with Execution-Annotated Program Graphs

The [paper](paper.pdf) reports the frozen synthetic pilot, 13-group six-representation ablation, domain/intake audits, and executed bounded multi-agent prospective scalar (Part A) and blinded contract (Part B) studies. See [Reproducibility](../docs/REPRODUCIBILITY.md) and [Independent Audit](../docs/INDEPENDENT_AUDIT.md) for verification tiers, gate dispositions, and private custody boundaries.

Build cleanly from the repository root with `eapg.py` (requires `pdflatex` and `bibtex`):

~~~sh
python -B eapg.py build-paper --clean
~~~

From the repository root, replay all saved evidence strata and manuscript table checks:

~~~sh
python -B eapg.py verify --mode common --verbose
python -B eapg.py replay --stage all
~~~

The [research record](../development/RESEARCH_RECORD.md) documents the adaptation recipe, checkpoint assembly, PIE validation case, and scalar comparison. The [library calibration artifact](../artifacts/weighted_panel/README.md) provides the protocol, original and corrected locks, raw counts, and full rerun commands. The earlier [two-workload search report](weighted_find_results.json) is an archived single-feature calibration precursor superseded by `artifacts/weighted_panel/`.

The [comparator-swap diagnostic](../development/RESEARCH_RECORD.md#comparator-swap-diagnostic) provides the raw operation counts, predictions, and WSL rerun command for the paired growth labels. The [transitive-edit diagnostic](../development/RESEARCH_RECORD.md#transitive-edit-diagnostic) and [pilot stdout replay](../development/RESEARCH_RECORD.md#pilot-stdout-replay) provide complete execution receipts and fresh-run commands.

The [CPU study runbook](../development/SYNTHETIC_STUDY_RUNBOOK.md) gives the separately pinned custodian, predictor, and scorer commands, along with a fresh authored dry run.

The [scope-boundary calculation](../development/RESEARCH_RECORD.md#scope-boundary-with-analytic-profiles) and [archived comparator-domain audit](../development/RESEARCH_RECORD.md#comparator-domain-and-external-source-feasibility) document the applicability checks and replay commands.
