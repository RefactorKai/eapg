"""Reproduce the S1 holds and fixed agreement draw from committed metadata."""

import argparse
from collections import Counter
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2] / "artifacts" / "paired_benchmark_freeze"
MANIFEST_PIN = "5b432d827f324c073eb7ed14b4df4b5d18f5eb2a90c4d97d358405a800d27346"
STATEMENTS = "s1_statement_inventory.json"
CLOSED_TAGS = {"script", "style", "noscript"}


class Images(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.skip = self.count = 0
        self.feed(html)
        self.close()

    def handle_starttag(self, tag, attrs):
        if tag in CLOSED_TAGS:
            self.skip += 1
        if not self.skip and tag == "img":
            self.count += 1

    def handle_endtag(self, tag):
        if tag in CLOSED_TAGS:
            self.skip = max(0, self.skip - 1)


def digest(raw):
    return sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def pair_id(row):
    return f'{row["corpus"]}:{row["id"]}'


def agreement_rank(row):
    key = ["eapg-s1-agreement-v1", 20261121, row["corpus"], row["id"]]
    return digest(json.dumps(key, ensure_ascii=False, separators=(",", ":")).encode()), pair_id(row)


def inventory(problems, source):
    records = {}
    for problem in sorted(problems):
        html = (source / f"{problem}.html").read_bytes()
        records[problem] = {"html_sha256": digest(html), "images": Images(html.decode("utf-8")).count}
    return records


def derive(rows, statements):
    held, ready = [], []
    for row in sorted(rows, key=pair_id):
        identity = {"corpus": row["corpus"], "pair_id": row["id"]}
        if row["frame"] == "Repository":
            # The frozen Repository inputs have no independent specification.
            reason = "no_independent_repository_spec"
        elif statements[row["problem_id"]]["images"]:
            # No images were included in the frozen rater packet.
            reason = "unbundled_statement_images"
        else:
            ready.append(row)
            continue
        held.append({**identity, "reason": reason})
    sample = [{"corpus": row["corpus"], "pair_id": row["id"]}
              for row in sorted(ready, key=agreement_rank)[:100]]
    return held, ready, sample


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--statements", type=Path, help="audit inventory against Project CodeNet 1.0.0 problem_descriptions")
    parser.add_argument("--write", action="store_true", help="materialize only the derived metadata files")
    args = parser.parse_args()
    if args.write and args.statements is None:
        parser.error("--write requires --statements")
    raw = (ROOT / "manifest-expanded.json").read_bytes()
    if digest(raw) != MANIFEST_PIN:
        parser.error("frozen manifest hash mismatch")
    rows = [row for row in json.loads(raw)["pairs"] if not row.get("intake_stop")]
    problems = {row["problem_id"] for row in rows if row["frame"] == "Contest"}
    statements = inventory(problems, args.statements) if args.statements else json.loads((ROOT / STATEMENTS).read_bytes())
    if set(statements) != problems:
        parser.error("incomplete or extra S0-pass Contest statement inventory")
    held, ready, sample = derive(rows, statements)
    if (len(rows), len(held), len(ready), len(sample)) != (977, 133, 844, 100):
        parser.error("recomputed scope does not match the amendment")
    for name, value in ((STATEMENTS, statements), ("s1_hold_list.json", held), ("s1_agreement_draw.json", sample)):
        path, data = ROOT / name, encoded(value)
        if args.write:
            path.write_bytes(data)
        elif path.read_bytes() != data:
            parser.error(f"{name} does not match recomputed metadata")
        print(f"{digest(data)}  {name}")
    print(f"{len(ready)} rateable, {len(held)} held: {dict(sorted(Counter(row['corpus'] for row in held).items()))}")


if __name__ == "__main__":
    main()
