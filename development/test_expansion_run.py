import base64
from io import BytesIO, StringIO
import json
from types import SimpleNamespace

import pytest

from development.paired_study import expansion_run as run


def line(doc):
    return (run.dump(doc) + "\n").encode()


def encoded(raw):
    return base64.b64encode(raw).decode()


def artifact(raw):
    return {"base64": encoded(raw), "sha256": run.digest(raw)}


def proof(value):
    return artifact(line({"binding_sha256": run.json_pin(value), "rationale": "Synthetic test evidence"}))


@pytest.fixture
def inputs():
    source = b"int main() {}"
    side = {"files": [{"path": "main.cpp", "sha256": run.digest(source)}]}
    pair = {"id": "synthetic", "corpus": "codenet", "cluster_id": "synthetic-cluster",
            "quarantined": False, "slow": side, "fast": side}
    manifest = {"protocol_sha256": run.PROTOCOL_SHA, "status": "scrape_frozen",
                "held_out_used": False, "pairs": [pair]}
    samples = [{"size": size, "stream": stream, "input": str(size), "expected": "1\n"}
               for stream in "abc" for size in (1, 2, 4, 8, 16, 32)]
    variants = {side: {"plain": encoded(source), "counted": encoded(source)} for side in run.SIDES}
    case = {
        "originals": {side: {"path": "main.cpp", "source": encoded(source)} for side in ("slow", "fast")},
        "samples": samples, "variants": variants,
        "evidence": {
            "oracle": proof(["1\n"] * 18),
            "workload": proof([[s["stream"], s["size"], s["input"]] for s in samples]),
            "counter_calibration": proof({side: encoded(source) for side in run.SIDES}),
            "intervention": proof(variants),
        },
    }
    key = "codenet:synthetic"
    bundle = {
        "schema": "eapg.expansion.inputs.v1", "manifest_sha256": run.digest(line(manifest)),
        "desk": {key: {"status": "pass", "evidence": "Synthetic pass"}},
        "desk_evidence": {f"{key}_sha256": run.digest(key.encode()) for key in
                          ("packet", "rater_a", "rater_b", "adjudication")},
        "fixtures": {key: case},
    }
    return manifest, bundle, key


def load(inputs, **kwargs):
    manifest, bundle, _ = inputs
    manifest_raw, bundle_raw = line(manifest), line(bundle)
    return run.load_inputs(BytesIO(manifest_raw + bundle_raw), run.digest(bundle_raw),
                           manifest_pin=run.digest(manifest_raw), **kwargs)


@pytest.mark.parametrize("missing, message", [
    ("bundle", "missing adjudicated S1 labels and case fixtures"),
    ("desk", "incomplete adjudicated S1 coverage"),
    ("desk_evidence", "missing blind S1 evidence pins"),
    ("fixtures", "need exactly one pinned fixture"),
    ("oracle", "missing independent oracle"),
    ("output", "oracle evidence does not bind"),
    ("workload", "requires six sizes"),
])
def test_cli_refuses_before_gate1(inputs, monkeypatch, capsys, missing, message):
    manifest, bundle, key = inputs
    if missing in ("desk", "desk_evidence", "fixtures"):
        del bundle[missing]
    if missing == "oracle":
        del bundle["fixtures"][key]["evidence"]["oracle"]
    if missing == "output":
        bundle["fixtures"][key]["samples"][0]["expected"] = "changed"
    if missing == "workload":
        bundle["fixtures"][key]["samples"].pop()
    manifest_raw = line(manifest)
    bundle_raw = b"" if missing == "bundle" else line(bundle)
    load_inputs = run.load_inputs
    monkeypatch.setattr(run, "load_inputs", lambda stream, pin, **kwargs: load_inputs(
        stream, pin, manifest_pin=run.digest(manifest_raw), **kwargs))
    monkeypatch.setattr(run.sys, "stdin", SimpleNamespace(buffer=BytesIO(manifest_raw + bundle_raw)))
    monkeypatch.setattr(run.sys, "argv", ["expansion_run", "--bundle-sha256", run.digest(bundle_raw)])
    monkeypatch.setattr(run.gate, "invoke", lambda *a, **kw: pytest.fail("Gate 1 must not run"))
    with pytest.raises(SystemExit) as error:
        run.main()
    assert error.value.code == 2
    out = capsys.readouterr()
    assert not out.out and message in out.err


def test_held_requires_exact_list_and_explicit_amendment(inputs):
    manifest, bundle, key = inputs
    bundle["desk"].clear()
    bundle["fixtures"].clear()
    held = artifact(line([{"id": key, "corpus": "codenet", "source": "CodeNet",
                           "cluster": manifest["pairs"][0]["cluster_id"], "quarantined": False,
                           "hold": "unbundled_statement_images"}]))
    amendment = artifact(b"Synthetic amendment")
    bundle["scope_exception"] = {"held": held, "amendment": amendment}
    with pytest.raises(ValueError, match="missing approved S1 amendment"):
        load(inputs)
    with pytest.raises(ValueError, match="wrong S1 amendment"):
        load(inputs, amendment_pin="0" * 64)
    with pytest.raises(ValueError, match="wrong S1 held-list"):
        load(inputs, amendment_pin=amendment["sha256"])
    header, entries, desk, fixtures = load(inputs, amendment_pin=amendment["sha256"], held_pin=held["sha256"])
    row = run.checkpoint(key, entries[key], desk, fixtures, [])
    assert row["terminal"] == run.HELD_LABEL
    assert header["held_list_sha256"] == held["sha256"]
    assert run.summarize(entries, [row])["by_source"]["CodeNet"]["not_desk_rateable"] == 1


def test_cli_check_never_starts_gate1(inputs, monkeypatch, capsys, tmp_path):
    manifest, bundle, key = inputs
    bundle["desk"][key] = {"status": "desk_blocked", "bucket": "route", "reason": "missing_pinned_dependency",
                           "evidence": "Synthetic desk stop"}
    bundle["fixtures"].clear()
    header, entries, desk, fixtures = load(inputs)
    path = tmp_path / "checkpoint.jsonl"
    path.write_bytes(line(header) + line(run.checkpoint(key, entries[key], desk, fixtures, [])))
    manifest_raw, bundle_raw = line(manifest), line(bundle)
    load_inputs = run.load_inputs
    monkeypatch.setattr(run, "load_inputs", lambda stream, pin, **kwargs: load_inputs(
        stream, pin, manifest_pin=run.digest(manifest_raw), **kwargs))
    monkeypatch.setattr(run.sys, "stdin", SimpleNamespace(buffer=BytesIO(manifest_raw + bundle_raw)))
    monkeypatch.setattr(run.sys, "argv", [
        "expansion_run", "--bundle-sha256", run.digest(bundle_raw), "--check", str(path),
    ])
    monkeypatch.setattr(run.gate, "invoke", lambda *a, **kw: pytest.fail("Gate 1 must not run"))
    run.main()
    out = capsys.readouterr()
    assert not out.err
    assert json.loads(out.out)["complete"] is True


def result(stdout=b"", *, rc=0, counter=b"", stderr=b"", timed_out=False):
    return SimpleNamespace(stdout=stdout, returncode=rc, counter_wire=counter,
                           stderr=stderr, timed_out=timed_out, events={})


@pytest.mark.parametrize("outcome, terminal", [
    ("ok", "no_alert"), ("caps", "insufficient_fit"), ("oracle", "execution_oracle_failure"),
    ("boundary", "support_boundary_closed"), ("infrastructure", "execution_infrastructure_failure"),
    ("counter", None),
])
def test_measure_and_replay(inputs, monkeypatch, outcome, terminal):
    _, _, key = inputs
    header, entries, desk, fixtures = load(inputs)
    case = fixtures[key]

    def invoke(command, **kwargs):
        if outcome == "infrastructure":
            raise RuntimeError("synthetic Gate 1 failure")
        if command[0] == "g++":
            assert "-E" in command
            if outcome == "boundary":
                return result(stderr=b"fatal error: dependency.h: No such file or directory", rc=1)
            return result()
        assert command[:2] == ["/bin/sh", "-ec"]
        return result(b"\x7fELF")

    def execute(binary, data, *, counter_scale):
        assert binary == b"\x7fELF"
        assert counter_scale is None or counter_scale == int(data)
        if outcome == "oracle":
            return result(b"2\n")
        if outcome == "caps" and int(data) >= 8:
            return result(rc=124, timed_out=True)
        if outcome == "counter" and counter_scale:
            return result(b"1\n", counter=b"junk")
        return result(b"1\n", counter=b"1 0\n" if counter_scale else b"")

    monkeypatch.setattr(run.gate, "invoke", invoke)
    monkeypatch.setattr(run.gate, "execute", execute)
    raw = []
    run.measure(case, raw)
    checkpoint = run.checkpoint(key, entries[key], desk, fixtures, raw)
    assert checkpoint["terminal"] == terminal
    receipt = StringIO((line(header) + line(checkpoint)).decode())
    saved = run.replay(receipt, header, entries, desk, fixtures)
    assert saved == [checkpoint]
    counts = run.summarize(entries, saved)["by_source"]["CodeNet"]
    assert counts["fitted"] == (outcome == "ok")
    assert counts["execute_wall_timeout"] == (outcome == "caps")
    assert counts["node_filter_excluded"] == 0
    raw[0]["step"] = ["preprocess", "fast"]
    with pytest.raises(ValueError, match="measurement order"):
        run.replay(StringIO((line(header) + line(checkpoint)).decode()), header, entries, desk, fixtures)
