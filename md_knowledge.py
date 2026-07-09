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
