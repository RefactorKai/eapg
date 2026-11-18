"""Replay the committed origin-family draw and bind its workload digests.

Use the independently recorded protocol and frame pins on both invocations.
Omit --inputs to write the private selection. Add --inputs and --inputs-sha256
to write the scorer draw. Use --verify against either previously sealed output.
All JSON manifests use sorted keys, compact separators, ASCII escapes for
non-ASCII strings, and UTF-8 without a BOM or trailing newline.

In the frame, sham_classes maps analytic growth classes to superlinear flags.
The allocation gives quotas in mechanism, sham class, off-site band, and
at-site band cells. Each quota takes the lowest SHA-256 keys of the canonical
JSON arrays [selection schema, draw seed, zero-based frame position]. Ties
follow frame order. Rows outside allocated cells receive zero draws.

Each slot's registration digest binds the raw edit, mechanism, growth bands,
oracles, and output relation. The off-site spans use half-open byte offsets in
the evaluated source. Null provenance marks unknown keys for quarantine.
The comparator-swap family and its two slots are fixed outside core sampling.

The eapg-synthetic-inputs-v1 manifest holds selection_sha256 and a families
object keyed by selected family ID. Each value contains 18 {seed, n, sha256}
rows ordered by seed 42, 43, 44 and increasing size from n0 to 32*n0 within seed.
The frame, selection, input manifests and draw stay with the custodian.
Signatures, timestamps, and verification against raw bytes are custody steps.
"""

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path

from score_synthetic import SEEDS, digest, exact_keys, identifier, read_pinned, require, unique_strings


FRAME = "eapg-synthetic-frame-v1"
SELECTION = "eapg-synthetic-selection-v1"
INPUTS = "eapg-synthetic-inputs-v1"
CORE_SLOTS = ("positive_off_site", "positive_at_site", "same_growth_sham", "appropriate_superlinear")
SWAP_SLOTS = ("comparator_swap_positive", "comparator_swap_sham")
NEAR_BANDS = ("near_below", "near_above")  # [0.55, 0.70) and [0.70, 0.85]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def commitment(value):
    return sha256(canonical(value)).hexdigest()


def span(value):
    return (isinstance(value, list) and len(value) == 2 and all(type(pos) is int for pos in value)
            and 0 <= value[0] < value[1])


def validate_slots(slots, slot_names, case_ids):
    exact_keys(slots, " ".join(slot_names), "registered slots")
    for slot, row in slots.items():
        fields = "case_id source_hashes registration_sha256"
        if slot in CORE_SLOTS[:2]:
            fields += " band"
        if slot == "positive_off_site":
            fields += " edit_span intended_statement_span"
        exact_keys(row, fields, slot)
        pid = row["case_id"]
        require(identifier(pid) and pid not in case_ids, f"Invalid or duplicate case ID for {slot}")
        case_ids.add(pid)
        hashes = row["source_hashes"]
        exact_keys(hashes, "original evaluated restored", f"{pid} source hashes")
        require(all(map(digest, hashes.values())) and digest(row["registration_sha256"]),
                f"Invalid source or registration digest for {pid}")
        require(hashes["restored"] == hashes["original"] and
                (hashes["original"] == hashes["evaluated"]) == (slot == "appropriate_superlinear"),
                f"Invalid planned source versions for {pid}")
        if slot in CORE_SLOTS[:2]:
            require(row["band"] in ("strong", *NEAR_BANDS), f"Invalid positive band for {pid}")
        if slot == "positive_off_site":
            edit, statement = row["edit_span"], row["intended_statement_span"]
            require(span(edit) and span(statement) and (edit[1] <= statement[0] or statement[1] <= edit[0]),
                    f"Off-site spans overlap or are invalid for {pid}")


def select(frame, protocol_sha256):
    """Return a private selection and its ordered (family, slot, case plan) rows."""
    exact_keys(frame, "schema protocol_sha256 draw_seed sham_classes allocation families comparator_swap", "frame")
    require(frame["schema"] == FRAME and digest(protocol_sha256) and frame["protocol_sha256"] == protocol_sha256,
            "Invalid frame schema or protocol pin")
    seed, classes = frame["draw_seed"], frame["sham_classes"]
    require(type(seed) is int, "Invalid draw seed")
    require(isinstance(classes, dict) and len(classes) >= 2 and any(classes.values())
            and all(identifier(name) and type(superlinear) is bool for name, superlinear in classes.items()),
            "Register multiple sham growth classes, including a superlinear class")

    require(isinstance(frame["families"], list), "Expected an ordered family list")
    families, case_ids, origins, available = {}, set(), {}, defaultdict(list)
    for position, family in enumerate(frame["families"]):
        exact_keys(family, "family_id problem_id problem_aliases specification_sha256 implementation_origin "
                   "generator_id generator_ancestors mechanism sham_class workload slots", "origin family")
        fid, mechanism, sham = family["family_id"], family["mechanism"], family["sham_class"]
        require(identifier(fid) and fid not in families, "Invalid or duplicate family ID")
        require(identifier(mechanism) and identifier(sham) and sham in classes, f"Invalid stratum for {fid}")
        require(digest(family["specification_sha256"]), f"Invalid specification digest for {fid}")
        for kind, singular, plural in (("problem", "problem_id", "problem_aliases"),
                                       ("implementation", "implementation_origin", None),
                                       ("generator", "generator_id", "generator_ancestors")):
            origin, related = family[singular], family.get(plural)
            require((origin is None or identifier(origin)) and (related is None or unique_strings(related)),
                    f"Invalid {kind} provenance for {fid}")
            for key in ({origin} | set(related or ())) - {None}:
                owner = origins.setdefault((kind, key), fid)
                require(owner == fid, f"Shared {kind} provenance in origin families {owner} and {fid}")
        workload = family["workload"]
        exact_keys(workload, "generator_sha256 distribution n0 size_parameters", f"{fid} workload")
        require(digest(workload["generator_sha256"]) and identifier(workload["distribution"])
                and identifier(workload["size_parameters"]) and type(workload["n0"]) is int and workload["n0"] > 0,
                f"Invalid workload recipe for {fid}")
        slots = family["slots"]
        validate_slots(slots, CORE_SLOTS, case_ids)
        cell = (mechanism, sham, *(slots[slot]["band"] for slot in CORE_SLOTS[:2]))
        available[cell].append((commitment([SELECTION, seed, position]), position, fid))
        families[fid] = family

    quota, drawn, shams, near_bands, near_mechanisms = set(), [], Counter(), set(), set()
    require(isinstance(frame["allocation"], list), "Expected ordered allocation rows")
    for row in frame["allocation"]:
        exact_keys(row, "mechanism sham_class off_site_band at_site_band count", "allocation row")
        cell = tuple(row[key] for key in ("mechanism", "sham_class", "off_site_band", "at_site_band"))
        count = row["count"]
        require(all(map(identifier, cell)) and cell not in quota and type(count) is int
                and 0 < count <= len(available[cell]), "Invalid or unavailable allocation cell")
        quota.add(cell)
        drawn.extend(fid for _, _, fid in sorted(available[cell])[:count])
        shams[cell[1]] += count
        bands = set(cell[2:]).intersection(NEAR_BANDS)
        if bands:
            near_bands.update(bands)
            near_mechanisms.add(cell[0])
    require(len(drawn) == 80, "The core draw requires 80 origin families")
    require(set(shams) == set(classes) and max(shams.values()) - min(shams.values()) <= 1,
            "Allocation must balance the registered sham growth classes")
    require(near_bands == set(NEAR_BANDS) and len(near_mechanisms) >= 2,
            "Allocation needs both near-threshold bands across at least two mechanisms")

    swap = frame["comparator_swap"]
    exact_keys(swap, "family_id slots", "comparator swap")
    swap_id = swap["family_id"]
    require(identifier(swap_id) and swap_id in families, "Unknown comparator-swap family")
    validate_slots(swap["slots"], SWAP_SLOTS, case_ids)
    left, right = (swap["slots"][slot]["source_hashes"] for slot in SWAP_SLOTS)
    require(left["evaluated"] == right["evaluated"] and left["original"] != right["original"],
            "Comparator swap requires identical evaluated bytes and distinct comparators")
    cases = [(families[fid], slot, families[fid]["slots"][slot]) for fid in drawn for slot in CORE_SLOTS]
    cases.extend((families[swap_id], slot, swap["slots"][slot]) for slot in SWAP_SLOTS)
    selection = {"schema": SELECTION, "protocol_sha256": protocol_sha256, "frame_sha256": commitment(frame),
                 "draw_seed": seed, "core_family_ids": drawn, "comparator_swap_family_id": swap_id,
                 "case_ids": [row["case_id"] for _, _, row in cases]}
    return selection, cases


def build_draw(selection, cases, inputs):
    """Bind one ordered seed-major grid of input SHA-256s per selected family."""
    exact_keys(inputs, "schema selection_sha256 families", "input digest manifest")
    require(inputs["schema"] == INPUTS and inputs["selection_sha256"] == commitment(selection),
            "Input digests do not bind the replayed selection")
    families = {family["family_id"]: family for family, _, _ in cases}
    grids = inputs["families"]
    require(isinstance(grids, dict) and grids.keys() == families.keys(),
            "Input digests must cover the selected families exactly")
    workload_pins = {}
    for fid, family in families.items():
        workload, grid = family["workload"], grids[fid]
        coordinates = [(seed, workload["n0"] << power) for seed in SEEDS for power in range(6)]
        require(isinstance(grid, list) and len(grid) == len(coordinates), f"Incomplete input digest grid for {fid}")
        for row, (seed, n) in zip(grid, coordinates):
            exact_keys(row, "seed n sha256", f"{fid} input digest")
            require(type(row["seed"]) is int and row["seed"] == seed and type(row["n"]) is int and row["n"] == n
                    and digest(row["sha256"]), f"Invalid or out-of-order input digest for {fid}")
        workload_pins[fid] = commitment({"recipe": workload, "inputs": grid})
    draw = {key: selection[key] for key in ("protocol_sha256", "frame_sha256", "draw_seed")}
    draw.update(schema="eapg-synthetic-draw-v1", allocation=dict(Counter(slot for _, slot, _ in cases)),
                cases=[{"case_id": row["case_id"], "intended_slot": slot,
                        "source_sha256": row["source_hashes"]["evaluated"],
                        "workload_sha256": workload_pins[family["family_id"]]} for family, slot, row in cases])
    return draw


def read_canonical(path, pin):
    value = read_pinned(path, pin)
    require(commitment(value) == pin, f"Noncanonical JSON in {path.name}")
    return value


def main():
    cli = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("protocol", "frame", "inputs"):
        cli.add_argument(f"--{name}", required=name != "inputs", type=Path)
        cli.add_argument(f"--{name}-sha256", required=name != "inputs")
    destination = cli.add_mutually_exclusive_group(required=True)
    destination.add_argument("--output", type=Path)
    destination.add_argument("--verify", type=Path)
    args = cli.parse_args()
    try:
        require(bool(args.inputs) == (args.inputs_sha256 is not None), "Pass both input manifest and pin")
        require(digest(args.protocol_sha256) and sha256(args.protocol.read_bytes()).hexdigest() == args.protocol_sha256,
                "Protocol digest mismatch")
        frame = read_canonical(args.frame, args.frame_sha256)
        selection, cases = select(frame, args.protocol_sha256)
        value = build_draw(selection, cases, read_canonical(args.inputs, args.inputs_sha256)) if args.inputs else selection
        raw = canonical(value)
        if args.verify:
            require(args.verify.read_bytes() == raw, "Sealed output differs from the replayed manifest")
        else:
            with args.output.open("xb") as stream:
                stream.write(raw)
    except (OSError, ValueError) as error:
        cli.error(str(error))
    print(f"{sha256(raw).hexdigest()}  {(args.output or args.verify).name}")


if __name__ == "__main__":
    main()
