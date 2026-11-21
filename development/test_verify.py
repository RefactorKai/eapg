from hashlib import sha256
from pathlib import Path
import subprocess

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
    assert "Verified" not in capsys.readouterr().out


@pytest.mark.parametrize("skipped", [False, True])
def test_linux_verify_reports_paired_sandbox_skips(monkeypatch, capsys, skipped):
    candidate = b"test candidate"
    monkeypatch.setattr(eapg, "CANDIDATE_PROSPECTIVE_SHA256", sha256(candidate).hexdigest())
    monkeypatch.setattr(eapg, "_check_candidate_build", lambda **kwargs: None)

    def run(cmd, **kwargs):
        if cmd[2] == "development/build_candidate.py":
            Path(cmd[-1]).write_bytes(candidate)
        if skipped and cmd[2] == "development/test_synthetic_intervention.py":
            flag, code = cmd[-2:]
            assert flag == "--skip-exit-code"
            return subprocess.CompletedProcess(cmd, int(code))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(eapg.subprocess, "run", run)
    assert eapg.main(["verify", "--mode", "linux"]) == 0
    output = capsys.readouterr().out
    assert ("SKIPPED: paired intervention sandbox tests" in output) is skipped
    assert ("Verified EAPG artifact checks cleanly" in output) is not skipped
