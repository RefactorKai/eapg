# Repository intake timeline — 2026-11-21 UTC

The initial unscoped search was rate-limited and returned too few C++ repositories. The repository-first search's first page yielded 17 repositories meeting the metadata filters, below the required 30 even before source retrieval. The intake rule recorded the decision to add pages 2–5 at 07:16:12 UTC, without changing the queries or ranking rule.

| UTC | Event |
|---|---|
| 07:16:23–07:16:59 | Saved repository metadata pages 2–5. |
| 07:20:03 | Saved the last missing commit-search batches after a rate-limit retry. The expanded manifest pins each snapshot by SHA-256. |
| 07:21:19 | Wrote the hash-ordered draw, SHA-256 `1b8bb98777dbb2acb08e33510fc706684feeef3c64e1b177d980425ca9681313`. |
| 07:21:35 | Started retrieving the selected Repository pairs. The first new pinned source file was saved at 07:21:40. |

The separate downloads of archived CppPerf files were for quarantine and did not supply Repository candidates. The page expansion preceded retrieval of any newly selected Repository pair. No pairs were executed in this scrape stage. This is an intake record, not a protocol amendment.
