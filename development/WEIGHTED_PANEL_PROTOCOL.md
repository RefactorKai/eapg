# Calibration of container-size work proxies

**Version 1.0 · 15 November 2026**

Does a full-range container-size weight estimate the growth in comparisons or swaps for selected C++17 library calls? This deterministic calibration extends the previous first-versus-last search probe. Use it to study construct validity. The three authored programs share a design, so their eight workloads are fixed experimental conditions. They supply no estimate of accuracy in a population of programs or bugs.

## Design and oracle

Each program reads a vector length `N` and a position `p`. It invokes one full-range library operation `N` times on a vector of length `N`. Take `N = 16, 32, 64, 128, 256, 512` in every condition. The first two programs place one matching value at zero-based position `p` when `p < N`. Position `N` codes absence. The reverse program starts with values 0 through `N - 1` in order and adds the first value to a checksum after every reversal.

| Operation | Condition | Position | Count observable in the distinct counting build |
|---|---|---:|---:|
| Find | first | 0 | `N` comparisons |
| Find | square root | `isqrt(N) - 1` | `N × isqrt(N)` comparisons |
| Find | midpoint | `N // 2` | `N × (N // 2 + 1)` comparisons |
| Find | last | `N - 1` | `N²` comparisons |
| Find | absent | `N` | `N²` comparisons |
| Count | present | `N // 2` | `N²` comparisons |
| Count | absent | `N` | `N²` comparisons |
| Reverse | full | 0 | `N × (N // 2)` swaps |

The output oracle is `N × p` for find, `N × (p < N)` for count, and `(N - 1) × ((N + 1) // 2)` for reverse. Find and count counting builds run the library operation with a needle whose equality operator increments an observable counter. The reverse counting build uses a value type whose argument-dependent swap increments an observable counter. The wrappers preserve the checksum and exercise the pinned library. We measure comparisons and swaps in their counting instantiations. In particular, the find formula assumes ordered traversal through the first matching element or the end. The C++ specification gives an upper bound for find. Compiler optimization can elide equivalent work in the plain build. The panel measures no machine instructions, wall time, or whole-program asymptotic complexity. [Find](https://eel.is/c++draft/alg.find) · [Count](https://eel.is/c++draft/alg.count) · [Reverse](https://eel.is/c++draft/alg.reverse)

## Execution and analysis

Before compilation, seal the report schema, exact script and program source digests, candidate and runner digests, ordered input grid, and output and operation oracles into a local manifest. Supply its SHA-256 independently to the execution command. Use GCC and the existing WSL sandbox. Treat the effective `-O2` flag as primary and `-O0` and `-O3` as fixed sensitivity conditions. Use the same input bytes and require matching checksums for the original, EAPG-instrumented and independent counting builds at each optimization level. Also run the UBSan build at `-O2`. Retain all failures and caps by grid position and stage. A condition enters slope analysis only if all six scales passed at the optimization level being analyzed. Missing evidence yields an incomplete condition.

Bind the comparison to the one canonical node representing the registered full-range call in the normalized source. For each condition and optimization level, retain hits, projected work, and observed operations at every size. Estimate each exponent by unrounded univariate OLS on natural-log counts against natural-log size. Show the signed and absolute error against the measured-operation exponent for both channels, and the per-size ratios of proxy units per measured operation. Report all fixed conditions individually. The eight conditions and three optimization levels are repeated measurements of a shared authored design. No pooled uncertainty interval is computed.

For the site-level hidden-work criterion, classify the difference between the measured-operation slope and hit slope as qualifying at 0.70 or above. Apply the same criterion to the proxy slope minus the hit slope and report disagreements. Separately record whether the real EAPG work selector qualifies and selects the target call. Compare it with the same selector and source using hit fits in place of work fits throughout. A site-level classification error concerns the specified slope margin on this grid. It makes no claim about whether the program contains a bug.

We expect the proxy to track the measured-operation slope for full scans and swaps. We expect it to overstate growth for first-position and square-root-position searches. A reverse level error can coexist with an accurate slope because the proxy counts container elements and the oracle counts swaps. Report deviations and all failed stages under this version. Make analysis changes under a new version and retain the first run.
