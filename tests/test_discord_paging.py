import unittest

from cogs.ai import AI


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


if __name__ == "__main__":
    unittest.main()
