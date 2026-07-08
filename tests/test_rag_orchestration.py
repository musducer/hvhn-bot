import unittest

from cogs.ai import Formatter, Planner, QuoteExtractor


class RAGOrchestrationTest(unittest.TestCase):
    def test_quote_single_author_filter_returns_only_requested_author(self):
        query = "Theo t\u00e0i li\u1ec7u, h\u00e3y ch\u00e9p nguy\u00ean v\u0103n nh\u1eadn \u0111\u1ecbnh c\u1ee7a L\u00ea \u0110\u1ea1t."
        plan = Planner.build(query)
        meta = {
            "chunks": [
                {"title": "a.pdf", "chunk_index": 1, "content": "Nguy\u1ec5n Minh Ch\u00e2u nh\u1eadn \u0111\u1ecbnh: \u201cV\u0103n h\u1ecdc v\u00e0 \u0111\u1eddi s\u1ed1ng l\u00e0 nh\u1eefng v\u00f2ng tr\u00f2n \u0111\u1ed3ng t\u00e2m.\u201d"},
                {"title": "b.pdf", "chunk_index": 2, "content": "L\u00ea \u0110\u1ea1t vi\u1ebft: \u201cM\u1ed7i c\u00f4ng d\u00e2n c\u00f3 m\u1ed9t d\u1ea1ng v\u00e2n tay. M\u1ed7i ng\u01b0\u1eddi ngh\u1ec7 s\u0129 th\u1ee9 thi\u1ec7t c\u00f3 m\u1ed9t d\u1ea1ng v\u00e2n ch\u1eef.\u201d"},
            ]
        }
        quotes = QuoteExtractor.extract(meta, plan, query)
        answer = Formatter.quote_single(quotes, plan)
        self.assertEqual(plan.intent, "QUOTE_SINGLE")
        self.assertIn("L\u00ea \u0110\u1ea1t", answer)
        self.assertIn("M\u1ed7i c\u00f4ng d\u00e2n c\u00f3 m\u1ed9t d\u1ea1ng v\u00e2n tay", answer)
        self.assertNotIn("Nguy\u1ec5n Minh Ch\u00e2u nh\u1eadn \u0111\u1ecbnh", answer)

    def test_quote_collection_collects_many_quotes(self):
        query = "Theo t\u00e0i li\u1ec7u, h\u00e3y t\u1ed5ng h\u1ee3p m\u1ecdi nh\u1eadn \u0111\u1ecbnh v\u1ec1 ch\u1ee9c n\u0103ng c\u1ee7a v\u0103n ch\u01b0\u01a1ng."
        plan = Planner.build(query)
        meta = {
            "chunks": [
                {"title": "a.pdf", "chunk_index": 1, "content": "Th\u1ea1ch Lam cho r\u1eb1ng: \u201cV\u0103n ch\u01b0\u01a1ng l\u00e0 m\u1ed9t th\u1ee9 kh\u00ed gi\u1edbi thanh cao v\u00e0 \u0111\u1eafc l\u1ef1c.\u201d"},
                {"title": "b.pdf", "chunk_index": 2, "content": "Nguy\u1ec5n V\u0103n D\u00e2n vi\u1ebft: \u201cV\u0103n h\u1ecdc gi\u00fap con ng\u01b0\u1eddi t\u1ef1 nh\u1eadn th\u1ee9c v\u1ec1 ch\u00ednh m\u00ecnh.\u201d"},
            ]
        }
        quotes = QuoteExtractor.extract(meta, plan, query)
        answer = Formatter.quote_collection(quotes, plan)
        self.assertEqual(plan.intent, "QUOTE_COLLECTION")
        self.assertIn("V\u0103n ch\u01b0\u01a1ng l\u00e0 m\u1ed9t th\u1ee9 kh\u00ed gi\u1edbi", answer)
        self.assertIn("V\u0103n h\u1ecdc gi\u00fap con ng\u01b0\u1eddi", answer)

    def test_absent_evidence_does_not_invent(self):
        query = "Theo t\u00e0i li\u1ec7u, h\u00e3y ch\u00e9p nguy\u00ean v\u0103n nh\u1eadn \u0111\u1ecbnh c\u1ee7a L\u00ea \u0110\u1ea1t."
        plan = Planner.build(query)
        answer = Formatter.quote_single([], plan)
        self.assertIn("Ch\u01b0a t\u00ecm th\u1ea5y", answer)
        self.assertIn("Kh\u00f4ng n\u00ean t\u1ef1 b\u1ecba", answer)


if __name__ == "__main__":
    unittest.main()
