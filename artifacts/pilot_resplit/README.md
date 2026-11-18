# `artifacts/pilot_resplit/` — Strict 13-Group Pilot Refit & 6×2 Ablation

Contains the strictly grouped 5-fold pilot cross-validation receipts after pruning all shared template and prompt-hash edges across `pilot100_results.json` (`100` pairs across `13` connected groups; fold sizes `19, 19, 19, 21, 22`).

## Files
- [`results.json`](results.json) (SHA-256 `a89d40d0846b1e3cf16bfc85faa9c30d1f07bce1431a70d3b38dec5d4cb5bebb`) — Grouped 5-fold `abstract_graph` QLoRA vs. Base vs. refined Symbolic (`def_use=True`) refit predictions and contrasts (`assemble_pilot_resplit.py`, `train_pilot_resplit.py`).
- [`ablation_results.json`](ablation_results.json) (SHA-256 `5302a926d68d4bb975c2fd2565a588d09ae3a3bdf49aba580c63f1db6f52c83d`) — Saved candidate logits and scores for all six prompt serializations (`raw_code`, `hotspot_raw`, `static_eapg`, `abstract_hits_only`, `abstract_graph`, `full_eapg`) across Base and QLoRA (`Qwen2.5-Coder-1.5B` 4-bit NF4), Unconstrained vs. Slice-Constrained decoding, and four fixed-slice non-neural baselines (`uniform`, `raw_order`, `symbolic def_use=False`, `symbolic def_use=True`) backing Table II (`tab:eapg-resplit-ablation`). Note: `abstract_graph` reuses the `pilot-resplit-2026-11-11` fold checkpoints with identical 100-pair group and fold assignments (`split_sha256` differs between `3e7a4f34...` and `e2dce2ad...` because the ablation manifest hashes prompts across all six representations).

## Replay Commands

```sh
python -B eapg.py replay --stage resplit
python -B eapg.py replay --stage ablation
```
