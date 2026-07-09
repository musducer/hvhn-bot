import unittest
from cogs.setup import build_welcome_embed


class WelcomeEmbedTest(unittest.TestCase):
    def test_all_mentions_present(self):
        embed = build_welcome_embed("<@111>", "<#222>", "<#333>", "<#444>")
        blob = (embed.description or "") + " ".join(f.name + " " + f.value for f in embed.fields)
        for m in ("<@111>", "<#222>", "<#333>", "<#444>"):
            self.assertIn(m, blob)

    def test_mentions_two_gates(self):
        embed = build_welcome_embed("<@1>", "<#2>", "<#3>", "<#4>")
        blob = (embed.description or "") + " ".join(f.name + " " + f.value for f in embed.fields)
        self.assertIn("Thành viên", blob)
        self.assertIn("Dân làng Hua Tát", blob)


if __name__ == "__main__":
    unittest.main()
