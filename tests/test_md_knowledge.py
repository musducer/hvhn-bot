import unittest
from md_knowledge import parse_markdown


SAMPLE = """---
title: Chí Phèo - Nam Cao
source: sgk11
---

# Bi kịch bị cự tuyệt

Chí Phèo bị xã hội ruồng bỏ, khát khao hoàn lương nhưng bị chối từ.

> "Nghệ thuật không cần phải là ánh trăng lừa dối." — Nam Cao

## Nhận định mở rộng

> "Văn học và đời sống là những vòng tròn đồng tâm." — Nguyễn Minh Châu

Một câu không có tác giả: > "Ẩn danh nên không gán tên."
"""


class ParseMarkdownTest(unittest.TestCase):
    def setUp(self):
        self.doc = parse_markdown(SAMPLE)

    def test_frontmatter_title(self):
        self.assertEqual(self.doc["title"], "Chí Phèo - Nam Cao")

    def test_passages_split_by_heading(self):
        titles = [p["title"] for p in self.doc["passages"]]
        self.assertIn("Bi kịch bị cự tuyệt", titles)
        self.assertIn("Nhận định mở rộng", titles)

    def test_passage_content_captured(self):
        p = next(p for p in self.doc["passages"] if p["title"] == "Bi kịch bị cự tuyệt")
        self.assertIn("ruồng bỏ", p["content"])

    def test_quote_author_extracted(self):
        pairs = {(q["quote"], q["author"]) for q in self.doc["quotes"]}
        self.assertIn(("Nghệ thuật không cần phải là ánh trăng lừa dối.", "Nam Cao"), pairs)
        self.assertIn(("Văn học và đời sống là những vòng tròn đồng tâm.", "Nguyễn Minh Châu"), pairs)

    def test_quote_without_attribution_has_empty_author(self):
        anon = [q for q in self.doc["quotes"] if "Ẩn danh" in q["quote"]]
        self.assertTrue(anon)
        self.assertEqual(anon[0]["author"], "")

    def test_quote_carries_passage_title(self):
        q = next(q for q in self.doc["quotes"] if q["author"] == "Nguyễn Minh Châu")
        self.assertEqual(q["passage_title"], "Nhận định mở rộng")


if __name__ == "__main__":
    unittest.main()
