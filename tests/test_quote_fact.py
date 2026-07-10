import unittest
from cogs.ai import QuoteExtractor, Planner


class QuoteFactTest(unittest.TestCase):
    def test_fact_author_is_trusted(self):
        meta = {"chunks": [], "quotes": [
            {"quote": "Nghệ thuật không cần là ánh trăng lừa dối.", "author": "Nam Cao", "source": "s", "title": "t"}
        ]}
        plan = Planner.build("nhận định của Nam Cao")
        ev = QuoteExtractor.extract(meta, plan, "nhận định của Nam Cao")
        self.assertEqual(ev[0].author, "Nam Cao")
        self.assertEqual(ev[0].confidence, 1.0)

    def test_author_filter_excludes_other_fact(self):
        meta = {"chunks": [], "quotes": [
            {"quote": "Câu A.", "author": "Nam Cao", "source": "s", "title": "t"},
            {"quote": "Câu B.", "author": "Nguyễn Minh Châu", "source": "s", "title": "t"},
        ]}
        plan = Planner.build("nhận định của Nam Cao")
        ev = QuoteExtractor.extract(meta, plan, "nhận định của Nam Cao")
        authors = {e.author for e in ev}
        self.assertEqual(authors, {"Nam Cao"})


if __name__ == "__main__":
    unittest.main()
