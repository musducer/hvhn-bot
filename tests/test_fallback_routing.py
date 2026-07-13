# -*- coding: utf-8 -*-
import os
import unittest

os.environ.setdefault("GROQ_API_KEYS", "x")

from cogs.ai import AI


class FallbackRoutingTest(unittest.TestCase):
    def _meta(self):
        return {
            "chunks": [
                {
                    "title": "nguon_lac.pdf",
                    "chunk_index": 0,
                    "excerpt": "Một đoạn evidence ngắn.",
                    "content": "Một đoạn evidence ngắn.",
                }
            ]
        }

    def test_practical_hat_ru_question_uses_three_bullets_not_literary_fallback(self):
        q = (
            "Trình bày những cách để bảo tồn, phát huy nghệ thuật hát ru trong đời sống hiện đại. "
            "Trình bày 3 ý, thành gạch đầu dòng. Mỗi ý giải thích ngắn gọn."
        )
        answer = AI._evidence_fallback_answer(self._meta(), "", "", q, "literature")

        self.assertFalse(AI._is_literary_answer_request(q, "literature"))
        self.assertEqual(answer.count("\n- "), 2)
        self.assertTrue(answer.startswith("- "))
        self.assertIn("hát ru", answer)
        self.assertNotIn("phong cách thơ", answer)
        self.assertNotIn("Dựa trên các đoạn tài liệu", answer)

    def test_argumentative_composition_question_does_not_become_poetry_style(self):
        q = (
            "Luận điểm và sử dụng lí luận văn học như nào, viết phần bình luận sao cho hay, "
            "độc đáo, là 1hsgqg về đề: chúng ta có nghệ thuật để không chết vì sự thật, "
            "đồng thời tìm luận cứ luận chứng để phân tích chứng minh, từ ca dao đến văn học "
            "trung đại, hiện đại, và vươn ra thế giới với nhiều tác phẩm, thể loại khác"
        )
        answer = AI._evidence_fallback_answer(self._meta(), "", "", q, "literature")

        self.assertFalse(AI._is_literary_answer_request(q, "literature"))
        self.assertEqual(AI._query_subjects(q, None), [])
        self.assertIn("Luận điểm 1", answer)
        self.assertIn("Truyện Kiều", answer)
        self.assertIn("Ông già và biển cả", answer)
        self.assertNotIn("phong cách thơ", answer)
        self.assertNotIn("Luận Điểm", answer)

    def test_short_list_question_detection_is_kept_for_answer_planning(self):
        q = "Trình bày 3 ý thành gạch đầu dòng."
        self.assertTrue(AI._wants_brief_list_answer(q))


if __name__ == "__main__":
    unittest.main()
