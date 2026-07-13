import unittest

from cogs.ai import AI, GEMINI_MODELS


class AiTimeoutTest(unittest.TestCase):
    def test_answer_pipeline_has_no_arbitrary_response_timeout(self):
        source = __import__("inspect").getsource(AI._then_answer)
        self.assertNotIn("wait_for(", source)
        self.assertNotIn("_timeout_fallback_answer", source)

    def test_gemini_20_flash_is_skipped_by_default(self):
        self.assertNotIn("gemini-2.0-flash", GEMINI_MODELS)
        self.assertTrue(GEMINI_MODELS)


if __name__ == "__main__":
    unittest.main()
