"""Build the expansion runner bundle from sealed S1 and trusted, pinned recipes.

The recipe module exports RECIPES keyed by corpus:pair_id. Each recipe has a
spec_sha256; originals and variants in the runner format; streams mapping
names to six sizes; make_input(stream, size) and oracle(input_text) returning
text; and rationales for oracle, workload, counter_calibration and intervention.
Only already-reviewed local Python recipes may be used. No C++ is run.
"""

import argparse
import base64
import json
from pathlib import Path
import sys

from . import expansion_run as run


def evidence(value, rationale, spec_pin, recipe_pin):
    run.require(isinstance(rationale, str) and rationale.strip(), "missing evidence rationale")
    raw = run.dump({"binding_sha256": run.json_pin(value), "rationale": rationale,
                    "spec_sha256": spec_pin, "recipes_sha256": recipe_pin}).encode()
    return {"base64": base64.b64encode(raw).decode(), "sha256": run.digest(raw)}


def build_fixture(entry, recipe, recipe_pin):
    spec_pin = recipe["spec_sha256"]
    run.require(run.is_pin(spec_pin), "missing independent problem specification pin")
    samples = []
    for stream, sizes in sorted(recipe["streams"].items()):
        for size in sorted(sizes):
            data = recipe["make_input"](stream, size)
            run.require(isinstance(data, str), "workload generator must return text")
            expected = recipe["oracle"](data)
            run.require(isinstance(expected, str), "output oracle must return text")
            samples.append({"stream": stream, "size": size, "input": data, "expected": expected})
    fixture = {"originals": recipe["originals"], "variants": recipe["variants"], "samples": samples}
    fixture["evidence"] = {name: evidence(value, recipe["rationales"][name], spec_pin, recipe_pin)
                           for name, value in run.fixture_bindings(fixture).items()}
    run.validate_fixture(entry, fixture)
    return fixture


def build_bundle(seal, entries, desk, recipes, recipe_pin):
    passes = [key for key in entries if desk.get(key, {}).get("status") == "pass"]
    run.require(recipes.keys() == set(passes), "recipes must cover exactly the sealed S1 passes")
    fixtures = {key: build_fixture(entries[key], recipes[key], recipe_pin) for key in passes}
    return (run.dump({**seal, "fixtures": fixtures}) + "\n").encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--s1", type=Path, required=True, help="sealed S1 input object without fixtures")
    parser.add_argument("--s1-sha256", required=True)
    parser.add_argument("--recipes", type=Path, required=True, help="trusted local Python recipe module")
    parser.add_argument("--recipes-sha256", required=True)
    parser.add_argument("--amendment-sha256")
    args = parser.parse_args()
    try:
        manifest = run.load_manifest(args.manifest.read_bytes(), run.MANIFEST_SHA)
        seal_raw = args.s1.read_bytes()
        run.require(run.digest(seal_raw) == args.s1_sha256, "wrong sealed S1 SHA-256")
        seal = json.loads(seal_raw)
        run.require("fixtures" not in seal, "expected S1 input without fixtures")
        entries, desk = run.load_s1(manifest, seal, run.MANIFEST_SHA, args.amendment_sha256, run.HELD_SHA)
        recipes_raw = args.recipes.read_bytes()
        run.require(run.digest(recipes_raw) == args.recipes_sha256, "wrong trusted recipe module SHA-256")
        module = {"__name__": "expansion_recipes", "__file__": str(args.recipes)}
        exec(compile(recipes_raw, str(args.recipes), "exec"), module)
        raw = build_bundle(seal, entries, desk, module["RECIPES"], args.recipes_sha256)
        sys.stdout.buffer.write(raw)
        print(f"bundle_sha256={run.digest(raw)}", file=sys.stderr)
    except (KeyError, TypeError, AttributeError, ValueError, SyntaxError, OSError) as error:
        parser.exit(2, f"expansion fixtures: {error}\n")


if __name__ == "__main__":
    main()
