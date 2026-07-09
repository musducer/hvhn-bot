import unittest
from cogs.ai import Formatter, QuoteEvidence


class EvidenceFormattingTest(unittest.TestCase):
    def test_block_marks_author_and_unknown(self):
        items = [
            QuoteEvidence(quote="Nghệ thuật không cần là ánh trăng lừa dối",
                          author="Nam Cao", pdf_title="a.pdf"),
            QuoteEvidence(quote="Văn chương giúp con người đối thoại",
                          author="UNKNOWN", pdf_title="b.pdf"),
        ]
        block = Formatter.evidence_block(items)
        self.assertIn("Nam Cao", block)
        self.assertIn("CHUA XAC DINH TAC GIA", block)
        self.assertIn("a.pdf", block)


if __name__ == "__main__":
    unittest.main()
