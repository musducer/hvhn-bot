import hashlib
import io
import os
import re
from pathlib import Path

import asyncpg
from pypdf import PdfReader


PDF_CHUNK_SIZE = 1800
PDF_CHUNK_OVERLAP = 220
PDF_MAX_CHUNKS_PER_DOC = 500

PDF_KNOWLEDGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_pdf_documents (
    doc_key TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source TEXT,
    content_hash TEXT NOT NULL,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ai_pdf_chunks (
    doc_key TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (doc_key, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_ai_pdf_chunks_title_lower ON ai_pdf_chunks (lower(title));
"""


def _clean_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _safe_key(title: str) -> str:
    stem = Path(title).stem.lower()
    stem = re.sub(r"[^a-z0-9A-ZÀ-ỹ]+", "-", stem, flags=re.UNICODE).strip("-")
    return "pdf:" + (stem[:140] or "tai-lieu")


def _content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def extract_pdf_text_from_bytes(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    pages = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        text = _clean_text(text)
        if text:
            pages.append(f"[Trang {index}]\n{text}")
    return _clean_text("\n\n".join(pages))


def extract_pdf_text_from_path(path: str | os.PathLike) -> str:
    return extract_pdf_text_from_bytes(Path(path).read_bytes())


def build_chunks(text: str) -> list[str]:
    text = _clean_text(text)
    if not text:
        return []

    chunks = []
    start = 0
    while start < len(text) and len(chunks) < PDF_MAX_CHUNKS_PER_DOC:
        end = min(start + PDF_CHUNK_SIZE, len(text))
        if end < len(text):
            cut = max(text.rfind("\n\n", start, end), text.rfind(". ", start, end), text.rfind(" ", start, end))
            if cut > start + PDF_CHUNK_SIZE // 2:
                end = cut + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(0, end - PDF_CHUNK_OVERLAP)
    return chunks


async def ensure_pdf_knowledge_schema(db) -> None:
    await db.execute(PDF_KNOWLEDGE_SCHEMA)


async def index_pdf_bytes(db, title: str, data: bytes, *, source: str = "", created_by: int | None = None) -> dict:
    await ensure_pdf_knowledge_schema(db)
    title = Path(title).name
    doc_key = _safe_key(title)
    content_hash = _content_hash(data)

    current = await db.fetchrow(
        "SELECT content_hash, chunk_count FROM ai_pdf_documents WHERE doc_key = $1",
        doc_key,
    )
    if current and current["content_hash"] == content_hash:
        return {"doc_key": doc_key, "title": title, "chunks": current["chunk_count"], "changed": False}

    text = extract_pdf_text_from_bytes(data)
    chunks = build_chunks(text)
    if not chunks:
        await db.execute("DELETE FROM ai_pdf_chunks WHERE doc_key = $1", doc_key)
        await db.execute(
            """
            INSERT INTO ai_pdf_documents (doc_key, title, source, content_hash, chunk_count, updated_at)
            VALUES ($1, $2, $3, $4, 0, now())
            ON CONFLICT (doc_key) DO UPDATE
            SET title = EXCLUDED.title,
                source = EXCLUDED.source,
                content_hash = EXCLUDED.content_hash,
                chunk_count = 0,
                updated_at = now()
            """,
            doc_key,
            title,
            source,
            content_hash,
        )
        return {"doc_key": doc_key, "title": title, "chunks": 0, "changed": True}

    ctx = db.acquire() if hasattr(db, "acquire") else _NullAsyncContext(db)
    async with ctx as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM ai_pdf_chunks WHERE doc_key = $1", doc_key)
            await conn.executemany(
                """
                INSERT INTO ai_pdf_chunks (doc_key, chunk_index, title, content, source, updated_at)
                VALUES ($1, $2, $3, $4, $5, now())
                """,
                [(doc_key, i, title, chunk, source) for i, chunk in enumerate(chunks, start=1)],
            )
            await conn.execute(
                """
                INSERT INTO ai_pdf_documents (doc_key, title, source, content_hash, chunk_count, updated_at)
                VALUES ($1, $2, $3, $4, $5, now())
                ON CONFLICT (doc_key) DO UPDATE
                SET title = EXCLUDED.title,
                    source = EXCLUDED.source,
                    content_hash = EXCLUDED.content_hash,
                    chunk_count = EXCLUDED.chunk_count,
                    updated_at = now()
                """,
                doc_key,
                title,
                source,
                content_hash,
                len(chunks),
            )
    return {"doc_key": doc_key, "title": title, "chunks": len(chunks), "changed": True}


class _NullAsyncContext:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        return False


async def index_pdf_path(database_url: str, path: str | os.PathLike) -> dict:
    conn = await asyncpg.connect(database_url)
    try:
        path = Path(path)
        return await index_pdf_bytes(conn, path.name, path.read_bytes(), source=str(path))
    finally:
        await conn.close()


async def remove_pdf_document(db, title_or_key: str) -> None:
    await ensure_pdf_knowledge_schema(db)
    doc_key = title_or_key if title_or_key.startswith("pdf:") else _safe_key(title_or_key)
    await db.execute("DELETE FROM ai_pdf_chunks WHERE doc_key = $1", doc_key)
    await db.execute("DELETE FROM ai_pdf_documents WHERE doc_key = $1", doc_key)


async def remove_pdf_document_by_title(database_url: str, title_or_key: str) -> None:
    conn = await asyncpg.connect(database_url)
    try:
        await remove_pdf_document(conn, title_or_key)
    finally:
        await conn.close()


async def sync_pdf_folder(database_url: str, folder: str | os.PathLike) -> dict:
    folder = Path(folder)
    conn = await asyncpg.connect(database_url)
    try:
        await ensure_pdf_knowledge_schema(conn)
        paths = sorted(folder.glob("*.pdf")) if folder.exists() else []
        seen_keys = set()
        indexed = 0
        changed = 0
        for path in paths:
            result = await index_pdf_bytes(conn, path.name, path.read_bytes(), source=str(path))
            seen_keys.add(result["doc_key"])
            indexed += 1
            if result["changed"]:
                changed += 1

        folder_prefix = str(folder)
        if seen_keys:
            await conn.execute(
                """
                DELETE FROM ai_pdf_chunks
                WHERE doc_key IN (
                    SELECT doc_key FROM ai_pdf_documents
                    WHERE source LIKE $1 AND doc_key <> ALL($2::text[])
                )
                """,
                folder_prefix + "%",
                list(seen_keys),
            )
            await conn.execute(
                "DELETE FROM ai_pdf_documents WHERE source LIKE $1 AND doc_key <> ALL($2::text[])",
                folder_prefix + "%",
                list(seen_keys),
            )
        elif folder.exists():
            await conn.execute(
                """
                DELETE FROM ai_pdf_chunks
                WHERE doc_key IN (
                    SELECT doc_key FROM ai_pdf_documents
                    WHERE source LIKE $1
                )
                """,
                folder_prefix + "%",
            )
            await conn.execute("DELETE FROM ai_pdf_documents WHERE source LIKE $1", folder_prefix + "%")
        return {"indexed": indexed, "changed": changed}
    finally:
        await conn.close()


async def search_pdf_knowledge(db, query: str, *, limit: int = 10) -> str:
    await ensure_pdf_knowledge_schema(db)
    terms = [t.lower() for t in re.findall(r"[\wÀ-ỹ]{3,}", query, flags=re.UNICODE)][:8]
    if not terms:
        rows = await db.fetch(
            """
            SELECT title, content, source, chunk_index
            FROM ai_pdf_chunks
            ORDER BY updated_at DESC
            LIMIT $1
            """,
            limit,
        )
    else:
        patterns = [f"%{term}%" for term in terms]
        rows = await db.fetch(
            """
            SELECT title, content, source, chunk_index
            FROM ai_pdf_chunks
            WHERE lower(title) LIKE ANY($1::text[])
               OR lower(content) LIKE ANY($1::text[])
            ORDER BY updated_at DESC
            LIMIT 80
            """,
            patterns,
        )

    def score(row) -> int:
        haystack = f"{row['title']} {row['content']}".lower()
        return sum(haystack.count(term) for term in terms) + sum(3 for term in terms if term in row["title"].lower())

    ranked = sorted(rows, key=score, reverse=True)[:limit]
    blocks = []
    for index, row in enumerate(ranked, start=1):
        content = row["content"]
        if len(content) > 1200:
            content = content[:1200] + "..."
        source = row["source"] or row["title"]
        blocks.append(f"[P{index}] {row['title']} - đoạn {row['chunk_index']}\nNguồn PDF: {source}\n{content}")
    return "\n\n".join(blocks)
