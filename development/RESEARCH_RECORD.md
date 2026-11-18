# Phase 2 development research record

## Scope and custody

The frozen Phase 1 release supplies development evidence. The already-used PIE validation case, authored C++ fixtures, and published synthetic pilot are development inputs. The sealed PIE test draw remains under the original custody protocol. [Decision gates](../PHASE2_DECISION.md) · [External protocol](../artifacts/phase1_correction/phase2_protocol.md)

## Pilot stdout replay

We regenerated all 100 published synthetic pairs and checked the sources against the frozen pilot before compiling. GCC 15.2.0 built 200 uninstrumented C++17 programs at `-O2` in the WSL2 sandbox. All 472 executions completed. Slow and fast stdout agreed byte-for-byte in all 236 comparisons, covering sizes 16 and 24 for every pair and sizes 1, 2, 3, 8, 32, and 64 for the six A1.4 pairs. All 50 overlapping coordinates also matched the frozen modular correction controls. The [fresh receipt](pilot_output_agreement.json) records the source and binary digests, each input digest, and the exit and stdout bytes for both sides. Its SHA-256 is `36f3da88fb4f46e7cdbf99052e526383d216d5ba7e967ba76924d87f93f06224`.

```sh
PYTHONPATH="$HOME/.local/share/eapg-phase2/deps" python3 -B development/replay_pilot_outputs.py \
  --output .codex/private/pilot-output-agreement-new.json
```

## Paired Phase 1 sensitivity

Replayed `6b-slice` and Variant 2 Top-1 predictions against the same frozen reference nodes. The contrast below is neural minus symbolic in percentage points. Each group contrast is the mean of paired binary differences within the original prompt-merged template group. For the bootstrap, draw whole groups with replacement, weight each drawn group equally, and use nearest-rank 2.5% and 97.5% endpoints across 10,000 draws with seed 42. Multi-candidate means the frozen pruned slice contained at least two nodes.

| Cohort | Pairs | Groups | Equal-pair difference | Equal-group difference | 95% group-bootstrap interval | Leave-one-group-out range |
|---|---:|---:|---:|---:|---:|---:|
| All pilot pairs | 100 | 23 | +2.00 | −2.17 | [−15.22, +10.87] | [−6.82, +2.27] |
| Multi-candidate | 66 | 15 | +3.03 | −3.33 | [−23.33, +16.67] | [−10.71, +3.57] |

Both cohorts contain the same six discordant pairs. The four neural-only wins lie in one group. Two other groups account for the two symbolic-only wins. The reported intervals are descriptive sensitivity analyses conditional on the historical grouping. A stricter numeric-literal key connects examples across historical folds, and the pilot uses generator-aligned templates. The intervals therefore do not quantify transfer uncertainty on independent human-written programs. [Frozen evidence and leakage sensitivity](../AUDIT.md)

Run from the repository root with Python. The first command replays the historical results and the second checks the input digests and computes this contrast.

```sh
python -B verify_release.py
python -B development/replay_pilot_contrast.py
```

## Grouped pilot refit

The refit keeps the 100 published synthetic pairs, their reference nodes, and their saved pruned slices. Seed 42 assigns 13 connected groups to five folds of 19, 19, 19, 21, and 22 pairs. The grouping preserves problem IDs and the published template groups, and adds exact normalized source, identifier- and numeric-literal-normalized source fingerprints on both program versions, and exact 6b-slice prompt-token hashes. The 100 pairs yield 38 distinct prompts. The trainer checks that each key stays within one fold. Each adapter fits the other four folds for six fixed epochs with seed 42 and no model selection on fold scores. This trainer recomputes the forward activations and uses gradient checkpointing. The historical run cached the first 20 layers and used fold-dependent seeds, so differences between runs also reflect implementation and seed choices.

All three rankers use the same saved pruned candidates. The neural comparison evaluates the same quantized base model and exact prompts with and without the newly trained adapter. The symbolic comparison uses the published Variant 2 rule, which was refined on this pilot. The refit measures sensitivity to grouping within an already published corpus. It supplies no independent mechanism or human-code validation.

| Cohort | Groups | Adapted Top-1 | Base Top-1 | Symbolic Top-1 |
|---|---:|---:|---:|---:|
| All 100 pairs | 13 | 90/100 (84.44%) | 62/100 (52.29%) | 96/100 (92.31%) |
| 66 multi-candidate pairs | 10 | 56/66 (79.77%) | 28/66 (37.98%) | 62/66 (90.00%) |

Parentheses give the equal-group Top-1 rate. The 34 singleton slices already contain the reference and count as hits for all three rankers. The five folds contain 19, 6, 19, 0, and 22 multi-candidate pairs. Eight of nine mechanism labels each occur in a single fold, which ties their outcomes to that fold's fit.

On the multi-candidate cohort, the adapted-minus-base group contrast was +41.79 percentage points and the adapted-minus-symbolic contrast was −10.23 points. The fixed-prediction group bootstrap yielded descriptive 95% intervals of [16.59, 66.29] and [−37.95, 20.00] points, respectively. The fits share training data across folds, and the bootstrap resamples the predictions without refitting. These intervals describe sensitivity within the published pilot. [Run evidence and predictions](../artifacts/pilot_resplit/results.json) · [Bates et al. on cross-validation uncertainty](https://arxiv.org/abs/2104.00673)

Replay the saved fold predictions, split bindings and metrics on CPU using the standard library.

```sh
python -B development/replay_pilot_resplit.py
```

The five fits ran on an RTX 4060 Laptop GPU under native Windows Python. Peak PyTorch GPU allocation was 2.25 GiB. A fresh process reloaded the first fold's adapter and reproduced all 19 rankings and their candidate logits exactly. The result file records the pinned Qwen snapshot and dependency versions, including PyTorch 2.10.0+cu128, Transformers 5.17.0, PEFT 0.19.1, and bitsandbytes 0.49.2. For a new fit, use the local snapshot, the versions recorded in the result file, the pinned parser packages in `requirements-ast.txt`, and a BF16-capable CUDA device. Supply a fresh directory within an existing private output directory. The runner writes the split before fitting, then saves each fold's predictions, adapter, loss history, and hashes before writing the combined scores.

```sh
mkdir -p .codex/private
python -B development/train_pilot_resplit.py .codex/private/pilot-resplit-new
python -B development/assemble_pilot_resplit.py .codex/private/pilot-resplit-new .codex/private/pilot-resplit-new.json
```

The assembler verifies the split, fold predictions, adapter manifests, and aggregate scores. Assembling the completed five-fold run regenerated all 87,279 bytes of the released replay artifact.

## Candidate build and authored checks

The Phase 2 code is a patch against the frozen `pipeline.py`. The builder verifies the original byte digest, stages an LF-normalized copy, and applies the patch in a temporary directory. It refuses to replace an existing output. The candidate's SHA-256 is `ab43a6e4882bbba6d2f54a9dc9be99dfeb031d5d5633c265e993d53109f41563`. [Patch](phase2_pipeline.patch) · [Builder](build_candidate.py)

```sh
python -B development/build_candidate.py development/candidate_pipeline.py
python -B development/prompt_quarantine.py
```

All five AST tests and all nine selector and ranker tests passed. The isolated AST probe measured hit/work pairs of `(1, 8)`, `(1, 8)`, `(1, 8)`, `(1, 8)`, `(2, 16)`, and `(0, 0)` for the registered STL call sites in source order. The last site was short-circuited. The assigned recursive call registered one hit and one work unit before the process emitted its cap record at four total ticks, with one function entry. The AST recognizer covers supported full iterator ranges on known sequence variables and conservatively leaves ambiguous unqualified calls unweighted. [AST fixtures](../artifacts/phase2_data/test_phase2_ast.py) · [Selector and ranker fixtures](../artifacts/phase2_data/test_phase2_selection.py) · [Isolated AST probe](probe_gate2_ast.py)

On Ubuntu WSL2, use the pinned tree-sitter packages and run the integrated launcher on authored fixtures. The counter channel is a bounded per-invocation file separate from stdout and stderr. Its contents are telemetry from the instrumented process. The launcher validates the record against a separately observed process status.

```sh
python3 -B development/run_phase2_development.py --pipeline development/candidate_pipeline.py --probes-only
PYTHONPATH="$HOME/.local/share/eapg-phase2/deps" python3 -B development/probe_gate2_ast.py --pipeline development/candidate_pipeline.py
```

## Post-audit prospective development

The [draft synthetic protocol](PROSPECTIVE_SYNTHETIC_PROTOCOL.md) makes the same-symptom comparison with conventional backward slicing primary. The prototype uses the repaired work selector. The benchmark frame, whole-workload independent oracle builds, custody assignments, and signed lock remain pending.

The prospective build adds scoped receiver binding and derives caller evidence from AST call sites. Member weights require one recognized dot-member call. Caller inference covers one direct call to a visible global free-function definition. Forward declarations, overload resolution, argument-dependent lookup, and indirect calls are outside that caller model. The reference mapper reads the emitted byte spans and checks that its node IDs match the profiling receipt. The [prediction contract](prediction_contract.py) preserves the emitted slice, computes the actual prompt token count, and verifies that each candidate has a distinct single-token continuation. It emits abstentions for missing symptoms, empty slices, and unsupported representations.

The authored workflow uses three C++17 sources and four sizes. The reversible reset has an independent triangular-output oracle and closed-form cursor counts. The inverse is linear. An appropriate quadratic program can still trigger a slow-side symptom, illustrating why such an alert alone cannot establish a comparative regression. These fixtures check plumbing and specific expectations.

On Ubuntu WSL2 with GCC 15.2.0, the eight AST tests, ten selector tests, isolation and counter-transport probes, and source-map fixture passed. The prospective candidate SHA-256 was `2c95df0e5676e8b19464457adfb34cdf85a8a10cc0dca8b70557a1d587ced383`. The smoke run matched all 36 output checks across plain, UBSan and instrumented builds. The fitted work exponents at the independently counted increment were 1.97 for the reset and 1.00 for its inverse. The edited site mapped to `N4`, the work symptom was `N5`, and the symbolic order was `[N4, N5]`. The inverse abstained. The appropriate quadratic control had work exponent 2.00 and emitted a symptom. Two complete smoke reports were byte-identical with SHA-256 `30d0e1ab23d4fe16173274c7f04138ee0330e650c5bb97ceb21ceb9acfc83236`. The published stress cases retained all 12 references, with 10 ranked first, 68 clean runs, and four cap records.

From Ubuntu WSL, with the pinned parser packages and the existing Bubblewrap and systemd setup:

```sh
mkdir -p .codex/private
export PYTHONPATH="$HOME/.local/share/eapg-phase2/deps"
python3 -B development/build_candidate.py --prospective .codex/private/prospective.py
python3 -B artifacts/phase2_data/test_phase2_ast.py --pipeline .codex/private/prospective.py
python3 -B artifacts/phase2_data/test_phase2_selection.py --pipeline .codex/private/prospective.py
python3 -B development/probe_synthetic_intervention.py --pipeline .codex/private/prospective.py --output .codex/private/authored-smoke.json
```

From a Python environment with the pinned local Qwen snapshot, use the same files to verify prompt and target tokenization on CPU:

```sh
python -B development/probe_prediction_contract.py --pipeline .codex/private/prospective.py --profile .codex/private/authored-smoke.json
```

The pinned tokenizer produced 103 prompt tokens for the intervention and 77 for the appropriate quadratic control. All emitted candidates had single-token continuations. The linear inverse produced no prompt or candidate tokens.

### Corrections for the next manuscript

Describe the archived STL weight as applying to qualified `std::find` and `std::count`. Describe weighted `std::reverse` in the later implementation. The archived tick macro emits its cap record directly when work reaches or exceeds the ceiling. Its normal-exit handler runs on a separate path. Identify the revision used for each table and describe the weights as operation-count proxies. Lead the next manuscript with work-weighted profiling and scoped candidate selection. Present the historical adapter comparison and grouped refit as development evidence. [Archived weights](../pipeline.py#L401) · [Archived cap](../pipeline.py#L508)

### Conventional baseline and ledger replay

The [conventional comparator](backward_slice.py) computes reaching definitions and control dependence from a structured C++17 control-flow graph, then projects the backward dependence closure to canonical macro-nodes. Its current domain is one `int main()` with integral scalars, structured control flow, and modeled scalar standard I/O. General calls, containers, and aliases are excluded. The [factorial comparison](synthetic_arms.py) uses the same symptom and ranking policy within each hit or work channel. It keeps an observed alert when a comparator cannot produce a slice.

The [authored comparison probe](probe_synthetic_comparison.py) uses the reversible cursor reset, a same-growth sham, and an appropriate quadratic control across six sizes and the three registered seed IDs. These fixtures are deterministic, so all three seeds reuse the same inputs. The probe checks the affected operation counts against closed forms, verifies outputs through the existing plain, UBSan and instrumented paths, and generates separate draw, label, and prediction ledgers. At every seed, both work slices used `N5` as the symptom and retained the edit `N4`. The scoped arm ranked the edit first out of two candidates, and the conventional arm ranked it second out of five. The sham emitted no alert, and the appropriate quadratic control emitted one. The scorer classified the one positive family as under-sized. These runs exercise the machinery of the draft protocol.

Two WSL runs produced byte-identical ledgers. The prediction ledger SHA-256 was `f64c4c37df1c1f6a737efdd1f2c3cb8ea960fc7cda537edc0b0b9cdc578f5782`. The score report SHA-256 was `e5ef3ba210415b473acdab7e0baba89f320506ea752ad22d19c533ed1e630a42`. Nine backward-slice tests, four comparison-arm tests, three scorer tests, and the 18 AST and selector tests passed in WSL. The frozen release and refit score replays also passed.

The work and hits arms produced identical predictions on every scalar fixture. The library calibration below tests work weighting at an observed symptom. The scalar comparison supplies the separate reversible edit reference.

Run in the WSL environment above with a fresh ledger directory:

```sh
python3 -B development/probe_synthetic_comparison.py --pipeline .codex/private/prospective.py --output .codex/private/ledgers
```

Pass the three digests printed at generation to the [synthetic scorer](score_synthetic.py). Run this command in any Python environment with access to the ledgers:

```sh
python -B development/score_synthetic.py \
  --draw .codex/private/ledgers/draw.json --draw-sha256 "$DRAW_SHA" \
  --labels .codex/private/ledgers/labels.json --labels-sha256 "$LABELS_SHA" \
  --predictions .codex/private/ledgers/predictions.json --predictions-sha256 "$PREDICTIONS_SHA"
```

### Comparator-swap diagnostic

The evaluated program sums the integers from 1 through `N` by resetting a cursor to zero and incrementing it to the current index on each outer iteration. The linear comparator starts the cursor at `i - 1`. The quadratic comparator starts it at `1`. Each comparison changes only the reset statement and preserves the output. A separate counting build tallies scalar initializations and updates, condition evaluations, and input and output items. With `I` cursor increments it counts `8 + 5N + 2I` operations. The closed-form increment counts are `N(N+1)/2`, `N`, and `N(N-1)/2`, respectively.

All 54 independent counting-build outputs matched the result oracle and the operation formula. The plain, UBSan, and instrumented checks also completed successfully. We used `N = 8, 16, 32, 64, 128, 256` at `-O2` with GCC 15.2.0 in Ubuntu WSL2. The three seed IDs replayed the same deterministic inputs.

| Comparator | Growth order | Fitted log operation-ratio slope | Evaluated/comparator operations at N = 256 | Fixture disposition |
|---|---|---:|---:|---|
| Cursor starts at `i - 1` | Linear | 0.870 | 37.267× | Growth-changing positive |
| Cursor starts at `1` | Quadratic | −0.039 | 1.008× | Same-growth sham |

Both prediction calls received the same evaluated source, workload, and EAPG trace. All seven arms returned identical results across the two comparisons at each seed. The work selector alerted on `N5` both times. Scoped and conventional slicing ranked the reset `N4` first and second, respectively. For this pair of comparisons a binary alert using only the evaluated-side inputs must misclassify at least one label. The fixture checks this limit in an already used family, so it contributes no independent family to the prospective comparison. [Probe](probe_comparator_swap.py) · [Raw results](comparator_swap_results.json)

Two new runs generated byte-identical reports with SHA-256 `e0971ef538cc07bbe1fdc8115caa56f443930a6fdfc6433a52b07bd251496856`. Use the prospective build and WSL environment above to rerun the diagnostic.

```sh
python3 -B development/probe_comparator_swap.py \
  --pipeline .codex/private/prospective.py --output .codex/private/comparator-swap-new.json
```

### Transitive-edit diagnostic

The authored variant copies a reset value through two assignments before it reaches the inner loop guard. The original starts each inner traversal two increments below its endpoint. The edited version starts at zero and needs `2i` increments on outer iteration `i`. Both traverse to the same endpoint and sum the same integers through `N`. With `I` increments, the registered counting rule totals `10 + 7N + 2I` units for input and output items, initializations, tests, and updates. This gives `10 + 11N` units for the original and restored programs, and `10 + 7N + 2N(N+1)` for the edited program.

All 162 executions of the three source versions across the plain, UBSan, and counting builds matched their registered outputs on the six sizes. At `N=256` the observed operation count increased from 2,826 to 133,386, a ratio of 47.200. The fitted slope of the log ratio was 0.899 with the same inputs under each of the three seed IDs. The byte-exact mapper traced the altered RHS to `N7`. Both slicing arms used work symptom `N10`. The conventional slice retained `N7` and ranked it second among seven candidates. The scoped slice returned `[N9, N10]` and excluded the edit. Both arms missed at Top-1. This is a targeted failure mode in authored development evidence.

Two fresh runs matched in outputs, counts, fits, mappings, and predictions. Only launcher times and CPU-accounting fields differed. The [saved receipt](transitive_edit_results.json) has SHA-256 `38117df6bea6570b8e106457de8bdc6c16df907578a6f8102a3e06d3bec3a495`. The [manuscript verifier](verify_manuscript_pilot.py) replays each table from the frozen evidence and compares the stored diagnostic outputs and measurements with their analytic values.

```sh
python3 -B development/probe_transitive_edit.py \
  --pipeline .codex/private/prospective.py \
  --pipeline-sha256 2c95df0e5676e8b19464457adfb34cdf85a8a10cc0dca8b70557a1d587ced383 \
  --out .codex/private/transitive-edit-new.json
```

### Scope boundary with analytic profiles

The analytic fixture crosses four copy-chain depths (`0, 1, 2, 4`) with three counts of overwritten guard-variable assignments (`0, 2, 8`). Each outer iteration sums its index after advancing a cursor to that index. Changing the initial expression from `i - 1` to `0` changes inner-loop visits from `N` to `N(N+1)/2` and leaves the final sum unchanged. The constructed profiles on six sizes supply the derived counts to the same selector and both slicing arms.

The scoped inter-scope rule admits low-growth writes in the same parent that define a guard variable. It retains the edited definition only if the definition writes the cursor directly. Every overwritten cursor write satisfies this nomination rule even though its value never reaches the guard. The conventional closure follows the reaching copy chain and keeps the edit in all 12 cells. With depth `d` and overwritten count `k`, the scoped and conventional candidate counts are `k+2` and `d+6`. At zero depth and eight overwritten writes, the lists contain ten and six nodes respectively. The 12 cells are one authored mechanism family.

All 24 original and edited C++ sources pass GCC's C++17 syntax check. The fit profiles are analytic, and the archived receipt distinguishes them from the executed transitive-edit diagnostic. Two fresh static replays produced byte-identical JSON with SHA-256 `3ef5a388b2041097ad3fe2f768a2ca09b1d1537c2d4d7ffbc52bf7780d7d27c7`. [Receipt](scope_boundary_results.json)

```sh
python3 -B development/probe_scope_boundary.py \
  --pipeline .codex/private/prospective.py \
  --pipeline-sha256 2c95df0e5676e8b19464457adfb34cdf85a8a10cc0dca8b70557a1d587ced383 \
  --output .codex/private/scope-boundary-new.json
```

## Comparator domain and external source feasibility

The [archived domain audit](audit_pilot_baseline_domain.py) replays all 100 frozen slow sources through the current conventional slicer's static domain check. All use unsupported headers and define multiple top-level functions. The archive contains 66 programs with two functions and 34 with three. Archived preprocessing reattaches the headers, so the rejection is independent of counter values, reference membership, and scores. Thus the frozen cohort has zero conventional comparisons under the current scalar domain. Its same-work-symptom ablation remains reproducible across the internal scope configurations.

```sh
python -B development/audit_pilot_baseline_domain.py
python -B development/audit_pilot_baseline_domain.py --json
```

Public sources address different parts of the remaining design. Official contest problem specifications offer externally authored tasks for a controlled intervention study. Authors still need supported scalar implementations, reversible interventions, and independently checked oracles. UOJ-Bench publishes natural repair pairs, and its paper reports aggregate time-limit counts. A separate transfer screen would need verified rights for the submitted programs, an input-size growth screen and accepted spans. CppPerf-DB's repository patches and build containers suit a repository-level comparison once the analysis supports that domain. [NWERC problem packages](https://2025.nwerc.eu/) · [Yosupo Library Checker](https://github.com/yosupo06/library-checker-problems) · [UOJ-Bench paper](https://proceedings.mlr.press/v306/xu26co.html) · [CppPerf-DB paper](https://arxiv.org/html/2605.10890v1#S3.SS1)

For UOJ-Bench, the released repair rows contain code, problem IDs and language labels. The release files we inspected have no execution-verdict field. The paper's time-limit counts therefore do not identify specific candidates in those files. On the pinned release, the header rule excludes 491 of 500 Easy and 212 of 214 Hard C++-family evaluated programs. The 11 survivors span ten problem IDs. The same bound holds with the restriction checked on both versions. All 41 pairs explicitly labeled C++17 fail this check. This is a source-domain upper bound for the current comparator. Syntax, output equivalence, growth, and edit references still need checks on survivors. [Pinned release files](https://github.com/hehezhou/UOJ-Bench/tree/ce1c006d9f6cf57670d15e62c3e63a08ea669adb/dataset) · [Aggregate receipt](uoj_source_availability.json)

Use the pinned `sampled_large_submission_pairs.json` and `small_submission_pairs.json` files from that release. The script verifies both byte-level SHA-256 pins and emits only aggregate counts. Its output has SHA-256 `ab1262194cf52b7e1dde077316751b874ebec06091031c631dd26fc6610d181f` with UTF-8 and LF line endings.

```sh
python -B development/audit_uoj_source_availability.py \
  --easy "$UOJ_EASY_JSON" --hard "$UOJ_HARD_JSON"
```

The follow-up raw-AST audit passes **0/714** UOJ C++-family evaluated programs (303 problem IDs) and **0/100** frozen pilot evaluated programs (41 problem IDs) to a complete conventional CFG. Hiding only top-level literal include nodes gives the same two results. All 41 explicitly labeled C++17 UOJ rows still fail. After omission, the three most common first blockers in UOJ are `using_declaration` (281), raw parse errors (207), and `preproc_def` (137). The pilot first blocks on multiple function definitions (87) or unsupported top-level declarations (13). These are first blockers before preprocessing and brace normalization. The screen keeps nested and macro includes, all other nodes, and existing parse-error flags. It compiles and executes no released submissions. Two complete replays produced the same LF-delimited receipt, with SHA-256 `5fb9ea5ddee40c0023d870619e06f68c09d4f847e7adfa988c14146c57da5928`. [Script](audit_comparator_bottlenecks.py) · [Aggregate receipt](comparator_bottlenecks.json)

```sh
python -B development/audit_comparator_bottlenecks.py --download
```

The prospective preflight validates the entire inventory against planned raw version hashes before any compiler child process. It checks C++17 syntax, candidate normalization, and conventional CFG construction, and records reachable canonical role counts. Three focused unit checks passed. A separate authored-only replay used native GCC 15.1.0 for syntax and preprocessing with the pinned prospective Python code. It accepted 9/10 mock slots and one of two mock families and exercised normalized `<cstdio>` I/O and synthetic braces. WSL could not start on the host, so the new CLI still needs a pinned Ubuntu isolation replay. These are source-domain checks that give no localization measurements. [Preflight](audit_synthetic_frame_domain.py) · [Unit checks](test_audit_synthetic_frame_domain.py)

The external-specification screen supplies 16 credited OEIS definitions in ten candidate groups before further merging. It documents a development-only intake with original code and generators, separate publication rights, and stage-by-stage failure counts. Even these groups have unmeasured eligibility. No independently reviewed research cohort has been collected. [Candidate intake](SCALAR_FRAME_FEASIBILITY.md)

## Integrated CPU study dry run

The authored dry run invoked the custodian, blinded predictor, and independently pinned scorer as separate commands. Its 322-slot mock roster carried 316 provenance exclusions through scoring. Six slots from one development family executed in Ubuntu WSL2 with Bubblewrap and GCC 15.2.0. The oracle built 54 binaries and checked 972 executions. The profiler produced 90 evaluated runs and shared a single capture between the two comparator-swap entries. The scorer joined 322 labels and 966 prediction rows, verified one comparator-swap pair per seed, and recorded the primary cohort as under-sized. All 15 archived private stage receipts matched the final private evidence. [Dry-run command](SYNTHETIC_STUDY_RUNBOOK.md#authored-dry-run)

The canonical authored score has SHA-256 `3be674f5c39e7ea62f5115d1c7261e7bd886774f5db4e5c8d6eb958d04f6a532`. Compare scientific outcomes and coverage across executions. Raw build and execution receipts also bind runtime and CPU-accounting observations, which can vary.

The source fingerprint replay uses the candidate's normalizer and parser and compares the entire source inventory against the attested graph inputs. Unit checks and a separate native GCC preprocessing check on three authored inputs confirmed that renaming a local `count` binding and changing numeric literals preserves the template digest, while changing an arithmetic operator changes it. The latter check used the pinned Python candidate through native preprocessing after the host could no longer start Ubuntu WSL. The WSL provenance command remains to be exercised in the final pinned environment. [Fingerprint replay](synthetic_source_fingerprints.py) · [Planning sensitivity](PROSPECTIVE_SYNTHETIC_PROTOCOL.md#estimands-sizing-and-decision)

## Library work-proxy calibration

The [locked library calibration](../artifacts/weighted_panel/README.md) extends the first-versus-last search probe to eight conditions across three C++17 library operations. Separate counting builds and closed-form oracles confirmed comparisons and swaps across all six sizes. Under each of three optimization levels, the proxy's growth classification agreed with the oracle in six of eight conditions and overstated growth in two early-match searches. The work selector chose the target call eight times and the hits-only selector emitted no symptom. The artifact includes the first lock for the interrupted reporting attempt and the corrected lock used in two byte-identical complete runs. These workloads calibrate the measured construct at a library call. They contribute no independent edit families to the prospective comparison.

## Registered PIE development replay

On the previously registered validation pair, both submissions matched the independent output oracle on all 18 inputs at each stage. That gives 36 checks each for the original, UBSan, and instrumented builds. All 36 instrumented outputs also matched byte-for-byte. Across the 18 slow-side runs, the independently derived formula `(N / 4 − 1)(N / 2 + 2) + 1` matched the traversal counts of `N12`. Work scaling on this node was 2.00 with R² 1.00 for each of seeds 42, 43, and 44.

The frozen work selector chose `N11` and kept `[N10, N11]` on each seed. The repaired selector chose `N12`, its only qualifier, and retained `[N12]` out of 20 nodes on each seed. This is 95% node reduction on one development pair under three input seeds. The two independently launched reports matched byte-for-byte with SHA-256 `e6f0b75f6625b2ed39bd846a2603a0330953a4bacb572d53d97568d35cb9aef8`. Because the repaired slice is a singleton, the result tests symptom selection and candidate retention. It supplies no independent ranker comparison, runtime speedup estimate, or held-out accuracy. [Historical redacted counters](../artifacts/phase2_data/development_counters.json) · [Candidate redacted summary](registered_validation_summary.json)

To reproduce, use a local copy of the hash-pinned validation release and a writable, ignored output directory. Use fresh output paths for both runs. From the repository root in Ubuntu WSL2:

```sh
mkdir -p .codex/private
python3 -B development/run_phase2_development.py --pipeline development/candidate_pipeline.py --registered-validation "$PIE_VAL_JSONL" --output .codex/private/registered-a.json
python3 -B development/run_phase2_development.py --pipeline development/candidate_pipeline.py --registered-validation "$PIE_VAL_JSONL" --output .codex/private/registered-b.json
python3 -B development/summarize_validation.py .codex/private/registered-a.json --repeat .codex/private/registered-b.json
```

### Replay from a fresh official download

On 15 November 2026, a fresh download of `val.jsonl` matched the registered digest and contained 2,544 pairs across 77 problem IDs. We ran the registered pair for problem `p03497` using prospective candidate `2c95df0e5676e8b19464457adfb34cdf85a8a10cc0dca8b70557a1d587ced383`. The original, UBSan, and instrumented builds each passed 36 output checks across both submissions. The work selector returned the quadratic traversal `N12` as its only candidate on all three seeds. All 18 independently calculated slow-side traversal counts matched. [Official PIE split folder](https://drive.google.com/drive/folders/1E_yFqM8khN1HAH03OKhjheSlNI4rYTT7)

Two fresh profiling runs produced byte-identical reports with SHA-256 `ddb78e081d37cf4b825bd1554a514f625d9e73d3b7aa294a3c7661186f0558dd`.

From the repository root in the Ubuntu WSL2 environment above, fetch to a fresh ignored directory and verify the bytes before use.

```sh
set -eu
mkdir -p .codex/private
out=$(mktemp -d .codex/private/pie-replay-XXXXXXXX)
curl --fail --show-error --silent --location --proto '=https' \
  --output "$out/pie_val.jsonl" \
  'https://drive.usercontent.google.com/download?id=1Z01XyFil-w2XN1i9TNn7idzZ2DzDz-XL&export=download&confirm=t'
printf '%s  %s\n' \
  6608a303c5c6ab61e7936599f3aa8cbde67bc36007e1a9739d7868665c531dab \
  "$out/pie_val.jsonl" | sha256sum --check
export PYTHONPATH="$HOME/.local/share/eapg-phase2/deps"
python3 -B development/build_candidate.py --prospective "$out/prospective.py"
python3 -B development/run_phase2_development.py --pipeline "$out/prospective.py" \
  --registered-validation "$out/pie_val.jsonl" --output "$out/profile.json"
python3 -B development/summarize_validation.py "$out/profile.json"
```

## Independent timing screen on the registered development pair

The protected monotonic timer ran inside each fresh sandbox, from immediately before spawning the candidate through wait. It includes the process startup cost and excludes sandbox setup. Twenty isolated no-op runs had a median of 0.612 ms. The screen used five repeats per submission, size, and input seed, with the order shuffled using seed 42. All 180 measurements passed the output, process, and clock-resolution checks.

| Input seed | Slow/fast median ratio at largest size | Slope of log ratio against log size | Timing screen |
|---:|---:|---:|---|
| 42 | 11.21× | 0.398 | Fail |
| 43 | 13.77× | 0.452 | Fail |
| 44 | 12.74× | 0.439 | Fail |

The rule requires a largest-size ratio of at least 1.5 and a slope of at least 0.50 on every seed. Each seed met the ratio threshold and missed the slope threshold. The counter-based quadratic traversal and the failed runtime screen measure different outcomes. Retain the development case as a diagnostic and exclude it from confirmed-positive claims under this screen. These timing measurements depend on the machine and scheduling. The fixed observations and calculations are available for replay. [Source-free timing observations](runtime_validation_timing.json) · [Timing harness](runtime_screen.py)

The fresh-download timing replay passed all 180 output checks. In seed order 42, 43, and 44, the median slow-to-fast ratios at the largest input were 14.43, 15.44, and 14.22. The fitted log-ratio slopes were 0.470, 0.490, and 0.491, all below 0.50. Median no-op startup was 0.564 ms. The local timing report SHA-256 is `e086bd9cefc42bca216a7807a31c53245a2369e6c56c3129083927e6dea0eba5`.

```sh
python3 -B development/runtime_screen.py --registered-validation "$PIE_VAL_JSONL" --output .codex/private/timing-new.json
python -B -c "import json,sys; sys.path.insert(0,'development'); from runtime_screen import summarize; r=json.load(open('development/runtime_validation_timing.json')); assert summarize(r['samples']) == r['per_seed']"
```

## Fixed synthetic stress cohort

Before running the candidate on this cohort, select the lexicographically first published pair in each mechanism and include `PAIR_033`–`PAIR_036` to exercise the reported loop-bound failure. Profile the 12 slow programs at sizes 2, 4, 8, 16, 32, and 64. Use the published generator and verify the generated source against the archived pilot. Map each frozen reference to a unique candidate node by role and full normalized source preview, after checking its published preview prefix. Fit only uncapped observations. Compare each uncapped instrumented output with the plain slow output byte-for-byte.

All 12 reference nodes mapped uniquely and were retained. Ten ranked first and two ranked second (`PAIR_063` and `PAIR_076`). The four loop-bound references ranked first. All 68 uncapped runs matched the plain slow output. The four capped runs were `PAIR_039` and `PAIR_089` at sizes 32 and 64. Each emitted a validated cap record at 2,000,000 ticks and was excluded from the fits. The rerun reproduced the 72 tick totals and statuses, 12 symptoms, reference mappings, and ranks. The rerun report's SHA-256 is `c11ce87755efa057b54db9a5177e0422629074c562121be24033d7ad467eb623`. This cohort measures behavior on published generator-aligned slow programs. The four loop-bound cases share one template group and exercise a targeted repair. [Reproduction script](probe_gate2_pilot.py)

```sh
PYTHONPATH="$HOME/.local/share/eapg-phase2/deps" python3 -B development/probe_gate2_pilot.py --pipeline development/candidate_pipeline.py
```

## Quarantine and external readiness

The final-prompt quarantine helper adds exact token-sequence fingerprints to the existing static custody graph. The authored self-check verifies numeric-literal normalization, equal prompts, transitive exclusion, and rejection of missing prompt information. Explicitly unsupported serializations retain their static graph links and are ineligible for training. Final fingerprints still require the pinned serializer and custodian-provided cohort inputs. [Quarantine helper](prompt_quarantine.py)

The external study remains gated on a frozen study revision, registered per-problem workloads and independent runtime screening, custodian-run quarantine on real cohorts, and independent blinded human reference adjudication. Preserve end-to-end equal-group paired Top-1 as primary. Treat matched multi-candidate ranking as secondary. Any held-out comparison must use the same canonical candidate sets and a fresh pinned, quarantined node-only adapter. [Decision gates](../PHASE2_DECISION.md) · [External protocol](../artifacts/phase1_correction/phase2_protocol.md)

For the proposed protocol revision, use the repaired selector and canonical ranker as the primary shared pipeline. Run the frozen Phase 1 selector as a separately labeled diagnostic. Fix polynomial eligibility at a work jump of at least 0.70 and a work exponent of at least 1.50, or a work-minus-hit gap of at least 0.70. Admit exponential fits at the first exponential scope. Order eligible nodes by exponential before polynomial and descending fitted exponent within family. Break exponent ties by preferring loops, function entries, or hidden work and then by traversal order. The registered development and synthetic replays motivate this proposal. The prospective test still requires a locked workload and eligibility ledger and a separate blinded human adjudication record. [Candidate policy](phase2_pipeline.patch)

The [external study handoff](EXTERNAL_STUDY_HANDOFF.md) specifies the custody, reference, and prediction boundaries and the scorer's input ledgers.

## Six-representation 13-group ablation matrix

The grouped 13-component ablation evaluates all six prompt representations (`raw_code`, `hotspot_raw`, `static_eapg`, `abstract_hits_only`, `abstract_graph`, `full_eapg`) across Base and 4-bit NF4 QLoRA `Qwen2.5-Coder-1.5B` under both Unconstrained ($V$) and Slice-Constrained ($C_{\mathrm{pruned}}$) decoding on RTX 4060 (`<= 496 <= 512` tokens, peak `2.91 GiB` VRAM), reusing the fold-disjoint 5-fold split (`19, 19, 19, 21, 22`). [Training runner](train_resplit_ablation.py) · [CPU replay](replay_resplit_ablation.py) · [Ablation JSON](../artifacts/pilot_resplit/ablation_results.json)

| Method / Representation | Max tok | Base Unc (All) | Base Con (All) | QLoRA Unc (All) | Constrained (All) | Multi-cand (66) | Off-symptom (18) |
|---|---:|---|---|---|---|---|---|
| `raw_code` | 246 | 9/100 (6.05) | 55/100 (48.78) | 54/100 (47.52) | 66/100 (67.84) | 32/66 (58.19) | 11/18 (67.50) |
| `hotspot_raw` | 346 | 6/100 (4.27) | 52/100 (43.41) | 62/100 (50.35) | 83/100 (79.85) | 49/66 (73.81) | 15/18 (75.00) |
| `static_eapg` | 413 | 3/100 (2.56) | 64/100 (46.51) | 39/100 (38.07) | 74/100 (66.43) | 40/66 (56.36) | 9/18 (50.00) |
| `abstract_hits_only` | 257 | 16/100 (11.18) | 66/100 (58.83) | 73/100 (60.09) | 78/100 (72.32) | 44/66 (64.02) | 9/18 (58.33) |
| `abstract_graph` | 307 | 21/100 (14.66) | 62/100 (52.29) | 85/100 (77.49) | 90/100 (84.44) | 56/66 (79.77) | 11/18 (70.83) |
| `full_eapg` | 496 | 2/100 (1.71) | 66/100 (47.91) | 73/100 (56.03) | 75/100 (58.27) | 41/66 (45.75) | 3/18 (23.33) |
| Uniform guessing | -- | -- | -- | -- | 63.57/100 (52.02) | 29.57/66 (37.62) | 5.57/18 (29.38) |
| Raw slice order | -- | -- | -- | -- | 41/100 (46.15) | 7/66 (30.00) | 7/18 (50.00) |
| Symbolic (`def_use=False`) | -- | -- | -- | -- | 70/100 (76.92) | 36/66 (70.00) | 14/18 (83.33) |
| Symbolic (`def_use=True`) | -- | -- | -- | -- | 96/100 (92.31) | 62/66 (90.00) | 14/18 (83.33) |

- Adding `a_work` alone (`abstract_graph` minus `abstract_hits_only`) increases multi-candidate Top-1 by `+15.75` group points (`[-6.07, +39.77]`, LOO `[+6.39, +23.06]`) and overall unconstrained Top-1 by `+17.40` points (`73 -> 85`).
- Adding raw identifiers and previews (`full_eapg`) overfits surface code on unseen templates (`0/6` `A1.4`, `7/13` `B.2`), trailing `abstract_graph` by `+26.17` points overall (`[+4.62, +50.11]`) and `+34.02` points on multi-candidate (`[+6.32, +62.12]`).
- Removing pilot-specific loop-alias tuning (`use_loop_def_use=False`, matching prospective protocol) reduces symbolic Top-1 by 26 pairs in `B.1`/`B.2` to `70/100 (76.92%)`.
- Ablation receipt SHA-256: `5302a926d68d4bb975c2fd2565a588d09ae3a3bdf49aba580c63f1db6f52c83d`.

## End-to-end live neural contract and OEIS scalar intake audit

- **Live prediction contract:** `predict_external_contract.py` connects `prediction_contract.prepare_prediction` through pinned 4-bit QLoRA weights to `score_external.score` (`eapg-external-predictions-v1`), testing all seven abstention and success dispositions in CPU unit tests (`test_predict_external_contract.py`) and verifying live GPU execution on RTX 4060 with pinned fold-0 adapter `33dfb098f723365b98b98a396d23e0005c353963c26283f908b3367084527637` against `authored-smoke.json` (`D_pos=2`, `D_elig=1`, `verified_negative_alerts=1/2`). [Contract executor](predict_external_contract.py) · [Contract test](test_predict_external_contract.py)
- **Development-only 10-group OEIS intake funnel:** Evaluates trusted C++17 sketches across all 10 OEIS groups (11 specs) via native GCC 15.1.0 syntax/preprocessing, pinned normalizer `2c95df0e`, conventional CFG, intervention resolution, and analytic scaling. Four reject prior to scaling (`A000788`, `A000045`, `A006257`, `A003586`), zero fail CFG/token mapping, two fail the `0.55` slope floor (`A006218_quotient` `0.4827`, `A002088` `0.5116`), leaving 5 eligible specs across 4 distinct mechanisms (`A000328` and `A000201` collapse onto `monotone_cursor_reset`). On analytic profiles, `work_scoped` hits `3/5` Top-1 (`4/5` retained; misses two-scope `A400004` `N7 -> N9` and ranks `N6` ahead of `N7` on `A001399`) vs `0/5` Top-1 (`5/5` retained) for `work_conventional`. Extractor analysis across the 100 pilot slow programs shows `pipeline.py:312-314` `for`-update `defs` pollution fires on `0/193` pilot loops yet fires on `3/7` syntax-passing OEIS cases. [Intake audit](audit_scalar_intake.py) · [Intake receipt](scalar_intake_feasibility.json) · [Intake test](test_audit_scalar_intake.py) (`46b5d2216063f888567779d8dc8d31cab6828614683bba7255f66d2f835831f7`).

## Role-separated multi-agent prospective scalar study and blinded contract

> **Note:** Both parts are bounded feasibility runs (`primary_sized=false`, $10 < 60$ families; `positive_transfer_evidence=false`, $11 < 20$ groups). See [`../docs/INDEPENDENT_AUDIT.md`](../docs/INDEPENDENT_AUDIT.md).

Executed in both unmodified Linux WSL2 (`Linux 6.6.87.2-microsoft-standard-WSL2`, `GCC 15.2.0`, `Bubblewrap 0.11.1`, `systemd-run --user --scope`, `-fsanitize=undefined -fno-sanitize-recover=undefined`, FD 199 counter transport; all four `probe_gate1.py --probes-only` checks passing) and Windows 11 native (`MSYS2 GCC 15.1.0`, `-fsanitize-trap=undefined`, file-backed counter wire, RTX 4060 8 GB VRAM), proving cross-OS exact equivalence across all 322 labels (excl. platform `operation_evidence_sha256`), all 42 active trace projections, all 294 predictions, and byte-identical `score.json` (`ce049b3262f536599d9c332c6a8558fd0073bd94df8f37692e901f25fab6f4b9`). Four role-separated isolated subagents performed pre-execution verification (Part A) and blinded reference adjudication (Part B). Receipt: `prospective_multiagent_results.json` (`2016611a8d142b0068b5e5c03ed9f685a0196c6159510b808ca2135c7928cf81`) · Primary WSL2 ledgers: `frame` `79fe894b`, `draw` `e7b6d1e5`, `quarantine` `9b97ec6b`, `labels` `81208be9`, `blind` `5513afd1`, `predictions` `6bb9971d`, `score` `ce049b32` (Windows cross-OS: `labels` `b0540ab1`, `blind` `928d49af`, `predictions` `4060140b`, `score` `ce049b32`) · [Execution runner](run_prospective_multiagent_study.py) · [Verifier test](test_prospective_multiagent_study.py).

- **Part A (10 unseen scalar families, 80-family / 322-slot frame, 280 placeholder-quarantined slots via synthetic `exposure_frame_placeholders` bridge across `102` total exposure rows and `0` real collisions with `101` pilot+PIE exposure rows, 42 active slots, 0 pilot template or prompt-token collisions, 378 oracle builds, 6,804 oracle runs, 738 profile runs across seeds 42–44):**
  - Core 20 positives: `work_scoped` (`def_use=False`, unbiased default) scores `15/20 (75.00%)` equal-family Top-1 (`16/20` retention, `89.38%` mean reduction; matching `hits_scoped` at `15/20` and raw slice order `6/9` multi-candidate) vs. `0/20 (0.00%)` for `work_conventional` (`20/20` retention, `64.34%` reduction; paired `+75.00 pp`, 95% bootstrap `[60.00, 90.00]`, LOO `[72.22, 77.78]`, driven by shared ranker hoisting CFG-reachable `STATE_UPD` initializers/accumulators ahead of the symptom) and `14/20 (70.00%)` for pilot-refined `work_scoped_symbolic` (`def_use=True`, `F08` off-site inversion).
  - Off-site positives (`N=10`): `6/10 (60.00%)` vs. `0/10` (`+60.00 pp` `[30.00, 90.00]`), missing `F02`, `F04`, `F06`, and deliberate 2-hop chain `F10`; `work_scoped` emits false alerts on `5/10` quadratic shams, `10/10` appropriate controls (`0%` specificity), and `1/1` comparator-swap pair on `F01`.
  - Live 4-bit NF4 GPU inference (max `2.182 GiB` VRAM; uniform `core_20` denominator vs. `21`-slot all-confirmed including duplicate `F01 comparator_swap_positive`): Base Constrained `12/20 (60.00%)` [`12/21, 58.33%`], Base Unconstrained `0/20` [`0/21`], fold-0 `abstract_graph` Constrained `11/20 (55.00%)` [`11/21, 53.33%`] / Unconstrained `2/20 (10.00%)` [`2/21, 10.00%`], fold-0 `hotspot_raw` Constrained `13/20 (65.00%)` [`14/21, 65.00%`].
- **Part B (`14` positive pairs across `11` groups — `12` pilot pairs held out-of-fold, `1` authored smoke pair, `1` sub-0.50 timing pair `PIE_DEV_p03497` — + `2` verified negative controls, blinded Reviewer A/B + Adjudicator C + live RTX 4060 `predict_external_contract` + `score_external`):**
  - Cross-OS stress reproduction (`72` runs across 12 stress pairs, Windows GCC 15.1.0 `2c95df0e` vs. archived Ubuntu WSL2 GCC 15.2.0 `c4260272` receipt): exact match (`repro_mismatches=[]`), plus byte-identical Linux normalized hashes on `PIE_DEV_p03497` (`6133cd49...`) and `AUTHORED_SMOKE_POS` (`03c3f0dc...`).
  - Adjudication: Reviewers A & B marked identical raw line spans on `13/14` positives; `PAIR_013` resolved by round-1 consensus (`N6`), and `13` mapped/adjudicated via Adjudicator C (`14/14` resolved).
  - External contract scoring (`D_pos = D_elig = 14` across 11 groups; `D_rank = 10` across 7 groups): `work_scoped` slice recall `12/14 (81.82% group / 85.71% pair, 86.47% mean reduction)`; strictly out-of-fold `abstract_graph` scores `10/14 (63.64% group)` (vs. partially in-fold `fold-0` at `12/14 = 81.82%`), beating unbiased symbolic (`def_use=False`, `6/14`, `54.55% group`; `+9.09 pp [-27.27, +45.45]`, `6` neural-only vs. `2` symbolic-only) and matching `prediction_contract.py`'s pilot-refined symbolic rule (`def_use=True`, `10/14`, `63.64% group`; `0.00 pp [-36.36, +36.36]`, `2` vs. `2` pairs). On `D_rank = 10`, strict OOF `abstract_graph` and refined symbolic (`def_use=True`) score `8/10 (71.43% group)` vs. `4/10 (57.14% group)` for unbiased `def_use=False`; verified-negative alert rate `1/2` (`AUTHORED_SMOKE_APPR` ranked `N4`; `AUTHORED_SMOKE_INV` returned `NO_SYMPTOM`).
