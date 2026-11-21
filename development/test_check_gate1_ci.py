"""Test that the strict CI gate rejects duplicate probes and skipped tests."""

import json
from types import SimpleNamespace
import unittest

import pytest

import check_gate1_ci


@pytest.mark.parametrize(("duplicate", "skip", "exit_code"), [
    (False, False, 0),
    (True, False, 1),
    (False, True, 1),
])
def test_gate_rejects_incomplete_validation(monkeypatch, duplicate, skip, exit_code):
    probe_names = ["a", "b", "c", "c" if duplicate else "d"]
    output = "\n".join(json.dumps({"probe": name, "status": "passed"}) for name in probe_names)
    monkeypatch.setattr(check_gate1_ci, "subprocess",
                        SimpleNamespace(PIPE=None, run=lambda *a, **kw: SimpleNamespace(returncode=0, stdout=output)))

    def sandbox_test():
        if skip:
            raise unittest.SkipTest("no sandbox")

    def load_tests(names):
        assert len(names) == 7
        return unittest.TestSuite(unittest.FunctionTestCase(sandbox_test) for _ in names)

    monkeypatch.setattr(unittest.defaultTestLoader, "loadTestsFromNames", load_tests)
    assert check_gate1_ci.main() == exit_code
