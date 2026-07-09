import hashlib
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
        async with conn.transaction():
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


def build_md_context(chunks: list[dict]) -> str:
    blocks = []
    for i, c in enumerate(chunks, start=1):
        title = c.get("title") or ""
        source = c.get("source") or title
        content = c.get("excerpt") or c.get("content") or ""
        blocks.append(f"[P{i}] Tai lieu MD - {title} - doan {c.get('chunk_index')}\nNguon MD: {source}\n{content}")
    return "\n\n".join(blocks)


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
    chunks = [{"title": r["title"], "content": r["content"], "excerpt": r["content"],
               "source": r["source"], "chunk_index": i, "page": None} for i, r in enumerate(rows)]
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
    return {"context": build_md_context(chunks), "chunks": chunks, "quotes": quotes,
            "selected_count": len(chunks), "candidate_count": len(chunks), "top_score": top}
