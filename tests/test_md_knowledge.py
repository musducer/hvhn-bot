import inspect
import unittest
from unittest.mock import patch
from md_knowledge import parse_markdown
from md_knowledge import MD_KNOWLEDGE_SCHEMA
from md_knowledge import build_md_context
from md_knowledge import index_md_bytes
from md_knowledge import index_md_path


SAMPLE = """---
title: Chí Phèo - Nam Cao
source: sgk11
---

# Bi kịch bị cự tuyệt

Chí Phèo bị xã hội ruồng bỏ, khát khao hoàn lương nhưng bị chối từ.

> "Nghệ thuật không cần phải là ánh trăng lừa dối." — Nam Cao

## Nhận định mở rộng

> "Văn học và đời sống là những vòng tròn đồng tâm." — Nguyễn Minh Châu

> "Ẩn danh nên không gán tên."
"""

# Mẫu rút từ file thật của chủ: "nhan dinh van chuong.md" (danh sách +/-, tác giả trong ngoặc,
# danh xưng đi kèm, thơ nhiều dòng, không có heading).
REAL_SAMPLE = """
NHỮNG PHÁT BIỂU HAY VỀ VĂN CHƯƠNG

+ “Mỗi công dân có một dạng vân tay. Mỗi nhà thơ thứ thiệt cũng có một dạng vân chữ. Trộn không lẫn.” (Nhà thơ Lê Đạt)
+ "Thơ có quyền lạ hóa nhưng thiên chức của thơ không được xa lạ hóa con người." (Huỳnh Văn Thống)
- “Nghệ thuật dân tộc là nghệ thuật mang mùi hương đất đai, trong tiếng mẹ đẻ mỗi từ dường như có hai lần ý nghĩa nghệ thuật…" (Nhà văn Tolstoy)
+ “Tôi tin vào cá tính đến được với người đọc qua bất kỳ ngôn ngữ nào, bất kỳ hình thức nào.” (Pablo Neruda, nhà thơ quốc dân của Chile, được trao giải Nobel Văn chương năm 1971)
- "Hình thức tuyệt nhiên không phải là một thứ thao tác mang tính kỹ thuật bề ngoài." (Nhà văn Lý Nhuệ - Trung Quốc)
+ “Mỗi cuộc đời mang thầm bao nhiêu chuyện
Chạm nổi chạm chìm trong thịt trong xương.”
(Nhà thơ Huy Cận)

Trong bài có nhắc tới bài thơ “Bài hát ngày trở về” (Bình Nguyên Trang) để làm sáng tỏ.
"""


class RealWorldFormatsTest(unittest.TestCase):
    def setUp(self):
        self.doc = parse_markdown(REAL_SAMPLE)
        self.pairs = {(q["quote"], q["author"]) for q in self.doc["quotes"]}
        self.authors = {q["author"] for q in self.doc["quotes"]}

    def test_plus_list_with_role_prefix(self):
        self.assertIn("Lê Đạt", self.authors)

    def test_bare_author_no_role(self):
        self.assertIn("Huỳnh Văn Thống", self.authors)

    def test_minus_list_and_role_stripped(self):
        self.assertIn("Tolstoy", self.authors)

    def test_author_with_trailing_bio_comma(self):
        self.assertIn("Pablo Neruda", self.authors)

    def test_author_with_nationality_dash(self):
        self.assertIn("Lý Nhuệ", self.authors)

    def test_multiline_poem_author_on_next_line(self):
        poem = [q for q in self.doc["quotes"] if "vân tay" not in q["quote"] and "Chạm nổi" in q["quote"]]
        self.assertTrue(poem)
        self.assertEqual(poem[0]["author"], "Huy Cận")

    def test_mid_sentence_title_not_extracted_as_fact(self):
        # “Bài hát ngày trở về” là TÊN TÁC PHẨM giữa câu, không phải nhận định
        self.assertNotIn("Bình Nguyên Trang", self.authors)

    def test_headingless_file_still_has_passages(self):
        self.assertTrue(self.doc["passages"])
        joined = " ".join(p["content"] for p in self.doc["passages"])
        self.assertIn("vân chữ", joined)


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


class SchemaShapeTest(unittest.TestCase):
    def test_schema_has_tables(self):
        for tbl in ("ai_md_documents", "ai_md_passages", "ai_md_quotes"):
            self.assertIn(tbl, MD_KNOWLEDGE_SCHEMA)


class BuildMdContextTest(unittest.TestCase):
    def test_context_lists_passages_with_source(self):
        chunks = [
            {"title": "Bi kịch", "content": "Chí Phèo bị ruồng bỏ.", "source": "sgk11", "chunk_index": 0},
            {"title": "Mở rộng", "content": "Vòng tròn đồng tâm.", "source": "sgk11", "chunk_index": 1},
        ]
        ctx = build_md_context(chunks)
        self.assertIn("Chí Phèo bị ruồng bỏ.", ctx)
        self.assertIn("Bi kịch", ctx)
        self.assertIn("[P1]", ctx)
        self.assertIn("[P2]", ctx)

    def test_empty_chunks_empty_context(self):
        self.assertEqual(build_md_context([]), "")


class IndexMdPathTest(unittest.TestCase):
    def test_index_md_path_is_async_and_reads_file(self):
        src = inspect.getsource(index_md_path)
        self.assertIn("index_md_bytes", src)
        self.assertIn("connect", src)


class IndexMdBytesTest(unittest.IsolatedAsyncioTestCase):
    async def test_unchanged_document_returns_existing_counts(self):
        data = b"# Title\n\nBody"

        class FakeDb:
            async def fetchrow(self, *args):
                from md_knowledge import _content_hash
                return {"content_hash": _content_hash(data), "author": "",
                        "passage_count": 839, "quote_count": 180}

            async def execute(self, *args):
                raise AssertionError("unchanged document should not rewrite passages")

        async def noop_schema(db):
            return None

        with patch("md_knowledge.ensure_md_schema", noop_schema):
            result = await index_md_bytes(FakeDb(), "Title", data, source="same.md")

        self.assertFalse(result["changed"])
        self.assertEqual(result["passages"], 839)
        self.assertEqual(result["quotes"], 180)

    async def test_unchanged_empty_index_is_repaired(self):
        data = b"# Title\n\nBody"

        class Tx:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

        class FakeDb:
            def __init__(self):
                self.inserts = 0

            async def fetchrow(self, *args):
                from md_knowledge import _content_hash
                return {"content_hash": _content_hash(data), "author": "",
                        "passage_count": 0, "quote_count": 0}

            def transaction(self):
                return Tx()

            async def execute(self, query, *args):
                if "INSERT INTO ai_md_passages" in query:
                    self.inserts += 1

        async def noop_schema(db):
            return None

        db = FakeDb()
        with patch("md_knowledge.ensure_md_schema", noop_schema):
            result = await index_md_bytes(db, "Title", data, source="same.md")

        self.assertTrue(result["changed"])
        self.assertEqual(result["passages"], 1)
        self.assertEqual(db.inserts, 1)


if __name__ == "__main__":
    unittest.main()
