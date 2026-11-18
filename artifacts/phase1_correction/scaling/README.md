# Corrected fast recurrence profiles

This rerun covers the 13 A2.1 and 12 B.3 fast fixtures affected by signed overflow. The runner verifies the frozen corpus and pipeline hashes before compiling the synthetic sources. It stores the corrected sources, outputs, exit status, per-node counters, and both fit families in `fast_recurrence_results.json`.

The corrected fast programs evaluate the recurrence modulo 2^64 with unsigned 64-bit arithmetic and preserve the B.3 fixture-specific output offset. The A2.1 memo sentinel is the maximum unsigned value, which the independent oracle verifies never occurs among memoized values through the largest tested size. The runner checks that each fast program retains the original macro-node roles, parent edges, and counter weights. It also makes the inherited instrumenter's successful exit handler return normally after flushing the counters.

| Mechanism | Fast fixtures | Mean of per-fixture maximum work exponent |
|---|---:|---:|
| A2.1 | 13 | 1.02 |
| B.3 | 12 | 1.01 |

All 200 fast outputs matched the Python recurrence oracle. The fit uses 125 clean runs at sizes 16, 64, 256, 1024, and 4096. The 75 additional checks at sizes 24, 91, and 92 are outside the fit. The runner also recompiles the original slow sources and confirms matching output for each affected pair at sizes 16 and 24. The large-size checks establish correctness of the repaired fast programs under the stated modulo oracle. The paired comparison covers the two smaller sizes.

## Reproduction

Run from the repository root with Python 3.14.2, tree-sitter 0.26.0, tree-sitter-cpp 0.23.4, and g++ 15.1.0 (MSYS2 UCRT64) on PATH. The runner creates temporary binaries and replaces the separate corrected JSON only after the checks pass.

~~~powershell
python -B artifacts/phase1_correction/scaling/check_fast_recurrences.py
~~~

This fast-side rerun supplies the two corrected work-exponent cells. The frozen slow profiles and node-localization evaluation serve as the original Phase 1 evidence.
