# Amendment 1 to the frozen benchmark expansion protocol: desk (S1) labelling

Date: 2026-11-21. Amends `BENCHMARK_EXPANSION_PROTOCOL.md` (SHA-256 `8a9692457cdba6d9b2860717b8bc254dae47dc48eebe7baacabb17a82007953e`) for the frozen manifest `artifacts/paired_benchmark_freeze/manifest-expanded.json` (SHA-256 `5b432d827f324c073eb7ed14b4df4b5d18f5eb2a90c4d97d358405a800d27346`). The frozen protocol is committed beside this file, unchanged. This amendment is committed before any S1 label exists and before any S2 or S3 run (§11). The author has seen no label, rater output or execution result.

## What changes

1. **Rater design (replaces §2, line 54).** One rater model labels every desk-rateable pair. Its label is the S1 label used in every primary and secondary analysis. The two-family rating with a third-family adjudicator is not run.
2. **Desk-rateable set.** Of the 977 S0-pass pairs (477 confirmatory, 500 quarantined), 844 can be desk-rated. The other 133 lack the specification material the desk criteria need: 100 Contest pairs have statements that reference images not included in the frozen packet, and the frozen inputs for 33 GitHub pairs provide no independent specification. This was recorded from packet contents before any label. These 133 get the new terminal label `desk_unrateable`† at S1. They are not sent to a rater and do not go to S2. By source: PIE 60, CodeNet 40, GitHub 33. The committed IDs, corpora and reason codes are in [the hold list](s1_hold_list.json), SHA-256 `6bc97deac805d67528e1939481c75745f51cf7350c0d3ee757598eb55c5dad01`. The minimized list has the same held pairs and reason codes as the private custody list.
   - Recompute the held and rateable sets and check the agreement draw with `python -B development/paired_study/s1_scope.py`. The rule holds S0-pass Contest pairs whose statement contains an HTML `img` outside `script`, `style` and `noscript`, because the frozen packet contains no images. It holds every S0-pass Repository pair, because the frozen Repository inputs have no independent specification.
   - The committed [statement inventory](s1_statement_inventory.json) records only problem IDs, statement HTML hashes and image counts from Project CodeNet 1.0.0. To check it against the original HTML, pass `--statements /path/to/Project_CodeNet/problem_descriptions`. No statement content is committed.
3. **Agreement sample.** A second rater from a different model family labels a fixed sample of 100 of the 844 desk-rateable pairs.
   - Draw rule: for each desk-rateable pair, compute SHA-256 of the compact UTF-8 JSON `["eapg-s1-agreement-v1", 20261121, corpus, pair_id]` (separators `,` and `:`, `ensure_ascii=False`). Sort ascending by that hash, with lexical ties on `corpus:pair_id`. Take the first 100. The seed is 20261121.
   - [The fixed draw](s1_agreement_draw.json), SHA-256 `e15d89ed6808527a91a6dd9188162dad4a280baefe44653fe5a9f5c97b521ced`, is committed before either rater runs.
4. **Agreement statistic (replaces S11).** Cohen's κ between the primary and second rater on the 100 pairs, on exact labels and on bucket labels (pass, source, contract, route), with counts. The 95% interval is the whole-cluster percentile bootstrap of §4 (clusters sorted ascending, Python `random` seed 42, 10,000 draws, nearest ranks 250 and 9,750). Pairs in the sample can share a cluster, so this is a descriptive interval. Raw percent agreement is reported next to κ.
5. **No relabelling.** Disagreements on the 100 are reported only. They never change a primary label, and no third model adjudicates. κ is a secondary result (nominal, exploratory) and is never part of the Holm family.

## How `desk_unrateable` is counted

`desk_unrateable` is a terminal S1 outcome, not an exclusion (§7 "never excluded"). It stays in every denominator past S0. In P1 and S9 it counts as not reaching execution. In P2 and S1 it counts as a desk stop. A new sensitivity analysis S13 repeats P1, P2 and P3 with these pairs removed. Its share is reported per frame and per source in the flow table.

## Repository frame

All 33 S0-pass GitHub pairs (32 clusters) are `desk_unrateable`, so the Repository frame has 0 desk-rated pairs. This is reported as a finding: public performance-fix commits carry no independent specification, so the S1 desk criteria cannot be applied to them. There is no Repository-frame test. S10 per-frame rates, the Repository side of S1 and the E/R/X route comparison (§9) are reported as counts only. The Union frame equals the Contest frame for every rated or executed result; the 33 Repository pairs appear only in the S0/S1 flow counts. S13 drops the 133 `desk_unrateable` pairs, so it is a Contest-only analysis.

## What stays the same

- The frozen manifest, clusters, representative pairs, quarantine and S0 labels.
- The blind input packet (96 batches) remains private custody material under D5. Neither its manifest (SHA-256 `1f66f5b6b46456208ea3f8ab9e0a86d04ed9f4c6e52c48da1d1c3a89a5261d4d`) nor the rater ZIP (SHA-256 `723a0bae85d045e9fe2a91c270f514c9ca6a4cd372543ab0c2ebdbc9ae6a7c3e`) is committed; the hashes are recorded here for custody verification only. Raters see no outcome, no other rater's labels and no prior study disposition.
- Each rater's raw output, with model ID, version, date, decoding settings and full prompt, is saved and hash-sealed before any comparison.
- The closed label set of §2 (plus `desk_unrateable`†), the S1-before-S2 order, the no-deferral rule and stable-hash order into S2.
- All thresholds, outcomes, tests, Holm family {P1, P2, P3}, gates and the go/no-go rule. The analysis runs once, with no interim look at P1–P3.

## Reason

Model quota does not allow two full rater passes plus adjudication over 844 pairs. No threshold, outcome or test changes. The change is procedural.

## Deviations from the frozen protocol and owner rules

1. §2 line 54: one rater instead of two blind raters from different families plus a third-family adjudicator. The S1 label is the primary rater's label, not an adjudicated label.
2. §2 line 43: the closed label set gains `desk_unrateable`†.
3. S11: κ is computed on a 100-pair sample, not on all desk labels.
4. §11: a change needs "disjoint evidence". There is none for a quota limit; the decision and its reason are recorded here instead.
5. Repository frame: the frozen plan reports Contest, Repository and Union separately. Repository has no rated pairs, so no Repository test runs and Union = Contest.
6. Owner rule D4 and the repository skill `eapg-blind-validation` (two blind sessions on different model families plus a third-model adjudicator): S1 departs from it as in item 1, by owner decision on 2026-11-21.

## Effect on claims

- The S1 labels are single-model labels. P1 and P2 depend on them, so the paper says so wherever it reports them, and calls the 100-pair κ "model agreement" on a sample, never validation of all labels or human validation.
- Desk-stop rates (S1 vs R1) and P2 include `desk_unrateable`; S13 shows how much they move without it.
- §12 gains: "S1 labels come from one model; inter-model agreement was measured on a fixed 100-pair sample only."
- §12 gains: "No Repository-frame pair could be desk-rated, because public performance-fix commits carry no independent specification. Every rated and executed result is Contest-only, and Union equals Contest."
- The paper makes no claim about the Repository frame beyond the S0/S1 counts.
