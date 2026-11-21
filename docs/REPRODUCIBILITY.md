# Reproducibility Guide

All manuscript tables and empirical claims replay deterministically from committed receipts and source checks using [`eapg.py`](../eapg.py).

---

## 1. Verification Tiers

| Tier | Command | Requirements | What It Verifies |
|---|---|---|---|
| **Tier 0: Status** | `python -B -S eapg.py status` | Python 3.11+ stdlib | All `SHA256SUMS` digests, PDF existence, multi-agent JSON digest, toolchain paths |
| **Tier 1: Fast Replay** | `python -B -S eapg.py verify --mode fast` | Python stdlib + `git` | Release SHA-256s, Phase 1/resplit contrasts, all 5 manuscript tables (`I`–`V`), multi-agent Part A/B invariants, archived candidate digest `ab43a6e4...` |
| **Tier 2: Common CI** | `python -B eapg.py verify --mode common` | Python stdlib + `git` | All 18 cross-platform unit, intake, oracle, frame, quarantine, contract, and replay checks + archived candidate digest `ab43a6e4...` |
| **Tier 3: AST, Selector & Sandbox** | `python -B eapg.py verify --mode linux --with-probes` | `g++`, `git`, `tree-sitter==0.26.0`, `tree-sitter-cpp==0.23.4` (`--with-probes` requires Linux + `bwrap` + `systemd-run --user`) | Runs Tier 2, materializes prospective candidate `2c95df0e...`, runs all 10 AST/selector/slice/intervention/custodian/frame-domain/intake suites + 4 Gate 1 Bubblewrap probes (`--with-probes`) |
| **Tier 4: Dual-OS Full** | `python -B eapg.py verify --mode wsl2 --with-probes` | Windows 11 + Ubuntu WSL2 | Executes Tier 2 on Windows followed by Tier 3 inside `wsl -d Ubuntu` (set `PYTHONUTF8=1`, handled automatically by `eapg.py`) |
| **Tier 5: Pytest Suite** | `python -B -m pytest -q` | `pytest>=8.0` + `requirements-ast.txt` | Runs all 19 `development/test_*.py` modules plus `artifacts/phase2_data/test_phase2_*.py` (Gate 1 sandbox tests skip cleanly when not on unprivileged user-systemd Linux) |
| **Tier 6: LaTeX Build** | `python -B eapg.py build-paper --clean` | `pdflatex`, `bibtex`, `IEEEtran.cls` | Compiles `manuscript/paper.pdf` with zero `Overfull \hbox` or undefined warnings and removes intermediate `.aux/.log` files |

> **Windows UTF-8 Note:** Frozen `pipeline.py` uses default text encoding on `g++` pipes (`SHA256SUMS`-pinned). Always invoke checks via `eapg.py` (which sets `PYTHONUTF8=1`) or `python -X utf8` on Windows hosts with non-ASCII C++ fixtures.

> **Linux Host Sandbox Note:** [`development/gate1_sandbox.py`](../development/gate1_sandbox.py) requires an unprivileged Linux user with user-level `systemd` cgroup v2 (`memory.swap.max = 0`), `bwrap` with user namespaces, `prlimit`, and x86_64 `/usr/lib64`; `eapg.py --mode wsl2` expects AST deps under `$HOME/.local/share/eapg-phase2/deps` unless installed globally.

For LaTeX, install `IEEEtran.cls` from Ubuntu's `texlive-publishers` package:
`sudo apt-get install -y texlive-publishers poppler-utils`.

Gate 1 host prerequisites: stock Ubuntu 22.04 is insufficient (systemd 249 rejects
`OOMPolicy=continue` on scopes, CPU delegation to `user@.service` is absent,
Bubblewrap 0.6.1 lacks `--disable-userns`, and a session bus may be absent).
Use Bubblewrap >= 0.8, a `user@.service` drop-in with
`Delegate=cpu cpuset io memory pids`, and a `systemd-run` shim that drops
`OOMPolicy` (or a systemd version accepting it). Enable lingering with
`loginctl enable-linger "$USER"` and set `XDG_RUNTIME_DIR=/run/user/$(id -u)`
with a working user session bus. The archive pins GCC 15.2.0 and Bubblewrap 0.11.1
in `development/prospective_multiagent_results.json` (`execution_environment`).

The stale paired-study Markdown draft has been removed; use
[`paired_mechanism.tex`](../manuscript/paired_mechanism.tex). Its old pathname in
`artifacts/paired_development/historical-manifest.json` is a sealed historical
inventory entry, not a link to a current manuscript.

---

## 2. Optional Environment Setup

Install optional AST packages for Tier 3 & Tier 5:

```sh
pip install -r requirements-ast.txt
# or editable source install with dev tools:
pip install -e .[ast,dev]
```

Install optional GPU stack for live 4-bit NF4 `Qwen2.5-Coder-1.5B` inference (verified on 8 GB RTX 4060 with CUDA PyTorch 2.10.0+cu128, Transformers 5.17.0 / PEFT 0.19.1 / bitsandbytes 0.49.2 / Accelerate 1.15.0):

```sh
pip install -e .[gpu]
```

External PIE acquisition and static manifest generation follow [`artifacts/phase2_data/README.md`](../artifacts/phase2_data/README.md) (`artifacts/phase2_data/prepare_pie.py`).

---

## 3. Manuscript Table-to-Script Mapping

| Manuscript Table / Claim | Verification Entrypoint | Backing Receipt |
|---|---|---|
| Table I (`tab:eapg-pilot-slicing`) | `python -B eapg.py replay --stage manuscript` | [`artifacts/scope_isolated_pilot/pilot100_results.json`](../artifacts/scope_isolated_pilot/pilot100_results.json) |
| Table II (`tab:eapg-resplit-ablation`) | `python -B eapg.py replay --stage ablation` | [`artifacts/pilot_resplit/ablation_results.json`](../artifacts/pilot_resplit/ablation_results.json) |
| Table III (`tab:dev-feasibility`) | `python -B eapg.py replay --stage manuscript` | [`development/uoj_source_availability.json`](../development/uoj_source_availability.json), [`development/scalar_intake_feasibility.json`](../development/scalar_intake_feasibility.json), [`development/comparator_swap_results.json`](../development/comparator_swap_results.json), [`development/transitive_edit_results.json`](../development/transitive_edit_results.json), [`development/scope_boundary_results.json`](../development/scope_boundary_results.json) |
| Table IV (`tab:prospective-multiagent`) | `python -B eapg.py verify --mode fast` | [`development/prospective_multiagent_results.json`](../development/prospective_multiagent_results.json) (`2016611a...`) |
| Table V (`tab:library-calibration`) | `python -B eapg.py replay --stage library` | [`artifacts/weighted_panel/results.json`](../artifacts/weighted_panel/results.json) |
| Frozen Phase 1 Audit (`AUDIT.md`) | `python -B eapg.py replay --stage release` | [`artifacts/phase1_correction/scaling/fast_recurrence_results.json`](../artifacts/phase1_correction/scaling/fast_recurrence_results.json) |

---

## 4. Private Custody Artifacts & Full Prospective Re-execution

Public cloning includes all source checks, sealed receipts, and replayable tables above. Re-running [`development/run_prospective_multiagent_study.py`](../development/run_prospective_multiagent_study.py) (`eapg study`) from scratch additionally requires non-public local bundles outside git (`.gitignore`-excluded `.codex/private/` inside the repo or its parent workspace):

- Local HuggingFace `Qwen2.5-Coder-1.5B` snapshot (`df3ce67c0e24480f20468b6ef2894622d69eb73b`)
- Trained fold adapters: `pilot-resplit-2026-11-11` (`abstract_graph` folds `0..4`) and `resplit-ablation-20261116` (`hotspot_raw` fold-0)
- Private custody receipts and PIE extract: `multiagent-run/` (`part_a_verifier_attestation.json`, `part_b/review_{a,b}.json`, `adjudication_c.json`, `sealed_references/*`), `prospective-final-GYSE9euA/`, `pie-download-VkVck8zh/pie_val.jsonl`, and `blinded_raw_14pairs.json`

When those private artifacts are mounted, run:

```sh
# Linux WSL2 Bubblewrap Part A ledger generation (~12 min, 378 builds, 6,804 oracle runs)
python3 -B eapg.py study --wsl2-part-a-only

# Assemble verified dual-OS Part A + live RTX 4060 GPU + Part B external contract (~2 min)
python -B eapg.py study --reuse-ledgers
```
