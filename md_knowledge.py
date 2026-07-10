import hashlib
import re

import asyncpg
import os as _os

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")

# Parser BAO DUNG dinh dang: nhan dinh co the mo dau bang +, -, *, > hoac dau ngoac kep
# dung dau dong; tac gia trong (…) hoac sau — o cuoi; tho nhieu dong voi tac gia o dong duoi.
_OPEN_QUOTES = "“\"'‘"
_CLOSE_QUOTES = "”\"'’"
_LINE_START = re.compile(r'^\s*(?:[+\-*>•]\s*)?(?P<oq>[“"])')
_ATTR_PAREN = re.compile(r'\(([^)\n]{2,120})\)')
_ATTR_DASH = re.compile(r'^[\s.]*[—–-]\s*(?P<name>[^"“”(\n]{2,80})\s*$')
_PAREN_ONLY_LINE = re.compile(r'^\s*\(([^)\n]{2,120})\)\s*\.?\s*$')

# Danh xung thuong gap truoc ten tac gia — bo khi chuan hoa.
_ROLE_PREFIXES = (
    "nha tho", "nha van", "nha nghien cuu", "nha phe binh", "nha viet kich", "nha bao",
    "nha triet hoc", "triet gia", "hoc gia", "dich gia", "nhac si", "dao dien",
    "giao su", "pho giao su", "tien si", "gs", "pgs", "ts", "thac si", "ths",
)


def _plain(text: str) -> str:
    import unicodedata
    folded = unicodedata.normalize("NFD", text or "")
    return "".join(ch for ch in folded if unicodedata.category(ch) != "Mn").lower().strip()


def _clean_author(raw: str) -> str:
    # "(Pablo Neruda, nha tho quoc dan cua Chile, ...)" -> "Pablo Neruda"
    # "(Nha van Ly Nhue - Trung Quoc)" -> "Ly Nhue"
    value = (raw or "").strip().strip(".")
    value = value.split(",")[0]
    value = re.split(r"\s[—–-]\s", value)[0].strip()
    changed = True
    while changed:
        changed = False
        plain = _plain(value)
        for role in _ROLE_PREFIXES:
            if plain.startswith(role + " "):
                value = value[len(role):].strip()
                changed = True
                break
    tokens = [t for t in value.split() if t]
    if not tokens or len(tokens) > 6 or len(value) > 60:
        return ""
    if not tokens[0][:1].isupper():
        return ""
    capitalised = sum(1 for t in tokens if t[:1].isupper())
    # >=50% de nhan ten phien am kieu "Sê khốp", "Đôxtôiepxki"
    if capitalised / len(tokens) < 0.5:
        return ""
    return value


def _extract_quote_facts(lines: list[str], passage_title: str) -> list[dict]:
    facts: list[dict] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _LINE_START.match(line)
        if not m:
            i += 1
            continue
        open_pos = m.end() - 1
        rest = line[open_pos + 1:]
        quote_lines: list[str] = []
        tail = ""
        consumed = 0
        # tim dau dong ngoac kep, co the o dong sau (tho nhieu dong)
        scan = rest
        j = i
        while True:
            close_idx = next((k for k, ch in enumerate(scan) if ch in _CLOSE_QUOTES), -1)
            if close_idx >= 0:
                quote_lines.append(scan[:close_idx])
                tail = scan[close_idx + 1:]
                break
            quote_lines.append(scan)
            j += 1
            if j >= len(lines) or j - i > 12:
                quote_lines = []
                break
            scan = lines[j]
        if not quote_lines:
            i += 1
            continue
        quote = " ".join(part.strip() for part in quote_lines if part.strip()).strip()
        if len(quote) < 15:
            i = j + 1
            continue
        author = ""
        pm = _ATTR_PAREN.search(tail)
        if pm:
            author = _clean_author(pm.group(1))
        if not author:
            dm = _ATTR_DASH.match(tail)
            if dm:
                author = _clean_author(dm.group("name"))
        if not author and not tail.strip():
            # tac gia co the nam o 1-2 dong ke tiep dang "(Ten)"
            for look in range(j + 1, min(j + 3, len(lines))):
                if not lines[look].strip():
                    continue
                pl = _PAREN_ONLY_LINE.match(lines[look])
                if pl:
                    author = _clean_author(pl.group(1))
                    consumed = look - j
                break
        facts.append({"quote": quote, "author": author, "passage_title": passage_title})
        i = j + 1 + consumed
    return facts


def _fallback_passages(content: str, max_chars: int = 1200) -> list[dict]:
    # file khong co heading: gom cac doan van (cach nhau dong trong) thanh block ~max_chars
    paragraphs = []
    for para in re.split(r"\n\s*\n", content):
        para = para.strip()
        if not para:
            continue
        if len(para) <= max_chars:
            paragraphs.append(para)
            continue
        # doan qua kho (vd danh sach nhan dinh khong co dong trong): cat theo dong
        cur = ""
        for line in para.split("\n"):
            if cur and len(cur) + len(line) + 1 > max_chars:
                paragraphs.append(cur)
                cur = line
            else:
                cur = f"{cur}\n{line}" if cur else line
        if cur:
            paragraphs.append(cur)
    blocks: list[str] = []
    cur = ""
    for para in paragraphs:
        if cur and len(cur) + len(para) + 2 > max_chars:
            blocks.append(cur)
            cur = para
        else:
            cur = f"{cur}\n\n{para}" if cur else para
    if cur:
        blocks.append(cur)
    return [{"title": "", "content": b} for b in blocks]


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


def _preprocess(text: str) -> str:
    # don dep artefact tu pandoc/converter: \+ \- \" \' va span [x]{.mark}
    text = re.sub(r"\\([+\-\"'*.])", r"\1", text)
    text = re.sub(r"\[([^\[\]]*)\]\{\.[^}]+\}", r"\1", text)
    text = text.replace("**", "")
    return text


def parse_markdown(text: str) -> dict:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = _preprocess(text)
    meta, body = _parse_frontmatter(text)

    # 1) chia section theo heading (neu co)
    sections: list[tuple[str, list[str]]] = []
    cur_title = ""
    cur_lines: list[str] = []
    for line in body.split("\n"):
        m = _HEADING.match(line)
        if m:
            if cur_title or any(l.strip() for l in cur_lines):
                sections.append((cur_title, cur_lines))
            cur_title = m.group(2).strip()
            cur_lines = []
            continue
        cur_lines.append(line)
    if cur_title or any(l.strip() for l in cur_lines):
        sections.append((cur_title, cur_lines))

    # 2) trich fact nhan dinh + dung passage
    passages: list[dict] = []
    quotes: list[dict] = []
    for title, lines in sections:
        quotes.extend(_extract_quote_facts(lines, title))
        content = "\n".join(lines).strip()
        if not (title or content):
            continue
        if len(content) > 1500:
            for idx, block in enumerate(_fallback_passages(content)):
                part_title = title if idx == 0 else (f"{title} (tiếp {idx})" if title else "")
                passages.append({"title": part_title, "content": block["content"]})
        else:
            passages.append({"title": title, "content": content})

    title = meta.get("title") or (sections[0][0] if sections and sections[0][0] else "")
    if not title:
        first_line = next((l.strip() for l in body.split("\n") if l.strip()), "")
        if len(first_line) <= 100 and not _LINE_START.match(first_line):
            title = first_line
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


async def search_md_knowledge(db, query: str, *, limit: int = 5) -> str:
    result = await retrieve_md_knowledge(db, query, limit=limit)
    return result.get("context", "")


async def index_md_path(database_url: str, path) -> dict:
    with open(path, "rb") as f:
        data = f.read()
    title = _os.path.splitext(_os.path.basename(str(path)))[0]
    conn = await asyncpg.connect(database_url)
    try:
        return await index_md_bytes(conn, title, data, source=str(path))
    finally:
        await conn.close()
