"""Run the four Gate 1 probes and require all seven sandbox tests to pass."""

import subprocess
import sys
import unittest


GATE1_TESTS = (
    "test_changed_byte_resolves_inside_braceless_statement",
    "test_rejects_two_sibling_statements_in_one_splice",
    "test_rejects_equivalent_span_of_a_different_token",
    "test_macro_directive_retains_nodes_for_unresolved_reference",
    "test_directive_change_is_not_a_single_code_statement_edit",
    "test_builtin_expansion_yields_nonconserving_origin",
    "test_equal_canonical_owners_remain_unresolved",
)


def main():
    subprocess.run([sys.executable, "-B", "development/probe_gate1.py", "--probes-only"], check=True)
    print("Gate 1 probes: 4/4 passed", flush=True)
    tests = unittest.defaultTestLoader.loadTestsFromNames(
        [f"test_synthetic_intervention.InterventionTest.{name}" for name in GATE1_TESTS]
    )
    result = unittest.TextTestRunner(verbosity=2).run(tests)
    if not result.wasSuccessful() or result.skipped or result.testsRun != len(GATE1_TESTS):
        return 1
    print(f"Gate 1 sandbox tests: {result.testsRun}/{len(GATE1_TESTS)} passed, 0 skipped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
