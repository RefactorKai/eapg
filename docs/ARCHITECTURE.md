# EAPG System Architecture

Technical reference for the Execution-Annotated Program Graphs pipeline, slicing rules, prompt representations, sandbox isolation, and cryptographic custody chain.

---

## 1. Normalization and Canonical AST Extraction

1. **Pass 0 (`g++ -E -P` Preprocessing):** Extracts literal `#include` directives, runs `g++ -E -P -x c++ -` (normalizing `\r\n -> \n` on Windows hosts — host provenance: the recorded Windows run used MSYS2 g++ — so normalized SHA-256 digests match Linux GCC `15.2.0` byte-for-byte), and restores the original `#include` header lines.
2. **Pass 1 (`tree-sitter-cpp` Bracing):** Inserts `{ ... }` around single-statement `for`, `while`, `do`, and `if/else` bodies in strict reverse-byte order (`right-to-left`), then validates syntax via `g++ -std=c++17 -fsyntax-only`.
3. **Canonical Macro-Nodes:** Pre-order traversal assigns IDs `N1`, `N2`, ... over function entries, loops, branches, calls, and state updates, partitioned by `MAIN_SCOPE`. Approximated `defs(u)` / `uses(u)` track reads and writes; prospective candidate [`2c95df0e`](../development/build_candidate.py) scopes container receiver bindings lexically and restricts inferred caller edges to visible free functions. Note that `for`-loop update expressions place all parsed identifiers into both `defs` and `uses` (`pipeline.py:312-314`).

---

## 2. Dynamic Micro-Instrumentation and Scaling Models

- **Event Counters & Work Proxies:** Each visited macro-node increments hit count $h_v(N)$ by $1$ and operation work count $w_v(N)$ by a static weight expression (container size $s$ for `std::find`, `std::count`, `std::reverse`, and recognized linear container operations; $\lfloor\log_2(s+2)\rfloor$ for ordered tree operations; $1$ for hash lookups and unknown receivers in the prospective revision).
- **Dynamic Tick Ceiling & Sandbox (`development/gate1_sandbox.py`):**
  $$B(N) = \max\bigl(2 \times 10^6,\; 5N^2\bigr)$$
  Exceeding $B(N)$ emits `CAP_BREACHED` and exits via `std::exit(0)`; only `CLEAN_COMPLETION` runs enter scaling fits. On Linux WSL2, [`gate1_sandbox.py`](../development/gate1_sandbox.py) isolates each build and binary invocation inside per-run Bubblewrap (`0.11.1`) mounts + `systemd-run --user --scope` resource limits, streaming JSON records over FD `199`. All four Gate 1 isolation fixtures ([`probe_gate1.py`](../development/probe_gate1.py)) pass cleanly.
- **Scaling Regression:** For each node $v$ and channel $c \in \{\mathrm{hits}, \mathrm{work}\}$ over uncapped sizes, OLS estimates both power-law slope $\alpha_v^c$ ($\log \max(1, Y_v^c)$ vs. $\log N$) and exponential slope $\beta_v^c \ge 0.02$ ($\log_2 \max(1, Y_v^c)$ vs. $N$, selecting exponential when $R^2 \ge 0.85$ strictly beats power-law).

---

## 3. Symptom Selection and Two-Tier Scoped Slicing

A canonical node $s$ triggers a work symptom via:
1. Exponential onset relative to its parent scope,
2. Hidden-work gap $\alpha_s^{\mathrm{work}} - \alpha_s^{\mathrm{hits}} \ge 0.70$, or
3. Scope-relative work jump $\Delta\alpha_s = \alpha_s^{\mathrm{work}} - \alpha_{\mathrm{parent}(s)}^{\mathrm{work}} \ge 0.70$ with $\alpha_s^{\mathrm{work}} \ge 1.50$ (in the repaired prospective rule, which admits top-level `MAIN_SCOPE` loops and prioritizes exponential over polynomial fits).

Given guard variables $V_{\mathrm{guard}}(s) = \mathrm{uses}(s)$, the pruned two-tier slice is $C_{\mathrm{pruned}}(s) = \{s\} \cup C_{\mathrm{inter}}(s) \cup C_{\mathrm{intra}}(s)$:
$$C_{\mathrm{inter}}(s) = \bigl\{u : \mathrm{par}(u)=\mathrm{par}(s),\; \mathrm{defs}(u)\cap V_{\mathrm{guard}} \neq \emptyset,\; (\mathrm{exp}(s) \lor \alpha_u^{\mathrm{work}} \le \alpha_s^{\mathrm{work}} - 0.50)\bigr\}$$
$$C_{\mathrm{intra}}(s) = \bigl\{u : \mathrm{par}(u)=s,\; \mathrm{defs}(u)\cap V_{\mathrm{guard}} \neq \emptyset,\; (\mathrm{reset}(u) \lor \mathrm{nested}(u)) \land \neg\mathrm{step}(u)\bigr\}$$

Candidate search-space reduction is $R_{\mathrm{search}} = 1 - |C_{\mathrm{pruned}}(s)| / |V|$. Single-parent scope locality explains both why $C_{\mathrm{pruned}}$ shrinks slices by ~89% and why multi-hop transitive writes ($d > 0$) and two-scope patterns (`F10`, `A400004`) require conventional CFG closures when non-local edits occur. In ranking (`pipeline.py:rank_candidates_by_role_priority`), any surviving non-symptom `STATE_UPD` node inside $C \setminus \{s\}$ is hoisted ahead of $s$ (intra-resets before inter-resets), optionally pruned for loop-bound aliases when `use_loop_def_use=True` (pilot-refined) vs. `use_loop_def_use=False` (prospective default).

---

## 4. Six-Representation Neural Matrix & External Contract

| Representation | Roles / D-U Field | $\alpha^{\mathrm{hits}}$ | $\alpha^{\mathrm{work}}$ | `SLICE` Tag | Code Preview (26 chars) | Max Pilot Tokens |
|---|---|:-:|:-:|:-:|:-:|---:|
| `raw_code` | — | — | — | — | Yes | 246 |
| `hotspot_raw` | — | Yes | — | — | Yes | 346 |
| `static_eapg` | Yes | — | — | — | Yes | 413 |
| `abstract_hits_only` | Yes (counts) | Yes | — | Yes | Stripped | 257 |
| `abstract_graph` | Yes (counts) | Yes | Yes | Yes | Stripped | 307 |
| `full_eapg` | Yes ($\le 2$ D/U ids) | Yes | Yes | Yes | Yes | 496 |

Prompts serialize canonical nodes into single-token choice IDs (`A..Z`, hard budget $\le 512$ tokens, $|V| \le 26$) and score next-token logits under 4-bit NF4 double quantization (`torch.bfloat16`) in `Qwen2.5-Coder-1.5B`. [`prediction_contract.py`](../development/prediction_contract.py) and [`predict_external_contract.py`](../development/predict_external_contract.py) fail closed across all seven statuses (`RANKED`, `NO_SYMPTOM`, `EMPTY_SLICE`, `NODE_LIMIT`, `CONTEXT_LIMIT`, `UNSUPPORTED_NODE_TOKEN`, `NORMALIZATION_FAILURE`). Note that `prediction_contract.py` runs `use_loop_def_use=True` (pilot-refined symbolic rule), while [`run_prospective_multiagent_study.py`](../development/run_prospective_multiagent_study.py) reports both `def_use=False` (unbiased default) and `def_use=True` separately.

---

## 5. Cryptographic Provenance, Artifacts Layout & Custody

- **Frozen Release Manifest ([`SHA256SUMS`](../SHA256SUMS)):** Pins core `pipeline.py`, `verify_release.py`, `artifacts/scope_isolated_pilot/*`, `artifacts/phase1_correction/*`, `artifacts/phase2_data/{README.md,prepare_pie.py,run_development.py,development_*.json}`, and root documents (`README.md`, `AUDIT.md`, `requirements-ast.txt`, `.gitignore`, `.gitattributes`). Additional evidence under `artifacts/` (`artifacts/pilot_resplit/*`, `artifacts/weighted_panel/*`, and `artifacts/phase2_data/test_phase2_*.py`) is verified by test and replay suites rather than `SHA256SUMS`.
- **PDF Provenance:** [`manuscript/paper.pdf`](../manuscript/paper.pdf) is the current paper; [`artifacts/paper_sections_and_refs.pdf`](../artifacts/paper_sections_and_refs.pdf) (pre-audit Phase 1) and [`artifacts/phase1_correction/paper_sections_and_refs.pdf`](../artifacts/phase1_correction/paper_sections_and_refs.pdf) (post-Phase-1 correction) are preserved solely as frozen historical snapshots matching `AUDIT.md`.
- **Role-Separated Prospective Custody:** Three independent code bundles with composite SHA-256 locks:
  1. **Custodian** ([`synthetic_study_custodian.py`](../development/synthetic_study_custodian.py), `e0c327f6...`): validates protocol, draw, quarantine, source fingerprints, executes oracle + profile builds, strips ground truth into `blind.json`.
  2. **Blinded Predictor** ([`synthetic_study_predict.py`](../development/synthetic_study_predict.py), `7cda5c19...`): consumes strictly `blind.json`, emits 7-arm predictions (`hit_growth`, `work_symptom`, `work_scoped`, `work_conventional`, `hits_scoped`, `hits_conventional`, `work_scoped_symbolic`).
  3. **Scorer** ([`synthetic_study_score.py`](../development/synthetic_study_score.py), `39c2b1f7...` / [`score_external.py`](../development/score_external.py)): joins sealed ground-truth labels and predictions into equal-family paired statistics (`D_pos`, `D_elig`, `D_rank`, `verified_negative_alerts`).
