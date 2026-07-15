# -*- coding: utf-8 -*-
import os
import unittest

os.environ.setdefault("GROQ_API_KEYS", "x")

from cogs.setup import DEFAULT_RULES, build_rules_embed, build_rules_embeds, _link_channels, _roman


class FakeChannel:
    def __init__(self, name, cid):
        self.name = name
        self.mention = f"<#{cid}>"


class FakeGuild:
    def __init__(self, channels):
        self.channels = channels
        self.threads = []


class RulesEmbedTest(unittest.TestCase):
    def _guild(self):
        return FakeGuild([
            FakeChannel("hỏi-đáp-bài-tập", 111),
            FakeChannel("chia-sẻ-tài-liệu", 222),
            FakeChannel("thảo-luận-văn-học", 333),
            FakeChannel("thư-viện-tài-liệu", 444),
            FakeChannel("lệnh-bot-chung", 555),
            FakeChannel("hướng-dẫn-dùng-bot", 666),
            FakeChannel("bảng-tin-thông-báo", 777),
        ])

    def test_roman_numbering(self):
        self.assertEqual(_roman(1), "I")
        self.assertEqual(_roman(8), "VIII")

    def test_channel_token_resolves_to_mention(self):
        g = self._guild()
        out = _link_channels(g, "Đăng ở #thảo-luận-văn-học nhé")
        self.assertIn("<#333>", out)
        self.assertNotIn("#thảo-luận-văn-học", out)

    def test_unknown_channel_stays_plain_not_broken(self):
        g = self._guild()
        out = _link_channels(g, "Xem #kênh-không-tồn-tại")
        self.assertIn("#kênh-không-tồn-tại", out)  # giữ nguyên chữ, không thành mention hỏng
        self.assertNotIn("<#", out)

    def test_thread_is_resolved_when_not_a_channel(self):
        g = FakeGuild([])
        g.threads = [FakeChannel("thảo-luận-văn-học", 999)]
        out = _link_channels(g, "#thảo-luận-văn-học")
        self.assertEqual(out, "<#999>")

    def test_build_embed_numbers_and_links_all_default_chapters(self):
        g = self._guild()
        chapters = DEFAULT_RULES
        embed = build_rules_embed(chapters, g)
        self.assertEqual(len(embed.fields), len(chapters))
        self.assertTrue(embed.fields[0].name.startswith("Chương I."))
        self.assertTrue(embed.fields[-1].name.startswith(f"Chương {_roman(len(chapters))}."))
        # Kênh trong Chương II đã thành mention, không còn '# unknown'-prone token.
        ch2 = embed.fields[1].value
        self.assertIn("<#111>", ch2)  # hỏi-đáp-bài-tập
        self.assertIn("<#333>", ch2)  # thảo-luận-văn-học

    def test_every_field_value_within_discord_limit(self):
        embed = build_rules_embed(DEFAULT_RULES, self._guild())
        for f in embed.fields:
            self.assertLessEqual(len(f.value), 1024)
            self.assertGreater(len(f.value), 0)
            self.assertLessEqual(len(f.name), 256)

    def test_build_embed_without_guild_keeps_tokens(self):
        embed = build_rules_embed(DEFAULT_RULES, None)
        self.assertIn("#hỏi-đáp-bài-tập", embed.fields[1].value)  # không có guild -> giữ token

    def test_large_rule_set_is_paginated_with_continuous_numbering(self):
        chapters = [(f"Mục {i}", "x" * 1024) for i in range(1, 31)]
        embeds = build_rules_embeds(chapters, None)
        self.assertGreater(len(embeds), 1)
        self.assertEqual(sum(len(embed.fields) for embed in embeds), len(chapters))
        self.assertTrue(embeds[0].fields[0].name.startswith("Chương I."))
        self.assertTrue(embeds[-1].fields[-1].name.startswith(f"Chương {_roman(30)}."))
        for embed in embeds:
            self.assertLessEqual(len(embed.fields), 25)
            self.assertLessEqual(len(embed), 6000)


if __name__ == "__main__":
    unittest.main()
