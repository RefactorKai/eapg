from hashlib import sha256
import json
from pathlib import Path, PureWindowsPath
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

import eapg


@pytest.mark.parametrize("mode", ["fast", "common"])
def test_verify_propagates_paired_replay_failure(monkeypatch, capsys, mode):
    replay = ("-B", "-S", "artifacts/paired_development/replay.py")

    def run(args, **kwargs):
        if args == replay:
            raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(eapg, "_run_py", run)
    monkeypatch.setattr(eapg, "_check_candidate_build", lambda **kwargs: None)
    with pytest.raises(subprocess.CalledProcessError) as exc:
        eapg.main(["verify", "--mode", mode])
    assert exc.value.cmd == replay
    output = capsys.readouterr().out
    assert "Replay-only: artifacts/paired_development/replay.py" in output
    assert "Verified" not in output


@pytest.mark.parametrize("mode", ["fast", "common", "linux", "auto"])
@pytest.mark.parametrize(("skipped", "allow_skips", "status"), [(False, False, 0), (True, False, 2), (True, True, 0)])
def test_verify_reports_skips_in_selected_suites(monkeypatch, capsys, mode, skipped, allow_skips, status):
    candidate = b"test candidate"
    monkeypatch.setattr(eapg, "CANDIDATE_PROSPECTIVE_SHA256", sha256(candidate).hexdigest())
    monkeypatch.setattr(eapg, "_check_candidate_build", lambda **kwargs: None)
    uses_linux = mode in ("linux", "auto")
    monkeypatch.setattr(eapg, "sys", SimpleNamespace(platform="linux", executable=sys.executable,
                                                    stderr=sys.stderr, stdout=sys.stdout))
    suite = ("development/test_synthetic_intervention.py" if uses_linux else
             "development/test_prospective_multiagent_study.py")

    def run(cmd, **kwargs):
        if cmd[2] == "development/build_candidate.py":
            Path(cmd[-1]).write_bytes(candidate)
        if skipped and suite in cmd:
            assert "development/verify_unittest.py" in cmd
            return subprocess.CompletedProcess(cmd, 3, stderr="SKIPPED: test requires a sandbox\n")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(eapg.subprocess, "run", run)
    flags = ["--allow-skips"] if allow_skips else []
    assert eapg.main(["verify", "--mode", mode, *flags]) == status
    captured = capsys.readouterr()
    assert ("SKIPPED: test requires a sandbox" in captured.err) is skipped
    assert (f"SKIPPED: tests in {suite}" in captured.out) is skipped
    assert ("Verified selected EAPG artifact checks" in captured.out) is not skipped
    assert (f"Not selected in {mode} mode" in captured.out) is not uses_linux
    assert f"{'Re-executed' if uses_linux else 'Replay-only'}: {suite}" in captured.out


@pytest.mark.parametrize("allow_skips", [False, True])
@pytest.mark.parametrize("skips_on", ["windows", "wsl"])
def test_wsl_verify_keeps_skip_outcome(monkeypatch, capsys, skips_on, allow_skips):
    suite = "development/test_prospective_multiagent_study.py"
    monkeypatch.setattr(eapg, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(eapg, "ROOT", PureWindowsPath("C:/eapg"))
    monkeypatch.setattr(eapg, "_check_candidate_build", lambda **kwargs: None)
    monkeypatch.setattr(eapg, "_run_verify_check",
                        lambda cmd, **kwargs: suite if suite in cmd and skips_on == "windows" else None)

    def run(cmd, **kwargs):
        assert cmd[0] == "wsl"
        assert b"summarize_success=False" in kwargs["input"]
        assert b"--allow-skips" not in kwargs["input"]
        if skips_on == "wsl":
            print("SKIPPED: paired sandbox requires user systemd")
        return subprocess.CompletedProcess(cmd, 2 if skips_on == "wsl" else 0)

    monkeypatch.setattr(eapg.subprocess, "run", run)
    flags = ["--allow-skips"] if allow_skips else []
    assert eapg.main(["verify", "--mode", "wsl2", *flags]) == (0 if allow_skips else 2)
    output = capsys.readouterr().out
    assert "SKIPPED:" in output
    assert "Verified" not in output


def test_unittest_wrapper_reports_actual_skip_reason(tmp_path):
    suite = tmp_path / "test_skip.py"
    suite.write_text(
        "import unittest\nclass Example(unittest.TestCase):\n"
        "    def test_skip(self):\n        self.skipTest('sandbox missing')\n"
        "unittest.main()\n",
        encoding="utf-8",
    )
    run = subprocess.run(
        [sys.executable, "-B", "-S", str(eapg.ROOT / "development/verify_unittest.py"), str(suite)],
        capture_output=True, text=True,
    )
    assert run.returncode == 3
    assert "SKIPPED: test_skip.py: sandbox missing" in run.stderr


@pytest.fixture
def public_checkout(tmp_path):
    files = subprocess.check_output(["git", "ls-files", "-z"], cwd=eapg.ROOT).decode("utf-8")
    sealed = {"pie_test.jsonl", "pie_test_static_manifest.json", "pie_merged_testcases.tar.gz"}
    for name in filter(None, files.split("\0")):
        path = Path(name)
        if ".codex" in path.parts or path.name in sealed:
            continue
        dest = tmp_path / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(eapg.ROOT / path, dest)
    return tmp_path


def write_receipt(path, data):
    raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(raw)
    return sha256(raw).hexdigest()


@pytest.mark.parametrize(("mutation", "error"), [
    (None, None),
    ("desk", "Phase A/B content differs from the archived ledger at rank 1"),
    ("fit_count", "Final dispositions do not reconcile"),
    ("scan_count", "Precedence sweep distinct.fully_scanned_slots disagrees with disjoint frame subtotals"),
])
def test_ordinary_verify_rejects_repinned_mutations(public_checkout, monkeypatch, mutation, error):
    prefix = "artifacts/paired_development/"
    artifact = public_checkout / prefix
    manifest_path = artifact / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    changed = {}
    if mutation in ("desk", "fit_count"):
        ledger_path = artifact / "ledger.json"
        ledger = json.loads(ledger_path.read_bytes())
        if mutation == "desk":
            assert ledger["rows"][0]["phase_a"]["disposition"] == "eligible"
            ledger["rows"][0]["phase_a"]["disposition"] = "excluded"
        else:
            assert ledger["totals"]["verified_growth_evaluation"] == 5
            ledger["totals"]["verified_growth_evaluation"] -= 1
        ledger_sha = changed[prefix + ledger_path.name] = write_receipt(ledger_path, ledger)
        for name, pin in manifest["pins"]["results"].items():
            path = artifact / name
            receipt = json.loads(path.read_bytes())
            receipt.get("inputs", receipt)["ledger_sha256"] = ledger_sha
            pin["sha256"] = changed[prefix + name] = write_receipt(path, receipt)
    elif mutation == "scan_count":
        path = artifact / "precedence-sweep.json"
        sweep = json.loads(path.read_bytes())
        assert sweep["summary"]["distinct"]["fully_scanned_slots"] == 82
        sweep["summary"]["distinct"]["fully_scanned_slots"] = 81
        manifest["pins"]["results"][path.name]["sha256"] = changed[prefix + path.name] = write_receipt(path, sweep)
    if changed:
        manifest["public"].update(changed)
        changed[prefix + manifest_path.name] = write_receipt(manifest_path, manifest)
        sums = public_checkout / "SHA256SUMS"
        entries = (line.split("  ", 1) for line in sums.read_text(encoding="utf-8").splitlines() if line)
        sums.write_text("".join(f"{changed.get(name, digest)}  {name}\n" for digest, name in entries), encoding="utf-8")

    monkeypatch.delenv("EAPG_REPO_ROOT", raising=False)
    result = subprocess.run([sys.executable, "-B", "-S", "eapg.py", "verify", "--mode", "fast"],
                            cwd=public_checkout, capture_output=True, text=True, encoding="utf-8")
    assert "Replay-only: artifacts/paired_development/replay.py" in result.stdout
    if error:
        assert result.returncode == 1
        assert error in result.stderr
        assert "Verified selected" not in result.stdout
    else:
        assert result.returncode == 0, result.stderr
        assert "Re-executed: development/build_candidate.py" in result.stdout
        assert "Replay-only: development/test_prospective_multiagent_study.py" in result.stdout
        assert "Not selected in fast mode: Linux/WSL2 checks, including paired intervention sandbox tests." in result.stdout


@pytest.mark.parametrize("allow_skips", [False, True])
def test_ordinary_verify_reports_an_injected_skip(public_checkout, monkeypatch, allow_skips):
    suite = public_checkout / "development/test_prospective_multiagent_study.py"
    suite.write_text(
        "import unittest\nclass Example(unittest.TestCase):\n"
        "    def test_skip(self):\n        self.skipTest('sandbox unavailable')\n"
        "unittest.main()\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("EAPG_REPO_ROOT", raising=False)
    flags = ["--allow-skips"] if allow_skips else []
    result = subprocess.run([sys.executable, "-B", "-S", "eapg.py", "verify", "--mode", "fast", *flags],
                            cwd=public_checkout, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == (0 if allow_skips else 2), result.stderr
    assert "SKIPPED: test_prospective_multiagent_study.py: sandbox unavailable" in result.stderr
    assert "Verified" not in result.stdout


@pytest.mark.parametrize(("source", "macro", "wrong_literal", "error"), [
    ("evaluation.tex", r"\GroupedNearestCFG{}", "5/5", "OEIS nearest-preceding CFG must use its generated macro"),
    ("paper.tex", r"\GroupedFullMultiCI", "[+6.32,+62.12]", "Grouped statistics macro references differ in abstract"),
])
def test_fast_verify_rejects_manuscript_macro_substitutions(public_checkout, monkeypatch,
                                                            source, macro, wrong_literal, error):
    manuscript = public_checkout / "manuscript" / source
    content = manuscript.read_text(encoding="utf-8")
    assert content.count(macro) == 1
    manuscript.write_text(content.replace(macro, wrong_literal), encoding="utf-8")
    monkeypatch.delenv("EAPG_REPO_ROOT", raising=False)
    result = subprocess.run([sys.executable, "-B", "-S", "eapg.py", "verify", "--mode", "fast"],
                            cwd=public_checkout, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 1
    assert error in result.stderr
