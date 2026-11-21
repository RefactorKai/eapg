"""Check the frozen pilot's Gate 1 subprocess and receipt contracts."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import reexec_pilot_gate1 as reexec


@pytest.fixture
def stages(monkeypatch):
    result = SimpleNamespace(returncode=0, timed_out=False, stdout=b"output\r\n", stderr=b"counter")
    mocks = SimpleNamespace(invoke=Mock(return_value=result), execute=Mock(return_value=result),
                            compile_cpp=Mock(return_value=b"program"))
    for name, mock in vars(mocks).items():
        monkeypatch.setattr(reexec.gate1, name, mock)
    return mocks


def test_frozen_pilot_uses_gate1_for_every_cpp_stage(stages):
    gen = reexec.pilot.load_frozen_pipeline()
    gen.subprocess = reexec.Gate1Subprocess()
    source = "int main() {}"
    assert gen.preprocess_pass_zero(source)[0] == "\n\noutput\n"
    stages.invoke.assert_called_with(["g++", "-E", "-P", "-x", "c++", "-"], data=source.encode(), timeout=10)
    assert gen.verify_cpp_syntax(source)
    stages.invoke.assert_called_with(["g++", "-std=c++17", "-fsyntax-only", "-x", "c++", "-"],
                                    data=source.encode(), timeout=10)

    assert gen.compile_cpp_binary(source, "pilot.exe")
    stages.compile_cpp.assert_called_once_with(source.encode())
    assert gen.run_sandboxed_binary("pilot.exe", "input") == (0, "output\n", "counter", "CLEAN_COMPLETION")
    stages.execute.assert_called_once_with(b"program", b"input", timeout=3.0)
    stages.invoke.return_value.stderr = b'---EAPG_DUMP_START--- {"status":"CAP_BREACHED"} ---EAPG_DUMP_END---'
    assert gen.run_instrumented_binary("pilot.exe", "input", 16) == ("CAP_BREACHED", {})
    stages.invoke.assert_called_with(["/usr/bin/env", "EAPG_N=16", "/program"],
                                    data=b"input", binary=b"program", timeout=3.0)


def test_failed_preprocessing_cannot_use_frozen_host_fallback(stages):
    stages.invoke.return_value.returncode = 1
    gen = reexec.pilot.load_frozen_pipeline()
    gen.subprocess = reexec.Gate1Subprocess()
    with pytest.raises(SystemExit, match="Sandbox stage failed: exit=1"):
        gen.preprocess_pass_zero("int main() {}")


def test_unrecognized_command_fails_without_running(stages):
    with pytest.raises(SystemExit, match="no host fallback"):
        reexec.Gate1Subprocess().run(["/bin/true"], input="", timeout=1, text=True, capture_output=True)
    stages.invoke.assert_not_called()
    stages.execute.assert_not_called()
    stages.compile_cpp.assert_not_called()


def test_receipt_check_rejects_archive_differences_and_stale_expected_receipt():
    with pytest.raises(SystemExit, match="1 differences"):
        reexec.validate({"differences": ["PAIR_001:skeleton"]})
    with pytest.raises(SystemExit, match="differs at: counters_sha256"):
        reexec.validate({"differences": [], "counters_sha256": "new"},
                        {"differences": [], "counters_sha256": "old"})
    reexec.validate({"differences": []}, {"differences": []})
