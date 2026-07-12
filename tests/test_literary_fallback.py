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


if __name__ == "__main__":
    unittest.main()
