# Path B empirical census artifact

The [147-slot ledger](ledger.json) and [derived tables](tables.md) support the paired manuscript. The [active manifest](manifest.json) indexes the standalone Path B artifact. The [historical ledger](historical-ledger.json), [tables](historical-tables.md), and [manifest](historical-manifest.json) preserve the 24-slot record. The [authored timing receipt](a01-steady.json) records separate exploratory in-process measurements that are not used in the manuscript.

## Replay the artifact

From the repository root, run `python -B -S artifacts/paired_development/replay.py`. The verifier checks the public inventory, rederives both tables, recomputes the timing statistics and checks the row-to-evidence links using Python's standard library. An independently recorded manifest digest can be supplied with `--manifest-sha256`.

Append `--verify-local` to check the authorized custody files, the execution and prediction reruns, and the static result projections. The default custody roots are `.codex/private` in the repository and its parent workspace. Authorized independent checkouts can pass `--repo-custody` and `--workspace-custody`. An ordinary public checkout can reproduce all 147 slot summaries and public tables. Local verification requires the indexed custody inputs.

The [precedence sweep](precedence-sweep.json) reports syntax occurrences with explicit parse coverage and an independently witnessed Half Reflector defect. The [retrospective agreement](desk-agreement-existing.json) and [prospective re-audit](desk-agreement-reaudit.json) report separate observed panels. The re-audit uses a stratified draw of exclusions, with three isolated AI desk auditors blinded to the previous decisions and measured outcomes. Restricted packets, source copies and individual votes remain in custody.

## Reproduce the new experiments

From the canonical repository root, prepare each of the five selected slots with Windows Python and the pinned tree-sitter dependencies. Preparation uses only the PIE validation split and the CppPerf source blobs named in the ledger. Keep the local upstream source files in their custody locations.

```powershell
python -B -m development.paired_study.path_b_run prepare RANK NEW_DIRECTORY
```

Use ranks 17, 60, 62, 71 and 137. Preparation prints the identifier for the prepared bundle. From the same directory in Ubuntu WSL2, use the designated isolated runner for all C++ builds and executions.

```bash
python3 -B development/probe_gate1.py --probes-only
python3 -B -S -m development.paired_study.path_b_run run NEW_DIRECTORY PREP_SHA NEW_RECEIPT.json
python3 -B -S -m development.paired_study.path_b_run preprocess-support NEW_SUPPORT.json
python3 -B -S -m development.paired_study.steady NEW_TIMING.json
```

The runner seals a separate prediction before executing the restoration and sham. The preparation and execution receipts are under `.codex/private/lab/path-b-census/phase-b/<rank>/` in the canonical repository, and `support.json` records the ten dependency-only stops. Local receipts and prepared sources require access to their custody folder. The five source oracles and edit sites are in [path_b_cases.py](../../development/paired_study/path_b_cases.py).

The census build uses `python -B -S -m development.paired_study.path_b_close` with those local receipts. To reproduce the public tables from the final ledger and the timing receipt, run `python -B -S artifacts/paired_development/replay.py` from the repository root.

## Historical 24-slot acquisition and runs

- Use only the **PIE validation** file with SHA-256 `6608a303c5c6ab61e7936599f3aa8cbde67bc36007e1a9739d7868665c531dab`. The [intake instructions](../../docs/PAIRED_STUDY_INTAKE.md) identify the published validation input and reproduce the draw. The local preparation scripts expect `.codex/private/pie-download-VkVck8zh/pie_val.jsonl` under the workspace root, one level above the canonical repository. Read the exact submission IDs in `ledger.json`.
- Fetch the [fixed CppPerf tree](https://api.github.com/repos/vizual1/CppPerf/git/trees/a7cba4f6ced9535ab652f1589f1e31bf324edfe6?recursive=1) and the pinned old and new upstream files named by the intake metadata and source pin receipts. The `fmt` run pins the `format.h`, `base.h` and `format-inl.h` Git blobs. The LeetCode run pins the submission source. The `sqlpp11` run pins both binder sources and the date v3.0.0 and SQLite 3.46.1 headers. Its host runtime library SHA-256 is recorded in the execution receipt. Keep upstream licenses and acquisition terms with retrieved sources.
- The intake command writes the same case list when the inputs match. The combined draw SHA-256 is `76196f0a83422f44df6f990c8412352c8a647b03cc3dbd362ba6dbbd42e9c5a1`. `ledger.json` carries one row per distinct problem or project. Three groups of repeated workload streams and compiler modes are within-case checks.

## Rerun the historical isolated measurements

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

Each supported case isolates target, reference, restoration, and sham, checks plain and UBSan outputs against an independent oracle, and validates exact logical counts at O0/O2/O3. Blind inputs contain the original target and reference observations. The paired predictor checks its pinned trace and source-map digests. At B.3, the `p03788` diagnostic records a disagreement between the previously accepted reference and the independent oracle, so the case has no fitted screen. HiGHS and OpenTelemetry stopped at B.3 during dependency-only preprocessing under the current Gate 1 single-translation-unit runner. The checks require the full solver or SDK runtime. The artifact records preprocessing diagnostics for these cases.

The scopes in `tables.md` describe source-level operations. The artifact makes no runtime, held-out transfer, or natural ranking claim.
