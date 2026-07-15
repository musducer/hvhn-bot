# -*- coding: utf-8 -*-
import os
import unittest

os.environ.setdefault("GROQ_API_KEYS", "x")

from cogs.ai import AI, Planner


class LiteraryFallbackTest(unittest.TestCase):
    def _mixed_meta(self):
        return {
            "context": "",
            "selected_count": 3,
            "candidate_count": 3,
            "top_score": 1.0,
            "chunks": [
                {
                    "title": "1.2 Những biểu hiện của cái tôi",
                    "doc_title": "Tài liệu lạc",
                    "author": "",
                    "chunk_index": 1,
                    "excerpt": "Trong thơ Nôm Nguyễn Trãi, ta bắt gặp một con người có ý thức cao. Nguyễn Bỉnh Khiêm hay nói đến chữ nhàn.",
                    "content": "Trong thơ Nôm Nguyễn Trãi, ta bắt gặp một con người có ý thức cao. Nguyễn Bỉnh Khiêm hay nói đến chữ nhàn.",
                },
                {
                    "title": "Nguyễn Bính và hồn quê",
                    "doc_title": "Ba đỉnh cao Thơ mới",
                    "author": "",
                    "chunk_index": 2,
                    "excerpt": (
                        "Nghiên cứu Nguyễn Bính tôi thấy thơ ông nổi lên hai giọng điệu trữ tình: than thở và đùa ghẹo. "
                        "Cả hai đều có ngọn nguồn từ ca dao dân ca. Ta vẫn thấy điều hơn người ở Nguyễn Bính là Hồn quê."
                    ),
                    "content": (
                        "Nghiên cứu Nguyễn Bính tôi thấy thơ ông nổi lên hai giọng điệu trữ tình: than thở và đùa ghẹo. "
                        "Cả hai đều có ngọn nguồn từ ca dao dân ca. Ta vẫn thấy điều hơn người ở Nguyễn Bính là Hồn quê."
                    ),
                },
                {
                    "title": "4.6 Đề 6",
                    "doc_title": "Đề lạc",
                    "author": "",
                    "chunk_index": 3,
                    "excerpt": "Bài viết bàn rộng về quy luật sáng tạo của văn chương và thơ ca nói chung.",
                    "content": "Bài viết bàn rộng về quy luật sáng tạo của văn chương và thơ ca nói chung.",
                },
            ],
        }

    def test_subject_filter_keeps_only_requested_author_chunks(self):
        q = "Phân tích phong cách thơ Nguyễn Bính"
        filtered = AI._filter_pdf_meta_to_subject(q, Planner.build(q), self._mixed_meta())
        self.assertEqual(len(filtered["chunks"]), 1)
        self.assertIn("Nguyễn Bính", filtered["chunks"][0]["excerpt"])
        self.assertNotIn("Nguyễn Trãi", filtered["context"])
        self.assertNotIn("Nguyễn Bỉnh Khiêm", filtered["context"])

    def test_literary_fallback_is_not_raw_evidence_dump(self):
        q = "Phân tích phong cách thơ Nguyễn Bính"
        answer = AI._evidence_fallback_answer(self._mixed_meta(), "", "", q, "literature")
        self.assertIn("Nguyễn Bính", answer)
        self.assertIn("chất quê", answer)
        self.assertIn("Giọng thơ", answer)
        self.assertNotIn("Dựa trên các đoạn tài liệu đã truy xuất", answer)
        self.assertNotIn("(đoạn 1)", answer)
        self.assertNotIn("Nguyễn Trãi", answer)
        self.assertNotIn("Nguyễn Bỉnh Khiêm", answer)


class TopicAnchorGroundingTest(unittest.TestCase):
    def _meta(self, *chunks, quotes=None):
        return {
            "context": "",
            "selected_count": len(chunks),
            "candidate_count": len(chunks),
            "top_score": 9.0,
            "chunks": list(chunks),
            "quotes": list(quotes or []),
        }

    def test_existentialism_question_rejects_story_that_only_matches_generic_words(self):
        query = "Trình bày hiểu biết về phong trào văn học hiện sinh"
        wrong_story = {
            "title": "Hoa Champoon",
            "doc_title": "Chuyện ở Taimuang",
            "content": "Người kể học ở Penang rồi làm giám sát lao động. Champoon là con gái Đại ca.",
            "excerpt": "Người kể học ở Penang rồi làm giám sát lao động.",
        }
        wrong_quote = {
            "title": "Hoa Champoon",
            "author": "Không rõ",
            "quote": "Người kể trở về Pa-nga sau thời gian học tập.",
        }
        filtered = AI._filter_pdf_meta_to_topic(query, self._meta(wrong_story, quotes=[wrong_quote]))
        self.assertEqual(AI._query_topic_anchors(query), ["hien sinh"])
        self.assertEqual(filtered["chunks"], [])
        self.assertEqual(filtered["quotes"], [])
        self.assertEqual(filtered["context"], "")

    def test_existentialism_question_keeps_actual_topic_evidence(self):
        query = "Trình bày hiểu biết về phong trào văn học hiện sinh"
        relevant = {
            "title": "Văn học hiện sinh",
            "doc_title": "Chủ nghĩa hiện sinh",
            "content": "Văn học hiện sinh tập trung vào tự do, lựa chọn, cô đơn và phi lý.",
            "excerpt": "Văn học hiện sinh tập trung vào tự do và lựa chọn.",
        }
        filtered = AI._filter_pdf_meta_to_topic(query, self._meta(relevant))
        self.assertEqual(filtered["chunks"], [relevant])

    def test_topic_filter_also_handles_quote_only_retrieval(self):
        query = "Trình bày hiểu biết về phong trào văn học hiện sinh"
        relevant_quote = {
            "title": "Nhận định về văn học hiện sinh",
            "author": "Jean-Paul Sartre",
            "quote": "Con người phải tự chịu trách nhiệm về lựa chọn của mình.",
        }
        wrong_quote = {
            "title": "Hoa Champoon",
            "author": "Không rõ",
            "quote": "Người kể làm việc tại một công ty khai khoáng.",
        }
        filtered = AI._filter_pdf_meta_to_topic(
            query,
            self._meta(quotes=[wrong_quote, relevant_quote]),
        )
        self.assertEqual(filtered["quotes"], [relevant_quote])

    def test_generic_request_wording_does_not_become_a_topic_anchor(self):
        self.assertEqual(
            AI._query_topic_anchors("Trích dẫn quan niệm của Sartre về văn học"),
            [],
        )

    def test_final_answer_gate_rejects_the_original_off_topic_story(self):
        query = "Trình bày hiểu biết về phong trào văn học hiện sinh"
        wrong = "Người kể làm việc ở mỏ rồi yêu Champoon, con gái của Đại ca."
        right = "Văn học hiện sinh đặt con người trước tự do, lựa chọn và trách nhiệm."
        self.assertFalse(AI._answer_matches_topic(query, wrong))
        self.assertTrue(AI._answer_matches_topic(query, right))

    def test_librarian_dump_detector_catches_report_shape_from_regression(self):
        raw = (
            "**Bản rút gọn nội dung (ưu tiên tài liệu liên quan nhất)**\n\n"
            "**Thiếu dữ liệu**\nKhông có thông tin chính xác.\n\n"
            "**Kết luận**: Văn bản hiện tại cung cấp một câu chuyện phức tạp."
        )
        self.assertTrue(AI._looks_like_librarian_dump(raw))


class LibrarianDumpRecoveryTest(unittest.IsolatedAsyncioTestCase):
    async def test_safe_generate_never_returns_librarian_dump_when_repair_fails(self):
        raw_dump = (
            "Bản rút gọn nội dung (ưu tiên tài liệu liên quan nhất)\n"
            "Thiếu dữ liệu\nKết luận: một câu chuyện không liên quan."
        )
        direct_answer = "Văn học hiện sinh thường tập trung vào tự do lựa chọn, sự cô đơn và cảm thức phi lý của con người."
        ai = object.__new__(AI)
        replies = iter([raw_dump, raw_dump, direct_answer, direct_answer])

        async def fake_generate(*args, **kwargs):
            return next(replies)

        ai.generate = fake_generate
        answer, _ = await ai._safe_generate(
            "Trả lời câu hỏi: Trình bày hiểu biết về phong trào văn học hiện sinh",
            "",
            "",
            "general_safe",
        )

        self.assertEqual(answer, direct_answer)
        self.assertFalse(AI._looks_like_librarian_dump(answer))
        self.assertNotIn("câu chuyện không liên quan", answer)


if __name__ == "__main__":
    unittest.main()
