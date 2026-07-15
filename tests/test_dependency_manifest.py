from inspect import signature
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import encrypt_pdf as encrypt_pdf_module
from encrypt_pdf import encrypt_pdf


class DependencyManifestTest(unittest.TestCase):
    def test_secure_pdf_dependencies_are_declared_for_fresh_watcher_installs(self):
        requirements = Path("requirements.txt").read_text(encoding="utf-8")
        self.assertIn("img2pdf==", requirements)
        self.assertIn("pikepdf==", requirements)

    def test_standalone_encryptor_has_no_predictable_owner_password(self):
        self.assertIsNone(signature(encrypt_pdf).parameters["owner_password"].default)

    def test_standalone_encryptor_publishes_atomically(self):
        class BrokenPdf:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def save(self, path, **_kwargs):
                Path(path).write_bytes(b"partial")
                raise RuntimeError("save failed")

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "secure.pdf"
            output.write_bytes(b"complete-old-file")
            with patch.object(encrypt_pdf_module.pikepdf, "open", return_value=BrokenPdf()):
                with self.assertRaisesRegex(RuntimeError, "save failed"):
                    encrypt_pdf("input.pdf", str(output))
            self.assertEqual(output.read_bytes(), b"complete-old-file")
            self.assertEqual(list(Path(temp_dir).glob("*.part.pdf")), [])


if __name__ == "__main__":
    unittest.main()
