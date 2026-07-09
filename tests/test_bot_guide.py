import unittest
from cogs.setup import build_guide_embed, BotGuideView


class BotGuideTest(unittest.TestCase):
    def test_guide_embed_has_key_sections(self):
        embed = build_guide_embed()
        blob = embed.title + " " + (embed.description or "") + " ".join(
            f.name + " " + f.value for f in embed.fields
        )
        self.assertIn("làm được", blob.lower())
        self.assertIn("hạn chế", blob.lower())
        self.assertIn("prompt", blob.lower())

    def test_guide_view_button_custom_id(self):
        view = BotGuideView()
        ids = [c.custom_id for c in view.children if hasattr(c, "custom_id")]
        self.assertIn("confirm_bot_guide", ids)


if __name__ == "__main__":
    unittest.main()
