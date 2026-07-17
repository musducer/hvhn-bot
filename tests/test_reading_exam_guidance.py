import inspect
import re
import unittest
from pathlib import Path

from cogs import ai


class ReadingExamGuidanceTest(unittest.TestCase):
    def test_dgnl_query_adds_hsa_aliases_for_knowledge_retrieval(self):
        query = "Giải câu ĐGNL này và chọn đáp án đúng nhất"
        enriched = ai.ReadingExamGuidance.retrieval_query(query)

        self.assertIn(query, enriched)
        self.assertIn("HSA", enriched)
        self.assertIn("DGNL", enriched)
        self.assertTrue(enriched.startswith("DGNL HSA"))

    def test_reading_question_gets_evidence_first_specialist_guidance(self):
        guidance = ai.ReadingExamGuidance.for_question(
            "Đọc hiểu đoạn trích sau, phương án nào không đúng?"
        )

        self.assertIn("Van ban va cac phuong an nguoi dung gui", guidance)
        self.assertIn("Khong suy dien vuot qua van ban", guidance)
        self.assertIn("Dap an: ... Can cu: ...", guidance)

    def test_general_literary_composition_does_not_activate_reading_exam_mode(self):
        self.assertFalse(
            ai.ReadingExamGuidance.is_active("Phân tích hình tượng người lính trong bài thơ Tây Tiến")
        )

    def test_live_answer_path_keeps_skill_documents_out_of_quote_evidence(self):
        source = inspect.getsource(ai.AI._then_answer)

        self.assertIn("topic_gate_bypassed reason=reading_exam", source)
        self.assertIn("quote_evidence = [] if is_reading_exam", source)
        self.assertIn("ReadingExamGuidance.for_question", source)

    def test_discord_prompt_has_no_mojibake_markers(self):
        self.assertIsNone(
            re.search(r"(?:Ã|Â|Ä|Æ)[\x80-\xbf]|á[º»]", ai.THEN_SYSTEM_PROMPT)
        )

    def test_new_opal_section_is_utf8_and_append_only_specialist_content(self):
        text = Path("OPAL_PROMPT.md").read_text(encoding="utf-8")
        marker = "# CHUYÊN ĐỀ BỔ SUNG: ĐỌC HIỂU VÀ ĐÁNH GIÁ NĂNG LỰC"
        section = text[text.index(marker):]

        self.assertIn("chỉ bổ sung, không thay thế", section)
        self.assertIn("Văn bản, đoạn trích và các phương án", section)
        self.assertIsNone(re.search(r"(?:Ã|Â|Ä|Æ)[\x80-\xbf]|á[º»]", section))


if __name__ == "__main__":
    unittest.main()
