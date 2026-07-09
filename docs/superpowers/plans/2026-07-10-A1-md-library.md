# A1 — Thư viện md_knowledge (parse + index) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Nền tảng nhóm A — parse file `.md` theo quy ước nhẹ thành passages (retrieval) + facts quote→author (deterministic), lưu vào DB idempotent, và retrieve theo query.

**Architecture:** Module mới `md_knowledge.py`. Hàm thuần `parse_markdown` (TDD kỹ). Schema + `index_md_bytes` + `retrieve_md_knowledge` theo đúng pattern `pdf_knowledge.py` (idempotent theo content_hash, FTS/trigram). Chưa wire vào ai.py (đó là A2).

**Tech Stack:** Python, asyncpg/Postgres, unittest.

## Global Constraints

- Không thêm dependency (chỉ stdlib + asyncpg đã có). Test: `python -m unittest tests.test_md_knowledge -v` từ repo root.
- `parse_markdown` là hàm THUẦN, không I/O — test đầy đủ.
- Quy ước .md: heading `#..######` = ranh giới passage; blockquote `> "…" — Tác giả` hoặc `> "…" (Tác giả)` = fact quote→author; author rỗng nếu không khớp mẫu (KHÔNG đoán).
- Idempotent theo `content_hash` như `index_pdf_bytes`.

---

### Task 1: `parse_markdown` — hàm thuần

**Files:**
- Create: `md_knowledge.py`
- Test: `tests/test_md_knowledge.py`

**Interfaces:**
- Produces: `parse_markdown(text: str) -> dict` với khoá `"title"` (str), `"passages"` (list `{"title": str, "content": str}`), `"quotes"` (list `{"quote": str, "author": str, "passage_title": str}`).

- [ ] **Step 1: Viết test**

Tạo `tests/test_md_knowledge.py`:

```python
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
```

- [ ] **Step 2: Chạy test — phải fail**

Run: `python -m unittest tests.test_md_knowledge -v`
Expected: FAIL (`ModuleNotFoundError: md_knowledge`).

- [ ] **Step 3: Viết md_knowledge.parse_markdown**

Tạo `md_knowledge.py`:

```python
import re

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
# blockquote chua trich dan trong ngoac kep, kem attribution tuy chon: — Tac gia | (Tac gia)
_QUOTE = re.compile(
    r'>\s*[""\"](?P<quote>.+?)[""\"]'
    r'(?:\s*(?:[—\-–]\s*(?P<a1>[^"\n(]+?)|\((?P<a2>[^)\n]+?)\)))?\s*$'
)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    block = text[3:end].strip()
    rest = text[end + 4:].lstrip("\n")
    meta = {}
    for line in block.splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            meta[key.strip().lower()] = val.strip()
    return meta, rest


def parse_markdown(text: str) -> dict:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    meta, body = _parse_frontmatter(text)

    passages: list[dict] = []
    quotes: list[dict] = []
    cur_title = ""
    cur_lines: list[str] = []

    def _flush():
        content = "\n".join(cur_lines).strip()
        if cur_title or content:
            passages.append({"title": cur_title, "content": content})

    for line in body.split("\n"):
        m = _HEADING.match(line)
        if m:
            _flush()
            cur_title = m.group(2).strip()
            cur_lines = []
            continue
        cur_lines.append(line)
        qm = _QUOTE.search(line)
        if qm:
            author = (qm.group("a1") or qm.group("a2") or "").strip()
            quotes.append({
                "quote": qm.group("quote").strip(),
                "author": author,
                "passage_title": cur_title,
            })
    _flush()

    title = meta.get("title") or (passages[0]["title"] if passages else "")
    return {"title": title, "source": meta.get("source", ""), "passages": passages, "quotes": quotes}
```

- [ ] **Step 4: Chạy test — phải pass**

Run: `python -m unittest tests.test_md_knowledge -v`
Expected: PASS 6/6.

- [ ] **Step 5: Commit**

```bash
git add md_knowledge.py tests/test_md_knowledge.py
git commit -m "Add markdown parser for passages and quote-author facts"
```

---

### Task 2: Schema + index_md_bytes + retrieve_md_knowledge (theo pattern pdf_knowledge)

**Files:**
- Modify: `md_knowledge.py`
- Reference (đọc để bám pattern): `pdf_knowledge.py:26-47` (schema), `pdf_knowledge.py:295-372` (`index_pdf_bytes`), `pdf_knowledge.py:404-470` (`sync`/retrieve), `pdf_knowledge.py:83-130` (`_score_pdf_text`, retrieve shape).

**Interfaces:**
- Produces: `MD_KNOWLEDGE_SCHEMA: str`; `async ensure_md_schema(db)`; `async index_md_bytes(db, title: str, data: bytes, *, source: str = "", created_by: int | None = None) -> dict` (khoá `{doc_key, title, passages, quotes, changed}`); `async retrieve_md_knowledge(db, query: str, *, limit: int = 5) -> dict` trả **pdf_meta-shape**: `{"chunks": [{"title","content","source","chunk_index","page"}], "quotes": [{"quote","author","source","title"}], "selected_count": int, "candidate_count": int, "top_score": float}`.

- [ ] **Step 1: Viết test cấu trúc (không cần DB)**

Thêm vào `tests/test_md_knowledge.py`:

```python
from md_knowledge import MD_KNOWLEDGE_SCHEMA


class SchemaShapeTest(unittest.TestCase):
    def test_schema_has_tables(self):
        for tbl in ("ai_md_documents", "ai_md_passages", "ai_md_quotes"):
            self.assertIn(tbl, MD_KNOWLEDGE_SCHEMA)
```

- [ ] **Step 2: Chạy test — phải fail**

Run: `python -m unittest tests.test_md_knowledge -v`
Expected: FAIL (`ImportError: MD_KNOWLEDGE_SCHEMA`).

- [ ] **Step 3: Thêm schema + index + retrieve**

Đọc `pdf_knowledge.py` các vùng đã nêu để sao đúng pattern (hàm `_content_hash`, cách upsert 2 bảng, FTS index `to_tsvector('simple', ...)`, cách `retrieve_pdf_knowledge` chấm điểm và trả `chunks`). Thêm vào `md_knowledge.py`:

```python
import hashlib

MD_KNOWLEDGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_md_documents (
    doc_key TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source TEXT,
    content_hash TEXT NOT NULL,
    passage_count INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS ai_md_passages (
    doc_key TEXT NOT NULL,
    passage_index INTEGER NOT NULL,
    title TEXT,
    content TEXT NOT NULL,
    source TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ai_md_passages_fts
ON ai_md_passages USING GIN (to_tsvector('simple', coalesce(title,'') || ' ' || coalesce(content,'')));
CREATE TABLE IF NOT EXISTS ai_md_quotes (
    doc_key TEXT NOT NULL,
    quote TEXT NOT NULL,
    author TEXT,
    passage_title TEXT,
    source TEXT
);
"""


def _content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def ensure_md_schema(db) -> None:
    await db.execute(MD_KNOWLEDGE_SCHEMA)


async def index_md_bytes(db, title: str, data: bytes, *, source: str = "", created_by=None) -> dict:
    await ensure_md_schema(db)
    doc_key = (source or title or _content_hash(data)[:16]).strip().lower()
    content_hash = _content_hash(data)
    current = await db.fetchrow("SELECT content_hash FROM ai_md_documents WHERE doc_key = $1", doc_key)
    parsed = parse_markdown(data.decode("utf-8", errors="replace"))
    doc_title = title or parsed["title"] or doc_key
    doc_source = source or parsed.get("source", "")
    if current and current["content_hash"] == content_hash:
        return {"doc_key": doc_key, "title": doc_title, "passages": 0, "quotes": 0, "changed": False}
    async with db.acquire() if hasattr(db, "acquire") else _null_ctx(db) as conn:
        await conn.execute("DELETE FROM ai_md_passages WHERE doc_key = $1", doc_key)
        await conn.execute("DELETE FROM ai_md_quotes WHERE doc_key = $1", doc_key)
        for i, p in enumerate(parsed["passages"]):
            await conn.execute(
                "INSERT INTO ai_md_passages (doc_key, passage_index, title, content, source) VALUES ($1,$2,$3,$4,$5)",
                doc_key, i, p["title"], p["content"], doc_source,
            )
        for q in parsed["quotes"]:
            await conn.execute(
                "INSERT INTO ai_md_quotes (doc_key, quote, author, passage_title, source) VALUES ($1,$2,$3,$4,$5)",
                doc_key, q["quote"], q["author"], q["passage_title"], doc_source,
            )
        await conn.execute(
            """
            INSERT INTO ai_md_documents (doc_key, title, source, content_hash, passage_count, updated_at)
            VALUES ($1,$2,$3,$4,$5, now())
            ON CONFLICT (doc_key) DO UPDATE SET
                title = EXCLUDED.title, source = EXCLUDED.source,
                content_hash = EXCLUDED.content_hash, passage_count = EXCLUDED.passage_count,
                updated_at = now()
            """,
            doc_key, doc_title, doc_source, content_hash, len(parsed["passages"]),
        )
    return {"doc_key": doc_key, "title": doc_title,
            "passages": len(parsed["passages"]), "quotes": len(parsed["quotes"]), "changed": True}


class _null_ctx:
    def __init__(self, db): self.db = db
    async def __aenter__(self): return self.db
    async def __aexit__(self, *a): return False


async def retrieve_md_knowledge(db, query: str, *, limit: int = 5) -> dict:
    await ensure_md_schema(db)
    rows = await db.fetch(
        """
        SELECT doc_key, title, content, source,
               ts_rank(to_tsvector('simple', coalesce(title,'') || ' ' || coalesce(content,'')),
                       plainto_tsquery('simple', $1)) AS rank
        FROM ai_md_passages
        WHERE to_tsvector('simple', coalesce(title,'') || ' ' || coalesce(content,''))
              @@ plainto_tsquery('simple', $1)
        ORDER BY rank DESC
        LIMIT $2
        """,
        query, limit,
    )
    chunks = [{"title": r["title"], "content": r["content"], "source": r["source"],
               "chunk_index": i, "page": None} for i, r in enumerate(rows)]
    qrows = await db.fetch(
        """
        SELECT q.quote, q.author, q.source, d.title
        FROM ai_md_quotes q JOIN ai_md_documents d ON d.doc_key = q.doc_key
        WHERE to_tsvector('simple', coalesce(q.quote,'') || ' ' || coalesce(q.author,''))
              @@ plainto_tsquery('simple', $1)
        LIMIT $2
        """,
        query, max(limit, 8),
    )
    quotes = [{"quote": r["quote"], "author": r["author"] or "", "source": r["source"], "title": r["title"]}
              for r in qrows]
    top = float(rows[0]["rank"]) if rows else 0.0
    return {"chunks": chunks, "quotes": quotes, "selected_count": len(chunks),
            "candidate_count": len(chunks), "top_score": top}
```

- [ ] **Step 4: Chạy test — phải pass**

Run: `python -m unittest tests.test_md_knowledge -v`
Expected: PASS (7 test: 6 parse + 1 schema).

- [ ] **Step 5: Kiểm import sạch**

Run: `python -c "import md_knowledge"`
Expected: không lỗi.

- [ ] **Step 6: Commit**

```bash
git add md_knowledge.py tests/test_md_knowledge.py
git commit -m "Add markdown knowledge schema, indexing, and retrieval"
```

---

## Self-Review

**Spec coverage (A1):** parse .md (heading→passage, blockquote→quote/author) → Task 1 ✔; schema + index idempotent + retrieve pdf_meta-shape → Task 2 ✔. Wire ai.py = A2 (ngoài A1). DB unit test bỏ qua (theo pattern test PDF chỉ test hàm thuần); `parse_markdown` test đầy đủ.

**Placeholder scan:** không TBD; mọi step có code/command. `_null_ctx` xử lý cả pool (`acquire`) lẫn connection trực tiếp.

**Type consistency:** `parse_markdown->dict{title,source,passages,quotes}`; `index_md_bytes->dict{doc_key,title,passages,quotes,changed}`; `retrieve_md_knowledge->dict{chunks,quotes,selected_count,candidate_count,top_score}` — pdf_meta-shape để A2 wire thẳng vào QuoteExtractor/Formatter.
