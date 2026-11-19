# Accounting for repeated scan work in paired C++ executions

## Abstract

A comparative performance diagnosis depends on the reference and the workload. For aligned forward scans, we account for the difference in successful advances in terms of endpoints, skipped forward distance, and repeated traversal. Executed definitions can connect some of the repeated work to a changed source unit, and a correctness-preserving restoration can test that explanation. In 12 authored cases from one family, rewind attribution ranked an accepted cause first in 5 of 6 count-confirmed positives. Value-sensitive change impact ranked an accepted cause first in all 6. A fixed draw of 12 PIE validation problems and 12 CppPerf projects yielded eight independently oracle-checked local restorations and zero eligible natural ranking cases. An output disagreement invalidated the highest-priority growth candidate, and Railroad Trip replaced the scans needed for alignment. The natural cases characterize where local operations can be measured and restored under the stated contract. Comparative ranking and runtime effectiveness on human-written cases remain open.

## Paired accounting

The same target trace is compatible with a reference that grows at the same rate and a reference with slower growth. Any target-only rule receives the same observations in both comparisons and must give the same answer. Under equal weighting of opposite labels, even a randomized rule has expected error one half. A target profile can still measure the growth of its own named event.

Consider `m` ordered scan episodes over one stable logical sequence, aligned across versions by query ordinal, object and mapped scan site. Episode `j` enters at position `aⱼ` and exits at `bⱼ`, with each successful advance moving one position forward. The total `F = Σ(bⱼ − aⱼ)` telescopes to `bₘ − a₁ + R − J`. Here `R = Σⱼ₌₂ᵐ max(0, bⱼ₋₁ − aⱼ)` is the backward distance between episodes and `J = Σⱼ₌₂ᵐ max(0, aⱼ − bⱼ₋₁)` is the skipped forward distance. Subtract the reference identity from the target identity and check the result against an independent count. The accounting makes one pass over aligned episodes. Collecting traces and establishing alignment have separate costs.

The implemented ranker follows executed reaching definitions and control edges from differing entries. It assigns a signed difference in rewind distance when the previous exits agree and the dependence paths reach exactly one changed unit. It tracks joint and unassigned distance and work outside the scan. The stronger comparator uses the same paired evidence and credits changed units with reachable positive extra work, including work outside the scan. It filters uniquely matched definitions that recorded equal values. A distance charge explains work in the trace. A restoration tests whether changing the proposed unit removes that work while preserving outputs. [Design and qualification rules](../docs/RESEARCH_REWORK_PLAN.md#3-what-the-candidate-would-measure) · [Ranker implementation](../development/paired_study/predict.py)

For nondecreasing rank queries on a sorted array, let `fⱼ` be the correct rank at query `j` and let `f₀ = 0`. Carrying progress uses `Σ(fⱼ − fⱼ₋₁) = fₙ` advances, while resetting uses `Σfⱼ`. On the array and query stream `1, …, n`, those counts are `n` and `n(n+1)/2`. At `n = 8`, the reset explains exactly 28 extra advances despite executing only 8 times. Restoring carry recovers the 28 advances under the monotone-query contract. Decreasing ranks can require a restart, and a reset overwritten before entry contributes no distance. These conditions delimit the claim. [Worked proof and controls](../docs/RESEARCH_REWORK_PLAN.md#2-the-question-and-its-proof-obligations)

PerfImpact combines input search with dynamic change impact to prioritize changes using method timings across two revisions. The comparator here adapts that approach to fixed workloads, operation counts and statement-level units. CLARITY statically identifies redundant collection traversals. The mechanism here quantifies the excess work attributable to lost progress for a given pair of executions and exposes the conditions under which that account is possible. [Luo et al., PerfImpact](https://www.cs.wm.edu/~dposhyvanyk/pubs/MSR%2716-PerfImpact.pdf) · [Olivo et al., CLARITY](https://www.cs.utexas.edu/~lin/papers/pldi15.pdf)

## Authored development evidence

The authored study used an independent binary-search output oracle, a separate counting build, individual restorations and a challenge stream. Scan advances and explicit auxiliary-loop iterations were counted. All methods used the same finite-range detection screen and changed-unit universe. The seven localization arms gave the following descriptive results on one family. [Measurements and reproduction commands](../docs/PAIRED_STUDY_RUNBOOK.md#development-result)

| Localization arm | Top-1 on six positives | Top-2 on six positives | Alerts on four controls |
|---|---:|---:|---:|
| Rewind attribution | 5/6 | 5/6 | 0/4 |
| Value-sensitive change impact | 6/6 | 6/6 | 0/4 |
| Change impact | 3/6 | 6/6 | 0/4 |
| Entry definition vote | 4/6 | 5/6 | 0/4 |
| Target hotspot | 2/6 | 2/6 | 0/4 |
| Local count difference | 0/6 | 0/6 | 0/4 |
| Diff source order | 3/6 | 6/6 | 0/4 |

Both primary arms ranked an accepted cause first on the five cursor positives (`a01`–`a05`). Value-sensitive change impact also found the auxiliary-loop cause (`a10`). The family representative was a tie. The four negative controls comprised three verified negatives (`a06`–`a08`) and one same-growth constant-factor case (`a09`). Two smaller-effect cases (`a11`, `a12`) remained indeterminate and fall outside both denominators.

In the separate protected timing run for `a01`, the log time-ratio slopes ranged from −0.00144 to 0.01546 and target/reference time ratios at the largest size ranged from 0.878 to 1.001. The median no-op time was 0.731 ms, and the timer includes process startup. The pair passed the operation-count criterion and remained runtime-unconfirmed. The timing receipt covers only `a01`. [Timing protocol and receipt digest](../docs/PAIRED_STUDY_RUNBOOK.md#development-result)

## Railroad Trip eliminates the episodes we would align

PIE validation `p00537` pairs target `s172351000` with reference `s927361703`, two independently submitted solutions. The construction sets city count `N` and itinerary length `M` to `n`, alternates `1, n, 1, n, …` for exactly `n` visits, and gives each of the `n−1` edges the tariff `(A,B,C) = (3,1,2)`. All six sizes satisfy the official bounds `2 ≤ N,M ≤ 100,000`, `1 ≤ B < A ≤ 100,000` and `1 ≤ C ≤ 100,000`. Every visit is in range and differs from its predecessor. This gives one deterministic shape. Repeating it would give duplicate inputs. [JOI Railroad Trip statement, problem 1](https://www2.ioi-jp.org/joi/2014/2015-ho/2015-ho.pdf#page=1)

**Contract-derived oracle.** Each edge is crossed `n−1` times. Its cheapest fare is `min(3(n−1), (n−1)+2) = n+1` at all six sizes, so the expected output is the single integer `n²−1` followed by a newline.

**Source-derived counts.** Count explicit post-initialization writes to the array used to obtain edge usage, including writes to the difference-array sentinel. The target executes `Q[j]++` for each traversed edge of each trip, hence `(n−1)²` writes. The reference executes `sum[pl]++` and `sum[pr]--` once per trip, then `sum[i] += sum[i−1]` at indices `1` through `n−1`. That is `2(n−1) + (n−1) = 3(n−1)`. The final prefix write at `n−1` computes the zero sentinel, which the fare loop does not read. Zero initialization, fare summation and input storage are outside this event definition. These are source-level writes, independent of how a compiler emits stores. [PIE intake and source pin](../docs/PAIRED_STUDY_INTAKE.md#reproduce-the-draw)

| `n` | Expected fare | Target writes | Reference writes |
|---:|---:|---:|---:|
| 8 | 63 | 49 | 21 |
| 16 | 255 | 225 | 45 |
| 32 | 1,023 | 961 | 93 |
| 64 | 4,095 | 3,969 | 189 |
| 128 | 16,383 | 16,129 | 381 |
| 256 | 65,535 | 65,025 | 765 |

**Disposition.** The final usage arrays agree on the logical edges, but a reference trip contributes two signed endpoints and the one prefix scan combines all trips. There is no reference scan episode for each target trip. Retain the pair as an alignment boundary. Its predicted write counts do not establish elapsed time or a local-restoration label.

## fLIP isolates early termination

PIE validation `p03592` pairs two independently submitted solutions that enumerate the same row and column flip counts. The target records reachable black-cell counts in a fixed table. The reference sets a flag and breaks the inner loop at the first match. The intervention adds only the inner break after the target table write. Each truncated row preserves its matching witness. The table remains in place, and the arithmetic sham preserves the original visit count. [AtCoder fLIP contract](https://atcoder.jp/contests/code-festival-2017-quala/tasks/code_festival_2017_quala_b?lang=en)

An independent solver enumerates row choices and solves for the column count. It agreed with a physical bit-flip oracle on 116 small-grid checks. The pinned originals and both edits passed 640 isolated evaluation checks and 384 exact count records. On the half-black `256 × 512` input, target, reference, restoration, and sham evaluated 131,841, 65,793, 65,793, and 131,841 candidate pairs, respectively. The restoration still wrote to the table at every visited pair. The reference wrote its flag 257 times, so the visit recovery and the representation change account for distinct parts of the observed work. [Full development evidence](../artifacts/paired_development/tables.md)

The blind trial-count screen returned `no_alert` on all three workload shapes. The largest target/reference ratios were 1.0039 to 2.0039 and the fitted log-ratio slopes were −0.0289 to −0.0124. Both scans enter each row at zero. Any removed work occurs in the unmatched suffix after the earlier reference exit, leaving no changed entry definition to charge.

## Verified development flow

The metadata-first draw contains 12 PIE validation problems and 12 CppPerf projects. Eleven passed desk intake. Nine ran in the isolated environment, of which eight validated scoped restorations and one failed the output oracle. HiGHS and OpenTelemetry passed desk intake, then failed dependency-only preprocessing in Gate 1. Their proposed oracles require the real solver and SDK runtimes, respectively. The ledger retains all 24 slots with an evidence kind and a disposition for each. [Pinned draw](../docs/PAIRED_STUDY_INTAKE.md) · [Flow, dispositions and sample counts](../artifacts/paired_development/tables.md)

The highest-priority finite-range candidate was Half Reflector (`p03788`). The planned comparison varied the number of transitions at fixed input length. On `N=3, K=7, S=AAB`, the reference returned `ABA` under plain, UBSan and counting builds. The physical simulator, target, cutoff restoration, and sham returned `BBA`. The reference also failed a predeclared length-63 ladder input. We preserved the workload and excluded the pair from fitting. The scoped iguana and ZXing exclusions rest on source-level contract witnesses and carry no whole-library runtime judgment. [Case ledger](../artifacts/paired_development/ledger.json)

The validated cases include reductions in fixed DP initialization, candidate-pair trials, subtotal or feasibility-state updates, UTF-8 precision rescans, and explicit time-of-day normalizations. For example, the `fmt` restoration reduced logical precision-state writes from 770 to 258 at 512 UTF-8 code points, matching the reference while the sham stayed at 770. The paired callback count had a 2.0 ratio and zero growth slope on all three streams. The `p00464` restoration matched the reference’s logical DP-write count under the verified reset contract. Every valid natural pair returned `no_alert` under its scoped screen. The recorded operations describe instrumented source effects, and machine stores and elapsed time require separate measurements. [Verified controls and replay](../artifacts/paired_development/README.md)

## Evidence limits

The exact work account applies to stable sequences with valid paired alignment. The natural draw contributes feasibility boundaries and scoped restorations. It provides zero eligible natural cases for a paired ranking comparison. The authored experiment remains a separate one-family result with value-sensitive change impact as the primary comparator. A natural effectiveness study would require valid paired traces, independent labels, and a precommitted comparison in which distinct recommendations admit individually verifiable restorations. The reported development measurements used no held-out cases or external adjudication.
