import unittest

from cogs.ai import Planner, QuoteExtractor


class QuoteExtractorAttributionTest(unittest.TestCase):
    def setUp(self):
        self.meta = {
            "chunks": [
                {
                    "title": "multi_author.pdf",
                    "chunk_index": 7,
                    "content": (
                        "Nguy\u1ec5n Minh Ch\u00e2u kh\u1eb3ng \u0111\u1ecbnh: \u201cV\u0103n h\u1ecdc v\u00e0 \u0111\u1eddi s\u1ed1ng l\u00e0 nh\u1eefng v\u00f2ng tr\u00f2n \u0111\u1ed3ng t\u00e2m.\u201d "
                        "Nam Cao vi\u1ebft: \u201cNgh\u1ec7 thu\u1eadt kh\u00f4ng c\u1ea7n ph\u1ea3i l\u00e0 \u00e1nh tr\u0103ng l\u1eeba d\u1ed1i.\u201d"
                    ),
                }
            ]
        }

    def test_nguyen_minh_chau_query_never_returns_nam_cao(self):
        query = "Nh\u1eadn \u0111\u1ecbnh c\u1ee7a Nguy\u1ec5n Minh Ch\u00e2u"
        plan = Planner.build(query)
        quotes = QuoteExtractor.extract(self.meta, plan, query)
        self.assertEqual(len(quotes), 1)
        self.assertEqual(quotes[0].author, "Nguy\u1ec5n Minh Ch\u00e2u")
        self.assertIn("V\u0103n h\u1ecdc v\u00e0 \u0111\u1eddi s\u1ed1ng", quotes[0].quote)
        self.assertNotIn("Ngh\u1ec7 thu\u1eadt kh\u00f4ng c\u1ea7n", quotes[0].quote)

    def test_nam_cao_query_never_returns_nguyen_minh_chau(self):
        query = "Nh\u1eadn \u0111\u1ecbnh c\u1ee7a Nam Cao"
        plan = Planner.build(query)
        quotes = QuoteExtractor.extract(self.meta, plan, query)
        self.assertEqual(len(quotes), 1)
        self.assertEqual(quotes[0].author, "Nam Cao")
        self.assertIn("Ngh\u1ec7 thu\u1eadt kh\u00f4ng c\u1ea7n", quotes[0].quote)
        self.assertNotIn("V\u0103n h\u1ecdc v\u00e0 \u0111\u1eddi s\u1ed1ng", quotes[0].quote)

    def test_unknown_author_when_no_confident_attribution(self):
        meta = {"chunks": [{"title": "unknown.pdf", "chunk_index": 1, "content": "Trong s\u1ed5 tay c\u00f3 c\u00e2u: \u201cV\u0103n ch\u01b0\u01a1ng gi\u00fap con ng\u01b0\u1eddi \u0111\u1ed1i tho\u1ea1i v\u1edbi ch\u00ednh m\u00ecnh.\u201d"}]}
        plan = Planner.build("Cho m\u00ecnh m\u1ed9t nh\u1eadn \u0111\u1ecbnh")
        quotes = QuoteExtractor.extract(meta, plan, "Cho m\u00ecnh m\u1ed9t nh\u1eadn \u0111\u1ecbnh")
        self.assertEqual(quotes[0].author, "UNKNOWN")
        self.assertLess(quotes[0].confidence, 0.55)


if __name__ == "__main__":
    unittest.main()
