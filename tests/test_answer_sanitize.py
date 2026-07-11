# -*- coding: utf-8 -*-
import os
import unittest

os.environ.setdefault("GROQ_API_KEYS", "x")
from cogs.ai import AI


class StripMetaTest(unittest.TestCase):
    def test_removes_leading_and_trailing_meta(self):
        raw = (
            "Câu trả lời của bạn đã khá tốt, nhưng có thể cải thiện. Dưới đây là một phiên bản sửa đổi:\n"
            "A. Camus cho rằng văn nghệ phải dấn thân.\n"
            "Tôi đã giữ nguyên phần lớn nội dung nhưng thêm phân tích."
        )
        out = AI._strip_internal_markers(raw)
        self.assertIn("A. Camus cho rằng", out)
        self.assertNotIn("phiên bản sửa đổi", out)
        self.assertNotIn("Tôi đã giữ nguyên", out)

    def test_keeps_normal_answer(self):
        raw = "A. Camus là nhà văn hiện sinh. Ông cho rằng cuộc đời phi lý."
        self.assertEqual(AI._strip_internal_markers(raw), raw)

    def test_still_strips_internal_source_markers(self):
        raw = "Nhận định [P1] của Nam Cao. URL: https://x.com/abc"
        out = AI._strip_internal_markers(raw)
        self.assertNotIn("[P1]", out)
        self.assertNotIn("http", out)


if __name__ == "__main__":
    unittest.main()
