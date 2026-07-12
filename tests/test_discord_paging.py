import unittest

from cogs.ai import AI


class FakeUser:
    display_name = "Tester"


class FakeFollowup:
    def __init__(self, fail_embed_titles=()):
        self.fail_embed_titles = set(fail_embed_titles)
        self.sent = []

    async def send(self, content=None, *, embed=None, view=None, ephemeral=False):
        title = embed.title if embed else ""
        if embed and title in self.fail_embed_titles:
            self.fail_embed_titles.remove(title)
            raise RuntimeError("simulated discord embed failure")
        self.sent.append({"content": content, "embed": embed, "view": view, "ephemeral": ephemeral})


class FakeInteraction:
    def __init__(self, followup):
        self.followup = followup
        self.user = FakeUser()


class DiscordPagingTest(unittest.TestCase):
    def test_long_answer_splits_on_paragraph_boundaries(self):
        answer = "\n\n".join([
            "Đoạn một " + "a" * 900 + ".",
            "Đoạn hai " + "b" * 900 + ".",
            "Đoạn ba " + "c" * 900 + ".",
        ])

        pages = AI._split_answer_pages(answer, max_chars=1200)

        self.assertEqual(len(pages), 3)
        self.assertTrue(all(len(page) <= 1200 for page in pages))
        self.assertTrue(pages[0].startswith("Đoạn một"))
        self.assertTrue(pages[1].startswith("Đoạn hai"))
        self.assertTrue(pages[2].startswith("Đoạn ba"))
        self.assertNotIn("rut gon", "\n".join(pages).lower())
        self.assertNotIn("rút gọn", "\n".join(pages).lower())

    def test_oversized_paragraph_splits_without_mid_word_when_possible(self):
        answer = " ".join(f"word{i}" for i in range(300))

        pages = AI._split_answer_pages(answer, max_chars=180)

        self.assertGreater(len(pages), 1)
        self.assertTrue(all(len(page) <= 180 for page in pages))
        self.assertEqual(" ".join(pages).replace("  ", " "), answer)


class DiscordSendPagingTest(unittest.IsolatedAsyncioTestCase):
    async def test_send_answer_embeds_sends_every_page(self):
        ai = AI.__new__(AI)
        ai.bot = object()
        answer = "\n\n".join(["Một " + "a" * 3000, "Hai " + "b" * 3000])
        followup = FakeFollowup()

        await ai._send_answer_embeds(
            FakeInteraction(followup),
            title="Then - Hỏi Văn",
            answer=answer,
            full_prompt="prompt",
        )

        self.assertEqual(len(followup.sent), 2)
        self.assertEqual(followup.sent[0]["embed"].title, "Then - Hỏi Văn (1/2)")
        self.assertEqual(followup.sent[1]["embed"].title, "Then - Hỏi Văn (2/2)")

    async def test_failed_page_is_retried_as_smaller_embeds_not_plain_text(self):
        # Nguoi dung muon TAT CA tren embed: khi embed lon that bai, phai thu lai bang
        # embed nho hon, KHONG ha xuong tin nhan tho.
        ai = AI.__new__(AI)
        ai.bot = object()
        answer = "\n\n".join(["Một " + "a" * 3000, "Hai " + "b" * 3000])
        followup = FakeFollowup(fail_embed_titles={"Then - Hỏi Văn (2/2)"})

        await ai._send_answer_embeds(
            FakeInteraction(followup),
            title="Then - Hỏi Văn",
            answer=answer,
            full_prompt="prompt",
        )

        self.assertEqual(followup.sent[0]["embed"].title, "Then - Hỏi Văn (1/2)")
        # Trang 2 duoc gui lai duoi dang cac embed nho, khong co tin nhan tho nao.
        self.assertTrue(all(item["content"] is None for item in followup.sent))
        retry_titles = [item["embed"].title for item in followup.sent if item["embed"].title.startswith("Then - Hỏi Văn (2/2)")]
        self.assertTrue(all("[" in t for t in retry_titles))
        self.assertGreaterEqual(len(retry_titles), 2)

    async def test_plain_text_only_when_small_embed_also_fails(self):
        # Neu ca embed nho cung fail -> moi ha xuong tin nhan tho.
        ai = AI.__new__(AI)
        ai.bot = object()
        answer = "Một " + "a" * 3000
        # Fail embed lon lan ca hai embed nho.
        followup = FakeFollowup(fail_embed_titles={
            "Then - Hỏi Văn", "Then - Hỏi Văn [1/2]", "Then - Hỏi Văn [2/2]",
        })

        await ai._send_answer_embeds(
            FakeInteraction(followup),
            title="Then - Hỏi Văn",
            answer=answer,
            full_prompt="prompt",
        )
        self.assertTrue(any((item["content"] or "").startswith("**Then - Hỏi Văn") for item in followup.sent))


if __name__ == "__main__":
    unittest.main()
