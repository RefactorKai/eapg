---
name: eapg-citation-lookup
description: Literature Scout toolkit. Invoke with eapg-token-budget before citation verification, abstract lookup, or BibTeX deduplication.
---

# EAPG citation lookup

Follow `eapg-ground-rules` and `eapg-literature`. Query public bibliographic metadata only; never send private manuscript/data text.

## Verify metadata first
Run in Bash with `set -o pipefail`; failures or challenge pages mean unverified, not no results.

- Crossref (known DOI):
  `curl -fsSL 'https://api.crossref.org/works/10.1145%2F3597503.3639187' | jq '.message | {title, author, venue: ."container-title", published, DOI, URL}'`
- DBLP (public title search):
  `curl -fsSL --get 'https://dblp.org/search/publ/api' --data-urlencode 'q=algorithmic complexity' --data 'format=json' --data 'h=5' | jq '.result.hits.hit[]?.info | {title, authors, venue, year, doi, url}'`
  DBLP returned an HTTP 202 HTML bot challenge on this host during setup; JSON parsing must fail closed. Use Crossref/arXiv or an accessible publisher, not a fabricated verification.
- arXiv returns Atom XML, not JSON:
  `curl -fsSL 'https://export.arxiv.org/api/query?id_list=1706.03762' | python -c 'import sys,json,xml.etree.ElementTree as E; n={"a":"http://www.w3.org/2005/Atom"}; r=E.parse(sys.stdin); print(json.dumps([{"title":e.findtext("a:title",namespaces=n),"abstract":e.findtext("a:summary",namespaces=n),"url":e.findtext("a:id",namespaces=n)} for e in r.findall("a:entry",n)]))' | jq .`
- Read abstract and metadata before a PDF. Open full text only to verify a specific supported claim, methods detail, or contradictory result; abstracts alone do not prove claims.

## Deduplicate and hand off
- Limit lookup to the disputed citation or claim and closest necessary sources; do not reread the entire bibliography or manuscript for a local correction.
- Existing entries: `rg -n '^@|doi[[:space:]]*=|url[[:space:]]*=' manuscript/paired_mechanism.bib manuscript/references.bib`.
- Duplicate keys within each file: `for bib in manuscript/*.bib; do printf '%s\n' "$bib"; sed -nE 's/^@[^{]+\{([^,]+),.*/\1/p' "$bib" | sort | uniq -d; done`. Check DOI/title duplicates too; shared keys in separate manuscripts are not automatically errors.
- Record source URL, retrieval date, title/authors/venue/year, DOI and supported claim. Keep full metadata evidence locally; concise chat is not citation evidence. Rate limits: back off; do not repeatedly fetch the same record.
