"""Run a unittest script and give successful runs with skips a distinct status."""

from pathlib import Path
from runpy import run_path
import sys
import unittest


SKIPPED = 3


def main():
    script = Path(sys.argv[1]).resolve()
    sys.argv = [str(script), *sys.argv[2:]]
    sys.path[0] = str(script.parent)
    unittest_main = unittest.main

    def report(*args, **kwargs):
        result = unittest_main(*args, **{**kwargs, "exit": False}).result
        for reason in sorted({reason for _, reason in result.skipped}):
            print(f"SKIPPED: {script.name}: {reason}", file=sys.stderr)
        if not result.wasSuccessful():
            raise SystemExit(1)
        if result.skipped:
            raise SystemExit(SKIPPED)
        raise SystemExit(0 if result.testsRun else 5)

    unittest.main = report
    run_path(str(script), run_name="__main__")


if __name__ == "__main__":
    main()
