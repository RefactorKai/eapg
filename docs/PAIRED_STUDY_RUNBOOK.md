# Paired C++ repeated-work study

The public pipeline measures and explains repeated work on authored C++17 cases, tests that explanation against competing ranks, and produces replayable receipts. The development result below determines whether to advance to a human study. The [research design](RESEARCH_REWORK_PLAN.md) defines the hypothesis and its proof obligations.

## Run the authored study

Run from the repository root in Linux with GNU C++, Bubblewrap, an unprivileged user with working user systemd and cgroup v2, and Python 3.11 or later. The existing [Gate 1 launcher requirements](REPRODUCIBILITY.md#linux-host-sandbox-note) apply. Choose new output directories. The authored runner accepts its shipped fixture only.

```bash
python -B development/probe_gate1.py --probes-only
python -B -m development.paired_study.demo run build/paired-study-authored
python -B -m development.paired_study.timing --case a01 --output build/paired-study-authored/timing-a01.json
python -B -m pytest -q development/paired_study development/test_paired_intake.py
```

The panel writes materialized C++ sources, a prediction-side trace ledger, and an independent oracle ledger into `panel/`. The source map is byte-exact on this template. Plain and UBSan builds check outputs against binary-search ranks. An independent counting build and closed forms check the trace work. Counts are tested at `-O0`, `-O2` and `-O3`. Individual restorations are exercised against the main workload and a fourth challenge stream. A live library calibration checks predicate invocations for early, middle, late and absent `std::find_if` hits. The count unit is a successful cursor advance or a completed explicit auxiliary-loop iteration. It makes a defined workload comparison possible and has no assumed conversion to elapsed time.

The predictor reads both sides and the canonical source-unit map. It performs the same paired finite-range screen for all ranking arms. Then it ranks the surviving candidates from the largest common clean size and all registered workload streams. The reported hotspot, local-count and diff-order comparators are localization arms under that common detection gate. The change-impact arms enumerate reachable source units for counted events, including auxiliary work. The stronger arm excludes alignable writes whose recorded values agree. The rewind arm follows entry definitions and attributes signed excess distance only where the previous exit agrees, the current entry differs, and exactly one unit is reachable. It retains the previous-exit effect, unexplained work, joint assignments, and alignment failures in the evidence.

A workload has six planned geometric sizes. The paired fit requires four uncensored, matching-output observations spanning at least eightfold and positive costs on both sides. Any known wrong output invalidates screening for the case. The raw points, exclusions, ratio, log-ratio slope, fit quality and largest-size sensitivity are saved. Repeated seeds, sizes, compiler flags and closely related case variants supply repeated observations within a family.

The analysis writes a development registration, evaluation, selection, prediction and score ledger beneath `analysis/`. It also writes the attribution paths, a generated `booktabs` table, and a manifest of their SHA-256 digests. The authored oracles are deliberately public. Their development scores are descriptive.

The trace collector covers the shipped indexed-array fixture, including scalar copies, killed writes, loop-carried values, and nested conditional resets. The fixture also exercises a known pure helper expression. The library calibration establishes predicate counts for the shipped `std::find_if` workload. Pointer aliasing, arbitrary calls, range-for, macro-expanded spans, library cost inference, and cross-algorithm episode mapping remain unvalidated domains for this collector.

To replay measurement receipts across systems, supply the trace and oracle SHA-256 values recorded by the producer over a separate channel. Replay runs the analysis with existing measurements. A fresh run repeats compilation and measurement.

```text
python -B -m development.paired_study.demo replay NEW_DIRECTORY --panel PANEL_DIRECTORY --traces-sha256 TRACE_DIGEST --oracle-sha256 ORACLE_DIGEST
```

## Development result

The reference run used Ubuntu GCC 15.2.0 on x86-64 in WSL2. All four Gate 1 probes passed. The run produced 108 distinct fixture builds, 117 execution batches, 216 paired prediction observations across three distinct workload streams, and 72 library-calibration conditions. Each of the 12 cases comes from one authored family. Six cases met the large finite-range count rule and had an accepted local restoration. Four controls had independently justified negative growth labels, including the constant-factor case. Two smaller-growth cases remained indeterminate under the large-growth rule. The four negative controls and two indeterminate cases have different denominators.

| Localization arm | Top-1 on six positive cases | Top-2 | Alerts on four negative controls |
|---|---:|---:|---:|
| Rewind attribution | 5/6 | 5/6 | 0/4 |
| Value-sensitive change impact | 6/6 | 6/6 | 0/4 |
| Change impact | 3/6 | 6/6 | 0/4 |
| Entry definition vote | 4/6 | 5/6 | 0/4 |
| Target hotspot | 2/6 | 2/6 | 0/4 |
| Local count difference | 0/6 | 0/6 | 0/4 |
| Diff source order | 3/6 | 6/6 | 0/4 |

Both rewind attribution and value-sensitive change impact hit all five cursor cases at Top-1. Only impact identified the unrelated auxiliary slowdown. The all-case difference was −1/6. The single representative for the one family was a tie between methods. Use the full descriptive result when discussing the hypothesis. The development comparison favors keeping the quantitative explanation as a diagnostic and dropping the current standalone superiority claim.

The protected monotonic timing run used plain binaries, one warmup pair and five measured pairs per size and stream, with seeded random order within each pair. It tested case `a01` separately and reproduced all expected outputs. Its log-ratio slopes ranged from −0.002 to 0.016, and largest-size ratios from 0.88 to 1.00. A no-op process took about 0.73 ms at the median. Observed elapsed time from spawning the candidate binary to exit includes process startup. The fixture was count-confirmed and runtime-unconfirmed on this setup.

| Reference receipt | SHA-256 |
|---|---|
| Authored traces | `bb5b8610c9563672685978d4ffc5218602172afa58036d821fbbb12e7eb41084` |
| Authored oracle | `ad4a2a78144b23250fb6da5bf7a20436808dba71992ec34645cb4c636757e904` |
| Authored timing `a01` | `4626f75243995fa5366509370249555b5b007bcee07e783b3764b427627ebe8a` |

A second source-to-score run on the same WSL2 host reproduced the panel oracle, traces, scores, generated table, and analysis manifest byte for byte. The manifest digest was `eabc320f3d188b3883780210b0659c18697e10606fd69663f4ba64c0b791448a`. A separate run through the predictor and scorer command lines reproduced the authored scores. A mock-custody run exercised quarantine, workload validation, detached selection and final scoring, and verified rejection when the selection commitment was missing. These checks exercise reproducibility and pipeline gates. Independent-machine reproduction remains future work.

The [development intake](PAIRED_STUDY_INTAKE.md) records 24 reproducibly drawn human-written cases. Of these, zero have completed the required independent human eligibility and intervention checks. Several have mismatched algorithms or workload shapes. Two of 12 CppPerf cases have significant timing tests in the source release, which establish neither finite-range scaling effects nor local restoration. The confirmatory study is therefore **unregistered and ineligible to run**. No held-out outcome enters the development result.

## Register a new independent study

Advance only after there is a supported natural-case trace collector and source-mapped compiler slicing baseline, independently achievable case yield, and a new hypothesis that the stronger comparator could actually refute. The current graphs are checked dynamic dependencies on a known authored template. General C++ changes require validation of source maps, dynamic definitions, control edges, reference-site alignment, compiler versions and build isolation. LLVM DG was unavailable on the tested host, so no compiler-backed comparison is reported. The existing frozen scalar slicer remains useful for historical diagnostics. [LLVM DG](https://github.com/mchalupa/dg)

1. **Custodian.** Freeze one source population, complete frame, disjoint development exposure list, draw, orientation, canonical source map and workload definition. Build a versioned metadata inventory for each split, including undrawn bridge records, problem and project identities and aliases, submission IDs, source hashes and template hashes for both revisions. Use `quarantine` with both input digests and the expected group count. Save its audit. The tool verifies complete transitive grouping and a common fingerprint revision. The custodian must independently establish the metadata and fingerprint provenance.
2. **Study lead.** Record independent staffing, access, protocol, workloads, toolchain, method and analysis commitments before collecting predictions. The registration schema is `eapg.paired.registration.v1`. It pins the exact case array serialized with the scorer's sorted-key JSON, grouping from the split audit, predictor and scorer file digests, and the remaining signed study artifacts. Freeze one candidate, one strong comparator, a planned group count and one independent negative representative per group. The exact power planner quantifies the assumed paired benefit and discordance. Recompute them using independent feasibility evidence and budget for attrition.
3. **Evaluation team.** Two independent C++ reviewers receive the source pair, specification, declared input regime and independent measurement oracle. Each seals their own spans, minimal sufficient accepted units or joint sets, predicted counts and reasoning before discussion. A third reviewer adjudicates disagreements. Keep original reviews. Evaluate each proposed restoration against the unchanged target and reference with separate challenge inputs. Record count recovery, output checks, source hashes, unresolved reasons, and coverage across the draw. Only the evaluation ledger carries reference outcomes. `score select` verifies the registration and split audit, reads the evaluation ledger, and produces a pre-join representative selection that the custodian records independently.
4. **Prediction team.** Use only registration, the committed workload grid and the custodian's raw traces. Run `predict` and send the prediction file hash to the custodian. The tool checks the draw, method revision, source maps and workload coverage. Build traces under the registered process limits. Treat resource failures, unsupported constructs and unalignable episodes as explicit dispositions. The scoring pipeline accepts field-level evidence and recorded commitments. Independent access control and attestations establish role separation.
5. **Independent scorer.** Supply the pinned registration, audit, evaluation, predictions and selection to `score score`. The scorer checks hashes and exact case coverage, then reports group-weighted paired Top-1, candidate retention, tie and abstention counts, unresolved bounds, observed and conservative negative bounds, the 95% paired score interval, and the exact two-sided McNemar test. Complete-case coverage and exploratory grouped summaries accompany the primary endpoint. The specimen source population, approved dispositions and independent reproduction determine the scope of any paper claim. [Paired score interval](https://pubmed.ncbi.nlm.nih.gov/9595618/)

```text
python -B -m development.paired_study.quarantine --help
python -B -m development.paired_study.score power --groups 35 60 71 80 --win-probability 0.27 --loss-probability 0.07
python -B -m development.paired_study.score select --help
python -B -m development.paired_study.predict --help
python -B -m development.paired_study.score score --help
```

The planning example gives 43.3% exact-test power at 35 independent groups and 80.5% at 71. With zero false alerts among 29 independent negative controls, the one-sided 95% upper bound is 9.8%. Neither calculation treats the small authored panel as an independent sample. If a new feasible frame or advantage over the stronger comparator fails to emerge, write the paper around the measured mechanism, its failure boundaries, and the human-case feasibility evidence.
