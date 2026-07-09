import unittest
from pathlib import Path
from cogs import ai


class SystemInstructionsTest(unittest.TestCase):
    def test_full_instructions_loaded_uncut(self):
        raw = Path("SYSTEM INSTRUCTIONS.txt").read_text(encoding="utf-8").strip()
        # Nap tron ven, khong con cat 1500 ky tu.
        self.assertGreaterEqual(len(ai.LITERATURE_SYSTEM_INSTRUCTIONS), len(raw) - 5)

    def test_bonus_loaded_into_system_prompt(self):
        self.assertTrue(ai.BONUS_FEWSHOT)
        # Dau hieu dac trung tu BONUS.txt (loi chu Trung chen ngang lam vi du xau).
        self.assertIn("Van hoc la nhan hoc", ai._plain_ascii(ai.BONUS_FEWSHOT)) \
            if hasattr(ai, "_plain_ascii") else self.assertIn("nhan hoc", ai.BONUS_FEWSHOT.lower())

    def test_system_prompt_contains_instructions(self):
        self.assertIn(ai.LITERATURE_SYSTEM_INSTRUCTIONS[:50], ai.THEN_SYSTEM_PROMPT)

    def test_groq_system_prompt_exists_and_is_compact(self):
        self.assertTrue(hasattr(ai, "THEN_SYSTEM_PROMPT_GROQ"))
        self.assertLessEqual(len(ai.THEN_SYSTEM_PROMPT_GROQ), ai.GROQ_SAFE_PROMPT_CHARS)

    def test_groq_system_prompt_excludes_bonus(self):
        # BONUS.txt content (Chinese-character-mixed bad examples) must NOT be
        # in the compact Groq prompt - it's what made the prompt huge.
        bonus_marker = ai.BONUS_FEWSHOT[:80]
        self.assertNotIn(bonus_marker, ai.THEN_SYSTEM_PROMPT_GROQ)

    def test_groq_system_prompt_still_forbids_fabrication(self):
        lowered = ai.THEN_SYSTEM_PROMPT_GROQ.lower()
        self.assertTrue(
            "bịa" in lowered or "fabricat" in lowered or "khong duoc bia" in ai._plain_ascii(lowered)
        )

    def test_full_system_prompt_unchanged_for_gemini(self):
        # Gemini path must keep the FULL prompt including instructions + bonus.
        self.assertIn(ai.LITERATURE_SYSTEM_INSTRUCTIONS[:50], ai.THEN_SYSTEM_PROMPT)
        if ai.BONUS_FEWSHOT:
            self.assertIn(ai.BONUS_FEWSHOT[:80], ai.THEN_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
