# Path B empirical census

Six CppPerf patches share the project census and significant-test stratum. The overall
denominator counts each patch once. Every slot has a final disposition.

| Final disposition | 147 distinct | PIE 77 | CppPerf 42 | 119 census | Significant 34 |
|---|---:|---:|---:|---:|---:|
| `desk_blocked` | 8 | 0 | 0 | 0 | 8 |
| `desk_eligible_control_deferred` | 18 | 16 | 1 | 17 | 2 |
| `desk_excluded` | 82 | 45 | 23 | 68 | 16 |
| `execution_oracle_failure` | 1 | 1 | 0 | 1 | 0 |
| `historical_dependency_stop` | 2 | 0 | 2 | 2 | 0 |
| `historical_desk_excluded` | 13 | 6 | 7 | 13 | 1 |
| `support_boundary_closed` | 10 | 0 | 6 | 6 | 5 |
| `verified_growth_evaluation` | 5 | 4 | 0 | 4 | 1 |
| `verified_historical_control` | 8 | 5 | 3 | 8 | 1 |

## Audit flow by frame

| Stage | 147 distinct | PIE 77 | CppPerf 42 | 119 census | Significant 34 |
|---|---:|---:|---:|---:|---:|
| Desk stops | 103 | 51 | 30 | 81 | 25 |
| ↳ Source-level witness | 48 | 18 | 20 | 38 | 11 |
| ↳ Contract-level gap | 48 | 33 | 10 | 43 | 7 |
| ↳ Route-conditional desk stop | 7 | 0 | 0 | 0 | 7 |
| Eligible control or diagnostic deferred | 18 | 16 | 1 | 17 | 2 |
| Single-TU preprocessing stops | 12 | 0 | 8 | 8 | 5 |
| ↳ New dependency-only closure | 10 | 0 | 6 | 6 | 5 |
| ↳ Historical dependency stop | 2 | 0 | 2 | 2 | 0 |
| Reached isolated execution | 14 | 10 | 3 | 13 | 2 |
| ↳ Oracle failure | 1 | 1 | 0 | 1 | 0 |
| ↳ Fitted historical controls | 8 | 5 | 3 | 8 | 1 |
| ↳ Fitted new growth evaluations | 5 | 4 | 0 | 4 | 1 |
| Total intake | 147 | 77 | 42 | 119 | 34 |

## Fitted denominator and stream sensitivity

| Frame | Fitted | All streams | Any stream | Unfitted |
|---|---:|---:|---:|---:|
| 147 distinct | 13 | 4 | 4 | 134 |
| PIE 77 | 9 | 4 | 4 | 68 |
| CppPerf 42 | 3 | 0 | 0 | 39 |
| 119 census | 12 | 4 | 4 | 107 |
| Significant 34 | 2 | 0 | 0 | 32 |

Significant-test patches per project. `fmtlib/fmt` 4, `jeremy-rifkin/cpptrace` 1, `kimci86/bkcrack` 1, `kimwalisch/primecount` 9, `kimwalisch/primesieve` 1, `libgeos/geos` 3, `madmann91/bvh` 2, `microsoft/snmalloc` 4, `ridiculousfish/libdivide` 2, `wisdompeak/LeetCode` 1, `xtensor-stack/xsimd` 5, `yhirose/cpp-peglib` 1.

## Desk exclusions and blocks

| Desk reason | Excluded | Blocked |
|---|---:|---:|
| `alignment_boundary` | 6 | 0 |
| `concurrency_or_cache_layout` | 10 | 0 |
| `fixed_contract` | 8 | 0 |
| `forced_avx` | 3 | 0 |
| `forced_x86_native` | 1 | 0 |
| `graphics_driver_or_host_api` | 4 | 0 |
| `insufficient_workload_ladder` | 3 | 0 |
| `isa_or_arch_locked` | 7 | 0 |
| `missing_pinned_dependency` | 0 | 4 |
| `missing_pinned_dependency_and_calibration` | 0 | 1 |
| `no_common_calibrated_work` | 11 | 0 |
| `no_common_restoring_event` | 7 | 0 |
| `no_executable_work_delta` | 1 | 0 |
| `no_isolated_restoration` | 2 | 0 |
| `no_matching_work_delta` | 1 | 0 |
| `source_derived_numeric_oracle_failure` | 1 | 0 |
| `source_derived_oracle_failure` | 8 | 0 |
| `source_derived_undefined_behavior` | 7 | 0 |
| `unsupported_dependencies` | 2 | 0 |
| `unverified_assertion_configuration` | 0 | 1 |
| `unverified_cache_cutoff_alignment` | 0 | 1 |
| `unverified_calibrated_cache_work` | 0 | 1 |

| Rank | Disposition | Bucket | Census | Stratum | Verbatim reason |
|---:|---|---|---:|---:|---|
| 2 | historical_desk_excluded | contract | 2 | — | A fixed scalar contract supplies no size ladder. |
| 4 | historical_desk_excluded | contract | 4 | — | The contract supplies five inputs and no size ladder. |
| 7 | historical_desk_excluded | contract | 7 | — | Reference difference-array updates eliminate the target’s per-trip scans. Counts are source-derived. |
| 9 | historical_desk_excluded | contract | 9 | — | The string has exactly three characters. |
| 10 | historical_desk_excluded | source | 10 | — | Both exact files force AVX2. The reference also uses native word loads to parse input. |
| 12 | historical_desk_excluded | contract | 12 | — | The contract specifies one scalar pair, so EOF repetition changes the task. |
| 13 | desk_excluded | contract | 13 | — | alignment_boundary |
| 14 | desk_excluded | contract | 14 | — | alignment_boundary |
| 15 | desk_excluded | source | 15 | — | source_derived_oracle_failure |
| 16 | desk_excluded | contract | 16 | — | fixed_contract |
| 20 | desk_excluded | source | 20 | — | source_derived_undefined_behavior |
| 22 | desk_excluded | contract | 22 | — | alignment_boundary |
| 23 | desk_excluded | contract | 23 | — | fixed_contract |
| 24 | desk_excluded | contract | 24 | — | insufficient_workload_ladder |
| 25 | desk_excluded | contract | 25 | — | fixed_contract |
| 26 | desk_excluded | contract | 26 | — | no_isolated_restoration |
| 28 | desk_excluded | source | 28 | — | source_derived_numeric_oracle_failure |
| 29 | desk_excluded | contract | 29 | — | fixed_contract |
| 30 | desk_excluded | contract | 30 | — | no_common_restoring_event |
| 31 | desk_excluded | source | 31 | — | source_derived_oracle_failure |
| 32 | desk_excluded | source | 32 | — | source_derived_oracle_failure |
| 33 | desk_excluded | contract | 33 | — | fixed_contract |
| 34 | desk_excluded | contract | 34 | — | no_common_restoring_event |
| 35 | desk_excluded | contract | 35 | — | no_executable_work_delta |
| 36 | desk_excluded | source | 36 | — | forced_avx |
| 37 | desk_excluded | contract | 37 | — | fixed_contract |
| 38 | desk_excluded | source | 38 | — | forced_x86_native |
| 40 | desk_excluded | contract | 40 | — | fixed_contract |
| 41 | desk_excluded | contract | 41 | — | fixed_contract |
| 42 | desk_excluded | contract | 42 | — | no_common_restoring_event |
| 44 | desk_excluded | contract | 44 | — | no_matching_work_delta |
| 45 | desk_excluded | source | 45 | — | source_derived_undefined_behavior |
| 46 | desk_excluded | source | 46 | — | source_derived_undefined_behavior |
| 47 | desk_excluded | contract | 47 | — | insufficient_workload_ladder |
| 49 | desk_excluded | contract | 49 | — | insufficient_workload_ladder |
| 51 | desk_excluded | contract | 51 | — | no_common_restoring_event |
| 54 | desk_excluded | source | 54 | — | forced_avx |
| 56 | desk_excluded | contract | 56 | — | no_common_restoring_event |
| 57 | desk_excluded | source | 57 | — | source_derived_undefined_behavior |
| 58 | desk_excluded | source | 58 | — | source_derived_oracle_failure |
| 59 | desk_excluded | source | 59 | — | source_derived_oracle_failure |
| 61 | desk_excluded | contract | 61 | — | no_isolated_restoration |
| 64 | desk_excluded | source | 64 | — | source_derived_undefined_behavior |
| 65 | desk_excluded | source | 65 | — | source_derived_undefined_behavior |
| 66 | desk_excluded | source | 66 | — | source_derived_undefined_behavior |
| 67 | desk_excluded | contract | 67 | — | alignment_boundary |
| 69 | desk_excluded | contract | 69 | — | no_common_calibrated_work |
| 72 | desk_excluded | contract | 72 | — | no_common_restoring_event |
| 73 | desk_excluded | contract | 73 | — | no_common_restoring_event |
| 75 | desk_excluded | source | 75 | — | forced_avx |
| 77 | desk_excluded | contract | 77 | — | no_common_calibrated_work |
| 80 | historical_desk_excluded | source | 3 | — | Source-derived repeated packed segments witness append versus overwrite in the audited reader. |
| 81 | historical_desk_excluded | source | 4 | — | Changed behavior depends on cache placement and concurrent SPSC access. |
| 82 | historical_desk_excluded | contract | 5 | 4 | The libdwarf allocation/lifetime policy lacks a calibrated common event. |
| 83 | historical_desk_excluded | source | 6 | — | Source-derived cursor witness gives different bounded optional acceptance. End-to-end barcode decode was outside this check. |
| 84 | historical_desk_excluded | source | 7 | — | The border change requires a graphics context and driver. |
| 85 | historical_desk_excluded | source | 8 | — | AVX3 specialization. Portable execution bypasses the changed path. |
| 89 | historical_desk_excluded | source | 12 | — | AArch64-only ExtractOffset branch. Other hosts bypass the change. |
| 90 | desk_excluded | source | 13 | — | source_derived_oracle_failure |
| 92 | desk_excluded | source | 15 | — | concurrency_or_cache_layout |
| 95 | desk_excluded | contract | 18 | — | no_common_calibrated_work |
| 97 | desk_excluded | contract | 20 | — | alignment_boundary |
| 98 | desk_excluded | contract | 21 | — | no_common_calibrated_work |
| 99 | desk_excluded | source | 22 | — | graphics_driver_or_host_api |
| 100 | desk_excluded | contract | 23 | 5 | alignment_boundary |
| 101 | desk_excluded | source | 24 | — | concurrency_or_cache_layout |
| 104 | desk_excluded | source | 27 | — | concurrency_or_cache_layout |
| 105 | desk_excluded | contract | 28 | — | no_common_calibrated_work |
| 106 | desk_excluded | source | 29 | 11 | isa_or_arch_locked |
| 107 | desk_excluded | contract | 30 | — | no_common_calibrated_work |
| 108 | desk_excluded | source | 31 | — | graphics_driver_or_host_api |
| 110 | desk_excluded | contract | 33 | — | no_common_calibrated_work |
| 111 | desk_excluded | contract | 34 | — | no_common_calibrated_work |
| 112 | desk_excluded | source | 35 | — | concurrency_or_cache_layout |
| 113 | desk_excluded | source | 36 | — | concurrency_or_cache_layout |
| 114 | desk_excluded | source | 37 | — | graphics_driver_or_host_api |
| 115 | desk_excluded | source | 38 | — | isa_or_arch_locked |
| 116 | desk_excluded | contract | 39 | — | no_common_calibrated_work |
| 117 | desk_excluded | source | 40 | — | concurrency_or_cache_layout |
| 118 | desk_excluded | source | 41 | — | graphics_driver_or_host_api |
| 119 | desk_excluded | source | 42 | — | concurrency_or_cache_layout |
| 122 | desk_excluded | source | — | 6 | isa_or_arch_locked |
| 123 | desk_excluded | source | — | 8 | isa_or_arch_locked |
| 125 | desk_excluded | source | — | 10 | concurrency_or_cache_layout |
| 127 | desk_excluded | source | — | 13 | concurrency_or_cache_layout |
| 128 | desk_excluded | source | — | 14 | source_derived_oracle_failure |
| 129 | desk_blocked | contract | — | 15 | unverified_cache_cutoff_alignment |
| 130 | desk_excluded | route | — | 16 | unsupported_dependencies |
| 131 | desk_excluded | contract | — | 17 | no_common_calibrated_work |
| 132 | desk_blocked | route | — | 18 | missing_pinned_dependency |
| 133 | desk_excluded | route | — | 19 | unsupported_dependencies |
| 134 | desk_blocked | contract | — | 20 | unverified_assertion_configuration |
| 135 | desk_excluded | source | — | 21 | isa_or_arch_locked |
| 138 | desk_blocked | contract | — | 24 | unverified_calibrated_cache_work |
| 139 | desk_excluded | source | — | 25 | isa_or_arch_locked |
| 140 | desk_excluded | source | — | 26 | concurrency_or_cache_layout |
| 141 | desk_blocked | route | — | 27 | missing_pinned_dependency |
| 142 | desk_blocked | route | — | 28 | missing_pinned_dependency |
| 143 | desk_blocked | route | — | 29 | missing_pinned_dependency_and_calibration |
| 144 | desk_blocked | route | — | 30 | missing_pinned_dependency |
| 145 | desk_excluded | source | — | 31 | source_derived_oracle_failure |
| 146 | desk_excluded | contract | — | 32 | no_common_calibrated_work |
| 147 | desk_excluded | source | — | 34 | isa_or_arch_locked |

## All finite-range fits

Inherited summaries come from [historical-ledger.json](historical-ledger.json) and [historical-tables.md](historical-tables.md). A dash marks unavailable grid details.

| Rank | Case | Origin | Scoped event | Stream | Largest ratio | Slope | Ratio pass | Slope pass |
|---:|---|---|---|---|---:|---:|---|---|
| 1 | p02316 | Historical | Explicit memo/DP initialization writes | heavier | 1972.85 | -1 | True | False |
| 1 | p02316 | Historical | Explicit memo/DP initialization writes | light | 1972.85 | -1 | True | False |
| 1 | p02316 | Historical | Explicit memo/DP initialization writes | mixed | 1972.85 | -1 | True | False |
| 3 | p00464 | Historical | Logical DP cell writes (clear, seed, and propagation) | seed-11 | 5.74808 | -1.94744 | True | False |
| 3 | p00464 | Historical | Logical DP cell writes (clear, seed, and propagation) | seed-29 | 5.74808 | -1.94744 | True | False |
| 3 | p00464 | Historical | Logical DP cell writes (clear, seed, and propagation) | seed-47 | 5.74808 | -1.94744 | True | False |
| 6 | p00502 | Historical | Destination DP-cell initialization writes | D2 | 109.44 | -1 | True | False |
| 6 | p00502 | Historical | Destination DP-cell initialization writes | D3 | 82.0801 | -1 | True | False |
| 6 | p00502 | Historical | Destination DP-cell initialization writes | D4 | 65.6641 | -1 | True | False |
| 8 | p03592 | Historical | Candidate-pair trials | rectangular-half | 2.00388 | -0.0124189 | True | False |
| 8 | p03592 | Historical | Candidate-pair trials | rectangular-quarter-columns | 1.0039 | -0.0288819 | False | False |
| 8 | p03592 | Historical | Candidate-pair trials | square-zero | 1.00389 | -0.0273202 | False | False |
| 11 | p02994 | Historical | Subtotal materializations | crossing | 1.24806 | 0.0107287 | False | False |
| 11 | p02994 | Historical | Subtotal materializations | negative | 1.48837 | 0.0582641 | False | False |
| 11 | p02994 | Historical | Subtotal materializations | positive | 1 | 0 | False | False |
| 17 | p00256 | New | query day-accumulator updates | Dec-01 | 119.154 | 0.937383 | True | True |
| 17 | p00256 | New | query day-accumulator updates | Jan-01 | 1537 | 0.994657 | True | True |
| 17 | p00256 | New | query day-accumulator updates | Jul-01 | 193 | 0.959851 | True | True |
| 60 | p02346 | New | nonempty stored query contributions | alternate 1/N, weight 3 | 20 | 0.662703 | True | True |
| 60 | p02346 | New | nonempty stored query contributions | cycle 1..N, weight 2 | 18.8281 | 0.641502 | True | True |
| 60 | p02346 | New | nonempty stored query contributions | index 1, weight 1 | 20 | 0.662703 | True | True |
| 62 | p03048 | New | candidate residual arithmetic entries | R=N,G=N,B=1 | 350208 | 1.98405 | True | True |
| 62 | p03048 | New | candidate residual arithmetic entries | R=N/2,G=N,B=2 | 262656 | 1.98405 | True | True |
| 62 | p03048 | New | candidate residual arithmetic entries | R=N/4,G=N/2,B=3 | 116736 | 1.98405 | True | True |
| 71 | p03999 | New | input digits decoded during numeric preparation | nines | 22 | 1.34561 | True | True |
| 71 | p03999 | New | input digits decoded during numeric preparation | ones | 22 | 1.34561 | True | True |
| 71 | p03999 | New | input digits decoded during numeric preparation | repeat 27 truncated | 22 | 1.34561 | True | True |
| 78 | rbock/sqlpp11 | Historical | SQLite bind calls plus explicit duration normalizations | alternating-null | 1.5 | 0 | True | False |
| 78 | rbock/sqlpp11 | Historical | SQLite bind calls plus explicit duration normalizations | boundaries | 2 | 0 | True | False |
| 78 | rbock/sqlpp11 | Historical | SQLite bind calls plus explicit duration normalizations | microseconds | 2 | 0 | True | False |
| 79 | wisdompeak/LeetCode | Historical | Feasibility accumulator writes | alternating | 1.00164 | -0.0082447 | False | False |
| 79 | wisdompeak/LeetCode | Historical | Feasibility accumulator writes | clustered | 1.0019 | -0.0103245 | False | False |
| 79 | wisdompeak/LeetCode | Historical | Feasibility accumulator writes | homogeneous | 1.00152 | -0.00725676 | False | False |
| 86 | fmtlib/fmt | Historical | Non-initializer precision-state writes | ascii | 2 | 0 | True | False |
| 86 | fmtlib/fmt | Historical | Non-initializer precision-state writes | mixed_width | 2 | 0 | True | False |
| 86 | fmtlib/fmt | Historical | Non-initializer precision-state writes | multibyte_narrow | 2 | 0 | True | False |
| 137 | wisdompeak/LeetCode | New | combining comparisons | bounded_duplicates | 7.78022 | 0.129976 | True | False |
| 137 | wisdompeak/LeetCode | New | combining comparisons | interleaved_bit_reversal | 10.7821 | 0.210724 | True | False |
| 137 | wisdompeak/LeetCode | New | combining comparisons | seeded_permutations | 10.8812 | 0.199171 | True | False |

## Dependency-only closures

| Intake slot | Case | Translation unit | First unavailable include |
|---:|---|---|---|
| 91 | guillaumeblanc/ozz-animation | `src/animation/runtime/track_sampling_job.cc` | `ozz/animation/runtime/track_sampling_job.h` |
| 93 | libgeos/geos | `src/operation/relateng/RelateGeometry.cpp` | `geos/algorithm/Orientation.h` |
| 94 | jupp0r/prometheus-cpp | `core/src/histogram.cc` | `prometheus/histogram.h` |
| 102 | zeux/pugixml | `src/pugixml.cpp` | `pugixml.hpp` |
| 103 | kimci86/bkcrack | `src/password.cpp` | `password.hpp` |
| 109 | ecnerwala/cp-book | `src/fft.hpp` | `modnum.hpp` |
| 120 | libgeos/geos | `src/algorithm/construct/MaximumInscribedCircle.cpp` | `geos/algorithm/construct/MaximumInscribedCircle.h` |
| 121 | kimwalisch/primecount | `src/LogarithmicIntegral.cpp` | `primecount-internal.hpp` |
| 124 | kimwalisch/primecount | `include/generate_phi.hpp` | `primecount-internal.hpp` |
| 126 | kimwalisch/primecount | `include/generate_phi.hpp` | `primecount-internal.hpp` |

## New isolated comparisons

Counts are target, reference, restoration and sham. The screen concerns the first
registered event. An empty drop-largest slope means the shorter grid lacks four
distinct sizes spanning eightfold.

| Case | Stream | Largest size | Four counts | Ratio | Slope | Drop-largest slope | Pass |
|---|---|---:|---|---:|---:|---:|---|
| p00256 | Dec-01 | 204800 | 1549 / 13 / 13 / 1549 | 119.1538 | 0.9374 | 0.9222 | yes |
| p00256 | Jan-01 | 204800 | 1537 / 1 / 1 / 1537 | 1537.0000 | 0.9947 | 0.9933 | yes |
| p00256 | Jul-01 | 204800 | 1544 / 8 / 8 / 1544 | 193.0000 | 0.9599 | 0.9499 | yes |
| p02346 | alternate 1/N, weight 3 | 64 | 1280 / 64 / 64 / 1280 | 20.0000 | 0.6627 | 0.7585 | yes |
| p02346 | cycle 1..N, weight 2 | 64 | 1205 / 64 / 64 / 1205 | 18.8281 | 0.6415 | 0.7263 | yes |
| p02346 | index 1, weight 1 | 64 | 1280 / 64 / 64 / 1280 | 20.0000 | 0.6627 | 0.7585 | yes |
| p03048 | R=N,G=N,B=1 | 1024 | 1050625 / 3 / 3 / 1050625 | 350208.3333 | 1.9840 | 1.9800 | yes |
| p03048 | R=N/2,G=N,B=2 | 1024 | 1050625 / 4 / 4 / 1050625 | 262656.2500 | 1.9840 | 1.9800 | yes |
| p03048 | R=N/4,G=N/2,B=3 | 1024 | 1050625 / 9 / 9 / 1050625 | 116736.1111 | 1.9840 | 1.9800 | yes |
| p03999 | nines | 10 | 220 / 10 / 10 / 220 | 22.0000 | 1.3456 | — | yes |
| p03999 | ones | 10 | 220 / 10 / 10 / 220 | 22.0000 | 1.3456 | — | yes |
| p03999 | repeat 27 truncated | 10 | 220 / 10 / 10 / 220 | 22.0000 | 1.3456 | — | yes |
| wisdompeak/LeetCode | bounded_duplicates | 2048 | 152469 / 19597 / 19597 / 152469 | 7.7802 | 0.1300 | — | no |
| wisdompeak/LeetCode | interleaved_bit_reversal | 2048 | 220829 / 20481 / 20481 / 220829 | 10.7821 | 0.2107 | — | no |
| wisdompeak/LeetCode | seeded_permutations | 2048 | 216448 / 19892 / 19892 / 216448 | 10.8812 | 0.1992 | — | no |

## Authored a01 steady-state timing (exploratory; not used in the manuscript)

Medians are nanoseconds per full request. The historical no-op process median
was 731,000 ns and the startup-inclusive growth screen was unconfirmed.
At dense size 256 the target median is 10106.66 ns.

| Stream | Size | Target median (ns) | Reference median (ns) | Empty median (ns) |
|---|---:|---:|---:|---:|
| curved | 256 | 6684.35 | 288.16 | 1.07 |
| curved | 512 | 24086.32 | 668.27 | 1.29 |
| curved | 1024 | 89135.50 | 1774.41 | 2.05 |
| curved | 2048 | 337730.00 | 3626.94 | 2.73 |
| curved | 4096 | 1320469.56 | 7168.56 | 8.12 |
| curved | 8192 | 5248630.75 | 15158.50 | 18.88 |
| dense | 256 | 10106.66 | 156.34 | 1.18 |
| dense | 512 | 36944.66 | 518.47 | 1.40 |
| dense | 1024 | 134634.76 | 693.07 | 1.86 |
| dense | 2048 | 514401.70 | 1321.57 | 2.80 |
| dense | 4096 | 1942756.84 | 2614.56 | 4.70 |
| dense | 8192 | 8212676.81 | 5379.50 | 8.41 |
| plateau | 256 | 6094.25 | 149.35 | 1.15 |
| plateau | 512 | 20229.06 | 323.88 | 1.39 |
| plateau | 1024 | 70721.35 | 564.93 | 1.89 |
| plateau | 2048 | 273277.83 | 1049.15 | 2.78 |
| plateau | 4096 | 1048342.97 | 2183.77 | 4.42 |
| plateau | 8192 | 3981574.47 | 4223.06 | 6.72 |

| Stream | Largest ratio | Slope | Drop-largest slope | Pass |
|---|---:|---:|---:|---|
| curved | 346.250 | 0.7843 | 0.7348 | yes |
| dense | 1526.662 | 0.9702 | 0.9495 | yes |
| plateau | 942.817 | 0.9296 | 0.9173 | yes |
