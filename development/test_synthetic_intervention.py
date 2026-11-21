"""Test reversible-byte and canonical-reference contracts on authored C++."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from build_candidate import build_candidate
from run_phase2_development import load_pipeline, normalize
from synthetic_intervention import resolve_intervention, sha, verify_splice


PROSPECTIVE_SHA = "2c95df0e5676e8b19464457adfb34cdf85a8a10cc0dca8b70557a1d587ced383"


def _has_gate1_sandbox() -> bool:
    if sys.platform != "linux" or os.getuid() == 0:
        return False
    if not all(shutil.which(cmd) for cmd in ("systemd-run", "systemctl", "bwrap")):
        return False
    return subprocess.run(["systemctl", "--user", "show-environment"], capture_output=True).returncode == 0


HAS_GATE1_SANDBOX = _has_gate1_sandbox()


def intervention(original, removed, inserted, *, at=None, alternatives=()):
    before, after = removed.encode(), inserted.encode()
    raw = original.encode()
    start = raw.index(before) if at is None else at
    edited = (raw[:start] + after + raw[start + len(before):]).decode()
    return {"schema": "eapg-synthetic-intervention-v1", "original": original, "edited": edited,
            "restored": original, "source_sha256": {"original": sha(original), "edited": sha(edited),
                                                     "restored": sha(original)},
            "edit": {"start_byte": start, "removed": removed, "inserted": inserted},
            "equivalent_edited_intervals": list(alternatives)}


class InterventionTest(unittest.TestCase):
    pipeline = None
    _tempdir = None

    @classmethod
    def setUpClass(cls):
        if cls.pipeline is None:
            cls._tempdir = TemporaryDirectory(prefix="eapg-interv-test-")
            prosp = Path(cls._tempdir.name) / "prospective.py"
            digest = build_candidate(prosp, prospective=True)
            if digest != PROSPECTIVE_SHA:
                raise RuntimeError(f"Unexpected prospective candidate SHA-256: {digest}")
            cls.pipeline = load_pipeline(prosp)

    @classmethod
    def tearDownClass(cls):
        if cls._tempdir is not None:
            cls._tempdir.cleanup()
            cls._tempdir = None

    @unittest.skipUnless(HAS_GATE1_SANDBOX, "Requires Linux systemd --user + Bubblewrap Gate 1 sandbox")
    def test_changed_byte_resolves_inside_braceless_statement(self):
        source = r'''#include <cstdio>
int main() {
    int result = 0;
    // λ repeated literals appear on both paths
    if (result == 0)
        result = 11 + 11;
    result = 11 + 11;
    std::printf("%d\n", result);
}
'''.replace("\n", "\r\n")
        prefix = b"result = 11 + "
        start = source.encode().index(prefix) + len(prefix)
        record = intervention(source, "1", "2", at=start, alternatives=([start - 1, start + 2],))
        reference = resolve_intervention(self.pipeline, record)
        self.assertEqual(reference["reference_status"], "resolved")
        self.assertEqual(len(reference["token_origins"]), 1)
        token = reference["token_origins"][0]
        self.assertEqual(token["raw"], [start, start + 2])
        normalized, aliases = normalize(self.pipeline, record["edited"])
        self.assertEqual(reference["normalized_source_sha256"], sha(normalized))
        self.assertEqual([row["node_id"] for row in reference["canonical_nodes"]],
                         [node["id"] for node in self.pipeline.extract_macro_nodes(normalized, aliases)])
        owner, = [row for row in reference["canonical_nodes"] if row["node_id"] in reference["accepted_node_ids"]]
        self.assertEqual(owner["role"], "STATE_UPD")
        self.assertEqual(normalized.encode()[slice(*owner["span"])], b"result = 11 + 21;")
        self.assertEqual(normalized.encode()[slice(*token["normalized"])], b"21")

    def test_rejects_forged_inverse_even_with_matching_digest(self):
        record = intervention("int main() { return 10; }", "10", "15")
        record["restored"] = record["edited"]
        record["source_sha256"]["restored"] = sha(record["restored"])
        with self.assertRaisesRegex(ValueError, "Inverse splice"):
            verify_splice(record)

    def test_rejects_source_digest_mismatch(self):
        record = intervention("int main() { return 10; }", "10", "15")
        record["source_sha256"]["edited"] = record["source_sha256"]["original"]
        with self.assertRaisesRegex(ValueError, "source digest mismatch"):
            verify_splice(record)

    @unittest.skipUnless(HAS_GATE1_SANDBOX, "Requires Linux systemd --user + Bubblewrap Gate 1 sandbox")
    def test_rejects_two_sibling_statements_in_one_splice(self):
        source = "int main() { int x = 1; x = 10; x += 11; return x; }"
        record = intervention(source, "10; x += 11", "15; x += 16")
        with self.assertRaisesRegex(ValueError, "one expression or statement"):
            resolve_intervention(self.pipeline, record)

    @unittest.skipUnless(HAS_GATE1_SANDBOX, "Requires Linux systemd --user + Bubblewrap Gate 1 sandbox")
    def test_rejects_equivalent_span_of_a_different_token(self):
        record = intervention("int main() { int x = 10; return x + 25; }", "10", "15")
        start = record["edited"].encode().index(b"25")
        record["equivalent_edited_intervals"] = [[start, start + 2]]
        with self.assertRaisesRegex(ValueError, "different tokens"):
            resolve_intervention(self.pipeline, record)

    @unittest.skipUnless(HAS_GATE1_SANDBOX, "Requires Linux systemd --user + Bubblewrap Gate 1 sandbox")
    def test_macro_directive_retains_nodes_for_unresolved_reference(self):
        source = "#define NUMBER 10\nint main() { int x = NUMBER; return x; }"
        record = intervention(source, "NUMBER", "NUMBER + 5", at=source.encode().rindex(b"NUMBER"))
        result = resolve_intervention(self.pipeline, record)
        self.assertEqual(result["reference_reason"], "unsupported_preprocessor_directive")
        self.assertEqual(result["accepted_node_ids"], [])
        self.assertTrue(result["canonical_nodes"])
        self.assertTrue(result["normalized_source_sha256"])

    @unittest.skipUnless(HAS_GATE1_SANDBOX, "Requires Linux systemd --user + Bubblewrap Gate 1 sandbox")
    def test_directive_change_is_not_a_single_code_statement_edit(self):
        source = "#define NUMBER 10\nint main() { int x = NUMBER; return x; }"
        record = intervention(source, "10", "15")
        with self.assertRaisesRegex(ValueError, "one expression or statement"):
            resolve_intervention(self.pipeline, record)

    @unittest.skipUnless(HAS_GATE1_SANDBOX, "Requires Linux systemd --user + Bubblewrap Gate 1 sandbox")
    def test_builtin_expansion_yields_nonconserving_origin(self):
        source = "int main() { int x = 10; return x + __LINE__; }"
        record = intervention(source, "10", "15")
        result = resolve_intervention(self.pipeline, record)
        self.assertEqual(result["reference_reason"], "pass_zero_changed_token_stream")
        self.assertEqual(result["accepted_node_ids"], [])

    @unittest.skipUnless(HAS_GATE1_SANDBOX, "Requires Linux systemd --user + Bubblewrap Gate 1 sandbox")
    def test_equal_canonical_owners_remain_unresolved(self):
        source = "int main() { int x = 0; x = 10; return x; }"
        record = intervention(source, "10", "15")
        extract = self.pipeline.extract_macro_nodes

        def ambiguous(*args):
            nodes = extract(*args)
            state, = [node for node in nodes if node["source_preview"] == "x = 15;"]
            return [*nodes, dict(state, id=f"N{len(nodes) + 1}")]

        with patch.object(self.pipeline, "extract_macro_nodes", ambiguous):
            result = resolve_intervention(self.pipeline, record)
        self.assertEqual(result["reference_reason"], "ambiguous_canonical_owner")
        self.assertEqual(result["accepted_node_ids"], [])


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--pipeline", type=Path, default=None)
    cli.add_argument("--skip-exit-code", type=int, choices=range(3, 126), metavar="CODE",
                     help="Exit with CODE if tests succeed but some were skipped.")
    args, remaining = cli.parse_known_args()
    if args.pipeline is not None:
        InterventionTest.pipeline = load_pipeline(args.pipeline.resolve())
    result = unittest.main(argv=[sys.argv[0], *remaining], exit=args.skip_exit_code is None).result
    if not result.wasSuccessful():
        raise SystemExit(1)
    if result.skipped:
        raise SystemExit(args.skip_exit_code)
