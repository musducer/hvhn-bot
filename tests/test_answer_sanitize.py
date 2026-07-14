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

    def test_outline_contract_rejects_retrieval_summary(self):
        raw = (
            "Tóm tắt ngắn gọn nội dung & yêu cầu (ưu tiên tài liệu / manual liên quan nhất)\n"
            "Các trích dẫn đã được cung cấp\n"
            "Thiếu dữ liệu / cần làm rõ"
        )
        self.assertTrue(AI._violates_outline_contract(raw))

    def test_outline_contract_accepts_actual_outline(self):
        raw = (
            "# Dàn ý chi tiết\nI. Mở bài\n- Nêu vấn đề.\n\n"
            "II. Thân bài\n1. Giải thích\n2. Bàn luận\n3. Phản đề\n\n"
            "III. Kết bài\n- Khẳng định lại vấn đề.\n\n💡 Kho chất liệu"
        )
        self.assertFalse(AI._violates_outline_contract(raw))


if __name__ == "__main__":
    unittest.main()
