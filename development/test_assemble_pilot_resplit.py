"""Exercise packaging and rejection through the CLI without a GPU or trained adapters."""

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from assemble_pilot_resplit import ROOT, json_bytes
from train_phase2_adapter import digest_json


class AssemblePilotResplitTest(unittest.TestCase):
    def test_complete_run_and_rejections(self):
        archived = ROOT / "artifacts/pilot_resplit/results.json"
        report = json.loads(archived.read_bytes())
        with TemporaryDirectory() as temporary:
            run = Path(temporary)
            (run / "split_manifest.json").write_bytes(json_bytes(report["split"]))
            summary = {key: report[key] for key in ("split_sha256", "scores")}
            (run / "results.json").write_bytes(json_bytes(summary))
            for fold in report["folds"]:
                index = fold["fold"]
                directory = run / f"fold-{index}"
                adapter = directory / "adapter"
                adapter.mkdir(parents=True)
                files = {}
                for name in ("adapter_config.json", "adapter_model.safetensors"):
                    data = f"Fixture {index} {name}".encode()
                    (adapter / name).write_bytes(data)
                    files[name] = sha256(data).hexdigest()
                fold.update(adapter_files=files, adapter_manifest_sha256=digest_json(files))
                (directory / "provenance.json").write_bytes(json_bytes(fold))
                held_out = {pid: pred for pid, pred in report["predictions"].items() if pred["fold"] == index}
                (directory / "predictions.json").write_bytes(json_bytes(held_out))

            command = [sys.executable, "-B", str(ROOT / "development/assemble_pilot_resplit.py"), str(run)]
            output = run / "assembled.json"
            subprocess.run([*command, str(output)], check=True)
            expected = (json.dumps(report, indent=2, allow_nan=False) + "\n").encode()
            self.assertEqual(output.read_bytes(), expected)
            rejected = subprocess.run([*command, str(output)], capture_output=True, text=True)
            self.assertIn("Output already exists", rejected.stderr)
            self.assertEqual(rejected.returncode, 1)
            self.assertEqual(output.read_bytes(), expected)

            output.unlink()
            fold = report["folds"][4]
            provenance = run / "fold-4/provenance.json"
            provenance.write_bytes(json_bytes(dict(fold, split_sha256="bad split")))
            rejected = subprocess.run([*command, str(output)], capture_output=True, text=True)
            self.assertIn("different split", rejected.stderr)
            self.assertEqual(rejected.returncode, 1)
            self.assertFalse(output.exists())

            provenance.write_bytes(json_bytes(fold))
            (run / "fold-4/predictions.json").unlink()
            rejected = subprocess.run([*command, str(output)], capture_output=True, text=True)
            self.assertIn("predictions.json", rejected.stderr)
            self.assertEqual(rejected.returncode, 1)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
