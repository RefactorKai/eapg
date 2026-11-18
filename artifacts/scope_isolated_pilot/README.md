# `artifacts/scope_isolated_pilot/` — Frozen 100-Pair Synthetic Pilot

Archived Phase 1 evidence over `100` synthetic C++17 pairs spanning `23` template groups (`Track A1` state corruption, `Track A2` missing guard/memo, `Track B` algorithmic replacement). All files in this directory are pinned in [`../../SHA256SUMS`](../../SHA256SUMS).

## Contents
- [`pilot100_results.json`](pilot100_results.json) (SHA-256 `4a3b563cdd54c471f39df95e7d40ec3ae5433259795cadcde80272955ea44cb5`) — Per-pair `pipeline.py` outputs, four-tier slicing sets (`c_naive_work`, `c_inter_only`, `c_unpruned`, `c_pruned`), symptom selection (`100/100` work vs. `80/100` hits), and `1.90` (`89.0%` reduction) slice sizes backing Table I (`tab:eapg-pilot-slicing`).
- [`node_only_ablation/evaluation_results.json`](node_only_ablation/evaluation_results.json) (SHA-256 `1b0e5d8fbf53539543b894ca0ebd0646d244942ef1007a1d0fc9a90384235d14`) & [`node_only_ablation/table_ablation.tex`](node_only_ablation/table_ablation.tex) — Historical 23-group Phase 1 node-only ablation (`6b-slice` `98/100` pair / `93.48%` group vs. Variant 2 `96/100` pair / `95.65%` group).

## Verification Commands

```sh
python -B eapg.py replay --stage release
python -B eapg.py replay --stage pilot
```
