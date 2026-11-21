from hashlib import sha256
import json
from pathlib import Path
from runpy import run_path
import subprocess
import sys

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


@pytest.mark.parametrize("mode", ["fast", "common", "linux"])
@pytest.mark.parametrize(("skipped", "allow_skips", "status"), [(False, False, 0), (True, False, 2), (True, True, 0)])
def test_verify_reports_skips_in_selected_suites(monkeypatch, capsys, mode, skipped, allow_skips, status):
    candidate = b"test candidate"
    monkeypatch.setattr(eapg, "CANDIDATE_PROSPECTIVE_SHA256", sha256(candidate).hexdigest())
    monkeypatch.setattr(eapg, "_check_candidate_build", lambda **kwargs: None)
    suite = ("development/test_synthetic_intervention.py" if mode == "linux" else
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
    assert (f"Not selected in {mode} mode" in captured.out) is (mode != "linux")
    assert f"Re-executed: {suite}" in captured.out


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


def test_paired_replay_checks_content_beyond_hashes():
    artifact = eapg.ROOT / "artifacts/paired_development"
    replay = run_path(str(artifact / "replay.py"))
    ledger, historical, sweep = (json.loads((artifact / f"{name}.json").read_bytes())
                                 for name in ("ledger", "historical-ledger", "precedence-sweep"))

    replay["validate_phase_a"](ledger, historical)
    replay["validate_sweep_summary"](sweep, ledger)
    ledger["rows"][0]["phase_a"]["disposition"] = "excluded"
    with pytest.raises(ValueError, match="Phase A/B content differs from the archived ledger at rank 1"):
        replay["validate_phase_a"](ledger, historical)
    sweep["summary"]["distinct"]["fully_scanned_slots"] -= 1
    with pytest.raises(ValueError, match="fully_scanned_slots disagrees with disjoint frame subtotals"):
        replay["validate_sweep_summary"](sweep, ledger)
