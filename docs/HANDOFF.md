# EAPG Research & Engineering Handoff

**Last Updated:** 18 November 2026 · **Repository State:** Reorganized, independently re-audited across three blind subagent passes, and verified dual-OS (`Windows 11` + `Ubuntu Linux WSL2 Bubblewrap` + `RTX 4060 8 GB`). Main branch is ready for review (`ask-before-commit`: no commits created yet).

---

## 1. Copy-Pasteable Onboarding Prompt for the Next LLM

Use the block below verbatim when starting a new session on this repository:

```text
Act as the lead of a CS research and systems team taking over the Execution-Annotated Program Graphs (EAPG) repository.

Read these files first before making any plan or edit:
1. README.md
2. docs/HANDOFF.md (this file)
3. docs/ARCHITECTURE.md, docs/REPRODUCIBILITY.md, docs/INDEPENDENT_AUDIT.md
4. PHASE2_DECISION.md, AUDIT.md, and development/RESEARCH_RECORD.md
5. manuscript/paper.tex, manuscript/method.tex, manuscript/evaluation.tex

Persona, Workflow & Hard Constraints:
- Tone & engineering discipline: Be blunt, direct, and concise. Ask clarifying questions before coding whenever specs or edge cases are ambiguous. Make surgical edits only; do not reformat or rewrite unrelated working code.
- Role-separated verification: Use independent, unprimed subagents when auditing, reviewing, or adjudicating claims/code so reviewers are never biased by the main prompt. Reconcile every disagreement strictly against executed checks, raw JSON receipts, and code on disk.
- Cryptographic & release immutability:
  * NEVER edit any of the 29 frozen entries in SHA256SUMS (pipeline.py, verify_release.py, AUDIT.md, requirements-ast.txt, .gitattributes, .gitignore, artifacts/scope_isolated_pilot/*, artifacts/phase1_correction/*, artifacts/phase2_data/{README.md,prepare_pie.py,run_development.py,development_*.json}, etc.) unless the user explicitly authorizes a new release version. (Only update README.md's hash in SHA256SUMS if README.md changes.)
  * NEVER modify modules hashed by custodian_revision() (e0c327f6...), prediction_revision() (7cda5c19...), or scoring_revision() (39c2b1f7...) in development/synthetic_study_{custodian,predict,score}.py without regenerating and re-sealing the complete custody chain.
  * NEVER commit or push to git without explicit user confirmation (ask-before-commit).
- Hardware & sandbox guards:
  * Consumer GPU budget: 8 GB VRAM (RTX 4060). Keep Qwen2.5-Coder-1.5B in 4-bit NF4 double quantization with torch.bfloat16, prompt cap <= 512 tokens (<= 26 nodes), small batch/microbatch sizes, and gc.collect() + torch.cuda.empty_cache() around runs.
  * Never execute unvetted C++ outside Bubblewrap + systemd-run (development/gate1_sandbox.py). Keep any held-out PIE test split (pie_test.jsonl) strictly sealed; preserve group/problem_id/template+prompt quarantine with zero cross-split leakage.
  * On Windows hosts calling frozen pipeline.py directly, ensure PYTHONUTF8=1 (eapg.py sets this automatically).
- Scientific honesty: Report sample-size gate failures (Part A primary_sized=false, Part B positive_transfer_evidence=false), false-alert rates (5/10 sham, 10/10 appropriate controls), sub-threshold timing checks (PIE p03497 < 0.50), and baseline quirks (work_conventional 0/20 due to STATE_UPD hoisting; def_use=False vs. def_use=True) transparently. Never fabricate citations, contributor attestations, or synthetic filler to inflate sample counts.

Mandatory Startup Verification (Run Before Touching Code):
1. python -B -S eapg.py status
2. python -B -S eapg.py verify --mode fast
3. python -B eapg.py replay --stage all
4. python -B eapg.py verify --mode auto --verbose   (or --mode wsl2 --with-probes on Windows+WSL2)
```

---

## 2. Detailed Current State

### 2.1 Repository Architecture & Core CLI
- **Unified Entrypoint:** [`eapg.py`](../eapg.py) (stdlib-only core + [`pyproject.toml`](../pyproject.toml) editable install `pip install -e .`) exposes:
  - `verify --mode {auto,fast,common,linux,wsl2} [--with-probes] [--wsl-distro Ubuntu] [-v]`
  - `replay --stage {release,pilot,resplit,ablation,library,manuscript,all}`
  - `build-candidate <output> [--prospective]` (resolves relative paths from caller CWD)
  - `study [--reuse-ledgers] [--wsl2-part-a-only] [--pipeline ...] [--attestations-dir ...] [--workdir ...] [--wsl2-ledgers-dir ...] [--output ...]`
  - `build-paper [--clean]` (compiles `manuscript/paper.pdf` via `pdflatex` + `bibtex` and strips `.aux/.bbl/.blg/.log/.out` when `--clean` is passed)
  - `status` (verifies `31/31` `SHA256SUMS` digests, PDF size, multi-agent receipt SHA-256, and host tools)
- **CI Workflow:** [`.github/workflows/verify-artifact.yml`](../.github/workflows/verify-artifact.yml) runs `status`, `--mode common`, `requirements-ast.txt` + `pytest` + `--mode linux` on both `ubuntu-latest` and `windows-latest`, and Gate 1 probes when user systemd + unprivileged userns are available on Linux.
- **Manuscript Status:** [`manuscript/paper.pdf`](../manuscript/paper.pdf) is **8 IEEEtran pages** (`333,510` bytes, SHA-256 `034bf0384e8851d81c078dadcad608d0c6b663e21de659e9dbee8b7bf7ad7927`), builds cleanly with **`0` overfull hboxes** and **`0` undefined warnings**, and has all tables verified deterministically by [`development/verify_manuscript_pilot.py`](../development/verify_manuscript_pilot.py) and [`development/replay_resplit_ablation.py`](../development/replay_resplit_ablation.py).

### 2.2 Pinned Cryptographic Ledger & Digests

| Artifact / Code Bundle | Path | Verified SHA-256 | Role / Status |
|---|---|---|---|
| Frozen Phase 1/2 pipeline | [`pipeline.py`](../pipeline.py) | `7c855651566c1a7dc003fdcb291d8edd3ff1a99c671f781eb595d72c492ae743` | Immutable (`SHA256SUMS`) |
| Archived Phase 2 candidate | [`development/build_candidate.py`](../development/build_candidate.py) | `ab43a6e4882bbba6d2f54a9dc9be99dfeb031d5d5633c265e993d53109f41563` | Built from `phase2_pipeline.patch` |
| Prospective candidate | [`development/build_candidate.py`](../development/build_candidate.py) (`--prospective`) | `2c95df0e5676e8b19464457adfb34cdf85a8a10cc0dca8b70557a1d587ced383` | Built from `+phase2_prospective.patch` |
| Prospective Custodian bundle | `custodian_revision()` | `e0c327f6ee57ff3575e0a8f5d56a2105e6e9293ee531003acb1ff90caa0d797e` | Immutable 18-file hash |
| Prospective Predictor bundle | `prediction_revision()` | `7cda5c19...` (verified dynamically) | Immutable 13-file hash |
| Prospective Scorer bundle | `scoring_revision()` | `39c2b1f7...` (verified dynamically) | Immutable 5-file hash |
| Part A & Part B Multi-Agent Receipt | [`development/prospective_multiagent_results.json`](../development/prospective_multiagent_results.json) | `2016611a8d142b0068b5e5c03ed9f685a0196c6159510b808ca2135c7928cf81` | Dual-OS WSL2+Win verified; includes `core_20`, `prompt_quarantine_audit`, `score_unbiased_symbolic` |
| Part A `score.json` (WSL2 == Win) | Private ledger (`ce049b32...`) | `ce049b3262f536599d9c332c6a8558fd0073bd94df8f37692e901f25fab6f4b9` | Byte-identical across Ubuntu WSL2 & Windows 11 |
| 6×2 13-Group Ablation Receipt | [`artifacts/pilot_resplit/ablation_results.json`](../artifacts/pilot_resplit/ablation_results.json) | `5302a926d68d4bb975c2fd2565a588d09ae3a3bdf49aba580c63f1db6f52c83d` | Backs Table II (`10` rows) |
| 13-Group `abstract_graph` Refit | [`artifacts/pilot_resplit/results.json`](../artifacts/pilot_resplit/results.json) | `a89d40d0846b1e3cf16bfc85faa9c30d1f07bce1431a70d3b38dec5d4cb5bebb` | Checkpoints reused by `abstract_graph` in ablation |
| OEIS 10-Group Intake Receipt | [`development/scalar_intake_feasibility.json`](../development/scalar_intake_feasibility.json) | `46b5d2216063f888567779d8dc8d31cab6828614683bba7255f66d2f835831f7` | Backs OEIS row of Table III |
| Library Calibration Panel | [`artifacts/weighted_panel/results.json`](../artifacts/weighted_panel/results.json) | `95948c69a864...` (verified by `verify_weighted_panel.py`) | Backs Table V (`480` checks) |
| Compiled Manuscript PDF | [`manuscript/paper.pdf`](../manuscript/paper.pdf) | `034bf0384e8851d81c078dadcad608d0c6b663e21de659e9dbee8b7bf7ad7927` | 8 pages, 0 overfull hboxes |

### 2.3 Summary of All 5 Empirical Evidence Strata

1. **Frozen 100-Pair Synthetic Pilot (`Table I`, `23` groups):** Work weighting raises symptom coverage from `80/100` (hits-only) to `100/100`; two-tier pruned slicing retains `100/100` mechanism references at mean size `1.90` (`89.0%` reduction) vs. `4.89` (`71.2%`) unpruned. On 23 groups, `6b-slice` scores `98/100` pair / `93.48%` group vs. refined symbolic `96/100` / `95.65%`.
2. **Strict 13-Group Six-Representation × Two-Decoding Ablation (`Table II`, folds `[19, 19, 19, 21, 22]`):**
   - `abstract_graph` QLoRA reaches `90/100 (84.44% group)` constrained and `56/66 (79.77%)` multi-candidate (vs. `44/66 = 64.02%` for `abstract_hits_only` showing $\alpha_v^{\mathrm{work}}$ gain, and `41/66 = 45.75%` for `full_eapg` showing identifier overfitting).
   - `hotspot_raw` reaches `83/100 (79.85%)` and excels on `off_symptom` (`15/18 = 75.00%` group) where identifier-stripped `abstract_graph` drops to `11/18 (70.83%)`.
   - Non-neural fixed-slice baselines: unbiased symbolic (`def_use=False`) `70/100 (76.92% group)`, refined symbolic (`def_use=True`) `96/100 (92.31%)`, raw slice order `41/100 (46.15%)`, uniform guessing `63.57/100 (52.02%)`.
   - Structural caveats recorded: `8/9` mechanisms sit in one fold each; `abstract_graph` prompt normalization collapses `80` distinct templates into `38` prompts (`0` cross-fold leaks); unconstrained Base hits exact Top-1 logit ties on `2..45/100` pairs.
3. **Bounded Prospective 10-Family Scalar Cohort — Part A (`Table IV`, `primary_sized = false`):**
   - `80`-family / `322`-slot draw across Ubuntu WSL2 Bubblewrap (`0.11.1`, `GCC 15.2.0`, FD `199`, all `4` Gate 1 probes passing) and Windows 11 (`MSYS2 GCC 15.1.0`): `280` placeholder slots (`E01..E70`) quarantined via synthetic `exposure_frame_placeholders` bridge (`102` exposure rows; `0` real collisions with `101` pilot+PIE items; `0` prompt-token collisions); `10` active unseen scalar families (`42` active slots; `378` builds, `6,804` oracle runs, `738` profiles across seeds `42–44`).
   - Core 20 positives: `work_scoped` (`def_use=False`) `15/20 (75.00%)` vs. refined `work_scoped_symbolic` (`def_use=True`) `14/20 (70.00%)` vs. `work_conventional` `0/20 (0.00%)` (`+75.00 pp`, `20/20` retention; `0/20` caused by `rank_candidates_by_role_priority` hoisting CFG-reachable `STATE_UPD` initializers/accumulators ahead of the symptom). False alerts: `5/10` quadratic shams, `10/10` appropriate controls (`0%` specificity).
   - Live RTX 4060 GPU (`core_20`, max `2.182 GiB` VRAM): `hotspot_raw` fold-0 `13/20 (65.00%)` [`14/21` with duplicate `F01:comparator_swap_positive`] > Base `12/20 (60.00%)` [`12/21`] > `abstract_graph` fold-0 `11/20 (55.00%)` [`11/21`].
4. **Bounded Blinded 3-Agent Contract — Part B (`Table IV`, `positive_transfer_evidence = false`):**
   - `14` positives across `11` groups (`12` out-of-fold pilot pairs, `1` authored smoke pair, `1` sub-`0.50` wall-clock timing pair `PIE_DEV_p03497`) + `2` negative controls; `72` stress runs matched identically between Windows `2c95df0e` and archived Linux `c4260272`.
   - Strict OOF `abstract_graph` scores `10/14 (63.64% group)` (`8/10 = 71.43%` $D_{\mathrm{rank}}$), exceeding unbiased `symbolic` (`def_use=False`, `6/14 = 54.55%` group; `+9.09 pp [-27.27, +45.45]`), matching pilot-refined `prediction_contract.py` `symbolic` (`def_use=True`, `10/14 = 63.64%`; `0.00 pp [-36.36, +36.36]`), and removing in-fold `fold-0` inflation (`12/14 = 81.82%`); negative control alerts `1/2`.
5. **Calibration, Domain & Boundary Diagnostics (`Tables III & V`):**
   - Library calibration (`std::find`, `std::count`, `std::reverse`): `6/8` gap agreement across `-O0/-O2/-O3` (`480` checks).
   - UOJ raw-AST CFG audit: `0/714` pass (`11` header-clean across `10` problems); Pilot raw-AST: `0/100`.
   - OEIS 10-group funnel: `5/11` eligible (`4` mechanisms; `work_scoped` `3/5` vs. `work_conventional` `0/5`); `for`-update `defs` pollution triggers on `3/7` syntax-passing OEIS cases vs. `0/193` pilot loops.
   - Comparator swap (`0.870` vs. `-0.039`, `54` checks), transitive edit (`162` runs, scoped drops `d=2`), 12-cell analytic scope grid (`d=0` iff retained), and `p03497` wall-clock screen (`0.398..0.452` / `0.470..0.491` all `< 0.50`).

### 2.4 Independent Re-Audit Resolutions & Directory Layout
See [`docs/INDEPENDENT_AUDIT.md`](INDEPENDENT_AUDIT.md) for the complete resolution record of all Critical/High/Medium/Low findings from three unprimed subagent audits (`Systems & Packaging`, `Data & Quantitative`, `Docs & Manuscript`), and [`artifacts/README.md`](../artifacts/README.md) + [`development/README.md`](../development/README.md) for file-by-file indexing.

### 2.5 Remaining Open Work & Genuine Blockers
1. **Git Initialization:** All public files in `eapg-github/` sit cleanly as untracked `??` on unborn branch `main`; review diffs/file tree and confirm with the user before creating an initial commit.
2. **Independent Human Cohort (`>= 60` families / `>= 30` off-symptom):** Expanding Part A from bounded `10`-family feasibility (`primary_sized = false`) to a powered confirmatory benchmark requires recruiting external C++17 authors and independent verifiers outside the team.
3. **Sealed PIE Test Split & Human Adjudicators (`>= 20` groups):** Evaluating held-out PIE (`pie_test.jsonl`) for external human-code transfer requires governance approval to unseal `pie_test.jsonl`, Linux Bubblewrap custodian execution, and recruited human reviewers.
4. **Future Technical Extensions (Out of Current Frozen Release Scope):** Reducing false alerts on appropriate superlinear controls (`10/10` in Part A) and quadratic shams (`5/5`) and linear shams (`0/5`; `5/10` pooled), and expanding C++17 parser/comparator support beyond single-`main()` integral scalar programs (`0/714` UOJ raw CFG).
