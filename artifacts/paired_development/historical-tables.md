# Paired development evidence

The intake denominator is the fixed development draw. Isolated execution excludes
dependency-only preprocessing. Numeric sample rows report logical operations in
target, reference, restoration and sham order. Metrics vary across cases.

| Corpus | Drawn | A eligible | B dependency-only stops | B executed | Output-oracle failures | Verified restorations | Screened | Growth alerts | Ranking eligible |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| PIE validation | 12 | 6 | 0 | 6 | 1 | 5 | 5 | 0 | 0 |
| CppPerf | 12 | 5 | 2 | 3 | 0 | 3 | 3 | 0 | 0 |
| **Total** | 24 | 11 | 2 | 9 | 1 | 8 | 8 | 0 | 0 |

Desk feasibility was 11/24. Of those eligible,
9/11 ran and 8/9
of the executed cases validated a scoped restoration. All 8
verified cases were screened and 0/8 alerted.
Full alignment and mutual ranking support were available for 0/24
natural cases. Natural localization ties and abstention rates have no eligible
denominator. The final verified controls had no recorded count caps. All draw
slots have dispositions. Annotation time and overlap beyond the drawn group
identifiers were not measured. External labels were collected for 0/24 cases.

## Verified scoped restorations

The fit uses the screened event. Each pair gives the target/reference count ratio
at the largest common size and the slope of the log ratio against log size.
The example input can be smaller than the largest common size.
An alert requires a ratio ≥1.50× and slope ≥0.50 on every registered stream.

| Case | Restoration event | Example input | Target / reference / restoration / sham | Screened event and counts when distinct | Largest ratio / slope by stream | Screen |
|---|---|---|---|---|---|---|
| `p00464` | Logical DP cell writes (clear, seed, and propagation) | 128 × 128, 17 walkers | 1,034,770 / 49,410 / 49,410 / 1,034,770 | Same event | seed-11, seed-29, seed-47 (5.74808× / -1.94744) | `no_alert` |
| `p03592` | Candidate-pair trials | 256 × 512, half black | 131,841 / 65,793 / 65,793 / 131,841 | Same event | rectangular-half (2.00388× / -0.0124189)<br>rectangular-quarter-columns (1.0039× / -0.0288819)<br>square-zero (1.00389× / -0.0273202) | `no_alert` |
| `p02316` | Explicit memo/DP initialization writes | 64 items, capacity 512 | 1,010,101 / 512 / 32,832 / 1,010,101 | Same event | heavier, light, mixed (1972.85× / -1) | `no_alert` |
| `fmtlib/fmt` | Non-initializer precision-state writes | 512 UTF-8 code points | 770 / 258 / 258 / 770 | UTF-8 code-point callback visits (514 / 257 / 257 / 514) | ascii, mixed_width, multibyte_narrow (2× / 0) | `no_alert` |
| `wisdompeak/LeetCode` | Feasibility accumulator writes | 2 computers, 256 alternating batteries | 15,848 / 15,822 / 15,822 / 15,848 | Same event | alternating (1.00164× / -0.0082447)<br>clustered (1.0019× / -0.0103245)<br>homogeneous (1.00152× / -0.00725676) | `no_alert` |
| `p00502` | Destination DP-cell initialization writes | 2 days, 128 items | 42,025 / 384 / 384 / 42,025 | Same event | D2 (109.44× / -1)<br>D3 (82.0801× / -1)<br>D4 (65.6641× / -1) | `no_alert` |
| `p02994` | Subtotal materializations | 64 items, L = −100 | 64 / 1 / 1 / 64 | Item visits plus subtotal materializations (192 / 129 / 129 / 192) | crossing (1.24806× / 0.0107287)<br>negative (1.48837× / 0.0582641)<br>positive (1× / 0) | `no_alert` |
| `rbock/sqlpp11` | SQLite bind calls plus explicit duration normalizations | 256 non-null microsecond bindings | 512 / 256 / 256 / 512 | Same event | alternating-null (1.5× / 0)<br>boundaries, microseconds (2× / 0) | `no_alert` |

## PIE validation dispositions

| Case | Phase A | Phase B | Evidence |
|---|---|---|---|
| `p00464` | eligible | oracle confirmed | Active-rectangle reset removes fixed-table write excess. |
| `p00537` | alignment boundary | not run | Reference difference-array updates eliminate the target’s per-trip scans. Counts are source-derived. |
| `p02621` | fixed contract | not run | A fixed scalar contract supplies no size ladder. |
| `p02639` | fixed contract | not run | The contract supplies five inputs and no size ladder. |
| `p02753` | fixed contract | not run | The string has exactly three characters. |
| `p03635` | fixed contract | not run | The contract specifies one scalar pair, so EOF repetition changes the task. |
| `p03592` | eligible | oracle confirmed | Inner break recovers candidate-pair visits. Table and scalar writes remain separate. |
| `p02698` | host contract | not run | Both exact files force AVX2. The reference also uses native word loads to parse input. |
| `p02316` | eligible | oracle confirmed | Active memo rectangle removes 96.80% of excess initialization writes at the largest registered sample. |
| `p03788` | eligible | output mismatch | B.3 output-oracle failure. The pinned reference, marked Accepted in PIE, returned ABA on (3,7,AAB). The oracle and target variants returned BBA. No fitted count screen. |
| `p00502` | eligible | oracle confirmed | Active destination rectangle matches reference initialization writes on the measured workload. |
| `p02994` | eligible | oracle confirmed | Materialize the subtotal once after selection while preserving both scans. |

## CppPerf dispositions

| Case | Phase A | Phase B | Evidence |
|---|---|---|---|
| `fmtlib/fmt` | eligible | oracle confirmed | Precision traversal merge removes the redundant UTF-8 scan on the registered valid inputs. |
| `wisdompeak/LeetCode` | eligible | oracle confirmed | Both search bounds agree at two computers. Predicate restoration recovers logical accumulator edits. |
| `qicosmos/iguana` | output contract boundary | not run | Source-derived repeated packed segments witness append versus overwrite in the audited reader. |
| `zxing-cpp/zxing-cpp` | output contract boundary | not run | Source-derived cursor witness gives different bounded optional acceptance. End-to-end barcode decode was outside this check. |
| `open-telemetry/opentelemetry-cpp` | eligible | unsupported dependencies | B.3 preprocessing stopped at the current Gate 1 single-translation-unit boundary. The proposed log and span checks require the full OpenTelemetry SDK runtime, including the buffer, exporter and synchronization. |
| `ERGO-Code/HiGHS` | eligible | unsupported dependencies | B.3 preprocessing stopped at the current Gate 1 single-translation-unit boundary. The proposed terminal-copy check requires the full QUASS solver runtime. |
| `rbock/sqlpp11` | eligible | oracle confirmed | The exact binder restoration removes source normalizations with equal output from real SQLite. |
| `jeremy-rifkin/cpptrace` | unsupported metric | not run | The libdwarf allocation/lifetime policy lacks a calibrated common event. |
| `odygrd/quill` | host contract | not run | Changed behavior depends on cache placement and concurrent SPSC access. |
| `projectM-visualizer/projectm` | host contract | not run | The border change requires a graphics context and driver. |
| `google/highway` | host contract | not run | AVX3 specialization. Portable execution bypasses the changed path. |
| `google/snappy` | host contract | not run | AArch64-only ExtractOffset branch. Other hosts bypass the change. |

No natural case met the prerequisites for the paired ranking comparison.
The authored comparison remains a separate one-family experiment. Rewind ranked
5/6 positives first and value-sensitive change impact ranked 6/6 first. Both
reported 0/4 control alerts. The authored a01 timing result remained unconfirmed.

Neither external adjudication nor held-out evaluation is part of this artifact.
