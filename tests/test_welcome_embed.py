import unittest
from cogs.setup import build_welcome_embed


class WelcomeEmbedTest(unittest.TestCase):
    def test_all_mentions_present(self):
        embed = build_welcome_embed("<@111>", "<#222>", "<#333>", "<#444>", "<#555>")
        blob = (embed.description or "") + " ".join(f.name + " " + f.value for f in embed.fields)
        for m in ("<@111>", "<#222>", "<#333>", "<#444>", "<#555>"):
            self.assertIn(m, blob)

    def test_mentions_two_gates(self):
        embed = build_welcome_embed("<@1>", "<#2>", "<#3>", "<#4>", "<#5>")
        blob = (embed.description or "") + " ".join(f.name + " " + f.value for f in embed.fields)
        self.assertIn("Thành viên", blob)
        self.assertIn("Dân làng Hua Tát", blob)
        self.assertIn("Kích hoạt quyền truy cập tài liệu", blob)


if __name__ == "__main__":
    unittest.main()
