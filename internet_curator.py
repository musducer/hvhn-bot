import asyncio
import hashlib
import html
import ipaddress
import json
import os
import re
import tempfile
import time
import unicodedata
from io import BytesIO
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlsplit, urlunsplit

import aiohttp
import requests
from defusedxml import ElementTree
from pypdf import PdfReader
from env_utils import env_int


USER_AGENT = os.getenv(
    "HVHN_INTERNET_CURATOR_UA",
    "Mozilla/5.0 (compatible; HVHN-Internet-Curator/0.1)",
)
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=25)
MAX_RESPONSE_BYTES = env_int("HVHN_INTERNET_CURATOR_MAX_MB", 4, minimum=1, maximum=64) * 1024 * 1024
MAX_PDF_BYTES = env_int("HVHN_INTERNET_CURATOR_MAX_PDF_MB", 18, minimum=1, maximum=256) * 1024 * 1024
MAX_PDF_PAGES = env_int("HVHN_INTERNET_CURATOR_MAX_PDF_PAGES", 40, minimum=1, maximum=500)
DEFAULT_SOURCES_PATH = Path(os.getenv("HVHN_INTERNET_SOURCES", "internet_sources.json"))
DEFAULT_PENDING_DIR = Path(os.getenv("HVHN_INTERNET_PENDING_DIR", "internet_pending"))

INTERNET_CURATOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_internet_items (
    id SERIAL PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    source_name TEXT NOT NULL,
    source_home TEXT NOT NULL,
    title TEXT NOT NULL,
    author TEXT,
    published_at TEXT,
    language TEXT,
    excerpt TEXT,
    content TEXT NOT NULL,
    markdown TEXT NOT NULL,
    quality_score INTEGER NOT NULL DEFAULT 0,
    quality_notes TEXT,
    status TEXT NOT NULL DEFAULT 'pending_review',
    discovered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at TIMESTAMPTZ,
    reviewed_by BIGINT,
    imported_doc_key TEXT
);
CREATE INDEX IF NOT EXISTS idx_ai_internet_items_status ON ai_internet_items (status, discovered_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_internet_items_source ON ai_internet_items (source_name);
"""

RELEVANT_TERMS = {
    "van hoc", "tho", "truyen", "tieu thuyet", "phe binh", "ly luan", "tac pham",
    "tac gia", "nha van", "nha tho", "nghien cuu", "sang tac", "doc sach",
    "hoc thuat", "nghe thuat", "tap chi", "blog", "bai viet",
    "literature", "poetry", "poem", "fiction", "novel", "essay", "review",
    "booker", "pulitzer", "nobel", "writer", "author", "interview", "criticism",
}
BAD_PATH_TERMS = {
    "login", "signin", "signup", "register", "cart", "checkout", "account", "wp-admin",
    "wp-content", "cdn-cgi", "privacy", "terms", "contact", "lien-he", "gioi-thieu",
    "about", "advertise", "subscribe", "newsletter", "search",
}
LISTING_PATH_TERMS = {
    "category", "tag", "chuyen-muc", "tin-tuc", "van-hoc", "nghien-cuu", "phe-binh",
    "ly-luan", "hoc-thuat", "tap-chi", "blog", "post", "posts", "bai-viet",
    "news", "articles", "prizes", "poetry", "fiction", "interviews", "reviews",
}
COMMON_CATEGORY_PATHS = (
    "tin-tuc",
    "tin-tuc-su-kien",
    "bai-viet",
    "post",
    "posts",
    "blog",
    "category/blog",
    "hoc-thuat",
    "nghien-cuu",
    "nghien-cuu-van-hoc",
    "ly-luan",
    "ly-luan-van-hoc",
    "phe-binh",
    "phe-binh-van-hoc",
    "dien-dan-ly-luan-phe-binh",
    "tap-chi",
    "tap-chi-nghien-cuu-van-hoc",
    "van-hoc",
    "van-hoc-viet-nam",
    "van-hoc-nuoc-ngoai",
    "thu-vien",
    "sach-moi",
    "news",
    "articles",
    "reviews",
    "interviews",
    "fiction",
    "poetry",
    "essays",
)


@dataclass(frozen=True)
class InternetSource:
    name: str
    url: str
    languages: tuple[str, ...] = ("vi",)


@dataclass
class Article:
    source: InternetSource
    url: str
    title: str
    author: str
    published_at: str
    language: str
    excerpt: str
    content: str
    quality_score: int
    quality_notes: list[str]
    markdown: str


def _clean_space(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _plain(value: str) -> str:
    folded = unicodedata.normalize("NFD", value or "")
    stripped = "".join(ch for ch in folded if unicodedata.category(ch) != "Mn")
    return stripped.replace("đ", "d").replace("Đ", "d").lower()


def _safe_meta(value: str) -> str:
    return _clean_space(value).replace("\n", " ")[:500]


def _slug(value: str, fallback: str = "internet") -> str:
    value = re.sub(r"[^\w\-. ]+", "_", value or "", flags=re.UNICODE)
    value = re.sub(r"\s+", "_", value).strip("._")
    return (value[:90] or fallback)


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, pending = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".part", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(pending, path)
    finally:
        try:
            os.remove(pending)
        except FileNotFoundError:
            pass


def normalize_url(url: str, base: str | None = None) -> str:
    if base:
        url = urljoin(base, url)
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().rstrip(".")
    try:
        port = parts.port
    except ValueError:
        return ""
    if (parts.scheme not in {"http", "https"} or not host
            or parts.username or parts.password or port not in (None, 80, 443)
            or host == "localhost" or host.endswith(".localhost")):
        return ""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        return ""
    query = parts.query if re.search(r"(^|&)p=\d+(&|$)", parts.query) else ""
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def same_site(url: str, home: str) -> bool:
    a = urlsplit(url)
    b = urlsplit(home)
    return a.netloc.lower().removeprefix("www.") == b.netloc.lower().removeprefix("www.")


def _requests_get_public(url: str, timeout: int):
    origin = normalize_url(url)
    if not origin:
        return None
    current = origin
    for _ in range(8):
        response = requests.get(
            current,
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            stream=True,
            allow_redirects=False,
        )
        if response.status_code not in (301, 302, 303, 307, 308):
            return response
        location = response.headers.get("location", "")
        target = normalize_url(location, current) if location else ""
        response.close()
        if not target or not same_site(target, origin):
            return None
        current = target
    return None


async def _aiohttp_get_public(session: aiohttp.ClientSession, url: str):
    origin = normalize_url(url)
    if not origin:
        return None
    current = origin
    for _ in range(8):
        response = await session.get(
            current,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
            allow_redirects=False,
        )
        if response.status not in (301, 302, 303, 307, 308):
            return response
        location = response.headers.get("location", "")
        target = normalize_url(location, current) if location else ""
        response.release()
        if not target or not same_site(target, origin):
            return None
        current = target
    return None


def _read_requests_bounded(response, limit: int) -> bytes | None:
    declared = response.headers.get("content-length", "")
    try:
        if declared and int(declared) > limit:
            return None
    except ValueError:
        pass
    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=256 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def load_sources(path: Path | str = DEFAULT_SOURCES_PATH) -> list[InternetSource]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    sources = []
    for item in raw:
        url = normalize_url(item.get("url", ""))
        name = _clean_space(item.get("name", "")) or urlsplit(url).netloc
        if not url:
            continue
        languages = tuple(item.get("languages") or ["vi"])
        sources.append(InternetSource(name=name, url=url, languages=languages))
    return sources


async def ensure_internet_schema(db) -> None:
    await db.execute(INTERNET_CURATOR_SCHEMA)


class LinkExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.feeds: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = {k.lower(): (v or "") for k, v in attrs}
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag == "link" and attrs.get("href"):
            rel = attrs.get("rel", "").lower()
            typ = attrs.get("type", "").lower()
            if "alternate" in rel and ("rss" in typ or "atom" in typ or "xml" in typ):
                self.feeds.append(attrs["href"])


class ArticleExtractor(HTMLParser):
    BLOCK_TAGS = {"p", "li", "blockquote", "h2", "h3"}
    SKIP_TAGS = {"script", "style", "noscript", "svg", "form", "nav", "footer", "header"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title_parts: list[str] = []
        self.h1_parts: list[str] = []
        self.paragraphs: list[str] = []
        self._tag_stack: list[str] = []
        self._skip_depth = 0
        self._capture_title = False
        self._capture_h1 = False
        self._block_depth = 0
        self._block_parts: list[str] = []
        self._focus_depth = 0
        self._focus_parts: list[str] = []
        self._focus_end_tags: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = {k.lower(): (v or "") for k, v in attrs}
        self._tag_stack.append(tag)
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        class_name = attrs.get("class", "").lower()
        if any(
            marker in class_name
            for marker in (
                "articlecontent",
                "article-content",
                "articlebody",
                "article-body",
                "entry-content",
                "post-content",
                "detail-content",
                "contentdetail",
            )
        ):
            self._focus_depth += 1
            self._focus_end_tags.append(tag)
        if tag == "meta":
            key = (attrs.get("property") or attrs.get("name") or "").lower()
            content = attrs.get("content", "")
            if key and content:
                self.meta[key] = _clean_space(content)
        if self._skip_depth:
            return
        if tag == "title":
            self._capture_title = True
        elif tag == "h1":
            self._capture_h1 = True
        elif tag in self.BLOCK_TAGS:
            self._block_depth += 1
            if self._block_depth == 1:
                self._block_parts = []
        if self._focus_depth and tag in {"br", "p", "div", "li", "blockquote", "h2", "h3"}:
            self._focus_parts.append("\n")

    def handle_endtag(self, tag):
        if self._skip_depth:
            if tag in self.SKIP_TAGS:
                self._skip_depth = max(0, self._skip_depth - 1)
            if self._tag_stack:
                self._tag_stack.pop()
            return
        if tag == "title":
            self._capture_title = False
        elif tag == "h1":
            self._capture_h1 = False
        elif tag in self.BLOCK_TAGS and self._block_depth:
            self._block_depth -= 1
            if self._block_depth == 0:
                paragraph = _clean_space(" ".join(self._block_parts))
                if len(paragraph) >= 35:
                    self.paragraphs.append(paragraph)
                self._block_parts = []
        if self._focus_depth and tag in {"p", "div", "li", "blockquote", "h2", "h3"}:
            self._focus_parts.append("\n")
        if self._focus_end_tags and tag == self._focus_end_tags[-1]:
            self._focus_end_tags.pop()
            self._focus_depth = max(0, self._focus_depth - 1)
        if self._tag_stack:
            self._tag_stack.pop()

    def handle_data(self, data):
        if self._skip_depth:
            return
        data = _clean_space(data)
        if not data:
            return
        if self._capture_title:
            self.title_parts.append(data)
        if self._capture_h1:
            self.h1_parts.append(data)
        if self._block_depth:
            self._block_parts.append(data)
        if self._focus_depth:
            self._focus_parts.append(data)

    def article(self) -> dict:
        h1 = _clean_space(" ".join(self.h1_parts))
        title = (
            self.meta.get("og:title")
            or self.meta.get("twitter:title")
            or h1
            or _clean_space(" ".join(self.title_parts))
        )
        title = re.sub(r"\s+[|-]\s+.*$", "", title).strip()
        author = (
            self.meta.get("author")
            or self.meta.get("article:author")
            or self.meta.get("parsely-author")
            or ""
        )
        published = (
            self.meta.get("article:published_time")
            or self.meta.get("date")
            or self.meta.get("pubdate")
            or self.meta.get("parsely-pub-date")
            or ""
        )
        desc = self.meta.get("description") or self.meta.get("og:description") or ""
        paragraphs = _dedupe_keep_order(self.paragraphs)
        if not paragraphs and self._focus_parts:
            focused = "\n".join(_clean_space(p) for p in "".join(self._focus_parts).split("\n"))
            paragraphs = [
                p for p in _dedupe_keep_order(re.split(r"\n\s*\n|\r\n\s*\r\n", focused))
                if len(p) >= 35
            ]
        return {
            "title": _clean_space(title),
            "author": _clean_space(author),
            "published_at": _clean_space(published),
            "excerpt": _clean_space(desc),
            "content": "\n\n".join(paragraphs),
        }


def _dedupe_keep_order(values: Iterable[str]) -> list[str]:
    seen = set()
    out = []
    for value in values:
        key = re.sub(r"\W+", "", value.lower())[:120]
        if key and key not in seen:
            seen.add(key)
            out.append(value)
    return out


def extract_links(raw_html: str, base_url: str) -> tuple[list[str], list[str]]:
    parser = LinkExtractor()
    parser.feed(raw_html or "")
    links = [normalize_url(link, base_url) for link in parser.links]
    feeds = [normalize_url(link, base_url) for link in parser.feeds]
    return [u for u in links if u], [u for u in feeds if u]


def extract_pdf_links(raw_html: str, base_url: str) -> list[str]:
    links, _ = extract_links(raw_html, base_url)
    return [u for u in links if urlsplit(u).path.lower().endswith(".pdf")]


def extract_article(raw_html: str, url: str) -> dict:
    parser = ArticleExtractor()
    parser.feed(raw_html or "")
    item = parser.article()
    if not item["title"]:
        stem = Path(urlsplit(url).path).stem.replace("-", " ").replace("_", " ")
        item["title"] = _clean_space(stem.title())
    return item


def fetch_pdf_text_requests(url: str) -> str:
    resp = None
    try:
        resp = _requests_get_public(url, timeout=35)
        if resp is None or resp.status_code >= 400:
            return ""
        data = _read_requests_bounded(resp, MAX_PDF_BYTES)
        if data is None:
            return ""
        reader = PdfReader(BytesIO(data))
        pages = []
        for page in reader.pages[:MAX_PDF_PAGES]:
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            text = _clean_space(text)
            if text:
                pages.append(text)
        return "\n\n".join(pages)[:60000]
    except Exception:
        return ""
    finally:
        if resp is not None:
            resp.close()


def link_score(url: str) -> int:
    parts = urlsplit(url)
    path = parts.path.lower()
    if any(term in path for term in BAD_PATH_TERMS):
        return -100
    score = 0
    if re.search(r"/20\d{2}[/\-]", path):
        score += 25
    if path.endswith((".html", ".htm")):
        score += 15
    words = re.findall(r"[a-z0-9]{3,}", path)
    if len(words) >= 4:
        score += 15
    if any(term in path for term in ("bai-viet", "tin", "van-hoc", "nghien-cuu", "ly-luan", "hoc-thuat", "blog", "post", "poem", "story", "article", "interview", "review")):
        score += 10
    if path in {"", "/"}:
        score -= 30
    return score


def is_listing_url(url: str, home: str) -> bool:
    path = urlsplit(url).path.lower().strip("/")
    if not path or url.rstrip("/") == home.rstrip("/"):
        return True
    return any(term in path for term in LISTING_PATH_TERMS) and link_score(url) < 25


def parse_xml_links(text: str, base_url: str) -> list[str]:
    links: list[str] = []
    try:
        root = ElementTree.fromstring(text.encode("utf-8"))
        for elem in root.iter():
            tag = elem.tag.lower().split("}", 1)[-1]
            if tag == "loc" and elem.text:
                links.append(normalize_url(elem.text.strip(), base_url))
            elif tag == "link":
                href = elem.attrib.get("href")
                if href:
                    links.append(normalize_url(href, base_url))
                elif elem.text and elem.text.strip().startswith(("http://", "https://")):
                    links.append(normalize_url(elem.text.strip(), base_url))
    except Exception:
        links.extend(normalize_url(m.group(1), base_url) for m in re.finditer(r"<loc>\s*([^<]+)\s*</loc>", text, re.I))
        links.extend(normalize_url(m.group(1), base_url) for m in re.finditer(r"<link>\s*([^<]+)\s*</link>", text, re.I))
    return [u for u in links if u]


async def fetch_text(session: aiohttp.ClientSession, url: str) -> tuple[str, str]:
    async def _read_once() -> tuple[str, str]:
        resp = await _aiohttp_get_public(session, url)
        if resp is None:
            return "", ""
        try:
            if resp.status >= 400:
                return await asyncio.to_thread(fetch_text_requests, url)
            data = await resp.content.read(MAX_RESPONSE_BYTES + 1)
            if len(data) > MAX_RESPONSE_BYTES:
                return "", ""
            content_type = resp.headers.get("content-type", "")
            encoding = resp.charset or "utf-8"
            return data.decode(encoding, errors="replace"), content_type
        finally:
            resp.release()

    try:
        text, content_type = await _read_once()
        # Some portal/CMS sites serve a short first shell and only return the full
        # anchor-rich HTML on the next request in the same session.
        lower_text = text.lower()
        blocked = "just a moment" in lower_text or "enable javascript" in lower_text or "cf-browser-verification" in lower_text
        if text and "html" in content_type.lower() and (blocked or ("<a " not in lower_text and len(text) < 40000)):
            retry_text, retry_type = await _read_once()
            retry_lower = retry_text.lower()
            if len(retry_text) > len(text) and ("<a " in retry_lower or ".pdf" in retry_lower):
                return retry_text, retry_type
            fallback_text, fallback_type = await asyncio.to_thread(fetch_text_requests, url)
            fallback_lower = fallback_text.lower()
            if len(fallback_text) > len(text) or "<a " in fallback_lower or ".pdf" in fallback_lower:
                return fallback_text, fallback_type
        return text, content_type
    except (aiohttp.ClientError, asyncio.TimeoutError, UnicodeError):
        return await asyncio.to_thread(fetch_text_requests, url)


def fetch_text_requests(url: str) -> tuple[str, str]:
    resp = None
    try:
        resp = _requests_get_public(url, timeout=20)
        if resp is None or resp.status_code >= 400:
            return "", ""
        content_type = resp.headers.get("content-type", "")
        data = _read_requests_bounded(resp, MAX_RESPONSE_BYTES)
        if data is None:
            return "", ""
        if "html" in content_type.lower() and "charset" not in content_type.lower():
            encoding = "utf-8"
        else:
            encoding = resp.encoding or "utf-8"
        return data.decode(encoding, errors="replace"), content_type
    except requests.RequestException:
        return "", ""
    finally:
        if resp is not None:
            resp.close()


async def discover_source_urls(
    session: aiohttp.ClientSession,
    source: InternetSource,
    *,
    max_candidates: int = 30,
    max_pages: int = 24,
    max_depth: int = 2,
) -> dict:
    home = normalize_url(source.url)
    candidate_urls: set[str] = set()
    feeds_seen: set[str] = set()
    discovery_notes: list[str] = []

    seed_paths = ("sitemap.xml", "sitemap_index.xml", "rss", "feed", "atom.xml")
    seed_urls = [urljoin(home.rstrip("/") + "/", path) for path in seed_paths]

    for seed in seed_urls:
        text, _ = await fetch_text(session, seed)
        if not text:
            continue
        urls = [u for u in parse_xml_links(text, seed) if same_site(u, home)]
        if urls:
            discovery_notes.append(f"{Path(urlsplit(seed).path).name or seed}: {len(urls)} links")
            if "sitemap" in seed:
                sitemap_children = [u for u in urls if u.endswith(".xml") or "sitemap" in u.lower()]
                article_like = [u for u in urls if link_score(u) >= 15]
                candidate_urls.update(article_like[:max_candidates])
                for child in sitemap_children[:6]:
                    child_text, _ = await fetch_text(session, child)
                    if child_text:
                        candidate_urls.update(
                            u for u in parse_xml_links(child_text, child)
                            if same_site(u, home) and link_score(u) >= 15
                        )
            else:
                feeds_seen.add(seed)
                candidate_urls.update(urls[:max_candidates])

    text, _ = await fetch_text(session, home)
    if text:
        links, feeds = extract_links(text, home)
        for feed in feeds[:5]:
            if feed not in feeds_seen and same_site(feed, home):
                feed_text, _ = await fetch_text(session, feed)
                if feed_text:
                    feed_links = [u for u in parse_xml_links(feed_text, feed) if same_site(u, home)]
                    candidate_urls.update(feed_links[:max_candidates])
                    discovery_notes.append(f"feed {feed}: {len(feed_links)} links")

    category_seeds = [normalize_url(urljoin(home.rstrip("/") + "/", path)) for path in COMMON_CATEGORY_PATHS]
    frontier: list[tuple[str, int]] = [(home, 0)] + [
        (u, 1) for u in category_seeds if u and same_site(u, home)
    ]
    visited: set[str] = set()
    pages_read = 0
    while frontier and pages_read < max_pages and len(candidate_urls) < max_candidates * 3:
        page_url, depth = frontier.pop(0)
        if page_url in visited or not same_site(page_url, home):
            continue
        visited.add(page_url)
        page, _ = await fetch_text(session, page_url)
        if not page:
            continue
        pages_read += 1
        links, _ = extract_links(page, page_url)
        ranked = sorted(
            (u for u in links if same_site(u, home) and u not in visited),
            key=link_score,
            reverse=True,
        )
        for link in ranked[:80]:
            score = link_score(link)
            if score >= 15:
                candidate_urls.add(link)
            if depth < max_depth and (is_listing_url(link, home) or score >= 25):
                frontier.append((link, depth + 1))
        await asyncio.sleep(0.05)

    ranked_candidates = sorted(candidate_urls, key=link_score, reverse=True)
    return {
        "urls": ranked_candidates[:max_candidates],
        "notes": discovery_notes + [f"deep pages read: {pages_read}", f"candidates: {len(ranked_candidates)}"],
    }


def quality(article: dict, source: InternetSource, url: str) -> tuple[int, list[str]]:
    text = _plain(f"{article.get('title', '')}\n{article.get('excerpt', '')}\n{article.get('content', '')}")
    score = 30
    notes = ["allowlisted source"]
    if article.get("title") and len(article["title"]) >= 8:
        score += 10
        notes.append("has title")
    content_len = len(article.get("content") or "")
    if content_len >= 900:
        score += 20
        notes.append("substantial text")
    if content_len >= 3000:
        score += 10
        notes.append("long article")
    if article.get("author"):
        score += 8
        notes.append("has author")
    if article.get("published_at") or re.search(r"/20\d{2}[/\-]", url):
        score += 8
        notes.append("has date signal")
    hits = [term for term in RELEVANT_TERMS if term in text]
    if hits:
        score += min(24, 4 * len(hits))
        notes.append("relevant: " + ", ".join(hits[:6]))
    if len(set(re.findall(r"\w+", text))) < 80:
        score -= 20
        notes.append("low unique-word count")
    if any(term in urlsplit(url).path.lower() for term in BAD_PATH_TERMS):
        score -= 40
        notes.append("bad path")
    return max(0, min(score, 100)), notes


def build_markdown(article: dict, source: InternetSource, url: str, score: int, notes: list[str]) -> str:
    language = ",".join(source.languages or ("vi",))
    title = _safe_meta(article.get("title") or url)
    author = _safe_meta(article.get("author") or "")
    published = _safe_meta(article.get("published_at") or "")
    excerpt = _safe_meta(article.get("excerpt") or "")
    content = article.get("content") or ""
    summary_seed = "\n\n".join(content.split("\n\n")[:3])[:1400]
    translation_note = (
        "Nguon co the khong phai tieng Viet. Khi su dung trong cau tra loi HVHN, "
        "Then can dien giai va dich noi dung lien quan sang tieng Viet, dong thoi giu trich dan nguon goc."
    )
    return (
        "---\n"
        f"title: {title}\n"
        f"author: {author}\n"
        f"source: {url}\n"
        f"source_name: {source.name}\n"
        f"published_at: {published}\n"
        f"language: {language}\n"
        "curation_status: pending_review\n"
        f"quality_score: {score}\n"
        "---\n\n"
        f"# {title}\n\n"
        f"- Nguon: {source.name}\n"
        f"- URL: {url}\n"
        f"- Tac gia: {author or 'chua ro'}\n"
        f"- Ngay dang: {published or 'chua ro'}\n"
        f"- Ngon ngu nguon: {language}\n"
        f"- Diem loc: {score}/100 ({'; '.join(notes)})\n\n"
        "## Ghi chu su dung\n\n"
        f"{translation_note}\n\n"
        "## Tom tat so bo\n\n"
        f"{excerpt or summary_seed or 'Chua co tom tat tu dong.'}\n\n"
        "## Noi dung nguon\n\n"
        f"{content}\n"
    )


async def extract_candidate_article(
    session: aiohttp.ClientSession,
    source: InternetSource,
    url: str,
    *,
    min_score: int,
) -> Article | None:
    raw, ctype = await fetch_text(session, url)
    if not raw or ("html" not in ctype.lower() and "<html" not in raw[:500].lower()):
        return None
    parsed = extract_article(raw, url)
    pdf_links = extract_pdf_links(raw, url)
    if len(parsed.get("content") or "") < 500 and pdf_links:
        pdf_text = await asyncio.to_thread(fetch_pdf_text_requests, pdf_links[0])
        if pdf_text:
            parsed["content"] = (
                (parsed.get("content") or parsed.get("excerpt") or parsed.get("title") or "").strip()
                + "\n\nToan van PDF lien ket trong bai:\n"
                + pdf_text
            ).strip()
            parsed["excerpt"] = parsed.get("excerpt") or f"Bai co PDF toan van: {pdf_links[0]}"
    if len(parsed.get("content") or "") < 500:
        return None
    score, notes = quality(parsed, source, url)
    if score < min_score:
        return None
    markdown = build_markdown(parsed, source, url, score, notes)
    return Article(
        source=source,
        url=url,
        title=parsed["title"],
        author=parsed.get("author", ""),
        published_at=parsed.get("published_at", ""),
        language=",".join(source.languages or ("vi",)),
        excerpt=parsed.get("excerpt", ""),
        content=parsed.get("content", ""),
        quality_score=score,
        quality_notes=notes,
        markdown=markdown,
    )


async def _existing_urls(db, urls: list[str]) -> set[str]:
    if not urls:
        return set()
    rows = await db.fetch("SELECT url FROM ai_internet_items WHERE url = ANY($1::text[])", urls)
    return {r["url"] for r in rows}


async def store_pending_articles(db, articles: list[Article], pending_dir: Path = DEFAULT_PENDING_DIR) -> int:
    if not articles:
        return 0
    await ensure_internet_schema(db)
    pending_dir.mkdir(parents=True, exist_ok=True)
    inserted = 0
    for article in articles:
        row_id = await db.fetchval(
            """
            INSERT INTO ai_internet_items (
                url, source_name, source_home, title, author, published_at, language,
                excerpt, content, markdown, quality_score, quality_notes, status
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,'pending_review')
            ON CONFLICT (url) DO NOTHING
            RETURNING id
            """,
            article.url,
            article.source.name,
            article.source.url,
            article.title,
            article.author,
            article.published_at,
            article.language,
            article.excerpt,
            article.content,
            article.markdown,
            article.quality_score,
            json.dumps(article.quality_notes, ensure_ascii=False),
        )
        if row_id:
            inserted += 1
            digest = hashlib.sha256(article.url.encode("utf-8")).hexdigest()[:10]
            filename = f"{int(time.time())}_{row_id}_{_slug(article.title)}_{digest}.md"
            try:
                _write_text_atomic(pending_dir / filename, article.markdown)
            except OSError:
                pass
    return inserted


async def scan_sources(
    db,
    *,
    sources_path: Path | str = DEFAULT_SOURCES_PATH,
    max_sources: int = 0,
    max_per_source: int = 8,
    min_score: int = 55,
    pending_dir: Path = DEFAULT_PENDING_DIR,
) -> dict:
    await ensure_internet_schema(db)
    sources = load_sources(sources_path)
    if max_sources and max_sources > 0:
        sources = sources[:max_sources]

    total_discovered = 0
    total_examined = 0
    total_inserted = 0
    source_reports = []
    async with aiohttp.ClientSession(headers={"User-Agent": USER_AGENT}) as session:
        for source in sources:
            discovered = await discover_source_urls(
                session,
                source,
                max_candidates=max(12, max_per_source * 4),
                max_pages=env_int("HVHN_INTERNET_DISCOVERY_PAGES", 24, minimum=1, maximum=200),
                max_depth=env_int("HVHN_INTERNET_DISCOVERY_DEPTH", 2, minimum=0, maximum=5),
            )
            urls = discovered["urls"]
            total_discovered += len(urls)
            existing = await _existing_urls(db, urls)
            fresh_urls = [u for u in urls if u not in existing]
            accepted: list[Article] = []
            for url in fresh_urls:
                if len(accepted) >= max_per_source:
                    break
                total_examined += 1
                item = await extract_candidate_article(session, source, url, min_score=min_score)
                if item:
                    accepted.append(item)
                await asyncio.sleep(0.08)
            inserted = await store_pending_articles(db, accepted, pending_dir=pending_dir)
            total_inserted += inserted
            source_reports.append(
                {
                    "source": source.name,
                    "discovered": len(urls),
                    "fresh": len(fresh_urls),
                    "accepted": len(accepted),
                    "inserted": inserted,
                    "notes": discovered["notes"],
                }
            )
    return {
        "sources": len(sources),
        "discovered": total_discovered,
        "examined": total_examined,
        "inserted": total_inserted,
        "reports": source_reports,
    }
