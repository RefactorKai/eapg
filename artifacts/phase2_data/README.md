# PIE data and first external run

Acquire these files from the official release and place them in this directory. The repository records their verified digests. Keep the test split held out. The validation split supplies development examples and has zero problem-ID overlap with test.

| File | Records | Problems | SHA-256 |
|---|---:|---:|---|
| PIE test | 978 | 41 | `e0b1ef26a22c0c60022acd469cffffac91fd55304a8161b333ae5aa51005d10b` |
| PIE validation | 2,544 | 77 | `6608a303c5c6ab61e7936599f3aa8cbde67bc36007e1a9739d7868665c531dab` |
| Merged correctness tests | 692,219 archive entries | — | `02f21225ba963ec9de89b3a5e42f2e9647d8333b717a02cf5bd8b4d088b8309c` |

The test file was compared byte-for-byte with the official release. These are research copies. Confirm dataset-specific terms before redistribution. [Official split files](https://drive.google.com/drive/folders/1E_yFqM8khN1HAH03OKhjheSlNI4rYTT7) · [Official merged tests](https://drive.google.com/file/d/1evBDJapwRvCQK6VUCTV8ZE9WG2k3QJQr/view) · [PIE release instructions](https://github.com/LearningOpt/pie#dataset)

## Held-out draw

The locally sealed static manifest contains 137 distinct-slow pairs across all 41 problems. Static fingerprints yield 35 connected groups and no overlap with the frozen pilot under the registered keys. The lexer fallback was used on 30 slow sources and 21 fast sources in the draw. These counts reflect the raw-source parser and do not establish compiler compatibility. All 9,959 references to correctness tests resolve to 3,005 unique input/output pairs in the released archive. Prompt-token quarantine and the count of verified scaling regressions are pending.

Run from the repository root to verify the releases, frame hash, sealed manifest, and archive coverage.

```powershell
python -X utf8 artifacts/phase2_data/prepare_pie.py --verify
```

Run without `--verify` first to generate the local manifest in this directory, then verify it. The script uses the existing custody runner and refuses to overwrite the saved manifest.

## First validation workload

[Development inputs](development_workload.json) target validation problem `p03497` with the original slow and fast submission IDs and source hashes. The 18 inputs cover six powers of two with three fixed shuffle seeds. Each case has `K=1`, two values occurring `N/4` times each, and `N/2` other values appearing once. The expected answer is `N` minus the largest frequency. [Original problem statement](https://atcoder.jp/contests/arc086/tasks/arc086_a)

The [Linux runner](run_development.py) used the frozen extractor, instrumentation placement, fitter, slice selector, and ranker. It replaced the profiler's exit and counter transport and ran both GCC stages and each binary in the same fixture-checked namespace. The [exported counters and results](development_counters.json) contains the checks, node counters, fits, and candidates. A replay in a fresh Linux directory reproduced it byte-for-byte.

- The original, UBSan, and instrumented builds each matched the oracle for both submissions on all 18 inputs. All 36 instrumented outputs matched byte-for-byte. Every instrumented run finished below the tick cap.
- On all three seeds, slow inner loop `N12` had work exponent 2.00 with polynomial fit R² of 1.000. Its measured hit count matched the independent formula `(N/4 - 1)(N/2 + 2) + 1` on every input. The count grew from 2,047 to 2,097,151 as `N` grew from 128 to 4,096.
- The frozen work selector chose outer loop `N11` on all three seeds. It pruned the 20 nodes to `[N10, N11]` and ranked `N10`, the initialization `j=0`, first. The slice excluded `N12`. The hit-only symptom was `N12`, and the unpruned candidate set retained it.

This is a development observation. It establishes agreement with the independent output oracle and a quadratic inner traversal on the registered inputs. It does not measure a runtime speedup or adjudicated localization accuracy. The fast version's sort call has unit work weight, so the fitted fast maximum of 1.00 does not measure the sort's asymptotic cost. The held-out draw was not executed.

From the repository root in Ubuntu, run the local fixture checks. Use the pinned `tree-sitter==0.26.0` and `tree-sitter-cpp==0.23.4` Linux wheels under `~/.local/share/eapg-phase2/deps`. Omit `--probes-only` to run the development case in a fresh copy. The runner writes the full local development result, which is excluded from version control.

```powershell
python3 -B artifacts/phase2_data/run_development.py --probes-only
```

The exported counters omit source previews and source-code identifiers. The export records the original result and runner hashes and the released runner hash. The released runner changes the host-path probe to a generic Windows system path. The measurement code is unchanged. The raw PIE archives and sealed held-out manifest stay outside the public artifact. The case's stage field describes workload registration. The slow and fast run sections hold the later observations.
