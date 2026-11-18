"""Count immutable header exclusions in the pinned UOJ-Bench repair release.

Pass locally downloaded Easy and Hard pair JSON files. The audit reads the code
as text, compiles and executes nothing, and emits only aggregate counts. Passing
the literal-header check leaves all other C++ subset and eligibility checks open.
"""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re


REVISION = "ce1c006d9f6cf57670d15e62c3e63a08ea669adb"
RELEASE = {
    "easy": ("sampled_large_submission_pairs.json", "7484b43a68846cba43d2f664bebb891a56e27ac35a5b13eb065f861ecc4844a3"),
    "hard": ("small_submission_pairs.json", "4b83be1865148e8dcd9cdff22b9ebe60bd6f5fbeca42cf3d55651dd6f16182e0"),
}
# Pass 0 extracts these lines before preprocessing and reattaches them unchanged.
INCLUDE = re.compile(r"^\s*#\s*include\b")
LITERAL_HEADER = re.compile(r'\s*(?:/\*.*?\*/\s*)*(<[^>]*>|"[^"]*")')


def unsupported_header(source):
    """Find a definite mismatch with the comparator's literal <cstdio> allowlist."""
    for line in source.splitlines():
        directive = INCLUDE.match(line)
        if directive and (header := LITERAL_HEADER.match(line, directive.end())) and header[1] != "<cstdio>":
            return True
    return False


def read_pairs(raw, track):
    name, expected = RELEASE[track]
    if sha256(raw).hexdigest() != expected:
        raise ValueError(f"Raw SHA-256 mismatch for official {track} file {name}")
    return json.loads(raw)


def counts(rows):
    problems = {row[0] for row in rows}
    return {"pair_rows": len(rows), "distinct_problem_ids": len(problems)}


def summarize(rows):
    return {
        "published": counts(rows),
        "evaluated_has_unsupported_literal_header": counts([row for row in rows if row[2]]),
        "comparison_has_unsupported_literal_header": counts([row for row in rows if row[3]]),
        "either_has_unsupported_literal_header": counts([row for row in rows if row[2] or row[3]]),
        "both_without_observed_unsupported_literal_header": counts([row for row in rows if not (row[2] or row[3])]),
    }


def report(easy, hard):
    def flags(pairs):
        return [(row["problem_id"], row["language"], unsupported_header(row["wrong_code"]),
                 unsupported_header(row["correct_code"])) for row in pairs]

    eligible_to_check = {"easy": flags(easy), "hard": flags(hard)}
    eligible_to_check["pooled"] = eligible_to_check["easy"] + eligible_to_check["hard"]
    return {"official_revision": REVISION, "tracks": {
        name: {"all_languages": summarize(rows),
               "cpp_family": summarize([row for row in rows if row[1].startswith("C++")]),
               "explicit_cpp17": summarize([row for row in rows if row[1] == "C++17"])}
        for name, rows in eligible_to_check.items()
    }}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for track, (name, _) in RELEASE.items():
        cli.add_argument(f"--{track}", type=Path, required=True, help=f"path to pinned {name}")
    args = cli.parse_args()
    try:
        easy, hard = (read_pairs(getattr(args, track).read_bytes(), track) for track in RELEASE)
        print(json.dumps(report(easy, hard), indent=2, sort_keys=True))
    except (OSError, ValueError) as error:
        cli.error(str(error))


if __name__ == "__main__":
    main()
