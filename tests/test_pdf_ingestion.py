import unittest

import fitz

from pdf_knowledge import build_chunks, extract_pdf_text_from_bytes


class PdfIngestionTest(unittest.TestCase):
    def test_extract_native_pdf_text_and_chunk(self):
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Khái niệm con người bị tha hóa xuất hiện trong tài liệu thử nghiệm.")
        data = doc.tobytes()
        doc.close()

        text = extract_pdf_text_from_bytes(data)
        self.assertIn("tha hóa", text)
        chunks = build_chunks(text)
        self.assertTrue(chunks)


if __name__ == "__main__":
    unittest.main()
