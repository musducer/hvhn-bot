# -*- coding: utf-8 -*-
import os
import unittest

os.environ.setdefault("GROQ_API_KEYS", "x")

from cogs.ai import AI, Planner, QuoteExtractor, _rag_plain
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


class SubjectMatchDiacriticTest(unittest.TestCase):
    """Bo dau lam 'Nguyen Binh' dinh voi 'Nguyen Binh Phuong' -> kho lac de bi coi la dung chu de
    -> bot bia tho. So khop chu de phai GIU DAU THANH."""

    def _subjects(self, q):
        return AI._query_subjects(q, None)

    def test_name_subject_is_extracted_with_diacritics(self):
        self.assertIn("nguyễn bính", self._subjects("Phân tích phong cách thơ Nguyễn Bính"))

    def test_similar_name_without_diacritics_does_not_collide(self):
        subs = self._subjects("Phân tích phong cách thơ Nguyễn Bính")
        off_topic = "Nguyễn Bình Phương bàn về thời gian; Mai Văn Phấn nói về bản sắc."
        self.assertFalse(AI._text_mentions_subject(subs, off_topic))

    def test_on_subject_text_still_matches(self):
        subs = self._subjects("Phân tích phong cách thơ Nguyễn Bính")
        on_topic = "Nguyễn Bính là nhà thơ chân quê, bài Tương tư nổi tiếng."
        self.assertTrue(AI._text_mentions_subject(subs, on_topic))

    def test_off_subject_pile_is_flagged(self):
        q = "Phân tích phong cách thơ Nguyễn Bính"
        plan = Planner.build(q)
        pdf_meta = {"chunks": [{"title": "", "first_500": "Nguyễn Bình Phương, Mai Văn Phấn", "excerpt": ""}]}
        self.assertTrue(AI._context_off_subject(q, plan, pdf_meta))


class SignatureTest(unittest.TestCase):
    def test_no_keys_signature_empty(self):
        # Process khong co embedding key -> signature rong (khong gia dinh gemini => tranh xoa embedding)
        import unittest.mock as mock
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(md_embeddings.active_provider(), "")
            self.assertEqual(md_embeddings.active_signature(), "")


if __name__ == "__main__":
    unittest.main()
