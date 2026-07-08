import unittest

from cogs.ai import AI


class DocumentGroundingTest(unittest.TestCase):
    def test_quote_mode_extracts_verbatim_from_pdf_chunk(self):
        query = "H\u00e3y ch\u00e9p nguy\u00ean v\u0103n nh\u1eadn \u0111\u1ecbnh c\u1ee7a L\u00ea \u0110\u1ea1t"
        profile = AI._request_profile(query)
        meta = {
            "chunks": [
                {
                    "title": "nhan_dinh.pdf",
                    "chunk_index": 3,
                    "content": "L\u00ea \u0110\u1ea1t vi\u1ebft: \u201cM\u1ed7i c\u00f4ng d\u00e2n c\u00f3 m\u1ed9t d\u1ea1ng v\u00e2n tay. M\u1ed7i ng\u01b0\u1eddi ngh\u1ec7 s\u0129 th\u1ee9 thi\u1ec7t c\u00f3 m\u1ed9t d\u1ea1ng v\u00e2n ch\u1eef.\u201d Ph\u1ea7n sau b\u00e0n th\u00eam.",
                }
            ]
        }
        answer = AI._deterministic_document_answer(query, meta, profile)
        self.assertIn("M\u1ed7i c\u00f4ng d\u00e2n c\u00f3 m\u1ed9t d\u1ea1ng v\u00e2n tay", answer)
        self.assertIn("nhan_dinh.pdf", answer)

    def test_aggregate_mode_keeps_multiple_document_quotes(self):
        query = "H\u00e3y t\u1ed5ng h\u1ee3p m\u1ecdi nh\u1eadn \u0111\u1ecbnh v\u1ec1 ch\u1ee9c n\u0103ng c\u1ee7a v\u0103n ch\u01b0\u01a1ng"
        profile = AI._request_profile(query)
        meta = {
            "chunks": [
                {"title": "a.pdf", "chunk_index": 1, "content": "Th\u1ea1ch Lam cho r\u1eb1ng: \u201cV\u0103n ch\u01b0\u01a1ng l\u00e0 m\u1ed9t th\u1ee9 kh\u00ed gi\u1edbi thanh cao v\u00e0 \u0111\u1eafc l\u1ef1c.\u201d"},
                {"title": "b.pdf", "chunk_index": 2, "content": "M\u1ed9t nh\u1eadn \u0111\u1ecbnh kh\u00e1c vi\u1ebft: \u201cV\u0103n h\u1ecdc gi\u00fap con ng\u01b0\u1eddi hi\u1ec3u m\u00ecnh v\u00e0 hi\u1ec3u \u0111\u1eddi s\u1ed1ng.\u201d"},
            ]
        }
        answer = AI._deterministic_document_answer(query, meta, profile)
        self.assertIn("V\u0103n ch\u01b0\u01a1ng l\u00e0 m\u1ed9t th\u1ee9 kh\u00ed gi\u1edbi", answer)
        self.assertIn("V\u0103n h\u1ecdc gi\u00fap con ng\u01b0\u1eddi", answer)


if __name__ == "__main__":
    unittest.main()
