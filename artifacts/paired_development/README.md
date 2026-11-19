# Paired development artifact

This artifact records the full 24-slot development draw, generates its flow and count tables, and indexes the evidence used in [the manuscript](../../manuscript/paired_mechanism.md). The authored-family results remain separate. The natural cases use scoped source events and independent output oracles. The artifact contains no held-out data or external adjudications.

## Replay the tables

From the repository root:

```powershell
python -B -S artifacts/paired_development/replay.py
python -B -S artifacts/paired_development/replay.py --verify-local
```

The first command checks the public inputs and compares the tables regenerated from `ledger.json` with `tables.md`. The second also verifies the locally retained evidence files indexed by `manifest.json`. The public artifact contains derived counts and acquisition references. Access to the separately held source and execution files is needed to verify those files or rerun C++.

## Acquire the inputs

- Use only the **PIE validation** file with SHA-256 `6608a303c5c6ab61e7936599f3aa8cbde67bc36007e1a9739d7868665c531dab`. The [intake instructions](../../docs/PAIRED_STUDY_INTAKE.md) identify the published validation input and reproduce the draw. The local preparation scripts expect `.codex/private/pie-download-VkVck8zh/pie_val.jsonl` under the workspace root, one level above the canonical repository. Read the exact submission IDs in `ledger.json`.
- Fetch the [fixed CppPerf tree](https://api.github.com/repos/vizual1/CppPerf/git/trees/a7cba4f6ced9535ab652f1589f1e31bf324edfe6?recursive=1) and the pinned old and new upstream files named by the intake metadata and source pin receipts. The `fmt` run pins the `format.h`, `base.h` and `format-inl.h` Git blobs. The LeetCode run pins the submission source. The `sqlpp11` run pins both binder sources and the date v3.0.0 and SQLite 3.46.1 headers. Its host runtime library SHA-256 is recorded in the execution receipt. Keep upstream licenses and acquisition terms with retrieved sources.
- The intake command writes the same case list when the inputs match. The combined draw SHA-256 is `76196f0a83422f44df6f990c8412352c8a647b03cc3dbd362ba6dbbd42e9c5a1`. `ledger.json` carries one row per distinct problem or project. Three groups of repeated workload streams and compiler modes are within-case checks.

## Rerun isolated measurements

Use Windows Python with the pinned `tree-sitter` and `tree-sitter-cpp` dependencies for the prepare commands. Use Ubuntu WSL2, GCC 15.2, Bubblewrap 0.11.1 and the existing systemd/cgroup Gate 1 environment for the run commands. Elevate access to WSL from the Windows host when needed. From the canonical repository directory in Ubuntu first run `python3 -B development/probe_gate1.py --probes-only`. Each preparation prints or records a manifest digest. Pass that exact value as `PREP_SHA` and use a fresh run name. Script paths below are relative to the canonical repository.

| Case | Windows preparation `python -B` arguments | Ubuntu execution `python3 -B -S` arguments |
|---|---|---|
| `p03592` | `.codex/private/lab/p03592-lean-2026-11-19/replay.py prepare` | same script, `runNEW PREP_SHA` |
| `p02316` | `.codex/private/lab/full-b-p02316/replay.py prepare` | same script, `runNEW PREP_SHA` |
| `p00502`, `p02994` | `.codex/private/lab/full-a3/replay.py prepare CASE` | same script, `run CASE runNEW PREP_SHA` |
| `p03788` | `.codex/private/lab/full-a3/replay.py prepare p03788` | `.codex/private/lab/full-a3/reject_reflector.py NEW.json`, using the pinned diagnostic prepared inputs |
| `fmt` | `.codex/private/lab/fmt-2026-11-19/run.py prepare OUT` | same script, `run OUT PREP_SHA` |
| LeetCode | `.codex/private/lab/full-a2/leetcode_replay.py prepare` | same script, `runNEW PREP_SHA` |
| `sqlpp11` | `.codex/private/lab/full-b-a4/sqlpp11/replay.py prepare` | same script, `runNEW PREP_SHA` |

Preparation uses fresh output directories. When a driver fixes its preparation path, use a fresh copy with the same directory depth or reuse the existing hash-verified preparation. `p00464` uses the archived case directory under `.codex/private/p00464-milestone-2026-11-19/`. To rerun it, prepare and run `prepare.py` and `run.py` with Windows and Ubuntu Python, respectively, in a fresh sibling copy with the same depth. Its historic receipt includes intentionally volatile cgroup details. Compare output hashes, count rows, and screen evidence. The initial plan includes that receipt rather than re-executing the completed control.

Each supported case isolates target, reference, restoration, and sham, checks plain and UBSan outputs against an independent oracle, and validates exact logical counts at O0/O2/O3. Blind inputs contain the original target and reference observations. The paired predictor checks its registered trace and source-map digests. The `p03788` diagnostic preserves the reference disagreement and produces no fitted screen. HiGHS and OpenTelemetry have dependency-only diagnostics and no execution measurements.

The scopes in `tables.md` describe source-level operations. The artifact makes no runtime, held-out transfer, or natural ranking claim.
