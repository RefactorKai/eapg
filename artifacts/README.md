# `artifacts/` Index

Research artifacts spanning the frozen Phase 1 pilot, Phase 1 independent audit corrections, Phase 2 PIE acquisition/fixtures, the strict 13-group six-representation ablation, and the library operation-proxy calibration panel.

> **Current Paper vs. Historical PDFs:** The canonical manuscript is [`../manuscript/paper.pdf`](../manuscript/paper.pdf). [`paper_sections_and_refs.pdf`](paper_sections_and_refs.pdf) (pre-audit Phase 1) and [`phase1_correction/paper_sections_and_refs.pdf`](phase1_correction/paper_sections_and_refs.pdf) (post-Phase-1 correction) are retained solely as immutable snapshots verified by [`../SHA256SUMS`](../SHA256SUMS) against [`board_of_audit_professors.md`](board_of_audit_professors.md) and [`../AUDIT.md`](../AUDIT.md).

---

## Subdirectories

| Path | Contents | Pinning / Verification |
|---|---|---|
| [`scope_isolated_pilot/`](scope_isolated_pilot/README.md) | Frozen 100-pair synthetic pilot receipts (`pilot100_results.json`) and 23-group `node_only_ablation/` (`evaluation_results.json`, `table_ablation.tex`) | Pinned in [`../SHA256SUMS`](../SHA256SUMS); verified by `eapg.py verify` & `eapg.py replay --stage pilot` |
| [`phase1_correction/`](phase1_correction/README.md) | Independent Phase 1 audit response, `200`-recurrence scaling check (`scaling/`), Phase 2 custody probes, and Phase 2 protocol spec | Pinned in [`../SHA256SUMS`](../SHA256SUMS); verified by `verify_release.py` (`eapg.py replay --stage release`) |
| [`phase2_data/`](phase2_data/README.md) | PIE `p03497` counters/workloads (`development_*.json`), `prepare_pie.py`, historical `run_development.py`, and Gate 2 AST/selector tests (`test_phase2_ast.py`, `test_phase2_selection.py`) | Core JSONs & runner pinned in [`../SHA256SUMS`](../SHA256SUMS); Gate 2 tests run in `eapg.py verify --mode linux` & `pytest` |
| [`pilot_resplit/`](pilot_resplit/README.md) | Strict 13-group 5-fold `abstract_graph` refit (`results.json`) and full 6-representation × 2-decoding ablation (`ablation_results.json`) | Verified by `eapg.py replay --stage resplit` and `eapg.py replay --stage ablation` |
| [`weighted_panel/`](weighted_panel/README.md) | Locked container-proxy calibration (`lock.json`, `lock-aborted.json`, `results.json`) across `std::find`, `std::count`, `std::reverse` (`-O0/-O2/-O3`, `480` checks) | Verified by `eapg.py replay --stage library` |

## Frozen Root Files (`SHA256SUMS`-Pinned)
- [`board_of_audit_professors.md`](board_of_audit_professors.md) — Phase 1 board-of-audit report (`76044792...`).
- [`paper_sections_and_refs.tex`](paper_sections_and_refs.tex), [`paper_sections_and_refs.pdf`](paper_sections_and_refs.pdf), [`references.bib`](references.bib) — Pre-audit Phase 1 snapshot retained solely for historical hash audit parity with [`../AUDIT.md`](../AUDIT.md).
