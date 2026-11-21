# Frozen PIE validation cohort

[The manifest](manifest.json) identifies 500 public C++ slow/fast pairs across 54 PIE validation problems. All pairs come from the same PIE validation release; CodeNet's original judge metadata identifies 436 as AtCoder and 64 as AIZU pairs. “Slow” and “fast” reflect PIE's released aggregate runtime ordering, not EAPG measurements. This is a development cohort. The scrape stage did not compile, execute or qualify programs, and the PIE test split was not opened.

## Contents and custody

- `manifest.json` records the source and release URL, scoped license, composite case ID and both CodeNet submission IDs, pair and source SHA-256s, and selection commitments. A pair's SHA-256 covers its exact canonical UTF-8 payload row without the final line feed. The payload SHA-256 covers the entire JSONL file, including line feeds. Source hashes cover each original code string encoded in UTF-8.
- The local source payload lives under the worktree's git-ignored `.codex/private/paired_benchmark_freeze/pairs.jsonl`. Obtain the input directly from the [public PIE validation asset](https://drive.google.com/file/d/1Z01XyFil-w2XN1i9TNn7idzZ2DzDz-XL/view). Do not add either raw source file to git, a PR, or an attachment.
- [CodeNet's dataset authors](https://openreview.net/forum?id=6vZVBkCDrHT) list [CDLA-Permissive-2.0](https://cdla.dev/permissive-2-0/) for the upstream data. The per-pair license field records that upstream license, not a separate grant from PIE or the original submitters. The [PIE repository's Apache-2.0 license](https://github.com/LearningOpt/pie/blob/eb3d72bc4f3c9095d0f62506340bc8ca0ef27b09/LICENSE) is not used as a claim about the exported code. The manifest pins the older PIE problem index used only to identify judges.

## Verify or reconstruct locally

From the repository worktree root, verify the stored payload with Python's standard library. The materializer checks the complete validation-file digest before reading its records; it cannot substitute the train or test split.

```sh
manifest=artifacts/paired_benchmark_freeze/manifest.json
payload=.codex/private/paired_benchmark_freeze/pairs.jsonl
sha256sum "$manifest"
python3 -B -S artifacts/paired_benchmark_freeze/materialize.py \
  --pie-validation /path/to/pie_val.jsonl --verify "$payload"
```

To re-create an absent payload, create its parent directory locally, then use `--output` instead of `--verify` with the same path. No C++ compiler or network access is used by the materializer.

The locked draw excludes the previously used `p03497` problem and known archived PIE source identities (including line-ending/outer-whitespace equivalents). It discards identical sides and duplicate unordered source pairs. The draw round-robins across problem queues, ordered by SHA-256 of compact canonical JSON `[seed,"problem",problem_id]`; each queue is ordered by SHA-256 of `[seed,"pair",case_id]`, with lexical tie breaks. The manifest pins the original seed, intake receipt, archived ledger and exclusion counts. Reconstructing from the frozen IDs does not redraw the cohort.
