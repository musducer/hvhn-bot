# -*- coding: utf-8 -*-
import os
import unittest

os.environ.setdefault("GROQ_API_KEYS", "x")

from cogs.ai import Planner, QuoteExtractor, _rag_plain
import md_embeddings


class AuthorFilterParseTest(unittest.TestCase):
    def test_initial_with_dot_kept(self):
        self.assertEqual(Planner.author_filter("nhận định của A. Camus"), "A. Camus")

    def test_full_name(self):
        self.assertEqual(Planner.author_filter("một số nhận định của Albert Camus"), "Albert Camus")

    def test_vietnamese_name(self):
        self.assertEqual(Planner.author_filter("nhận định của Vương Trí Nhàn về văn học"), "Vương Trí Nhàn")


class AuthorMatchTest(unittest.TestCase):
    def _m(self, req, auth):
        return QuoteExtractor._author_matches(_rag_plain(req), _rag_plain(auth))

    def test_full_vs_initial_same_surname(self):
        self.assertTrue(self._m("Albert Camus", "A.Camus"))
        self.assertTrue(self._m("A. Camus", "A.Camus"))

    def test_exact(self):
        self.assertTrue(self._m("Vương Trí Nhàn", "Vương Trí Nhàn"))

    def test_different_people_sharing_a_token_do_not_match(self):
        # "Nam Cao" khong duoc khop "Cao Ba Quat" chi vi chung token "Cao"
        self.assertFalse(self._m("Nam Cao", "Cao Bá Quát"))

    def test_empty_request_matches_all(self):
        self.assertTrue(self._m("", "bất kỳ ai"))


class SignatureTest(unittest.TestCase):
    def test_no_keys_signature_empty(self):
        # Process khong co embedding key -> signature rong (khong gia dinh gemini => tranh xoa embedding)
        import unittest.mock as mock
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(md_embeddings.active_provider(), "")
            self.assertEqual(md_embeddings.active_signature(), "")


if __name__ == "__main__":
    unittest.main()
