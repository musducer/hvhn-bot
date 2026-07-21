import unittest

from cogs.doc_storage import _safe_pdf_filename, _safe_person_name


class DocumentStorageSecurityTest(unittest.TestCase):
    def test_customer_names_cannot_break_tab_delimited_jobs_or_spreadsheets(self):
        self.assertEqual(_safe_person_name("  Nguyen Van An  "), "Nguyen Van An")
        self.assertIsNone(_safe_person_name("An\tadmin@example.com"))
        self.assertIsNone(_safe_person_name("=IMPORTXML(A1)"))

    def test_uploaded_pdf_names_are_normalized_before_they_enter_the_job_queue(self):
        self.assertEqual(_safe_pdf_filename(r"..\\unsafe<>name.pdf"), "unsafe_name.pdf")
        self.assertEqual(_safe_pdf_filename("   "), "tai_lieu.pdf")


if __name__ == "__main__":
    unittest.main()
