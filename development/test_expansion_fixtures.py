from io import BytesIO

import pytest

from development.paired_study import expansion_fixtures as gen
from development.paired_study import expansion_run as run
from development.test_expansion_run import inputs, line  # noqa: F401


def synthetic(inputs):
    manifest, seal, key = inputs
    fixture = seal.pop("fixtures")[key]
    manifest_raw = line(manifest)
    manifest_pin = run.digest(manifest_raw)
    entries, desk = run.load_s1(manifest, seal, manifest_pin, None, run.HELD_SHA)
    recipe = {"originals": fixture["originals"], "variants": fixture["variants"],
              "spec_sha256": run.digest(b"Synthetic contract: return twice the input"),
              "streams": {stream: [1, 2, 4, 8, 16, 32] for stream in "abc"},
              "make_input": lambda stream, size: f"{(ord(stream) - 96) * size}\n",
              "oracle": lambda text: f"{2 * int(text)}\n",
              "rationales": dict.fromkeys(run.ARTIFACTS, "Synthetic test evidence")}
    return manifest_raw, seal, entries, desk, key, recipe


def test_spec_oracle_produces_runner_compatible_bundle(inputs):
    raw, seal, entries, desk, key, recipe = synthetic(inputs)
    pin = run.digest(b"test recipe")
    first = gen.build_bundle(seal, entries, desk, {key: recipe}, pin)
    second = gen.build_bundle(seal, entries, desk, {key: recipe}, pin)
    assert first == second
    _, _, _, fixtures = run.load_inputs(BytesIO(raw + first), run.digest(first), manifest_pin=run.digest(raw))
    samples = fixtures[key]["samples"]
    assert len(samples) == 18
    assert samples[-1] == {"stream": "c", "size": 32, "input": "96\n", "expected": "192\n"}


def test_missing_or_extra_recipes_fail_before_workload_generation(inputs):
    _, seal, entries, desk, key, recipe = synthetic(inputs)
    recipe["make_input"] = lambda *_: pytest.fail("should not reach unsealed or extra input")
    for recipes in ({}, {key: recipe, "extra": recipe}):
        with pytest.raises(ValueError, match="recipes must cover exactly"):
            gen.build_bundle(seal, entries, desk, recipes, run.digest(b"test recipe"))


def test_desk_stop_does_not_get_a_fixture(inputs):
    _, seal, entries, desk, key, _ = synthetic(inputs)
    stop = {"status": "desk_blocked", "bucket": "route", "reason": "missing_pinned_dependency",
            "evidence": "Synthetic desk stop"}
    desk[key] = seal["desk"][key] = stop
    raw = gen.build_bundle(seal, entries, desk, {}, run.digest(b"test recipe"))
    assert b'"fixtures":{}' in raw


@pytest.mark.parametrize("correct_pin", [True, False])
def test_cli_pins_recipe_before_running_it(inputs, tmp_path, monkeypatch, capsys, correct_pin):
    raw, seal, _, _, key, recipe = synthetic(inputs)
    del recipe["make_input"], recipe["oracle"]
    code = (f"RECIPES = {{{key!r}: {recipe!r}}}\n"
            f"RECIPES[{key!r}].update(make_input=lambda stream, size: str(size), "
            "oracle=lambda text: str(2 * int(text)))\n").encode()
    manifest_path, s1_path, recipes_path = (tmp_path / name for name in ("manifest", "seal", "recipes.py"))
    manifest_path.write_bytes(raw)
    s1_path.write_bytes(line(seal))
    recipes_path.write_bytes(code)
    monkeypatch.setattr(run, "MANIFEST_SHA", run.digest(raw))
    monkeypatch.setattr(gen.sys, "argv", [
        "expansion_fixtures",
        "--manifest", str(manifest_path), "--s1", str(s1_path), "--s1-sha256", run.digest(line(seal)),
        "--recipes", str(recipes_path), "--recipes-sha256", run.digest(code) if correct_pin else "0" * 64,
    ])
    if not correct_pin:
        with pytest.raises(SystemExit) as err:
            gen.main()
        assert err.value.code == 2
        output = capsys.readouterr()
        assert not output.out and "wrong trusted recipe module SHA-256" in output.err
        return
    gen.main()
    output = capsys.readouterr()
    assert output.err.strip() == "bundle_sha256=" + run.digest(output.out.encode())
    assert '"expected":"64"' in output.out
