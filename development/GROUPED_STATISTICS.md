# Grouped statistics for paired benchmark qualification

The paper's primary evidence is the fixed 147-pair qualification ledger. The
pilot, prospective scalar cohort (Part A), blinded contract (Part B) and desk
agent agreement are secondary. They are not independent replications.

## Declared primary family

These two-sided nulls were declared for this redo of already observed outcomes.
Holm adjustment at family-wise alpha 0.05 applies to these two tests only.

| Receipt key | Metric and contrast | Denominator | Null |
|---|---|---|---|
| `desk_stop_minus_execution` | Difference in disposition rates: desk stop (exclusion or block) minus reached isolated execution (including oracle failure) | All 147 distinct selected pairs | Whole-cluster paired differences are sign-symmetric about zero |
| `all_stream_alert_minus_no_alert` | Difference in conditional verdict rates: all-stream scoped alert minus no alert | The 13 fitted pairs, including eight inherited controls | Whole-cluster paired differences are sign-symmetric about zero |

Both use equal-weight PIE problem / CppPerf project means (ledger `case_id`).
One shared patch contributes once to the distinct union, even when it belongs
to both CppPerf frames; separate frame rates overlap and are not independent
comparisons. The second endpoint conditions on obtaining a fit; the fitted
cases, especially the inherited controls, are not a probability sample.
Neither endpoint estimates a corpus-wide prevalence or tests ranking
effectiveness. Any-stream and drop-largest checks are sensitivity diagnostics;
an inadmissible or unavailable reduced ladder is not a negative verdict.

## Methods and replay

- Each contrast subtracts two binary outcomes **within pair**, averages the
  differences within the cluster, then averages the cluster effects with equal
  weights. Groups are connected template groups for stored-pilot predictions,
  scalar families for Part A, and adjudication groups for Part B. The primary
  tests and secondary comparisons use the two-sided exact whole-cluster
  sign-flip distribution, including ties in the tail; zero-effect clusters
  need not be permuted. The test assumes independent clusters and sign
  exchangeability under its null, not independent pairs. In the pilot,
  overlapping cross-validation training sets can still induce dependence.
- Rate intervals are two-sided 95% Clopper–Pearson binomial reference
  intervals, with numerator and denominator shown. Where cases within a
  cluster are dependent or the panel is fixed, these are descriptive
  working-independence reference intervals, **not** cluster-robust inference.
  Archived desk agreement instead uses its original resampling intervals.
- The whole-cluster percentile bootstrap is a descriptive sensitivity
  interval, not the test or a substitute for the adjusted p-value. Sort the
  cluster IDs ascending before drawing; with Python's seeded RNG (seed 42)
  draw the original number of clusters with replacement 10,000 times. Sort
  the replicate statistics and take nearest ranks 250 and 9,750. This
  conditions on the observed predictions and may under-cover with few
  clusters. Leave-one-group-out (LOO) endpoints give a **range**, not a CI.
  Report interval endpoints to one decimal in percentage points (or on the
  100×κ scale for agreement); calculate tests before any display rounding.
- Part A uses the archived per-pair `active_slot_details` for the two scalar
  arms with saved candidate sets, and matches neural predictions back to
  those cases by ID. The core excludes the comparator-swap duplicate. For
  other scalar arms the public receipt supports marginal counts but not
  individual paired discordances; a tie in aggregate is not proof of
  equivalence. Part B uses `pair_details` to reconstruct Top-1 from rankings
  and accepted references; all adjudicated positives remain in the
  denominator, including misses caused by slices. Both use
  `replay_pilot_contrast.py:contrast()`.
- The WP-A2 sensitivity checks are reconstructed from the public inputs,
  without depending on its unmerged branch. Part A uniform-CFG Top-1 sums
  exact accepted-in-slice fractions over the 20 core cases, excluding the
  comparator-swap duplicate. It is a conditional expectation, not an
  observed proportion. For OEIS, use only the five analytic-eligible cases;
  the parameter-free ranker selects the largest canonical node ID below the
  symptom, otherwise the symptom if present, otherwise the lowest candidate
  above it. Group inference by mechanism family; canonical ID is AST
  preorder, not CFG path distance.
- Agent judgments are secondary. The public desk receipts allow replay of
  the reported summaries and aggregate confusion counts; recomputing their
  bootstrap replicates still requires private vote vectors. Subset and
  protocol comparisons without released paired outcomes do not get a
  synthetic test. On sampled exclusions the public confusion matrix counts
  eligible votes, not eligible pairs. Its 95% Clopper–Pearson interval assumes
  independent votes as a binomial reference only. Votes repeat on cases; this
  does not bound how many of the 95 exclusions should change without
  case-level adjudication.
- Part A specificity is replay-only. Nominal per-seed strata come from
  WP-S1's verified receipt. Alerts on same-growth shams or appropriate
  superlinear controls are false alerts; only non-alerts are correct
  rejections. The grouped replay checks the seed-42 totals against the
  per-case Part A outcomes and checks the fitted alert and admitted
  drop-largest case sets against the paired ledger.

From the checkout, `python -B development/replay_grouped_statistics.py --write`
regenerates [the JSON receipt](grouped_statistics.json) and its
[WP-A4 manuscript macros](../manuscript/grouped_statistics_macros.tex). The
receipt pins input and script SHA-256s. The same command without `--write`
compares both outputs to a fresh recomputation, checks the manuscript's
macro references, and fails on drift;
`python -B eapg.py verify --mode linux` runs that comparison.
Archived releases, source programs, and full-precision historical receipts
are left unchanged.

See the [conclusions table](GROUPED_STATISTICS_CONCLUSIONS.md) for differences
from the previous analyses.
