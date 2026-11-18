# Library work-proxy calibration

The [protocol](../../development/WEIGHTED_PANEL_PROTOCOL.md) fixes eight workloads across three authored C++17 programs and six vector lengths. It specifies GCC 15.2.0 with effective optimization levels -O2, -O0, and -O3 and adds an undefined-behavior sanitizer build at -O2. The [result record](results.json) includes per-node counters, separate observed operation counts, checksums, fits, and selector outputs for every condition.

All 480 executions matched their output oracles. At each optimization level, the size proxy classified six of eight workloads consistently with the prespecified 0.70 growth margin using counted comparisons or swaps. The two disagreements were first- and square-root-position matches. Their comparison exponents were 1.000 and 1.508, with a work-proxy exponent of 2.000 for both. The work selector chose the target call in all eight conditions. The hits-only selector emitted no symptom. The comparison concerns growth at a library call on the tested grid. Comparisons and swaps were counted in different builds and have different units. The panel provides no estimate of runtime growth or edit localization accuracy.

## Locks and chronology

| File | SHA-256 |
|---|---|
| [First lock](lock-aborted.json) | a9642c56cb7295161220c4b626044bd43e8080c95cc64154d185fe7260426874 |
| [Corrected lock](lock.json) | cf5dfa4ca9bcb869918604dda16bed6022397298b437ed66ed5c8a91a1eb5af6 |
| [Results](results.json) | 95948c69a86410bb47384f87fa97ddb5cf76f3f973106cc7adc2bd9480c8e91d |

The first attempt stopped before writing a report. The reporting code tried to read an R² field from Python's linear-regression result. The corrected runner computes R² from the squared Pearson correlation and defines it as one for constant counts. The runner digest is the only change between locks. Both locks record the same sources, stage configuration, workloads, expected outputs, operation oracles, and decision rule. After resealing the runner, two complete WSL2 runs produced byte-identical reports.

## Replay and rerun

From the repository root, replay the checks, slopes, classifications, and ratios from the archived records with standard-library Python.

~~~sh
python -B development/verify_weighted_panel.py
~~~

To rerun the experiment under the recorded lock, use the unprivileged Ubuntu WSL2 environment in the [research record](../../development/RESEARCH_RECORD.md#post-audit-prospective-development), with systemd user scopes, Bubblewrap, GCC 15.2.0, Python 3.14.4, and the [pinned parsers](../../requirements-ast.txt) on the Python path. The lock checks the kernel and the recorded tool and source versions.

~~~sh
mkdir -p .codex/private
out=$(mktemp -d .codex/private/weighted-panel-XXXXXXXX)
export PYTHONPATH="$HOME/.local/share/eapg-phase2/deps"
python3 -B development/build_candidate.py --prospective "$out/prospective.py"
python3 -B development/run_weighted_panel.py --pipeline "$out/prospective.py" \
  --lock artifacts/weighted_panel/lock.json \
  --lock-sha256 cf5dfa4ca9bcb869918604dda16bed6022397298b437ed66ed5c8a91a1eb5af6 \
  --output "$out/results.json"
python3 -B development/verify_weighted_panel.py --results "$out/results.json"
cmp artifacts/weighted_panel/results.json "$out/results.json"
~~~

On a different Linux environment, first use the same runner with `--seal --output "$out/lock.json"`. Pass that fresh lock and its printed digest to the runner, then pass the same lock to the verifier. Keep the resulting run as a separate environment check.
