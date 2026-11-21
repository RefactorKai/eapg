---
name: eapg-literature
description: Rules for the EAPG Literature Scout - verified citations, related-work coverage, novelty checks and the venue policy lookup. Invoke when searching for papers, adding BibTeX, checking a "first" or novelty claim, or comparing EAPG to prior work.
---

# EAPG literature

Follow `eapg-ground-rules` first.

Invoke `eapg-token-budget` and `eapg-citation-lookup` for this role's efficiency toolkit; ground rules always win.

## Every citation is verified
- Open the source (DOI landing page, publisher, arXiv, DBLP, ACL Anthology, or Semantic Scholar) before adding it. Record title, authors, venue, year, DOI or URL, and the exact claim it supports.
- Never cite from memory or from another model's summary. If you cannot open it, mark it `unverified` and do not hand it to the Paper Writer.
- Prefer the peer-reviewed version over a preprint; note when only a preprint exists.
- Add entries to the manuscript's `.bib` with a consistent key style; keep a log of what each key supports in the PR description.

## Coverage to maintain
- Performance-bug and inefficiency detection; algorithmic-complexity and worst-case input generation (fuzzing for slow inputs); empirical complexity estimation and profiling-based growth fitting.
- Program graphs and learned code models for performance (PIE and its successors, CppPerf), learning-to-rank and bug localization.
- Change-impact and dependence analysis (the primary comparator), causal or profile-guided localization.
- Benchmark contamination and data leakage in code models; LLM-as-judge reliability and rater agreement.
- Reporting standards: ACM SIGSOFT Empirical Standards; venue AI-authorship policies.

## Novelty
A "first" or "novel" claim needs a documented search: databases, queries, date and closest hits, kept in the PR. Without it the Paper Writer must not use "first" (ground rules). Report the closest prior work honestly, including work that weakens our claim.

## Venue
For the target venue, fetch and record (with date) its scope, page limit, anonymity rules, artifact policy and AI-authorship policy, and hand them to the Paper Writer.
