"""Seal full-graph custody components from pinned synthetic provenance.

The eapg-synthetic-provenance-v1 document binds the scorer draw digest and
lists all drawn and undrawn frame cases, previously exposed rows, and proposed
training and validation rows. Undrawn frame cases can connect components.
The custodian attests each row and its full source-version inventory. The
problem IDs include aliases, implementation IDs include submission origins,
and generator IDs include ancestors. Scaffold SHA-256s identify nontrivial
reused code. Each source version supplies raw, normalized-source and template
SHA-256s, with the template normalizing identifiers and numeric literals.
Each drawn row binds its evaluated raw digest to the corresponding draw case.
Prompt pins cover each registered representation's final token sequence
without its answer, encoded as a canonical JSON array. Any fingerprint can
instead supply {"unavailable_reason": "..."}. Set unknown_provenance_reason
when origin provenance is incomplete. These are supplied custody facts.

The seal records every row, its keys and reasons, and hashes each component's
sorted member IDs to make a stable opaque family ID. Bridges survive all
exclusions. Provenance attestations and the resulting ledger stay in custody.
"""

import argparse
from collections import defaultdict
from pathlib import Path

from score_synthetic import digest, exact_keys, identifier, index, require, unique_strings
from synthetic_frame import canonical, commitment, read_canonical


PROVENANCE = "eapg-synthetic-provenance-v1"
QUARANTINE = "eapg-synthetic-quarantine-v1"
FRAME_COHORTS = ("drawn", "undrawn")
COHORTS = (*FRAME_COHORTS, "exposure", "validation", "train")


def attest(row, representations, draw_cases):
    exact_keys(row, "row_id cohort attestation_sha256 registered_family_id unknown_provenance_reason "
               "problem_ids implementation_ids generator_ids scaffold_sha256 sources prompts", "provenance row")
    rid, cohort, family = row["row_id"], row["cohort"], row["registered_family_id"]
    require(identifier(rid) and cohort in COHORTS and digest(row["attestation_sha256"]), "Invalid provenance row identity")
    framed = cohort in FRAME_COHORTS
    require((identifier(family) if framed else family is None), f"Invalid registered family for {rid}")
    unknown = row["unknown_provenance_reason"]
    require(unknown is None or identifier(unknown), f"Invalid unknown-provenance reason for {rid}")
    keys = {("registered_family", family)} if framed else set()
    for kind, field in (("problem", "problem_ids"), ("implementation", "implementation_ids"),
                        ("generator", "generator_ids"), ("scaffold", "scaffold_sha256")):
        values = row[field]
        require(unique_strings(values) and (kind != "scaffold" or all(map(digest, values))),
                f"Invalid {kind} keys for {rid}")
        keys.update((kind, value) for value in values)
    require(unknown or (row["problem_ids"] and row["implementation_ids"] and (not framed or row["generator_ids"])),
            f"Incomplete origin provenance without a reason for {rid}")

    unavailable = {}

    def fingerprint(kind, location, value):
        if digest(value):
            keys.add((kind, value))
        else:
            exact_keys(value, "unavailable_reason", f"{rid} {location} fingerprint")
            require(identifier(value["unavailable_reason"]), f"Missing fingerprint reason for {rid} {location}")
            unavailable[location] = value["unavailable_reason"]

    sources = row["sources"]
    require(isinstance(sources, dict) and sources and all(map(identifier, sources)), f"Invalid source inventory for {rid}")
    if framed:
        require((cohort == "drawn") == (rid in draw_cases), f"Incorrect draw membership for {rid}")
        require(sources.keys() == {"original", "evaluated", "restored"}, f"Missing {cohort} source version for {rid}")
    for version, fingerprints in sources.items():
        exact_keys(fingerprints, "raw_sha256 normalized_sha256 template_sha256", f"{rid} {version} source fingerprints")
        fingerprint("raw_source", f"sources.{version}.raw_sha256", fingerprints["raw_sha256"])
        fingerprint("normalized_source", f"sources.{version}.normalized_sha256", fingerprints["normalized_sha256"])
        fingerprint("template", f"sources.{version}.template_sha256", fingerprints["template_sha256"])
    if cohort == "drawn":
        evaluated = sources["evaluated"]["raw_sha256"]
        require(digest(evaluated) and evaluated == draw_cases[rid]["source_sha256"], f"Evaluated source differs from draw for {rid}")
    prompts = row["prompts"]
    require(isinstance(prompts, dict) and prompts.keys() == set(representations), f"Incomplete prompt representations for {rid}")
    for representation, value in prompts.items():
        fingerprint("prompt_tokens", f"prompts.{representation}", value)
    return {"row_id": rid, "cohort": cohort, "unknown_provenance_reason": unknown,
            "keys": [list(key) for key in sorted(keys)], "unavailable_fingerprints": unavailable}


def dispositions(members):
    cohorts = {row["cohort"] for row in members}
    unknown = any(row["unknown_provenance_reason"] is not None for row in members)
    blockers = {row["row_id"]: ["unavailable_prompt_fingerprint"]
                if any(key.startswith("prompts.") for key in row["unavailable_fingerprints"]) else [] for row in members}
    has_validation = any(row["cohort"] == "validation" and not blockers[row["row_id"]] for row in members)
    for row in members:
        cohort = row["cohort"]
        reasons = ["unknown_component_provenance"] if unknown else []
        if cohort == "exposure":
            reasons.append("prior_development_tuning_or_fit")
            status = "prior_exposure"
        elif cohort == "undrawn":
            status = "not_selected"
        elif cohort == "drawn":
            if "exposure" in cohorts:
                reasons.append("linked_to_prior_exposure")
            status = "quarantined" if reasons else "eligible"
        else:
            if "drawn" in cohorts:
                reasons.append("linked_to_draw")
            reasons.extend(blockers[row["row_id"]])
            if cohort == "train" and has_validation and not reasons:
                reasons.append("reserved_for_validation")
            status = "excluded" if reasons else "eligible"
        row.update(disposition=status, reasons=reasons)


def seal(draw, provenance):
    exact_keys(draw, "schema protocol_sha256 frame_sha256 draw_seed allocation cases", "draw ledger")
    require(draw["schema"] == "eapg-synthetic-draw-v1", "Wrong draw ledger schema")
    drawn = index(draw["cases"], "case_id intended_slot source_sha256 workload_sha256", "draw")
    draw_sha = commitment(draw)
    exact_keys(provenance, "schema draw_sha256 representations rows", "provenance manifest")
    require(provenance["schema"] == PROVENANCE and provenance["draw_sha256"] == draw_sha,
            "Provenance does not bind this draw")
    representations = provenance["representations"]
    require(unique_strings(representations) and isinstance(provenance["rows"], list), "Invalid representations or provenance rows")

    rows = {}
    for original in provenance["rows"]:
        row = attest(original, representations, drawn)
        rid = row["row_id"]
        require(rid not in rows, f"Duplicate provenance row {rid}")
        rows[rid] = row
    require(drawn and {rid for rid, row in rows.items() if row["cohort"] == "drawn"} == drawn.keys(),
            "Provenance must cover the drawn case IDs exactly")

    parents = {rid: rid for rid in rows}
    owners, components = {}, defaultdict(list)

    def root(rid):
        while parents[rid] != rid:
            parents[rid] = parents[parents[rid]]
            rid = parents[rid]
        return rid

    for rid, row in sorted(rows.items()):
        for key in row["keys"]:
            other = root(owners.setdefault(tuple(key), rid))
            current = root(rid)
            parents[max(other, current)] = min(other, current)
    for rid in sorted(rows):
        components[root(rid)].append(rows[rid])

    sealed = []
    for members in components.values():
        dispositions(members)
        family_id = commitment(["eapg-synthetic-family-v1", [row["row_id"] for row in members]])
        eligible_cohorts = {row["cohort"] for row in members if row["disposition"] == "eligible"}
        require(len(eligible_cohorts) <= 1, "Eligible rows span splits in a sealed component")
        require("drawn" not in eligible_cohorts or not any(row["cohort"] == "exposure" for row in members),
                "Eligible drawn component links to prior exposure")
        sealed.append({"family_id": family_id, "rows": members})
    return {"schema": QUARANTINE, "draw_sha256": draw_sha, "provenance_sha256": commitment(provenance),
            "representations": representations, "components": sealed}


def main():
    cli = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("draw", "provenance"):
        cli.add_argument(f"--{name}", type=Path, required=True)
        cli.add_argument(f"--{name}-sha256", required=True)
    destination = cli.add_mutually_exclusive_group(required=True)
    destination.add_argument("--output", type=Path)
    destination.add_argument("--verify", type=Path)
    args = cli.parse_args()
    try:
        draw = read_canonical(args.draw, args.draw_sha256)
        provenance = read_canonical(args.provenance, args.provenance_sha256)
        manifest = seal(draw, provenance)
        raw = canonical(manifest)
        if args.verify:
            require(args.verify.read_bytes() == raw, "Sealed output differs from the replayed manifest")
        else:
            with args.output.open("xb") as stream:
                stream.write(raw)
    except (OSError, ValueError) as error:
        cli.error(str(error))
    print(f"{commitment(manifest)}  {(args.output or args.verify).name}")


if __name__ == "__main__":
    main()
