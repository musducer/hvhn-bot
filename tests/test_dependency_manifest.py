from inspect import signature
from pathlib import Path
import unittest

from encrypt_pdf import encrypt_pdf


class DependencyManifestTest(unittest.TestCase):
    def test_secure_pdf_dependencies_are_declared_for_fresh_watcher_installs(self):
        requirements = Path("requirements.txt").read_text(encoding="utf-8")
        self.assertIn("img2pdf==", requirements)
        self.assertIn("pikepdf==", requirements)

    def test_standalone_encryptor_has_no_predictable_owner_password(self):
        self.assertIsNone(signature(encrypt_pdf).parameters["owner_password"].default)


if __name__ == "__main__":
    unittest.main()
