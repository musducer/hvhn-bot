import unittest

from cogs.ai import AI, GEMINI_MODELS


class AiTimeoutTest(unittest.TestCase):
    def test_timeout_fallback_mentions_timeout_and_evidence(self):
        meta = {
            "chunks": [
                {
                    "title": "tai_lieu.pdf",
                    "chunk_index": 2,
                    "excerpt": "Chi tiet nghe thuat lien quan.",
                }
            ]
        }
        answer = AI._timeout_fallback_answer(meta, "", "", 105)
        self.assertIn("quá thời gian", answer)
        self.assertIn("105", answer)
        self.assertIn("tai_lieu.pdf", answer)

    def test_gemini_20_flash_is_skipped_by_default(self):
        self.assertNotIn("gemini-2.0-flash", GEMINI_MODELS)
        self.assertTrue(GEMINI_MODELS)


if __name__ == "__main__":
    unittest.main()
