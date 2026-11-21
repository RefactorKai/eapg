# Repository intake timeline — 2026-11-21 UTC

The initial unscoped search was rate-limited and returned too few C++ repositories. The repository-first search's first page yielded 17 repositories meeting the metadata filters, below the required 30 even before source retrieval. The intake rule recorded the decision to add pages 2–5 at 07:16:12 UTC, without changing the queries or ranking rule.

| UTC | Event |
|---|---|
| 07:16:23–07:16:59 | Saved repository metadata pages 2–5. |
| 07:20:03 | Saved the last missing commit-search batches after a rate-limit retry. The expanded manifest pins each snapshot by SHA-256. |
| 07:21:19 | Wrote the hash-ordered draw, SHA-256 `1b8bb98777dbb2acb08e33510fc706684feeef3c64e1b177d980425ca9681313`. |
| 07:21:35 | Started retrieving the selected Repository pairs. The first new pinned source file was saved at 07:21:40. |

The separate downloads of archived CppPerf files were for quarantine and did not supply Repository candidates. The page expansion preceded retrieval of any newly selected Repository pair. No pairs were executed in this scrape stage. This is an intake record, not a protocol amendment.

The purpose of paging beyond page 1 was to reach the requested Repository coverage and the protocol's per-frame analysis gate, not a condition of the protocol itself. The 55 public metadata snapshots are retained in the scrape session's local `pie-expansion/` cache, with filenames and SHA-256s in the expanded manifest. The identical hashes for batches p3-b8, p4-b3 and p5-b9 are confirmed empty, complete result pages.

## Errata — 2026-11-21

- [Redot identifies itself as a Godot fork](https://www.redotengine.org/contact). Its frozen pair is relabelled to `repository/godotengine/godot` for quarantine and representative selection under §1 and §7. The original repository and commit pins still identify its source. No pair was redrawn or removed, and the protocol and payload did not change.
- OceanBase's pinned licence is `LicenseRef-MulanPubL-2.0`. It permits use but has no standard SPDX identifier. The pair is retained under the protocol's licence criterion; this is an exception to the intake rule's recognized-SPDX requirement.
