---
name: eapg-targeted-testing
description: Experiment Engineer toolkit. Invoke with eapg-token-budget before selecting tests or inspecting sandbox run logs; invoke ponytail for code changes.
---

# EAPG targeted testing

Follow `eapg-ground-rules` and `eapg-experiments`; activate the repo venv.

## Select by impact
- Start with the failing stack frame or symbol; read its range and direct callers only. Map tests with `rg -n 'module_name' development -g 'test_*.py'`; no whole-repo bug hunt or drive-by formatting.
- CLI/verification changes: `development/test_verify.py`; paired intake: `development/test_paired_intake.py`; synthetic oracle: `development/test_synthetic_oracle.py`. Confirm dependencies, not only filename similarity.
- Exploration when RTK exists: `rtk pytest development/test_verify.py -k skip -x`; otherwise `python -B -m pytest development/test_verify.py -k skip -x`.
- This repo disables pytest's cache provider. For local cached reruns, opt in with `python -B -m pytest -o addopts='' development/test_verify.py -x`, then `python -B -m pytest -o addopts='' --lf -x` after a known failure. An empty cache is not coverage. Use `-k` for changed behavior, then the full affected file; include empty/error cases.
- Use `ponytail` to avoid speculative helpers or dependencies, never to skip validation.

## Logs and sandbox
- Evidence example (Bash): `mkdir -p "$HOME/eapg-agent-logs"; python -B -m pytest development/test_verify.py -q -rs >"$HOME/eapg-agent-logs/verify-tests.log" 2>&1; rc=$?; tail -n 30 "$HOME/eapg-agent-logs/verify-tests.log"; test "$rc" -eq 0`.
- Retain complete logs before tailing. Report sandbox status, exit code, skips/reasons, receipt path and blockers briefly; raw counters and audit evidence remain full.
- Never run unvetted C++ directly. Use `development/gate1_sandbox.py` per the experiment protocol; final isolation probes: `python -B eapg.py verify --mode linux --with-probes`.
- Targeted tests do not replace full final R4 gates in `eapg-token-budget`.
