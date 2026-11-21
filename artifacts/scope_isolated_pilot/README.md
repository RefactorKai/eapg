# `artifacts/scope_isolated_pilot/` — Frozen 100-Pair Synthetic Pilot

Archived Phase 1 evidence over `100` synthetic C++17 pairs spanning `23` template groups (`Track A1` state corruption, `Track A2` missing guard/memo, `Track B` algorithmic replacement). All files in this directory are pinned in [`../../SHA256SUMS`](../../SHA256SUMS).

## Contents
- [`pilot100_results.json`](pilot100_results.json) (SHA-256 `4a3b563cdd54c471f39df95e7d40ec3ae5433259795cadcde80272955ea44cb5`) — Per-pair `pipeline.py` outputs, four-tier slicing sets (`c_naive_work`, `c_inter_only`, `c_unpruned`, `c_pruned`), symptom selection (`100/100` work vs. `80/100` hits), and `1.90` (`89.0%` reduction) slice sizes backing Table I (`tab:eapg-pilot-slicing`).
- [`pilot100_reexec_receipt.json`](pilot100_reexec_receipt.json) (SHA-256 `a3e38e8b4b256453811c9cc69d2bc2a56f4b0e6571fcfe4f64120c73627a91f8`) — Fresh re-execution of the 100 embedded slow/fast sources through frozen `pipeline.run_pilot_100_study.process_pair`: the regenerated `pilot100_results.json` is identical to the archived bytes after CRLF line-ending normalization (Linux writes LF, the archive is CRLF; `line_endings`, `fresh_pilot_raw_sha256`) (`0` mismatches over `3000` fields, `0` decision flips over `1800` pair decisions), and every slow/fast program's per-node raw hit/work counters per ladder scale plus dual-family fits (`alpha`, `beta`, `r2_poly`, `r2_exp`, growth class) are archived. Verification fails on any difference that remains after that normalization, and normal reexec runs the full static check on this receipt first. `comparison.vs_receipt` is a self-comparison at write time and later a regression check against this script's own earlier output, not independent evidence (`self_check`). `proxy_defaults` reruns the pilot with member calls on undeclared receivers weighted `1` (prospective default) instead of `size()` (archived): `0` of `3598` instrumented nodes change weight, so pilot values are identical under both defaults (`0` mismatches, `0` decision flips). **Not a sandboxed result:** this receipt was produced with g++ 11.4.0 on the host, and every preprocess, compile and binary run went through frozen `pipeline.py`'s own subprocess calls, outside [`development/gate1_sandbox.py`](../../development/gate1_sandbox.py) (recorded in `provenance.sandbox`). The sandboxed rerun is deferred to the WP-F1 container (m9).
- [`node_only_ablation/evaluation_results.json`](node_only_ablation/evaluation_results.json) (SHA-256 `1b0e5d8fbf53539543b894ca0ebd0646d244942ef1007a1d0fc9a90384235d14`) & [`node_only_ablation/table_ablation.tex`](node_only_ablation/table_ablation.tex) — Historical 23-group Phase 1 node-only ablation (`6b-slice` `98/100` pair / `93.48%` group vs. Variant 2 `96/100` pair / `95.65%` group).

## Verification Commands

```sh
python -B eapg.py replay --stage release
python -B eapg.py replay --stage pilot
python -B eapg.py verify --mode reexec                       # recompile + re-profile, compare with both files above
python -B development/reexec_pilot.py --static               # receipt fits recomputed from raw counters, no compiler
```
