import hashlib
import io
import os
import re
from pathlib import Path

import asyncpg
from pypdf import PdfReader


PDF_CHUNK_SIZE = 1800
PDF_CHUNK_OVERLAP = 220
PDF_MAX_CHUNKS_PER_DOC = 2200
OCR_MIN_TEXT_CHARS = 350
PDF_SEARCH_LIMIT_DEFAULT = 5
PDF_SEARCH_CANDIDATE_LIMIT = 300

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
CREATE INDEX IF NOT EXISTS idx_ai_pdf_chunks_fts_simple
ON ai_pdf_chunks USING GIN (to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(content, '')));
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


def _safe_doc_key(title: str, source: str = "") -> str:
    source_l = (source or "").lower()
    bot_dir = os.getenv("HVHN_BOT_DOCS_DIR", str(Path(__file__).resolve().parent / "bot_docs")).lower()
    namespace = "bot" if source_l.startswith("bot_only:") or (bot_dir and source_l.startswith(bot_dir)) else "exclusive"
    return _safe_key(namespace + "__" + title)


def _source_label(source: str, title: str) -> str:
    source_l = (source or "").lower()
    bot_dir = os.getenv("HVHN_BOT_DOCS_DIR", str(Path(__file__).resolve().parent / "bot_docs")).lower()
    if source_l.startswith("bot_only:") or (bot_dir and source_l.startswith(bot_dir)):
        return f"{title} (kho riêng cho bot)"
    return f"{title} (kho độc quyền)"


def _content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _env_flag(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _env_int(name: str, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _extract_native_pdf_text(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception:
        return ""
    pages = []
    max_pages = _env_int("HVHN_NATIVE_PDF_MAX_PAGES", 300, minimum=0)
    page_limit = len(reader.pages) if max_pages == 0 else min(len(reader.pages), max_pages)
    for index, page in enumerate(reader.pages[:page_limit], start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        text = _clean_text(text)
        if text:
            pages.append(f"[Trang {index}]\n{text}")
    if max_pages and len(reader.pages) > max_pages:
        pages.append(f"[Ghi chu]\nDa doc {max_pages}/{len(reader.pages)} trang theo gioi han HVHN_NATIVE_PDF_MAX_PAGES.")
    return _clean_text("\n\n".join(pages))


def _ocr_pdf_text_from_bytes(data: bytes) -> str:
    try:
        import fitz
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(f"Thiếu thư viện OCR: {exc}") from exc

    tesseract_cmd = os.getenv("HVHN_TESSERACT_CMD") or os.getenv("TESSERACT_CMD")
    if not tesseract_cmd:
        for candidate in (
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ):
            if Path(candidate).is_file():
                tesseract_cmd = candidate
                break
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    tessdata_dir = os.getenv("HVHN_TESSDATA_DIR") or str(Path(__file__).resolve().parent / "tessdata")
    ocr_config = "--psm 6"
    if Path(tessdata_dir).is_dir():
        os.environ.setdefault("TESSDATA_PREFIX", tessdata_dir)
        ocr_config = f"--tessdata-dir {tessdata_dir} --psm 6"

    lang = os.getenv("HVHN_OCR_LANG", "vie+eng")
    fallback_lang = os.getenv("HVHN_OCR_FALLBACK_LANG", "eng")
    dpi = _env_int("HVHN_OCR_DPI", 220, minimum=120, maximum=350)
    max_pages = _env_int("HVHN_OCR_MAX_PAGES", 300, minimum=0)
    zoom = dpi / 72

    pages = []
    with fitz.open(stream=data, filetype="pdf") as doc:
        total_pages = doc.page_count
        page_limit = total_pages if max_pages == 0 else min(total_pages, max_pages)
        matrix = fitz.Matrix(zoom, zoom)
        for page_index in range(page_limit):
            page = doc.load_page(page_index)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            image = Image.open(io.BytesIO(pix.tobytes("png")))
            try:
                text = pytesseract.image_to_string(image, lang=lang, config=ocr_config)
            except Exception as exc:
                if fallback_lang and fallback_lang != lang:
                    try:
                        text = pytesseract.image_to_string(image, lang=fallback_lang, config=ocr_config)
                    except Exception as fallback_exc:
                        raise RuntimeError(f"Tesseract OCR lỗi ở trang {page_index + 1}: {fallback_exc}") from fallback_exc
                else:
                    raise RuntimeError(f"Tesseract OCR lỗi ở trang {page_index + 1}: {exc}") from exc

            text = _clean_text(text)
            if text:
                pages.append(f"[Trang {page_index + 1} - OCR]\n{text}")
            image.close()
            del pix

        if max_pages and total_pages > max_pages:
            pages.append(f"[Ghi chú OCR]\nĐã OCR {max_pages}/{total_pages} trang theo giới hạn HVHN_OCR_MAX_PAGES.")

    return _clean_text("\n\n".join(pages))


def extract_pdf_text_from_bytes(data: bytes) -> str:
    native_text = _extract_native_pdf_text(data)
    min_text = _env_int("HVHN_OCR_MIN_TEXT_CHARS", OCR_MIN_TEXT_CHARS, minimum=0)
    if len(native_text) >= min_text or not _env_flag("HVHN_OCR_ENABLED", True):
        return native_text

    try:
        ocr_text = _ocr_pdf_text_from_bytes(data)
    except Exception as exc:
        print(f"[AI PDF] OCR chưa chạy được: {exc}", flush=True)
        return native_text
    return ocr_text if len(ocr_text) > len(native_text) else native_text


def extract_pdf_text_from_path(path: str | os.PathLike) -> str:
    return extract_pdf_text_from_bytes(Path(path).read_bytes())


def build_chunks(text: str) -> list[str]:
    text = _clean_text(text)
    if not text:
        return []

    chunks = []
    start = 0
    max_chunks = _env_int("HVHN_PDF_MAX_CHUNKS_PER_DOC", PDF_MAX_CHUNKS_PER_DOC, minimum=100)
    while start < len(text) and len(chunks) < max_chunks:
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
    try:
        await db.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_ai_pdf_chunks_trgm_content ON ai_pdf_chunks USING GIN (content gin_trgm_ops)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_ai_pdf_chunks_trgm_title ON ai_pdf_chunks USING GIN (title gin_trgm_ops)"
        )
    except Exception as exc:
        print(f"[AI PDF] pg_trgm unavailable; using FTS/keyword fallback: {exc}", flush=True)


async def index_pdf_bytes(db, title: str, data: bytes, *, source: str = "", created_by: int | None = None) -> dict:
    await ensure_pdf_knowledge_schema(db)
    title = Path(title).name
    doc_key = _safe_doc_key(title, source)
    content_hash = _content_hash(data)

    current = await db.fetchrow(
        "SELECT content_hash, chunk_count FROM ai_pdf_documents WHERE doc_key = $1",
        doc_key,
    )
    retry_empty = _env_flag("HVHN_RETRY_EMPTY_PDF_OCR", True)
    if current and current["content_hash"] == content_hash and (current["chunk_count"] > 0 or not retry_empty):
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
    if title_or_key.startswith("pdf:"):
        keys = [title_or_key]
    else:
        keys = [
            _safe_key(title_or_key),
            _safe_doc_key(title_or_key, ""),
            _safe_doc_key(title_or_key, "bot_only:" + title_or_key),
        ]
    await db.execute("DELETE FROM ai_pdf_chunks WHERE doc_key = ANY($1::text[])", keys)
    await db.execute("DELETE FROM ai_pdf_documents WHERE doc_key = ANY($1::text[])", keys)


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


async def retrieve_pdf_knowledge(db, query: str, *, limit: int = PDF_SEARCH_LIMIT_DEFAULT) -> dict:
    await ensure_pdf_knowledge_schema(db)
    evidence_limit = max(1, min(limit, _env_int("HVHN_PDF_EVIDENCE_LIMIT_MAX", 8, minimum=4)))
    candidate_limit = _env_int("HVHN_PDF_SEARCH_CANDIDATE_LIMIT", PDF_SEARCH_CANDIDATE_LIMIT, minimum=80)
    terms = [t.lower() for t in re.findall(r"[\w?-?A-Za-z0-9]{3,}", query, flags=re.UNICODE)][:16]
    if not terms:
        rows = await db.fetch(
            """
            SELECT title, content, source, chunk_index, 0::float AS rank
            FROM ai_pdf_chunks
            ORDER BY updated_at DESC
            LIMIT $1
            """,
            candidate_limit,
        )
    else:
        patterns = [f"%{term}%" for term in terms]
        ts_query = " ".join(terms)
        try:
            rows = await db.fetch(
                """
                WITH q AS (SELECT websearch_to_tsquery('simple', $1) AS query)
                SELECT title, content, source, chunk_index,
                       ts_rank_cd(
                         to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(content, '')),
                         q.query
                       ) AS rank
                FROM ai_pdf_chunks, q
                WHERE to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(content, '')) @@ q.query
                   OR lower(title) LIKE ANY($2::text[])
                   OR lower(content) LIKE ANY($2::text[])
                ORDER BY rank DESC
                LIMIT $3
                """,
                ts_query,
                patterns,
                candidate_limit,
            )
        except Exception as exc:
            print(f"[AI PDF] FTS search fallback: {exc}", flush=True)
            rows = await db.fetch(
                """
                SELECT title, content, source, chunk_index, 0::float AS rank
                FROM ai_pdf_chunks
                WHERE lower(title) LIKE ANY($1::text[])
                   OR lower(content) LIKE ANY($1::text[])
                LIMIT $2
                """,
                patterns,
                candidate_limit,
            )

    def score(row) -> int:
        haystack = f"{row['title']} {row['content']}".lower()
        return sum(haystack.count(term) for term in terms) + sum(3 for term in terms if term in row["title"].lower())

    ranked = sorted(rows, key=lambda row: (float(row["rank"] or 0), score(row)), reverse=True)
    selected = ranked[:evidence_limit]
    doc_refs = {}
    for row in selected:
        title = _source_label(row["source"] or "", row["title"])
        if title not in doc_refs:
            doc_refs[title] = len(doc_refs) + 1

    blocks = []
    if doc_refs:
        blocks.append(
            "TAI LIEU PDF LIEN QUAN (chi neu tai lieu that su dung):\n"
            + "\n".join(f"[{ref_no}] {title}" for title, ref_no in doc_refs.items())
        )
        blocks.append(
            "Quy uoc: [P...] la ma doan noi bo; [1], [2] la so tai lieu PDF co the neu trong ghi chu nguon neu can."
        )
        blocks.append(f"Da quet va rerank {len(rows)} ung vien PDF; chi dua {len(selected)} bang chung gon nhat vao prompt.")

    def best_excerpt(content: str, max_chars: int) -> str:
        if len(content) <= max_chars:
            return content
        lowered = content.lower()
        hits = [lowered.find(term) for term in terms if term and lowered.find(term) >= 0]
        if hits:
            center = min(hits)
            start = max(0, center - max_chars // 3)
        else:
            start = 0
        end = min(len(content), start + max_chars)
        excerpt = content[start:end].strip()
        if start > 0:
            excerpt = "..." + excerpt
        if end < len(content):
            excerpt += "..."
        return excerpt

    selected_meta = []
    for index, row in enumerate(selected, start=1):
        raw_content = row["content"]
        content = raw_content
        chunk_chars = _env_int("HVHN_PDF_SEARCH_CHUNK_CHARS", 850, minimum=500, maximum=1200)
        content = best_excerpt(content, chunk_chars)
        source = row["source"] or row["title"]
        ref_title = _source_label(source, row["title"])
        ref_no = doc_refs[ref_title]
        fts_rank = float(row["rank"] or 0)
        keyword_score = score(row)
        blocks.append(
            f"[P{index}] Tai lieu [{ref_no}] - {row['title']} - doan {row['chunk_index']}\n"
            f"Nguon PDF: {source}\n{content}"
        )
        selected_meta.append(
            {
                "index": index,
                "title": row["title"],
                "source": source,
                "chunk_index": row["chunk_index"],
                "rank": fts_rank,
                "keyword_score": keyword_score,
                "score": fts_rank + keyword_score,
                "excerpt": content,
                "first_500": raw_content[:500],
            }
        )
    top_score = selected_meta[0]["score"] if selected_meta else 0
    return {
        "context": "\n\n".join(blocks),
        "candidate_count": len(rows),
        "selected_count": len(selected_meta),
        "top_score": top_score,
        "chunks": selected_meta,
    }


async def search_pdf_knowledge(db, query: str, *, limit: int = PDF_SEARCH_LIMIT_DEFAULT) -> str:
    result = await retrieve_pdf_knowledge(db, query, limit=limit)
    return result["context"]


async def pdf_knowledge_stats(db, *, limit_zero: int = 15) -> dict:
    await ensure_pdf_knowledge_schema(db)
    total_docs = await db.fetchval("SELECT count(*) FROM ai_pdf_documents")
    total_chunks = await db.fetchval("SELECT coalesce(sum(chunk_count), 0) FROM ai_pdf_documents")
    zero_docs = await db.fetch(
        """
        SELECT title, source, updated_at
        FROM ai_pdf_documents
        WHERE chunk_count = 0
        ORDER BY updated_at DESC
        LIMIT $1
        """,
        limit_zero,
    )
    by_source = await db.fetch(
        """
        SELECT
          CASE
            WHEN lower(coalesce(source, '')) LIKE '%bot_docs%' OR lower(coalesce(source, '')) LIKE 'bot_only:%'
              THEN 'bot'
            ELSE 'exclusive'
          END AS kind,
          count(*) AS docs,
          coalesce(sum(chunk_count), 0) AS chunks
        FROM ai_pdf_documents
        GROUP BY kind
        """
    )
    return {
        "total_docs": int(total_docs or 0),
        "total_chunks": int(total_chunks or 0),
        "zero_docs": [dict(row) for row in zero_docs],
        "by_source": {row["kind"]: {"docs": int(row["docs"]), "chunks": int(row["chunks"])} for row in by_source},
    }
