---
name: eapg-receipt-queries
description: Data Analyst toolkit. Invoke with eapg-token-budget before inspecting committed receipts, tracing macros, or checking reported numbers.
---

# EAPG receipt queries

Follow `eapg-ground-rules` and `eapg-statistics`; never query sealed or private data.

## Query, do not dump
- Start at the disputed claim/macro; follow only its receipt fields and generator ranges. Do not scan all datasets or rewrite unrelated analysis.
- Confirm provenance: `git ls-files --error-unmatch artifacts/paired_development/ledger.json`.
- Ledger structure: `jq 'keys' artifacts/paired_development/ledger.json`.
- Disposition counts: `jq '.rows | group_by(.final_disposition) | map({disposition: .[0].final_disposition, n: length})' artifacts/paired_development/ledger.json`.
- Find macro definitions and uses: `rg -n -F '\newcommand' manuscript -g '*.tex'`; then `rg -n -F 'MacroName' manuscript development artifacts/paired_development -g '*.py' -g '*.tex' -g '*.json' -g '!ledger.json'`. Follow the generating script to its committed receipt and field; never infer provenance from a matching number.
- Claim registry, if present: `if test -f development/paper_claims.json; then jq 'keys' development/paper_claims.json; else printf '%s\n' 'paper_claims.json absent: report registry gap'; fi`. Inspect keys before selecting fields; this checkout has no registry.

## Verify the affected evidence
- Paired public receipt checks: `python -B -S artifacts/paired_development/replay.py --verify-public`.
- Manuscript pilot subset: `python -B eapg.py replay --stage manuscript`; weighted panel: `python -B eapg.py replay --stage library`.
- There is no `verify --subset` flag. These are targeted replay checks, not substitutes for final R4 gates. Preserve full raw output, denominator, unit, interval method and evidence class.
