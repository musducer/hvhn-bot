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
    stripped = "".join(ch for ch in folded if unicodedata.category(ch) != "Mn")
    # đ/Đ khong phan huy bang NFD -> map tay cho khop voi Postgres unaccent()
    return stripped.replace("đ", "d").replace("Đ", "d").lower().strip()


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
    if _plain(value) in _ROLE_PREFIXES:
        return ""  # chi con danh xung, khong co ten
    if not tokens[0][:1].isupper():
        return ""
    capitalised = sum(1 for t in tokens if t[:1].isupper())
    # >=50% de nhan ten phien am kieu "Sê khốp", "Đôxtôiepxki"
    if capitalised / len(tokens) < 0.5:
        return ""
    return value


_AUTHOR_KEYS = ("tac gia", "author", "tac gia tai lieu")


def _detect_author(meta: dict, body: str) -> str:
    # 1) frontmatter: author / tác giả
    for k, v in meta.items():
        if _plain(k) in _AUTHOR_KEYS and (v or "").strip():
            return _clean_author(v) or v.strip()
    # 2) dong metadata gan dau file: "Tác giả: Chu Văn Sơn"
    seen = 0
    for line in body.split("\n"):
        s = line.strip()
        if not s:
            continue
        seen += 1
        if seen > 10:
            break
        m = re.match(r"^\s*([^:：]{2,24})[:：]\s*(.+)$", s)
        if m and _plain(m.group(1)) in _AUTHOR_KEYS and m.group(2).strip():
            return _clean_author(m.group(2)) or m.group(2).strip()
    return ""


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
    author = _detect_author(meta, body)
    return {"title": title, "author": author, "source": meta.get("source", ""),
            "passages": passages, "quotes": quotes}


MD_KNOWLEDGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_md_documents (
    doc_key TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    author TEXT,
    source TEXT,
    content_hash TEXT NOT NULL,
    passage_count INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE ai_md_documents ADD COLUMN IF NOT EXISTS author TEXT;
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
    # unaccent: khop tra cuu khong phan biet dau (go sai/thieu dau van trung). Optional.
    try:
        await db.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    except Exception:
        pass
    # pgvector: tra cuu ngu nghia. Neu khong co ext thi bo qua (hybrid tu dong lui ve tu khoa).
    try:
        from md_embeddings import active_dim, active_signature, has_keys
        # AN TOAN: process KHONG co embedding key (vd watcher tren PC) TUYET DOI khong duoc
        # dong vao schema embedding — truoc day no lam active_signature() mac dinh 'gemini:768'
        # roi DROP cot, xoa sach embedding cua provider that (Jina/Voyage) do bot Render tao.
        # Chi tien trinh CO key (bot/backfill) moi so huu migration embedding.
        if not has_keys():
            return
        dimension = active_dim()
        signature = active_signature()
        await db.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await db.execute(
            "CREATE TABLE IF NOT EXISTS ai_md_embedding_config ("
            "id SMALLINT PRIMARY KEY CHECK (id = 1), signature TEXT NOT NULL)"
        )
        stored_signature = await db.fetchval(
            "SELECT signature FROM ai_md_embedding_config WHERE id = 1"
        )
        current_dimension = await db.fetchval(
            "SELECT atttypmod FROM pg_attribute "
            "WHERE attrelid = 'ai_md_passages'::regclass AND attname = 'embedding' AND NOT attisdropped"
        )
        # Embeddings from different providers/dimensions cannot be mixed.
        # This column is derived data, so recreate it and let backfill repopulate.
        if current_dimension is not None and (
            int(current_dimension) != dimension or stored_signature != signature
        ):
            await db.execute("DROP INDEX IF EXISTS idx_ai_md_passages_vec")
            await db.execute("ALTER TABLE ai_md_passages DROP COLUMN embedding")
        await db.execute(f"ALTER TABLE ai_md_passages ADD COLUMN IF NOT EXISTS embedding vector({dimension})")
        await db.execute(
            "INSERT INTO ai_md_embedding_config (id, signature) VALUES (1, $1) "
            "ON CONFLICT (id) DO UPDATE SET signature = EXCLUDED.signature",
            signature,
        )
        try:
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_ai_md_passages_vec "
                "ON ai_md_passages USING hnsw (embedding vector_cosine_ops)"
            )
        except Exception:
            pass  # hnsw can pgvector >=0.5; khong co index van chay (seq scan)
    except Exception:
        pass


async def has_passage_embeddings(db) -> bool:
    try:
        return bool(await db.fetchval("SELECT 1 FROM ai_md_passages WHERE embedding IS NOT NULL LIMIT 1"))
    except Exception:
        return False


async def count_missing_embeddings(db) -> int:
    # Tra -1 khi query loi (vd chua co cot embedding) — KHONG tra 0 gia (0 nghia la "da xong het").
    try:
        return int(await db.fetchval("SELECT count(*) FROM ai_md_passages WHERE embedding IS NULL") or 0)
    except Exception as exc:
        print(f"[md] count_missing_embeddings_error {exc}", flush=True)
        return -1


async def backfill_embeddings(db, embed_fn, *, batch: int = 40, max_passages: int = 5000,
                              pace_seconds: float = 16.0, max_rl_waits: int = 40) -> dict:
    """Nhung cac passage con thieu embedding, CO NHIP de ne quota free (100 req/phut).

    embed_fn(list[str]) -> list[list[float]] | None (async). Idempotent: chi dung embedding IS NULL.
    Khi dinh 429 (rate limited) thi nghi roi thu lai; het luot cho thi tra ok=False (chay lai sau).
    """
    import asyncio
    from md_embeddings import vec_literal, rate_limited_last, last_error
    await ensure_md_schema(db)
    done = 0
    rl_waits = 0
    while done < max_passages:
        rows = await db.fetch(
            "SELECT doc_key, passage_index, coalesce(title,'') || ' ' || coalesce(content,'') AS text "
            "FROM ai_md_passages WHERE embedding IS NULL LIMIT $1",
            batch,
        )
        if not rows:
            break
        vectors = await embed_fn([r["text"] for r in rows])
        if not vectors or len(vectors) != len(rows):
            if rate_limited_last() and rl_waits < max_rl_waits:
                rl_waits += 1
                await asyncio.sleep(30)  # het quota tam -> nghi roi thu lai chinh lo nay
                continue
            return {"embedded": done, "ok": False, "error": last_error()}
        for r, vec in zip(rows, vectors):
            await db.execute(
                "UPDATE ai_md_passages SET embedding = $3::vector WHERE doc_key = $1 AND passage_index = $2",
                r["doc_key"], r["passage_index"], vec_literal(vec),
            )
        done += len(rows)
        if len(rows) < batch:
            break
        await asyncio.sleep(pace_seconds)  # giu duoi ~100 req/phut
    return {"embedded": done, "ok": True}


async def index_md_bytes(db, title: str, data: bytes, *, source: str = "", author: str = "", created_by=None) -> dict:
    await ensure_md_schema(db)
    doc_key = (source or title or _content_hash(data)[:16]).strip().lower()
    content_hash = _content_hash(data)
    current = await db.fetchrow("SELECT content_hash, author FROM ai_md_documents WHERE doc_key = $1", doc_key)
    parsed = parse_markdown(data.decode("utf-8", errors="replace"))
    doc_title = title or parsed["title"] or doc_key
    doc_source = source or parsed.get("source", "")
    # Form-priority: tham so author > tac gia phat hien trong file.
    doc_author = (author or parsed.get("author", "") or "").strip()
    if current and current["content_hash"] == content_hash:
        # Noi dung khong doi nhung tac gia co the moi (them qua Form / metadata) -> cap nhat rieng.
        if doc_author and (current["author"] or "") != doc_author:
            await db.execute("UPDATE ai_md_documents SET author = $2 WHERE doc_key = $1", doc_key, doc_author)
        return {"doc_key": doc_key, "title": doc_title, "author": doc_author, "passages": 0, "quotes": 0, "changed": False}
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
                INSERT INTO ai_md_documents (doc_key, title, author, source, content_hash, passage_count, updated_at)
                VALUES ($1,$2,$3,$4,$5,$6, now())
                ON CONFLICT (doc_key) DO UPDATE SET
                    title = EXCLUDED.title, author = EXCLUDED.author, source = EXCLUDED.source,
                    content_hash = EXCLUDED.content_hash, passage_count = EXCLUDED.passage_count,
                    updated_at = now()
                """,
                doc_key, doc_title, doc_author, doc_source, content_hash, len(parsed["passages"]),
            )
    return {"doc_key": doc_key, "title": doc_title, "author": doc_author,
            "passages": len(parsed["passages"]), "quotes": len(parsed["quotes"]), "changed": True}


class _null_ctx:
    def __init__(self, db): self.db = db
    async def __aenter__(self): return self.db
    async def __aexit__(self, *a): return False


def build_md_context(chunks: list[dict]) -> str:
    blocks = []
    for i, c in enumerate(chunks, start=1):
        title = c.get("doc_title") or c.get("title") or ""
        author = (c.get("author") or "").strip()
        content = c.get("excerpt") or c.get("content") or ""
        if author:
            who = (f"Doan van xuoi nay do chinh tac gia tai lieu viet — TAC GIA: {author}. "
                   f"Neu can dan ten nguoi noi cua cac cau trong doan (khong co dau ngoac kep gan ten khac), "
                   f"do la {author}.")
        else:
            who = ("TAC GIA TAI LIEU: khong ro. Tuyet doi khong tu gan cac cau trong doan cho bat ky ten nao "
                   "lay tu tai lieu khac.")
        blocks.append(f"[P{i}] Trich tu tai lieu \"{title}\" (doan {c.get('chunk_index')})\n{who}\n{content}")
    return "\n\n".join(blocks)


_STOP_TERMS = {
    "của", "cho", "với", "trong", "những", "một", "các", "hay", "không", "nào",
    "gì", "mình", "bạn", "tôi", "và", "là", "có", "để", "về", "này",
}


def query_terms(query: str) -> list[str]:
    # giu nguyen dau (khop LIKE voi text co dau trong DB); cham diem thi bo dau
    terms = []
    for token in re.findall(r"[a-z0-9à-ỹđ]{2,}", (query or "").lower()):
        if token not in _STOP_TERMS and token not in terms:
            terms.append(token)
    return terms[:16]


def score_text(terms: list[str], text: str) -> int:
    plain = _plain(text)
    return sum(1 for t in terms if _plain(t) in plain)


_TOKEN_RE = re.compile(r"[a-z0-9à-ỹđ]+", re.I)


def _tok_set(text: str) -> set:
    return {_plain(w) for w in _TOKEN_RE.findall(text or "")}


def _tok_counts(text: str) -> dict:
    from collections import Counter
    return Counter(_plain(w) for w in _TOKEN_RE.findall(text or ""))


def _idf_weights(terms: list[str], texts: list[str]) -> dict:
    # Tu hiem trong tap ung vien -> trong so cao (ten rieng > tu pho bien nhu "tho", "phong").
    import math
    n = len(texts) or 1
    token_sets = [_tok_set(t) for t in texts]
    weights = {}
    for term in terms:
        pt = _plain(term)
        df = sum(1 for ts in token_sets if pt in ts)
        weights[term] = math.log((n + 1) / (df + 1)) + 1.0
    return weights


def score_weighted(terms: list[str], text: str, weights: dict) -> float:
    # Khop theo AM TIET (het nhieu chuoi-con: "le" khong con lot vao "len").
    # Cong tan suat co tran de doan nhac ten rieng nhieu lan thang doan chi nhac 1 lan.
    counts = _tok_counts(text)
    total = 0.0
    for term in terms:
        pt = _plain(term)
        c = counts.get(pt, 0)
        if c:
            total += weights.get(term, 1.0) * (1.0 + 0.4 * min(c - 1, 5))
    return total


async def _fetch_like(db, sql_unaccent: str, sql_plain: str, patterns_fold: list[str], patterns_raw: list[str]):
    # Uu tien khop khong dau (unaccent) de go sai/thieu dau van trung; neu unaccent chua co
    # tren DB thi lui ve LIKE thuong.
    try:
        return await db.fetch(sql_unaccent, patterns_fold)
    except Exception:
        return await db.fetch(sql_plain, patterns_raw)


def _rrf_merge(kw_ranked: list, vec_ranked: list, limit: int, c: int = 60) -> list:
    # Reciprocal Rank Fusion: gop 2 bang xep hang tu khoa + ngu nghia mot cach ben vung.
    scores: dict = {}
    holder: dict = {}
    for ranking in (kw_ranked, vec_ranked):
        for rank, r in enumerate(ranking, start=1):
            key = (r["doc_key"], r["passage_index"])
            scores[key] = scores.get(key, 0.0) + 1.0 / (c + rank)
            holder.setdefault(key, r)
    order = sorted(scores, key=lambda k: scores[k], reverse=True)
    return [holder[k] for k in order[:limit]]


async def retrieve_md_knowledge(db, query: str, *, limit: int = 5, query_vector=None) -> dict:
    await ensure_md_schema(db)
    terms = query_terms(query)
    patterns_fold = [f"%{_plain(t)}%" for t in terms] or ["%"]
    patterns_raw = [f"%{t}%" for t in terms] or ["%"]
    # Lay ung vien theo OR (bat ky term nao khop) roi cham diem trong Python.
    rows = await _fetch_like(
        db,
        """
        SELECT p.doc_key, p.passage_index, p.title, p.content, p.source, d.title AS doc_title, d.author
        FROM ai_md_passages p JOIN ai_md_documents d ON d.doc_key = p.doc_key
        WHERE unaccent(lower(coalesce(p.title,'') || ' ' || coalesce(p.content,''))) LIKE ANY($1::text[])
        LIMIT 300
        """,
        """
        SELECT p.doc_key, p.passage_index, p.title, p.content, p.source, d.title AS doc_title, d.author
        FROM ai_md_passages p JOIN ai_md_documents d ON d.doc_key = p.doc_key
        WHERE lower(coalesce(p.title,'') || ' ' || coalesce(p.content,'')) LIKE ANY($1::text[])
        LIMIT 300
        """,
        patterns_fold, patterns_raw,
    )
    # IDF tren tap ung vien: ten rieng/tu hiem duoc uu tien, tu pho bien bi ha thap.
    p_weights = _idf_weights(terms, [f"{r['title']} {r['content']}" for r in rows])
    kw_ranked = sorted(rows, key=lambda r: score_weighted(terms, f"{r['title']} {r['content']}", p_weights), reverse=True)

    # Tra cuu NGU NGHIA (neu co query_vector va passage da nhung) roi hop nhat bang RRF.
    vec_ranked = []
    best_sim = 0.0
    if query_vector is not None:
        try:
            from md_embeddings import vec_literal
            vrows = await db.fetch(
                """
                SELECT p.doc_key, p.passage_index, p.title, p.content, p.source,
                       d.title AS doc_title, d.author, 1 - (p.embedding <=> $1::vector) AS sim
                FROM ai_md_passages p JOIN ai_md_documents d ON d.doc_key = p.doc_key
                WHERE p.embedding IS NOT NULL
                ORDER BY p.embedding <=> $1::vector
                LIMIT 40
                """,
                vec_literal(query_vector),
            )
            vec_ranked = list(vrows)
            best_sim = float(vrows[0]["sim"]) if vrows else 0.0
        except Exception:
            vec_ranked = []

    if vec_ranked:
        selected = _rrf_merge(kw_ranked[:40], vec_ranked, limit)
    else:
        selected = kw_ranked[:limit]
    chunks = [{"title": r["title"], "doc_title": r["doc_title"], "author": r["author"],
               "content": r["content"], "excerpt": r["content"],
               "source": r["source"], "chunk_index": i, "page": None} for i, r in enumerate(selected)]
    qrows = await _fetch_like(
        db,
        """
        SELECT q.quote, q.author, q.source, d.title
        FROM ai_md_quotes q JOIN ai_md_documents d ON d.doc_key = q.doc_key
        WHERE unaccent(lower(coalesce(q.quote,'') || ' ' || coalesce(q.author,''))) LIKE ANY($1::text[])
        LIMIT 300
        """,
        """
        SELECT q.quote, q.author, q.source, d.title
        FROM ai_md_quotes q JOIN ai_md_documents d ON d.doc_key = q.doc_key
        WHERE lower(coalesce(q.quote,'') || ' ' || coalesce(q.author,'')) LIKE ANY($1::text[])
        LIMIT 300
        """,
        patterns_fold, patterns_raw,
    )
    q_weights = _idf_weights(terms, [f"{r['quote']} {r['author']}" for r in qrows])

    def _quote_score(r) -> float:
        # tac gia khop ten duoc uu tien manh (theo trong so IDF)
        author_hits = score_weighted(terms, r["author"] or "", q_weights) * 10
        return author_hits + score_weighted(terms, r["quote"] or "", q_weights)

    q_selected = sorted(qrows, key=_quote_score, reverse=True)[:max(limit, 8)]
    quotes = [{"quote": r["quote"], "author": r["author"] or "", "source": r["source"], "title": r["title"]}
              for r in q_selected]
    kw_top = score_weighted(terms, f"{selected[0]['title']} {selected[0]['content']}", p_weights) if selected else 0.0
    # Hit ngu nghia manh (sim cao) cung tinh la co can cu du tu khoa khong khop chu.
    top = max(float(kw_top), best_sim * 3.0)
    return {"context": build_md_context(chunks), "chunks": chunks, "quotes": quotes,
            "selected_count": len(chunks), "candidate_count": len(rows), "top_score": float(top)}


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
