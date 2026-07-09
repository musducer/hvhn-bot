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


if __name__ == "__main__":
    unittest.main()
