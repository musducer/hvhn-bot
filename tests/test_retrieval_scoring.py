import unittest

from pdf_knowledge import _query_features, _score_pdf_text


class RetrievalScoringTest(unittest.TestCase):
    def test_phrase_match_beats_common_literature_words(self):
        query = "con người bị tha hóa"
        good = _score_pdf_text(
            query,
            "Bai hoc ve con nguoi bi tha hoa",
            "Khái niệm con người bị tha hóa chỉ trạng thái nhân cách bị biến dạng bởi hoàn cảnh.",
            0,
        )
        bad = _score_pdf_text(
            query,
            "Lao Hac va van hoc hien thuc",
            "Con người trong văn học thường được nhìn qua số phận, phẩm chất và tình thương.",
            10,
        )
        self.assertIn("tha hoa", good["matched_phrases"])
        self.assertGreater(good["score"], bad["score"])

    def test_stopwords_do_not_create_false_hit(self):
        features = _query_features("theo tài liệu đã nạp, khái niệm con người bị tha hóa là gì?")
        self.assertIn("tha", features["terms"])
        self.assertIn("hoa", features["terms"])
        self.assertNotIn("theo", features["terms"])
        self.assertNotIn("lieu", features["terms"])


if __name__ == "__main__":
    unittest.main()
