import unittest

from cogs.moderation import contains_banned_word


class ModerationBoundaryTest(unittest.TestCase):
    def test_blank_banned_word_never_matches(self):
        self.assertFalse(contains_banned_word("một tin nhắn bình thường", {"", "   "}))

    def test_single_word_does_not_match_inside_an_unrelated_word(self):
        self.assertFalse(contains_banned_word("classical literature", {"ass"}))
        self.assertTrue(contains_banned_word("that word is ass!", {"ass"}))

    def test_vietnamese_phrase_matches_case_insensitively(self):
        self.assertTrue(contains_banned_word("CỤM TỪ không phù hợp.", {"cụm từ không phù hợp"}))


if __name__ == "__main__":
    unittest.main()
