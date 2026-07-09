import unittest
from cogs.ai import AI


class GuidanceInjectionTest(unittest.TestCase):
    def test_guidance_included_when_present(self):
        out = AI._guarded_prompt("Câu hỏi", "ctx", "", "analysis", guidance="KHUNG TƯ DUY LẬP LUẬN: test-marker")
        self.assertIn("KHUNG TƯ DUY LẬP LUẬN: test-marker", out)

    def test_no_guidance_key_when_empty(self):
        out = AI._guarded_prompt("Câu hỏi", "ctx", "", "analysis")
        self.assertNotIn("KHUNG TƯ DUY", out)

    def test_backward_compatible_signature(self):
        # Goi cu khong co guidance van chay.
        out = AI._guarded_prompt("Câu hỏi", "ctx", "", "chat")
        self.assertIn("YEU CAU NGUOI DUNG", out)


if __name__ == "__main__":
    unittest.main()
