---
name: eapg-experiments
description: Rules for the EAPG Experiment Engineer - sandboxed execution, frozen pipeline, versioned entry points, data custody, GPU budget, receipts and CI. Invoke before running, adding or changing any experiment, script, test, launcher or dataset step in RefactorKai/eapg.
---

# EAPG experiments

Follow `eapg-ground-rules` first.

## Where code goes
- `pipeline.py` is frozen and never edited. New behaviour goes in `development/` (paired study: `development/paired_study/`) or a new versioned entry point wired into `eapg.py`, with the old path intact.
- Other files listed in `SHA256SUMS` may change only with a `SHA256SUMS` update in the same PR. Check with `python -B -S eapg.py status` before and after.
- Add a `development/test_*.py` for each new module; `pytest` collects `development/` and `artifacts/phase2_data/`.

## Execution safety
- Every preprocessing, compile and run of C++ goes through `development/gate1_sandbox.py`: private bounded scratch, isolated process tree, supervisor protected, no network. Linux probes: `python -B eapg.py verify --mode linux --with-probes` (needs `bwrap` and `systemd-run --user`).
- Check exit status independently of counter dumps; bound captured output.

## Data custody and evidence class
- Never open the sealed PIE test split. Development cases come from PIE validation or CppPerf under `docs/PAIRED_STUDY_INTAKE.md`; select by a stable hash before reading outcomes and record every disposition with its reason.
- Private bundles live in `.codex/private/` (git-ignored) and never leave the machine (D5).
- `verify` must run on a clean clone without `.codex/private` and report which checks are full re-execution and which are replay-only (P-B4).

## Measurement protocol
- Before running a case, fix the output oracle, cost event, input generator, six geometrically spaced sizes, and three independent workload streams where meaningful. Need at least four common uncapped sizes over an eightfold span.
- Counts and timing are separate claims. Timing uses plain binaries, interleaved randomized version order, warmups, repeats and per-size variability. Record compiler, flags (`-O2` unless the protocol says otherwise), host and toolchain versions.
- Lock ranking and tie rules before predictions. Keep the stronger comparator (value-sensitive change impact) as primary.

## GPU (if used)
8 GB budget: Qwen2.5-Coder-1.5B in 4-bit NF4 double quant, bfloat16, prompt plus answer at most 512 tokens, small batches, `gc.collect()` and `torch.cuda.empty_cache()` around runs. Pin base model, tokenizer and adapter digests in the receipt.

## Receipts
Each run writes a JSON receipt: input and script SHA-256s, environment, seeds, per-size status, raw counters, fits and diagnostics, and dispositions. Regenerate twice and confirm byte-identical output before reporting.

## Before review
- `python -B eapg.py verify --mode linux --verbose` and `python -B -m pytest -q -rs` green. Report the skip count and every skip reason; a skipped required check (sandbox probes, Gate 1 tests) is not green. CI targets 0 skips (m8).
- `pipeline.py` untouched; `SHA256SUMS` unchanged or updated in the same PR; one work package per PR.
