import csv
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fitz

import hvhn_batch
from cogs.doc_storage import _safe_doc_base
from combined_pipeline import convert_to_secure_image_pdf


class AtomicPublicationTest(unittest.TestCase):
    def test_client_registry_updates_atomically_and_normalizes_email(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            clients_path = Path(temp_dir) / "clients.csv"
            clients_path.write_text("name,email\n", encoding="utf-8")
            with patch.object(hvhn_batch, "CLIENTS_CSV", str(clients_path)):
                hvhn_batch.append_client("  An  ", "An@Example.com")
                self.assertEqual(
                    hvhn_batch.load_clients(),
                    [{"name": "An", "email": "an@example.com"}],
                )
                with self.assertRaises(hvhn_batch.DuplicateClientEmailError):
                    hvhn_batch.append_client("An khac", "an@example.com")
                self.assertTrue(hvhn_batch.remove_client("AN@example.com"))
                self.assertEqual(hvhn_batch.load_clients(), [])
            self.assertEqual(list(Path(temp_dir).glob("*.part.csv")), [])

    def test_client_name_cannot_escape_output_or_break_sheet_names(self):
        self.assertEqual(hvhn_batch.normalize_client_name(r"../A/B:[test]*"), "A_B_test")
        self.assertEqual(hvhn_batch.normalize_client_name("=IMPORTXML"), "_=IMPORTXML")
        self.assertEqual(hvhn_batch.normalize_client_name("CON"), "_CON")
        self.assertEqual(hvhn_batch.normalize_client_name("CON.txt"), "_CON.txt")
        self.assertEqual(hvhn_batch.normalize_client_name("Dashboard"), "_Dashboard")
        self.assertEqual(hvhn_batch.normalize_client_name("Khách hàng"), "_Khách hàng")

    def test_fresh_install_without_registry_or_docs_is_empty(self):
        with tempfile.TemporaryDirectory() as temp_dir, \
                patch.object(hvhn_batch, "CLIENTS_CSV", str(Path(temp_dir) / "missing.csv")), \
                patch.object(hvhn_batch, "DOCS_DIR", str(Path(temp_dir) / "missing-docs")):
            self.assertEqual(hvhn_batch.load_clients(), [])
            self.assertEqual(hvhn_batch.list_docs(), [])

    def test_document_deletion_is_confined_to_the_document_store(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "docs"
            root.mkdir()
            document = root / "lesson.pdf"
            outside = Path(temp_dir) / "outside.pdf"
            document.write_bytes(b"inside")
            outside.write_bytes(b"outside")

            with patch.object(hvhn_batch, "DOCS_DIR", str(root)):
                for unsafe in ("../outside", r"..\outside", "/outside", "C:\\outside", ".."):
                    with self.subTest(unsafe=unsafe), self.assertRaises(ValueError):
                        hvhn_batch.remove_doc(unsafe)
                self.assertTrue(hvhn_batch.remove_doc("lesson.pdf"))

            self.assertFalse(document.exists())
            self.assertEqual(outside.read_bytes(), b"outside")

    def test_discord_document_name_uses_the_same_path_boundary(self):
        self.assertEqual(_safe_doc_base("Bài học.pdf"), "Bài học")
        for unsafe in ("../secret", r"..\secret", "/secret", "C:\\secret", "..", ""):
            with self.subTest(unsafe=unsafe):
                self.assertIsNone(_safe_doc_base(unsafe))

    def test_invalid_legacy_registry_row_is_reported(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            clients_path = Path(temp_dir) / "clients.csv"
            clients_path.write_text("name,email\nCON,not-an-email\n", encoding="utf-8")
            with patch.object(hvhn_batch, "CLIENTS_CSV", str(clients_path)):
                with self.assertRaisesRegex(ValueError, "dòng 2"):
                    hvhn_batch.load_clients()

    def test_each_default_csv_is_unique_and_fully_published(self):
        rows = [("An", "an@example.com", "An__doc.pdf")]
        with tempfile.TemporaryDirectory() as temp_dir, \
                patch.object(hvhn_batch, "out_root", return_value=temp_dir), \
                patch.object(hvhn_batch, "mirror_ready", return_value=False):
            first = Path(hvhn_batch.write_new_rows_csv(rows))
            second = Path(hvhn_batch.write_new_rows_csv(rows))

            self.assertNotEqual(first.name, second.name)
            self.assertTrue(first.name.startswith("new_rows_"))
            self.assertTrue(second.is_file())
            with first.open(encoding="utf-8", newline="") as handle:
                self.assertEqual(
                    list(csv.reader(handle)),
                    [["TenNguoiNhan", "Email", "TenFile"], list(rows[0])],
                )
            self.assertEqual(list(Path(temp_dir).glob("*.part")), [])

    def test_failed_pdf_save_never_replaces_the_previous_complete_output(self):
        class BrokenPdf:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def save(self, path, **_kwargs):
                Path(path).write_bytes(b"partial")
                raise RuntimeError("simulated disk failure")

        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "source.pdf"
            output_path = Path(temp_dir) / "output.pdf"
            source = fitz.open()
            source.new_page(width=300, height=400)
            source.save(source_path)
            source.close()
            output_path.write_bytes(b"previous-complete-output")

            with patch("combined_pipeline.pikepdf.open", return_value=BrokenPdf()):
                with self.assertRaisesRegex(RuntimeError, "simulated disk failure"):
                    convert_to_secure_image_pdf(
                        str(source_path), str(output_path), "An", "an@example.com", "HVHN", dpi=72,
                    )

            self.assertEqual(output_path.read_bytes(), b"previous-complete-output")
            self.assertEqual(list(Path(temp_dir).glob("*.part.pdf")), [])


if __name__ == "__main__":
    unittest.main()
