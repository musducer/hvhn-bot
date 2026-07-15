import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ConsoleEncodingTests(unittest.TestCase):
    def test_pipeline_output_survives_legacy_windows_encoding(self):
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "cp1252"
        env.pop("PYTHONUTF8", None)
        result = subprocess.run(
            [sys.executable, "-c", "import hvhn_batch; print('Đã xử lý tài liệu')"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertIn("Đã xử lý tài liệu", result.stdout.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
