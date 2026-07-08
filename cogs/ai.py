import os
import re
import asyncio
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from html import unescape
from urllib.parse import parse_qs, unquote, urlparse

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from pdf_knowledge import retrieve_pdf_knowledge, search_pdf_knowledge

GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
MAX_DISCORD_LEN = 3800
WEB_RESULT_LIMIT = 3
WEB_CONTEXT_LIMIT = 3
GROQ_MAX_PROMPT_CHARS = int(os.getenv("GROQ_MAX_PROMPT_CHARS", "24000"))
GROQ_SAFE_PROMPT_CHARS = int(os.getenv("GROQ_SAFE_PROMPT_CHARS", "18000"))
CONTEXT_MAX_CHARS = int(os.getenv("HVHN_CONTEXT_MAX_CHARS", "18000"))
COMPACT_CONTEXT_MAX_CHARS = int(os.getenv("HVHN_COMPACT_CONTEXT_MAX_CHARS", "9000"))
SYSTEM_EXTRA_MAX_CHARS = 1500
VERIFIER_EVIDENCE_MAX_CHARS = 6000
LOW_RETRIEVAL_SCORE = float(os.getenv("HVHN_LOW_RETRIEVAL_SCORE", "1.0"))
RETRIEVAL_DEBUG = os.getenv("HVHN_RETRIEVAL_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}
DEBUG_COMMAND_TIMEOUT_SECONDS = int(os.getenv("HVHN_DEBUG_COMMAND_TIMEOUT_SECONDS", "25"))
PDF_DEFAULT_LIMIT = int(os.getenv("HVHN_PDF_DEFAULT_LIMIT", "7"))
PDF_AGGREGATE_LIMIT = int(os.getenv("HVHN_PDF_AGGREGATE_LIMIT", "16"))
TRUSTED_SOURCE_HINTS = (
    ".gov.vn",
    ".edu.vn",
    "moet.gov.vn",
    "chinhphu.vn",
    "quochoi.vn",
    "thuvienphapluat.vn",
    "nxb",
    "thivien.net",
    "wikipedia.org",
)


def _load_literature_system_instructions() -> str:
    path = Path(__file__).resolve().parents[1] / "SYSTEM INSTRUCTIONS.txt"
    try:
        text = path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""
    if len(text) > SYSTEM_EXTRA_MAX_CHARS:
        text = text[:SYSTEM_EXTRA_MAX_CHARS] + "\n...(da rut gon chi thi he thong vi qua dai)"
    return text


LITERATURE_SYSTEM_INSTRUCTIONS = _load_literature_system_instructions()


def _clip_text(value: str, max_chars: int) -> str:
    value = (value or "").strip()
    if len(value) <= max_chars:
        return value
    return value[:max_chars].rsplit(" ", 1)[0].rstrip() + "\n...(rut gon vi qua dai)"


def _budget_append(parts: list[str], label: str, text: str, remaining: int) -> int:
    text = (text or "").strip()
    if not text or remaining <= len(label) + 20:
        return remaining
    block = f"{label}:\n{_clip_text(text, remaining - len(label) - 3)}"
    if len(block) > remaining:
        block = _clip_text(block, remaining)
    parts.append(block)
    return remaining - len(block) - 2


def build_context_budget(
    query: str,
    pdf_chunks: str,
    manual_knowledge: str,
    web_results: str,
    max_chars: int,
    *,
    teacher_feedback: str = "",
) -> str:
    parts: list[str] = []
    remaining = max(1200, max_chars)
    remaining = _budget_append(parts, "KHO PDF HVHN UU TIEN", pdf_chunks, remaining)
    remaining = _budget_append(parts, "TRI THUC HVHN THU CONG", manual_knowledge, remaining)
    remaining = _budget_append(parts, "GOP Y GIAO VIEN DA SUA", teacher_feedback, remaining)
    remaining = _budget_append(parts, "NGUON WEB TIN CAY BO SUNG", web_results, remaining)
    if not parts:
        return ""
    return "\n\n".join(parts)


def _context_part_stats(pdf_chunks: str, manual_knowledge: str, teacher_feedback: str, web_results: str, final_context: str) -> dict:
    return {
        "pdf_chars": len(pdf_chunks or ""),
        "manual_chars": len(manual_knowledge or ""),
        "feedback_chars": len(teacher_feedback or ""),
        "web_chars": len(web_results or ""),
        "final_context_chars": len(final_context or ""),
        "context_truncated": len(final_context or "") < (
            len(pdf_chunks or "") + len(manual_knowledge or "") + len(teacher_feedback or "") + len(web_results or "")
        ),
    }

SYSTEM_PROMPT = (
    "Bạn là trợ giảng môn Ngữ Văn cho cộng đồng HVHN. Trả lời bằng tiếng Việt có dấu, "
    "rõ trọng tâm, ưu tiên giúp học sinh tự suy nghĩ. Tuyệt đối không bịa thông tin. "
    "Nếu không đủ căn cứ, phải nói rõ không đủ dữ liệu thay vì đoán bừa."
)

THEN_SYSTEM_PROMPT = (
    "Bạn là Then, trợ giảng Ngữ Văn của Hồn Văn - Hồn Người.\n"
    "LUẬT BẮT BUỘC:\n"
    "1. Không được bịa tác giả, tác phẩm, nhân vật, năm sáng tác, hoàn cảnh sáng tác, "
    "trích dẫn, nhận định phê bình, số liệu, hay nội dung bài học.\n"
    "2. Không đặt trong dấu ngoặc kép bất kỳ câu nào nếu câu đó không xuất hiện trong "
    "văn bản người dùng gửi hoặc KHO PDF/TRI THỨC HVHN LIÊN QUAN.\n"
    "3. Nếu câu hỏi cần chi tiết văn bản/tác phẩm mà không có dữ liệu xác thực, hãy nói "
    "'không đủ dữ liệu để khẳng định' và đưa cách kiểm chứng/hướng làm an toàn.\n"
    "4. Chỉ nhận xét dựa trên văn bản người dùng đưa vào; không suy diễn "
    "học sinh đã viết những ý không có trong bài.\n"
    "5. Luôn trả lời trực tiếp vào câu hỏi trước, rồi mới nói nguồn/căn cứ sau.\n"
    "6. Không được trả lời kiểu 'có thể tham khảo các nguồn sau' rồi liệt kê link. "
    "Nguồn web chỉ là căn cứ để tổng hợp thành câu trả lời.\n"
    "Giọng văn: sắc, ấm, giàu hình ảnh nhưng không mơ hồ. Câu hỏi đơn giản thì trả lời gọn; "
    "câu hỏi cần phân tích thì đi sâu có lớp lang, tách rõ nội dung, nghệ thuật và liên hệ mở rộng."
)


class FeedbackModal(discord.ui.Modal, title="Sửa câu trả lời cho Then"):
    correction = discord.ui.TextInput(
        label="Câu sửa / góp ý của giáo viên",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1800,
    )

    def __init__(self, bot: commands.Bot, prompt: str, answer: str):
        super().__init__()
        self.bot = bot
        self.prompt = prompt
        self.answer = answer

    async def on_submit(self, interaction: discord.Interaction):
        await self.bot.db.execute(
            """
            INSERT INTO ai_feedback (user_id, prompt, answer, rating, correction)
            VALUES ($1, $2, $3, 'needs_fix', $4)
            """,
            interaction.user.id,
            self.prompt,
            self.answer,
            str(self.correction),
        )
        await interaction.response.send_message(
            "Đã lưu góp ý. Then sẽ dùng dữ liệu này để mài prompt/kho tri thức.",
            ephemeral=True,
        )


class FeedbackView(discord.ui.View):
    def __init__(self, bot: commands.Bot, prompt: str, answer: str):
        super().__init__(timeout=86400)
        self.bot = bot
        self.prompt = prompt
        self.answer = answer

    @discord.ui.button(label="Đúng", style=discord.ButtonStyle.success)
    async def good(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.bot.db.execute(
            """
            INSERT INTO ai_feedback (user_id, prompt, answer, rating)
            VALUES ($1, $2, $3, 'good')
            """,
            interaction.user.id,
            self.prompt,
            self.answer,
        )
        await interaction.response.send_message("Đã lưu đánh giá tốt.", ephemeral=True)

    @discord.ui.button(label="Cần sửa", style=discord.ButtonStyle.danger)
    async def needs_fix(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(FeedbackModal(self.bot, self.prompt, self.answer))


def _rag_plain(value: str) -> str:
    value = unicodedata.normalize("NFD", value or "")
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn").lower()
    return value.replace("đ", "d")


@dataclass
class RAGPlan:
    intent: str
    exact_quote: bool = False
    aggregate: bool = False
    document_only: bool = False
    external_knowledge: bool = False
    citations: bool = True
    author_filter: str = ""
    retrieval_limit: int = PDF_DEFAULT_LIMIT
    use_llm: bool = True
    reason: str = ""


@dataclass
class QuoteEvidence:
    quote: str
    author: str = "UNKNOWN"
    pdf_title: str = ""
    page: int | None = None
    chunk_id: str = ""
    source: str = ""
    chunk: int | None = None
    context: str = ""
    confidence: float = 0.0
    score: int = 0


@dataclass
class QuoteSpan:
    quote: str
    start: int
    end: int


class IntentClassifier:
    @staticmethod
    def classify(message: str) -> str:
        q = _rag_plain(message)
        if "debug" in q:
            return "DEBUG"
        quote_markers = ("chep nguyen van", "nguyen van", "dung tung chu", "trich dan", "trich nguyen")
        aggregate_markers = ("tong hop", "tat ca", "moi nhan dinh", "toan bo", "liet ke", "cho minh 5", "5 nhan dinh")
        if any(m in q for m in quote_markers):
            return "QUOTE_COLLECTION" if any(m in q for m in aggregate_markers) else "QUOTE_SINGLE"
        if any(m in q for m in aggregate_markers):
            return "QUOTE_COLLECTION" if "nhan dinh" in q or "trich" in q else "SUMMARY"
        if "so sanh" in q or "doi chieu" in q:
            return "COMPARE"
        if "dan y" in q or "lap dan y" in q:
            return "OUTLINE"
        if "phan tich" in q or "cam nhan" in q or "binh giang" in q:
            return "ANALYSIS"
        if "giai thich" in q or "la gi" in q or "khai niem" in q:
            return "EXPLAIN"
        if any(m in q for m in ("moi nhat", "hom nay", "hien nay", "tra cuu web", "tin tuc")):
            return "WEB_SEARCH"
        return "CHAT"


class Planner:
    @staticmethod
    def author_filter(message: str) -> str:
        patterns = [
            r"(?:của|cua)\s+([A-ZÀ-ỸĐ][\wÀ-ỹĐđ]*(?:\s+[A-ZÀ-ỸĐ][\wÀ-ỹĐđ]*){0,4})",
            r"(?:tác giả|tac gia)\s+([A-ZÀ-ỸĐ][\wÀ-ỹĐđ]*(?:\s+[A-ZÀ-ỸĐ][\wÀ-ỹĐđ]*){0,4})",
        ]
        for pattern in patterns:
            match = re.search(pattern, message or "")
            if match:
                value = re.sub(r"\s+", " ", match.group(1)).strip(" .,:;?!")
                stop = re.search(r"\b(về|ve|trong|theo|là|la|và|va)\b", value, flags=re.I)
                if stop:
                    value = value[:stop.start()].strip()
                return value
        return ""

    @classmethod
    def build(cls, message: str) -> RAGPlan:
        intent = IntentClassifier.classify(message)
        q = _rag_plain(message)
        author = cls.author_filter(message)
        exact = intent == "QUOTE_SINGLE"
        aggregate = intent == "QUOTE_COLLECTION"
        document_only = any(m in q for m in ("theo tai lieu", "tai lieu da nap", "trong tai lieu", "kho pdf", "da nap")) or intent.startswith("QUOTE")
        retrieval_limit = PDF_AGGREGATE_LIMIT if intent in {"QUOTE_COLLECTION", "COMPARE", "OUTLINE", "SUMMARY"} else PDF_DEFAULT_LIMIT
        return RAGPlan(
            intent=intent,
            exact_quote=exact,
            aggregate=aggregate,
            document_only=document_only,
            external_knowledge=(intent == "WEB_SEARCH"),
            citations=True,
            author_filter=author,
            retrieval_limit=retrieval_limit,
            use_llm=intent not in {"QUOTE_SINGLE", "QUOTE_COLLECTION"},
            reason=f"intent={intent}; author={author or 'none'}",
        )


class QuoteExtractor:
    QUOTE_PAIRS = ((chr(8220), chr(8221)), ('"', '"'), ("'", "'"))
    AUTHOR_VERBS = ("cho rang", "viet", "noi", "khang dinh", "nhan dinh", "quan niem", "tung viet")
    UNKNOWN = "UNKNOWN"

    @classmethod
    def quote_spans(cls, text: str) -> list[QuoteSpan]:
        text = re.sub(r"\s+", " ", text or "").strip()
        spans: list[QuoteSpan] = []
        for open_q, close_q in cls.QUOTE_PAIRS:
            start = 0
            while True:
                left = text.find(open_q, start)
                if left < 0:
                    break
                right = text.find(close_q, left + 1)
                if right < 0:
                    break
                quote = text[left + 1:right].strip()
                if 20 <= len(quote) <= 1200:
                    spans.append(QuoteSpan(quote=quote, start=left, end=right + 1))
                start = right + 1
        spans.sort(key=lambda item: item.start)
        deduped = []
        seen = set()
        for span in spans:
            key = _rag_plain(span.quote)[:260]
            if key in seen:
                continue
            seen.add(key)
            deduped.append(span)
        return deduped

    @classmethod
    def quoted_units(cls, text: str) -> list[str]:
        return [span.quote for span in cls.quote_spans(text)]

    @classmethod
    def _candidate_names(cls, text: str) -> list[tuple[str, int, int]]:
        token_pattern = re.compile(r"[^\W\d_][^\W\d_'-]*", flags=re.UNICODE)
        tokens = [(m.group(0), m.start(), m.end()) for m in token_pattern.finditer(text or "")]
        names = []
        i = 0
        while i < len(tokens):
            word, start, end = tokens[i]
            if not word[:1].isupper():
                i += 1
                continue
            words = [word]
            j = i + 1
            while j < len(tokens) and len(words) < 5 and tokens[j][0][:1].isupper():
                words.append(tokens[j][0])
                end = tokens[j][2]
                j += 1
            if len(words) >= 2:
                names.append((" ".join(words), start, end))
                i = j
            else:
                i += 1
        return names

    @classmethod
    def infer_author(cls, chunk_text: str, span: QuoteSpan) -> tuple[str, float]:
        before_start = max(0, span.start - 240)
        after_end = min(len(chunk_text), span.end + 140)
        before = chunk_text[before_start:span.start]
        after = chunk_text[span.end:after_end]
        near_before = cls._candidate_names(before)
        near_after = cls._candidate_names(after)
        best: tuple[str, float] = (cls.UNKNOWN, 0.0)
        for name, start, end in near_before:
            tail = _rag_plain(before[end:])
            distance = len(before) - end
            verb_bonus = 0.45 if any(verb in tail[-80:] for verb in cls.AUTHOR_VERBS) else 0.0
            colon_bonus = 0.25 if ":" in tail[-30:] else 0.0
            score = max(0.0, 0.65 - distance / 300) + verb_bonus + colon_bonus
            if score > best[1]:
                best = (name, min(score, 1.0))
        for name, start, end in near_after:
            head = _rag_plain(after[:start])
            distance = start
            verb_bonus = 0.35 if any(verb in head[:80] for verb in cls.AUTHOR_VERBS) else 0.0
            score = max(0.0, 0.35 - distance / 300) + verb_bonus
            if score > best[1]:
                best = (name, min(score, 0.85))
        if best[1] < 0.55:
            return cls.UNKNOWN, best[1]
        return best

    @classmethod
    def extract(cls, pdf_meta: dict, plan: RAGPlan, query: str) -> list[QuoteEvidence]:
        requested_plain = _rag_plain(plan.author_filter)
        evidences: list[QuoteEvidence] = []
        for chunk in pdf_meta.get("chunks") or []:
            text = re.sub(r"\s+", " ", chunk.get("content") or chunk.get("excerpt") or "").strip()
            spans = cls.quote_spans(text)
            if not spans and plan.intent in {"QUOTE_COLLECTION", "COMPARE", "ANALYSIS"}:
                units = AI._extract_units_from_chunk(query, chunk, quote_mode=False, max_units=2)
                spans = [QuoteSpan(unit, text.find(unit) if text.find(unit) >= 0 else 0, (text.find(unit) if text.find(unit) >= 0 else 0) + len(unit)) for unit in units]
            for span in spans:
                author, confidence = cls.infer_author(text, span)
                if requested_plain and _rag_plain(author) != requested_plain:
                    continue
                score = int(confidence * 100) + AI._unit_score(query, span.quote)
                evidences.append(QuoteEvidence(
                    quote=span.quote,
                    author=author,
                    pdf_title=chunk.get("title") or "",
                    page=chunk.get("page"),
                    chunk_id=f"{chunk.get('title') or ''}#{chunk.get('chunk_index')}",
                    source=chunk.get("source") or "",
                    chunk=chunk.get("chunk_index"),
                    context=text[max(0, span.start - 140): min(len(text), span.end + 140)],
                    confidence=confidence,
                    score=score,
                ))
        return Aggregator.deduplicate(evidences)


class Aggregator:
    @staticmethod
    def deduplicate(items: list[QuoteEvidence]) -> list[QuoteEvidence]:
        seen = set()
        out = []
        for item in sorted(items, key=lambda x: x.score, reverse=True):
            key = _rag_plain(item.quote)[:220]
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out


class Formatter:
    @staticmethod
    def quote_single(items: list[QuoteEvidence], plan: RAGPlan) -> str | None:
        if not items:
            who = f" của {plan.author_filter}" if plan.author_filter else ""
            return f"Chưa tìm thấy nhận định nguyên văn{who} trong các tài liệu đã truy xuất. Không nên tự bịa hoặc chép theo trí nhớ."
        item = items[0]
        author = item.author or plan.author_filter or "Không rõ tác giả trong đoạn truy xuất"
        source = f"\nNguồn: {item.pdf_title}" if item.pdf_title else ""
        return f"\"{item.quote}\"\n\nTác giả/người được gán: {author}{source}"

    @staticmethod
    def quote_collection(items: list[QuoteEvidence], plan: RAGPlan) -> str | None:
        if not items:
            return "Chưa tìm thấy các nhận định nguyên văn phù hợp trong tài liệu đã truy xuất. Không bổ sung bằng trí nhớ ngoài tài liệu."
        lines = ["Các nhận định/trích dẫn tìm thấy trong tài liệu đã truy xuất:"]
        for index, item in enumerate(items, 1):
            author = item.author or "Không rõ tác giả trong đoạn truy xuất"
            source = f" — {item.pdf_title}" if item.pdf_title else ""
            lines.append(f"{index}. \"{item.quote}\"\n   Tác giả/người được gán: {author}{source}")
        return "\n".join(lines)

    @staticmethod
    def compare_seed(items: list[QuoteEvidence], plan: RAGPlan) -> str:
        if not items:
            return ""
        lines = ["TRICH DAN CAN DUNG TRUOC KHI PHAN TICH:"]
        for item in items[:8]:
            author = item.author or "khong ro"
            lines.append(f"- {author}: \"{item.quote}\" ({item.pdf_title})")
        return "\n".join(lines)


class AI(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.groq_keys = [k.strip() for k in os.getenv("GROQ_API_KEYS", "").split(",") if k.strip()]
        self.gemini_keys = [k.strip() for k in os.getenv("GEMINI_API_KEYS", "").split(",") if k.strip()]
        self.serper_key = os.getenv("SERPER_API_KEY", "").strip()
        self.tavily_key = os.getenv("TAVILY_API_KEY", "").strip()
        self.last_ai_errors: list[str] = []
        self._last_verifier_rejected = False
        print(f"[ai] GROQ_MODEL={GROQ_MODEL}", flush=True)
        print(f"[ai] GEMINI_MODEL={GEMINI_MODEL}", flush=True)
        print(f"[ai] groq_keys={len(self.groq_keys)} gemini_keys={len(self.gemini_keys)}", flush=True)

    @staticmethod
    def _redact_key(key: str) -> str:
        if not key:
            return "<missing>"
        if len(key) <= 10:
            return key[:2] + "***" + key[-2:]
        return key[:6] + "***" + key[-4:]

    @staticmethod
    def _api_error(provider: str, model: str, status: int | None, body: str = "", exc: BaseException | None = None) -> dict:
        return {
            "provider": provider,
            "model": model,
            "status": status,
            "body": body or "",
            "exception": repr(exc) if exc else "",
        }

    @staticmethod
    def _estimated_tokens(*texts: str) -> int:
        chars = sum(len(text or "") for text in texts)
        return max(1, chars // 4)

    @staticmethod
    def _is_request_too_large(error: dict | str) -> bool:
        if isinstance(error, dict):
            status = error.get("status")
            body = str(error.get("body", "")).lower()
            return status == 413 or "request too large" in body or "tpm" in body or "tokens per minute" in body
        lowered = str(error).lower()
        return "413" in lowered or "request too large" in lowered or "tpm" in lowered

    @staticmethod
    def _compress_prompt_for_groq(prompt: str) -> str:
        head = (
            "BAN RUT GON CONTEXT: Uu tien bang chung PDF/manual lien quan nhat. "
            "Neu thieu du lieu, noi ro chua du du lieu de khang dinh.\n\n"
        )
        return head + _clip_text(prompt, COMPACT_CONTEXT_MAX_CHARS)

    def _log_api_event(
        self,
        event: str,
        *,
        provider: str,
        model: str,
        key: str,
        key_index: int,
        total_keys: int,
        status: int | None = None,
        body: str = "",
        exc: BaseException | None = None,
    ) -> None:
        print(
            "[ai-api] "
            f"event={event} provider={provider} model={model} "
            f"key_index={key_index}/{total_keys} key={self._redact_key(key)} key_exists={bool(key)} "
            f"groq_keys={len(self.groq_keys)} gemini_keys={len(self.gemini_keys)} "
            f"status={status} body={body!r} exception={repr(exc) if exc else ''}",
            flush=True,
        )

    async def ask_groq(
        self,
        session: aiohttp.ClientSession,
        key: str,
        prompt: str,
        system_prompt: str = SYSTEM_PROMPT,
        temperature: float = 0.2,
    ) -> tuple[bool, str | dict]:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "top_p": 0.4,
        }
        async with session.post(url, headers=headers, json=payload, timeout=60) as resp:
            if resp.status != 200:
                body = await resp.text()
                print(
                    f"[ai-api] provider=groq model={GROQ_MODEL} non_200 status={resp.status} body={body!r}",
                    flush=True,
                )
                return False, self._api_error("groq", GROQ_MODEL, resp.status, body)
            data = await resp.json()
            return True, data["choices"][0]["message"]["content"].strip()

    async def ask_gemini(
        self,
        session: aiohttp.ClientSession,
        key: str,
        prompt: str,
        system_prompt: str = SYSTEM_PROMPT,
        temperature: float = 0.2,
    ) -> tuple[bool, str | dict]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={key}"
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature, "topP": 0.4},
        }
        async with session.post(url, json=payload, timeout=60) as resp:
            if resp.status != 200:
                body = await resp.text()
                print(
                    f"[ai-api] provider=gemini model={GEMINI_MODEL} non_200 status={resp.status} body={body!r}",
                    flush=True,
                )
                return False, self._api_error("gemini", GEMINI_MODEL, resp.status, body)
            data = await resp.json()
            try:
                return True, data["candidates"][0]["content"]["parts"][0]["text"].strip()
            except (KeyError, IndexError):
                return False, self._api_error("gemini", GEMINI_MODEL, 200, repr(data))

    async def generate(
        self,
        prompt: str,
        system_prompt: str = SYSTEM_PROMPT,
        temperature: float = 0.2,
    ) -> str | None:
        errors: list[str] = []
        prompt_chars = len(prompt) + len(system_prompt)
        prompt_tokens = self._estimated_tokens(prompt, system_prompt)
        prefer_gemini = prompt_chars > GROQ_SAFE_PROMPT_CHARS and bool(self.gemini_keys)
        print(
            "[ai-api] "
            f"event=generate_start groq_keys={len(self.groq_keys)} gemini_keys={len(self.gemini_keys)} "
            f"groq_model={GROQ_MODEL} gemini_model={GEMINI_MODEL} "
            f"prompt_chars={prompt_chars} est_tokens={prompt_tokens} prefer_gemini={prefer_gemini}",
            flush=True,
        )
        async with aiohttp.ClientSession() as session:
            if prefer_gemini:
                for index, key in enumerate(self.gemini_keys, start=1):
                    self._log_api_event(
                        "try_long_context_first",
                        provider="gemini",
                        model=GEMINI_MODEL,
                        key=key,
                        key_index=index,
                        total_keys=len(self.gemini_keys),
                        body=f"prompt_chars={prompt_chars} est_tokens={prompt_tokens}",
                    )
                    try:
                        ok, content = await self.ask_gemini(session, key, prompt, system_prompt, temperature)
                        if ok:
                            self.last_ai_errors = []
                            self._log_api_event(
                                "ok",
                                provider="gemini",
                                model=GEMINI_MODEL,
                                key=key,
                                key_index=index,
                                total_keys=len(self.gemini_keys),
                            )
                            return str(content)
                        if isinstance(content, dict):
                            errors.append(
                                f"provider=gemini model={GEMINI_MODEL} status={content.get('status')} body={content.get('body', '')}"
                            )
                    except Exception as exc:
                        errors.append(f"Gemini exception: {type(exc).__name__}: {exc}")

            groq_prompt = prompt
            if len(groq_prompt) + len(system_prompt) > GROQ_MAX_PROMPT_CHARS:
                groq_prompt = self._compress_prompt_for_groq(prompt)
                print(
                    "[ai-api] "
                    f"event=groq_prompt_compressed original_chars={len(prompt) + len(system_prompt)} "
                    f"compressed_chars={len(groq_prompt) + len(system_prompt)} "
                    f"est_tokens={self._estimated_tokens(groq_prompt, system_prompt)}",
                    flush=True,
                )
            for index, key in enumerate(self.groq_keys, start=1):
                self._log_api_event(
                    "try",
                    provider="groq",
                    model=GROQ_MODEL,
                    key=key,
                    key_index=index,
                    total_keys=len(self.groq_keys),
                    body=f"prompt_chars={len(groq_prompt) + len(system_prompt)} est_tokens={self._estimated_tokens(groq_prompt, system_prompt)}",
                )
                try:
                    ok, content = await self.ask_groq(session, key, groq_prompt, system_prompt, temperature)
                    if ok:
                        self.last_ai_errors = []
                        self._log_api_event(
                            "ok",
                            provider="groq",
                            model=GROQ_MODEL,
                            key=key,
                            key_index=index,
                            total_keys=len(self.groq_keys),
                        )
                        return str(content)
                    if isinstance(content, dict):
                        self._log_api_event(
                            "non_200",
                            provider="groq",
                            model=GROQ_MODEL,
                            key=key,
                            key_index=index,
                            total_keys=len(self.groq_keys),
                            status=content.get("status"),
                            body=content.get("body", ""),
                        )
                        errors.append(
                            f"provider=groq model={GROQ_MODEL} status={content.get('status')} body={content.get('body', '')}"
                        )
                        if self._is_request_too_large(content) and groq_prompt == prompt:
                            retry_prompt = self._compress_prompt_for_groq(prompt)
                            self._log_api_event(
                                "retry_compressed_after_413",
                                provider="groq",
                                model=GROQ_MODEL,
                                key=key,
                                key_index=index,
                                total_keys=len(self.groq_keys),
                                status=content.get("status"),
                                body=f"retry_chars={len(retry_prompt) + len(system_prompt)} est_tokens={self._estimated_tokens(retry_prompt, system_prompt)}",
                            )
                            ok2, content2 = await self.ask_groq(session, key, retry_prompt, system_prompt, temperature)
                            if ok2:
                                self.last_ai_errors = []
                                return str(content2)
                            if isinstance(content2, dict):
                                errors.append(
                                    f"provider=groq model={GROQ_MODEL} retry status={content2.get('status')} body={content2.get('body', '')}"
                                )
                    else:
                        errors.append(f"Groq {content}")
                        self._log_api_event(
                            "error",
                            provider="groq",
                            model=GROQ_MODEL,
                            key=key,
                            key_index=index,
                            total_keys=len(self.groq_keys),
                            body=str(content),
                        )
                except Exception as exc:
                    msg = f"Groq exception: {type(exc).__name__}: {exc}"
                    errors.append(msg)
                    self._log_api_event(
                        "exception",
                        provider="groq",
                        model=GROQ_MODEL,
                        key=key,
                        key_index=index,
                        total_keys=len(self.groq_keys),
                        exc=exc,
                    )

            if prefer_gemini:
                gemini_iter = []
            else:
                gemini_iter = list(enumerate(self.gemini_keys, start=1))
            for index, key in gemini_iter:
                self._log_api_event(
                    "try",
                    provider="gemini",
                    model=GEMINI_MODEL,
                    key=key,
                    key_index=index,
                    total_keys=len(self.gemini_keys),
                )
                try:
                    ok, content = await self.ask_gemini(session, key, prompt, system_prompt, temperature)
                    if ok:
                        self.last_ai_errors = []
                        self._log_api_event(
                            "ok",
                            provider="gemini",
                            model=GEMINI_MODEL,
                            key=key,
                            key_index=index,
                            total_keys=len(self.gemini_keys),
                        )
                        return str(content)
                    if isinstance(content, dict):
                        self._log_api_event(
                            "non_200",
                            provider="gemini",
                            model=GEMINI_MODEL,
                            key=key,
                            key_index=index,
                            total_keys=len(self.gemini_keys),
                            status=content.get("status"),
                            body=content.get("body", ""),
                        )
                        errors.append(
                            f"provider=gemini model={GEMINI_MODEL} status={content.get('status')} body={content.get('body', '')}"
                        )
                    else:
                        errors.append(f"Gemini {content}")
                        self._log_api_event(
                            "error",
                            provider="gemini",
                            model=GEMINI_MODEL,
                            key=key,
                            key_index=index,
                            total_keys=len(self.gemini_keys),
                            body=str(content),
                        )
                except Exception as exc:
                    msg = f"Gemini exception: {type(exc).__name__}: {exc}"
                    errors.append(msg)
                    self._log_api_event(
                        "exception",
                        provider="gemini",
                        model=GEMINI_MODEL,
                        key=key,
                        key_index=index,
                        total_keys=len(self.gemini_keys),
                        exc=exc,
                    )
        self.last_ai_errors = errors[-8:]
        print(
            "[ai-api] "
            f"event=all_failed groq_keys={len(self.groq_keys)} gemini_keys={len(self.gemini_keys)} "
            f"errors={self.last_ai_errors!r}",
            flush=True,
        )
        return None


    def _has_ai(self) -> bool:
        return bool(self.groq_keys or self.gemini_keys)

    def _ai_error_message(self) -> str:
        joined = " | ".join(self.last_ai_errors)
        if not joined:
            return "AI loi API nhung chua co chi tiet trong log."
        compact = re.sub(r"\s+", " ", joined).strip()
        if len(compact) > 1500:
            compact = compact[:1500] + "..."
        return "AI API failed. Provider details: " + compact

    @staticmethod
    def _retrieval_count(context: str, marker: str) -> int:
        return len(re.findall(rf"^\[{re.escape(marker)}\d+\]", context or "", flags=re.M))

    @staticmethod
    def _insufficient_answer(answer: str) -> bool:
        lowered = AI._plain_text(answer or "")
        return "khong du du lieu de khang dinh" in lowered or "chua du du lieu de khang dinh" in lowered

    @staticmethod
    def _query_terms(query: str, limit: int = 16) -> list[str]:
        plain = AI._plain_text(query)
        return [t for t in re.findall(r"[a-z0-9]{3,}", plain)[:limit]]

    @classmethod
    def _important_query_terms(cls, query: str, limit: int = 10) -> list[str]:
        stop = {
            "hay", "theo", "tai", "lieu", "nap", "cho", "biet", "la", "gi", "ve", "cua", "mot", "cac",
            "nhung", "moi", "can", "dung", "trong", "duoc", "voi", "neu", "hoi", "van", "chuong",
            "nhan", "dinh", "tong", "hop", "trich", "dan", "nguyen", "van", "chep",
        }
        terms = []
        for term in cls._query_terms(query, 32):
            if term not in stop and term not in terms:
                terms.append(term)
        return terms[:limit]

    @classmethod
    def _request_profile(cls, query: str) -> dict:
        q = cls._plain_text(query)
        quote = any(marker in q for marker in (
            "chep nguyen van", "nguyen van", "dung tung chu", "trich dan", "trich nguyen", "chep lai",
        ))
        aggregate = any(marker in q for marker in (
            "tong hop", "tat ca", "moi nhan dinh", "toan bo", "liet ke", "gom lai", "he thong",
        ))
        document_only = any(marker in q for marker in (
            "theo tai lieu", "tai lieu da nap", "trong tai lieu", "kho pdf", "da nap",
            "chep nguyen van", "nguyen van", "trich dan",
        ))
        return {"quote": quote, "aggregate": aggregate, "document_only": document_only}

    @classmethod
    def _retrieval_hit(cls, query: str, pdf_meta: dict) -> bool:
        terms = cls._query_terms(query)
        if not terms:
            return bool(pdf_meta.get("selected_count"))
        for chunk in (pdf_meta.get("chunks") or []):
            if chunk.get("matched_phrases"):
                return True
            matched = set(chunk.get("matched_keywords") or [])
            coverage = len(matched) / max(1, len(terms))
            important_terms = {term for term in terms if len(term) >= 4}
            if coverage >= 0.65 and (not important_terms or len(matched & important_terms) >= max(1, len(important_terms) // 2)):
                return True
        haystack = cls._plain_text(" ".join(
            (chunk.get("first_500") or "") + " " + (chunk.get("excerpt") or "")
            for chunk in (pdf_meta.get("chunks") or [])
        ))
        return len([term for term in terms if term in haystack]) / max(1, len(terms)) >= 0.75

    @staticmethod
    def _log_top_pdf_chunks(pdf_meta: dict) -> None:
        for chunk in (pdf_meta.get("chunks") or [])[:5]:
            preview = re.sub(r"\s+", " ", chunk.get("first_500") or chunk.get("excerpt", "")).strip()[:500]
            print(
                "[debug] top_pdf_chunk "
                f"id=P{chunk.get('index')} score={chunk.get('score')} rank={chunk.get('rank')} "
                f"kw={chunk.get('keyword_score')} phrase={chunk.get('phrase_score')} coverage={chunk.get('coverage')} "
                f"matched_phrases={chunk.get('matched_phrases')} missing_keywords={chunk.get('missing_keywords')} "
                f"title={chunk.get('title')!r} chunk_index={chunk.get('chunk_index')} first500={preview!r}",
                flush=True,
            )

    @staticmethod
    def _reason_code(pdf_meta: dict, manual_count: int, feedback_count: int, web_count: int, verifier_changed: bool = False) -> str:
        if verifier_changed:
            return "VERIFIER_REJECTED"
        if not (pdf_meta.get("selected_count") or manual_count or feedback_count or web_count):
            return "NO_RETRIEVAL"
        if not (pdf_meta.get("context") or manual_count or feedback_count or web_count):
            return "EMPTY_CONTEXT"
        if pdf_meta.get("error"):
            return "OCR_FAILURE"
        if pdf_meta.get("candidate_count", 0) > 0 and pdf_meta.get("selected_count", 0) == 0:
            return "RERANK_REJECTED"
        if pdf_meta.get("selected_count") and float(pdf_meta.get("top_score") or 0) < LOW_RETRIEVAL_SCORE:
            return "LOW_RETRIEVAL_SCORE"
        return "UNKNOWN"

    @staticmethod
    def _has_strong_evidence(pdf_meta: dict, manual_count: int, feedback_count: int, web_count: int) -> bool:
        if manual_count or feedback_count or web_count:
            return True
        return bool(pdf_meta.get("selected_count")) and float(pdf_meta.get("top_score") or 0) >= LOW_RETRIEVAL_SCORE


    def _is_admin(self, interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member):
            return False
        role_name = os.getenv("HVHN_ADMIN_ROLE", "HVHN Admin").strip()
        return any(role.name == role_name for role in interaction.user.roles) or interaction.user.guild_permissions.manage_guild

    async def _pdf_knowledge_context(self, query: str) -> str:
        try:
            return await search_pdf_knowledge(self.bot.db, query, limit=5)
        except Exception as exc:
            print(f"[ai] PDF knowledge exception: {exc}", flush=True)
            return ""

    async def _pdf_retrieval(self, query: str, *, limit: int = PDF_DEFAULT_LIMIT) -> dict:
        try:
            return await retrieve_pdf_knowledge(self.bot.db, query, limit=limit)
        except Exception as exc:
            print(f"[ai] PDF retrieval exception: {exc}", flush=True)
            return {"context": "", "candidate_count": 0, "selected_count": 0, "top_score": 0, "chunks": [], "error": str(exc)}

    async def _knowledge_context(self, query: str, limit: int = 6) -> str:
        terms = [t.lower() for t in re.findall(r"[\w?-?A-Za-z0-9]{3,}", query, flags=re.UNICODE)][:12]
        if not terms:
            rows = await self.bot.db.fetch(
                "SELECT category, title, content FROM ai_knowledge WHERE approved = TRUE ORDER BY created_at DESC LIMIT $1",
                limit,
            )
        else:
            patterns = [f"%{term}%" for term in terms]
            try:
                rows = await self.bot.db.fetch(
                    """
                    WITH q AS (SELECT websearch_to_tsquery('simple', $1) AS query)
                    SELECT category, title, content,
                           ts_rank_cd(
                             to_tsvector('simple', coalesce(category, '') || ' ' || coalesce(title, '') || ' ' || coalesce(content, '')),
                             q.query
                           ) AS rank
                    FROM ai_knowledge, q
                    WHERE approved = TRUE
                      AND (
                        to_tsvector('simple', coalesce(category, '') || ' ' || coalesce(title, '') || ' ' || coalesce(content, '')) @@ q.query
                        OR lower(title) LIKE ANY($2::text[])
                        OR lower(content) LIKE ANY($2::text[])
                        OR lower(category) LIKE ANY($2::text[])
                      )
                    ORDER BY rank DESC
                    LIMIT $3
                    """,
                    " ".join(terms),
                    patterns,
                    limit,
                )
            except Exception as exc:
                print(f"[ai] manual knowledge FTS fallback: {exc}", flush=True)
                rows = await self.bot.db.fetch(
                    """
                    SELECT category, title, content, 0::float AS rank
                    FROM ai_knowledge
                    WHERE approved = TRUE
                      AND (
                        lower(title) LIKE ANY($1::text[])
                        OR lower(content) LIKE ANY($1::text[])
                        OR lower(category) LIKE ANY($1::text[])
                      )
                    LIMIT $2
                    """,
                    patterns,
                    limit,
                )
        if not rows:
            return ""

        chunks = []
        for index, row in enumerate(rows, start=1):
            content = row["content"]
            if len(content) > 900:
                content = content[:900] + "..."
            chunks.append(f"[S{index}] [{row['category']}] {row['title']}\n{content}")
        return "\n\n".join(chunks)

    async def _feedback_context(self, query: str, limit: int = 3) -> str:
        terms = [t.lower() for t in re.findall(r"[\w?-?A-Za-z0-9]{3,}", query, flags=re.UNICODE)][:8]
        if not terms:
            return ""
        patterns = [f"%{term}%" for term in terms]
        rows = await self.bot.db.fetch(
            """
            SELECT prompt, correction
            FROM ai_feedback
            WHERE rating = 'needs_fix'
              AND correction IS NOT NULL
              AND (lower(prompt) LIKE ANY($1::text[]) OR lower(correction) LIKE ANY($1::text[]))
            ORDER BY id DESC
            LIMIT $2
            """,
            patterns,
            limit,
        )
        if not rows:
            return ""
        blocks = []
        total = 0
        for i, row in enumerate(rows[:3], 1):
            remaining = max(0, 1000 - total)
            if remaining <= 80:
                break
            correction = _clip_text(str(row["correction"]), min(remaining, 320))
            block = f"[F{i}] Loi giao vien da sua:\n{correction}"
            blocks.append(block)
            total += len(block) + 2
        context = "\n\n".join(blocks)
        print(
            f"[debug] feedback_context count={len(blocks)} chars={len(context)} preview={context[:500]!r}",
            flush=True,
        )
        return context


    @staticmethod
    def _clean_text(text: str) -> str:
        text = unescape(text or "")
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def _source_score(url: str) -> int:
        lowered = url.lower()
        return sum(1 for hint in TRUSTED_SOURCE_HINTS if hint in lowered)

    @staticmethod
    def _unwrap_ddg_url(url: str) -> str:
        parsed = urlparse(unescape(url))
        if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
            target = parse_qs(parsed.query).get("uddg", [""])[0]
            if target:
                return unquote(target)
        return unescape(url)

    async def _search_serper(self, session: aiohttp.ClientSession, query: str) -> list[dict[str, str]]:
        if not self.serper_key:
            return []
        headers = {"X-API-KEY": self.serper_key, "Content-Type": "application/json"}
        payload = {"q": query, "gl": "vn", "hl": "vi", "num": WEB_RESULT_LIMIT}
        async with session.post("https://google.serper.dev/search", headers=headers, json=payload, timeout=12) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
        results = []
        for item in data.get("organic", [])[:WEB_RESULT_LIMIT]:
            link = item.get("link") or ""
            title = self._clean_text(item.get("title") or "")
            snippet = self._clean_text(item.get("snippet") or "")
            if link and title:
                results.append({"title": title, "url": link, "snippet": snippet})
        return results

    async def _search_tavily(self, session: aiohttp.ClientSession, query: str) -> list[dict[str, str]]:
        if not self.tavily_key:
            return []
        payload = {
            "api_key": self.tavily_key,
            "query": query,
            "search_depth": "basic",
            "max_results": WEB_RESULT_LIMIT,
            "include_answer": False,
        }
        async with session.post("https://api.tavily.com/search", json=payload, timeout=15) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
        results = []
        for item in data.get("results", [])[:WEB_RESULT_LIMIT]:
            link = item.get("url") or ""
            title = self._clean_text(item.get("title") or "")
            snippet = self._clean_text(item.get("content") or "")
            if link and title:
                results.append({"title": title, "url": link, "snippet": snippet[:450]})
        return results

    async def _search_duckduckgo(self, session: aiohttp.ClientSession, query: str) -> list[dict[str, str]]:
        params = {"q": query, "kl": "vn-vi"}
        headers = {"User-Agent": "Mozilla/5.0"}
        async with session.get("https://duckduckgo.com/html/", params=params, headers=headers, timeout=15) as resp:
            if resp.status != 200:
                return []
            html = await resp.text()

        results = []
        pattern = re.compile(
            r'<a[^>]+class="result__a"[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?'
            r'<a[^>]+class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
            re.S,
        )
        for match in pattern.finditer(html):
            url = self._unwrap_ddg_url(match.group("url"))
            title = self._clean_text(match.group("title"))
            snippet = self._clean_text(match.group("snippet"))
            if url and title:
                results.append({"title": title, "url": url, "snippet": snippet})
            if len(results) >= WEB_RESULT_LIMIT:
                break
        return results

    @staticmethod
    def _plain_text(value: str) -> str:
        value = unicodedata.normalize("NFD", value or "")
        value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn").lower()
        return value.replace("đ", "d")

    @staticmethod
    def _needs_web(query: str, mode: str, has_local_context: bool) -> bool:
        q = AI._plain_text(query)
        if mode == "user_text_only":
            return False
        current_markers = ("moi nhat", "hien nay", "hom nay", "2025", "2026", "tin", "luat", "diem chuan", "lich", "gia", "su kien")
        source_markers = ("dan nguon", "nguon", "kiem chung", "tra cuu", "ai la", "khi nao", "o dau")
        if any(marker in q for marker in current_markers + source_markers):
            return True
        return not has_local_context and len(q.split()) >= 6


    async def _web_context(self, query: str, mode: str, has_local_context: bool = False) -> str:
        if not self._needs_web(query, mode, has_local_context):
            print(f"[ai] web=skip mode={mode} local={has_local_context}", flush=True)
            return ""

        async with aiohttp.ClientSession() as session:
            try:
                results = []
                results.extend(await self._search_serper(session, query))
                results.extend(await self._search_tavily(session, query))
                if not results:
                    results = await self._search_duckduckgo(session, query)
            except Exception as exc:
                print(f"[ai] Web search exception: {exc}", flush=True)
                return ""

        deduped = {}
        for item in results:
            deduped.setdefault(item["url"], item)
        results = list(deduped.values())
        print(f"[ai] web_results={len(results[:WEB_CONTEXT_LIMIT])}", flush=True)

        chunks = []
        for index, item in enumerate(results[:WEB_CONTEXT_LIMIT], start=1):
            snippet = item["snippet"][:500]
            trust = "nguon dang tin hon" if self._source_score(item["url"]) else "can kiem chung"
            chunks.append(f"[W{index}] {item['title']}\nURL: {item['url']}\nDo tin cay: {trust}\nTom tat: {snippet}")
        return "\n\n".join(chunks)


    @staticmethod
    def _guarded_prompt(prompt: str, knowledge: str, web_context: str, mode: str) -> str:
        source_block = knowledge or "KHONG CO KHO PDF/TRI THUC HVHN PHU HOP DUOC NAP."
        web_block = web_context or "KHONG CO NGUON WEB DUOC TRUY XUAT."
        literature_rules = (
            "\n\nCHI THI NGU VAN BO SUNG TU SYSTEM INSTRUCTIONS.txt:\n"
            f"{LITERATURE_SYSTEM_INSTRUCTIONS}\n"
            if LITERATURE_SYSTEM_INSTRUCTIONS else ""
        )
        return (
            "Ban la Then, tro giang AI mon Ngu van cua HVHN. Luon tra loi bang tieng Viet co dau, tru khi nguoi dung yeu cau ngon ngu khac.\n"
            f"CHE DO: {mode}\n"
            f"{literature_rules}"
            "KHO PDF/TRI THUC/FEEDBACK HVHN DA TRUY XUAT:\n"
            f"{source_block}\n\n"
            "NGUON WEB DA TRA CUU (neu co):\n"
            f"{web_block}\n\n"
            "QUY TAC BAT BUOC:\n"
            "- Khong bia tac gia, tac pham, nhan vat, nam thang, hoan canh sang tac, trich dan, nhan dinh phe binh.\n"
            "- Neu KHO PDF/TRI THUC co noi dung lien quan, chi duoc tra loi tu KHO PDF/TRI THUC do; khong dung tri nho ngoai.\n"
            "- Neu nguoi dung hoi 'chep nguyen van', 'trich dan', 'nguyen van', phai giu dung tung chu tu context; khong dien giai/paraphrase.\n"
            "- Neu nguoi dung hoi 'tong hop', 'tat ca', 'moi nhan dinh', phai di qua tat ca doan [P...] duoc cap va rut ra moi y/trich dan lien quan; khong dung sau 1 doan.\n"
            "- Voi cau hoi theo tai lieu da nap, neu context co evidence thi khong duoc tra loi bang kien thuc chung hay tom tat chung chung.\n"
            "- Chi dat trong ngoac kep neu thay nguyen van trong van ban/context.\n"
            "- Neu context khong du de khang dinh, phai noi ro: chua du du lieu de khang dinh.\n"
            "- Neu KHO PDF/TRI THUC co bang chung lien quan, bat buoc tra loi dua tren bang chung do; khong duoc tu choi chung chung.\n"
            "- Duoc neu ghi chu nguon ngan gon khi cau tra loi mang tinh su kien/van hoc/can kiem chung.\n"
            "- Khong hien ma noi bo [P1], [S1], [W1] hoac URL dai; neu can, chi neu ten tai lieu/nguon ngan gon.\n"
            "- Tra loi thang vao cau hoi, sau do moi ghi can cu/nguon neu that su can.\n"
            "- Khong dung web neu kho HVHN da du; web chi bo sung thong tin thoi su/kiem chung.\n\n"
            "YEU CAU NGUOI DUNG:\n"
            f"{prompt}"
        )


    @staticmethod
    def _has_grounding_footer(answer: str) -> bool:
        lowered = answer.lower()
        return (
            "tài liệu tham khảo" in lowered
            or "tai lieu tham khao" in lowered
            or "nguồn:" in lowered
            or "nguon:" in lowered
            or "chưa đủ dữ liệu" in lowered
            or "chua du du lieu" in lowered
        )

    @staticmethod
    def _looks_like_source_dump(answer: str) -> bool:
        lowered = answer.lower()
        source_dump_phrases = (
            "tham khảo các nguồn",
            "tham khảo nguồn",
            "các nguồn thông tin sau",
            "danh sách nguồn",
            "sources",
        )
        has_dump_intro = any(phrase in lowered[:350] for phrase in source_dump_phrases)
        has_many_source_bullets = len(re.findall(r"^\s*[-•]\s+.*\[(?:w|W)\d+\]", answer, re.M)) >= 3
        return has_dump_intro or has_many_source_bullets

    @staticmethod
    def _pdf_reference_lines(knowledge: str) -> list[tuple[str, str]]:
        if "PDF" not in knowledge and "pdf" not in knowledge:
            return []
        refs = []
        for line in knowledge.splitlines():
            match = re.match(r"^\[(\d+)\]\s+(.+\.pdf)\s*$", line.strip(), flags=re.I)
            if match:
                refs.append((match.group(1), match.group(2).strip()))
        return refs

    @classmethod
    def _ensure_pdf_references(cls, answer: str, knowledge: str) -> str:
        refs = cls._pdf_reference_lines(knowledge)
        if not refs:
            return answer

        lowered = answer.lower()
        used_numbers = set(re.findall(r"(?<![A-Za-z])\[(\d+)\]", answer))
        selected = [(num, title) for num, title in refs if used_numbers and num in used_numbers]
        if not selected:
            selected = refs[:3]

        missing_titles = [(num, title) for num, title in selected if title not in answer]
        if "tài liệu tham khảo" in lowered or "tai lieu tham khao" in lowered:
            if not missing_titles:
                return answer
            lines = ["", "TÀI LIỆU THAM KHẢO (liên quan):"]
            lines.extend(f"[{num}] {title}" for num, title in missing_titles)
            return answer.rstrip() + "\n".join(lines)

        lines = ["", "TÀI LIỆU THAM KHẢO (liên quan):"]
        lines.extend(f"[{num}] {title}" for num, title in selected)
        return answer.rstrip() + "\n".join(lines)

    async def _verify_answer(
        self,
        answer: str,
        prompt: str,
        knowledge: str,
        web_context: str,
        mode: str,
        *,
        retrieval_hit: bool = False,
    ) -> str:
        if not answer:
            return answer
        compact_evidence = build_context_budget(
            prompt,
            knowledge,
            "",
            web_context,
            VERIFIER_EVIDENCE_MAX_CHARS,
        )
        compact_answer = _clip_text(answer, 4000)
        verifier_prompt = (
            "Kiem chung cau tra loi sau bang dung context duoc cung cap. "
            "Hay giu cau dung, xoa hoac viet lai moi khang dinh khong du can cu thanh 'chua du du lieu de khang dinh'. "
            "Neu BANG CHUNG RUT GON co thong tin lien quan, khong duoc bien cau tra loi thanh tu choi chung chung; hay sua de tra loi bang evidence. "
            "Tuyet doi khong them tac gia/tac pham/nam/trich dan/nhan dinh moi. "
            "Khong hien ma noi bo [P1]/[S1]/[W1] hoac URL dai. Tra lai ban da sua, tieng Viet.\n\n"
            f"CAU HOI/PROMPT:\n{prompt}\n\n"
            f"BANG CHUNG RUT GON:\n{compact_evidence or 'KHONG CO'}\n\n"
            f"CAU TRA LOI CAN KIEM:\n{compact_answer}"
        )
        if RETRIEVAL_DEBUG:
            print(f"[debug] verifier_prompt\n{verifier_prompt}", flush=True)
        verified = await self.generate(verifier_prompt, THEN_SYSTEM_PROMPT, temperature=0.0)
        if RETRIEVAL_DEBUG:
            print(f"[debug] verifier_output\n{verified}", flush=True)
        if verified:
            self._last_verifier_rejected = (not self._insufficient_answer(answer)) and self._insufficient_answer(verified)
            verifier_reason = "VERIFIER_REJECTED" if self._last_verifier_rejected else "OK"
            print(
                f"[debug] verifier_result mode={mode} rejected={self._last_verifier_rejected} "
                f"input_insufficient={self._insufficient_answer(answer)} output_insufficient={self._insufficient_answer(verified)} "
                f"retrieval_hit={retrieval_hit} verifier_reason={verifier_reason}",
                flush=True,
            )
            if retrieval_hit and self._insufficient_answer(verified):
                print("[debug] verifier_override=retrieval_hit_prevents_false_insufficient", flush=True)
                return answer
            return verified
        print(f"[debug] verifier_result mode={mode} skipped=True", flush=True)
        return answer

    async def _safe_generate(
        self,
        prompt: str,
        knowledge: str,
        web_context: str,
        mode: str,
        *,
        retrieval_hit: bool = False,
    ) -> tuple[str | None, str]:
        self._last_verifier_rejected = False
        full_prompt = self._guarded_prompt(prompt, knowledge, web_context, mode)
        if RETRIEVAL_DEBUG:
            print(f"[debug] final_prompt\n{full_prompt}", flush=True)
        answer = await self.generate(full_prompt, THEN_SYSTEM_PROMPT, temperature=0.05)
        needs_repair = bool(answer) and self._looks_like_source_dump(answer)
        if answer and needs_repair:
            repair_prompt = (
                "Sua cau tra loi sau de tra loi thang vao cau hoi, khong bia, khong chi liet ke nguon. "
                "Khong them thong tin moi ngoai context. Neu du lieu khong du, noi ro chua du du lieu de khang dinh.\n\n"
                f"CAU TRA LOI CAN SUA:\n{answer}"
            )
            repaired = await self.generate(
                self._guarded_prompt(repair_prompt, knowledge, web_context, "repair"),
                THEN_SYSTEM_PROMPT,
                temperature=0.0,
            )
            if repaired:
                answer = repaired
        if answer:
            answer = await self._verify_answer(answer, prompt, knowledge, web_context, mode, retrieval_hit=retrieval_hit)
            answer = self._strip_internal_markers(answer)
        return answer, full_prompt

    async def _force_grounded_answer(self, prompt: str, knowledge: str, web_context: str, mode: str) -> str | None:
        force_prompt = (
            "BAT BUOC TRA LOI BANG CHUNG DA TRUY XUAT NEU CO. "
            "Khong duoc noi 'khong du du lieu de khang dinh' khi KHO PDF/TRI THUC ben duoi co doan lien quan. "
            "Hay trich y tu evidence, noi ro can cu tu tai lieu nao, va chi tu choi nhung chi tiet khong nam trong evidence.\n\n"
            f"{prompt}"
        )
        full_prompt = self._guarded_prompt(force_prompt, knowledge, web_context, mode + "_force_grounded")
        if RETRIEVAL_DEBUG:
            print(f"[debug] forced_prompt\n{full_prompt}", flush=True)
        answer = await self.generate(full_prompt, THEN_SYSTEM_PROMPT, temperature=0.0)
        if answer:
            return self._strip_internal_markers(answer)
        return None

    @staticmethod
    def _evidence_fallback_answer(pdf_meta: dict, manual_knowledge: str, web_context: str) -> str:
        chunks = pdf_meta.get("chunks") or []
        if chunks:
            lines = ["Dựa trên các đoạn tài liệu đã truy xuất, có thể trả lời bằng chứng sau:"]
            for chunk in chunks[:3]:
                excerpt = re.sub(r"\s+", " ", chunk.get("excerpt", "")).strip()
                lines.append(f"- {chunk.get('title')} (đoạn {chunk.get('chunk_index')}): {excerpt[:650]}")
            lines.append("Phần trên là trích ý trực tiếp từ evidence; cần đối chiếu thêm tài liệu gốc nếu muốn diễn giải sâu hơn.")
            return "\n".join(lines)
        if manual_knowledge:
            return "Dựa trên tri thức HVHN đã truy xuất:\n" + _clip_text(manual_knowledge, 1800)
        if web_context:
            return "Dựa trên nguồn web đã truy xuất:\n" + _clip_text(web_context, 1800)
        return "Chưa có evidence đủ rõ để trả lời."


    @classmethod
    def _sentence_units(cls, text: str) -> list[str]:
        text = re.sub(r"\s+", " ", text or "").strip()
        if not text:
            return []
        units = re.split(r"(?<=[.!?])\s+|(?<=\")\s+", text)
        return [unit.strip() for unit in units if len(unit.strip()) >= 20]

    @classmethod
    def _quoted_units(cls, text: str) -> list[str]:
        text = re.sub(r"\s+", " ", text or "").strip()
        quotes = []
        quote_pairs = [(chr(8220), chr(8221)), ('"', '"'), ("'", "'")]
        for open_q, close_q in quote_pairs:
            start = 0
            while True:
                left = text.find(open_q, start)
                if left < 0:
                    break
                right = text.find(close_q, left + 1)
                if right < 0:
                    break
                quote = text[left + 1:right].strip()
                if 20 <= len(quote) <= 700 and quote not in quotes:
                    quotes.append(quote)
                start = right + 1
        return quotes

    @classmethod
    def _unit_score(cls, query: str, text: str) -> int:
        haystack = cls._plain_text(text)
        return sum(1 for term in cls._important_query_terms(query, 16) if term in haystack)

    @classmethod
    def _extract_units_from_chunk(cls, query: str, chunk: dict, *, quote_mode: bool, max_units: int = 4) -> list[str]:
        content = chunk.get("content") or chunk.get("excerpt") or chunk.get("first_500") or ""
        candidates = cls._quoted_units(content) if quote_mode else []
        if not candidates:
            candidates = cls._sentence_units(content)
        scored = []
        for unit in candidates:
            score = cls._unit_score(query, unit)
            if score > 0 or quote_mode:
                scored.append((score, unit))
        if not scored and candidates:
            scored = [(0, unit) for unit in candidates[:max_units]]
        scored.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
        selected = []
        seen = set()
        for _, unit in scored:
            key = cls._plain_text(unit)[:180]
            if key in seen:
                continue
            seen.add(key)
            selected.append(unit)
            if len(selected) >= max_units:
                break
        return selected

    @classmethod
    def _deterministic_document_answer(cls, query: str, pdf_meta: dict, profile: dict) -> str | None:
        chunks = pdf_meta.get("chunks") or []
        if not chunks or not (profile.get("quote") or profile.get("aggregate")):
            return None
        max_chunks = 12 if profile.get("aggregate") else 5
        lines = []
        extracted_any = False
        if profile.get("quote"):
            lines.append("Nguyen van trong tai lieu da truy xuat:")
        else:
            lines.append("Cac nhan dinh/trich dan tim thay trong tai lieu da truy xuat:")
        for chunk in chunks[:max_chunks]:
            raw_quotes = cls._quoted_units(chunk.get("content") or "")
            units = cls._extract_units_from_chunk(
                query,
                chunk,
                quote_mode=bool(profile.get("quote") or profile.get("aggregate")),
                max_units=3 if profile.get("aggregate") else 2,
            )
            if not units:
                continue
            extracted_any = True
            lines.append(f"\n- {chunk.get('title')} (doan {chunk.get('chunk_index')}):")
            for unit in units:
                unit = unit.strip()
                if profile.get("quote") or unit in raw_quotes:
                    lines.append(f'  + "{unit}"')
                else:
                    lines.append(f"  + {unit}")
        if not extracted_any:
            return None
        lines.append("\nGhi chu: phan tren chi lay tu cac doan PDF da truy xuat; khong bo sung bang tri nho ngoai tai lieu.")
        return "\n".join(lines).strip()


    @staticmethod
    def _strip_internal_markers(answer: str) -> str:
        lines = []
        for line in answer.splitlines():
            line = re.sub(r"\s*\[(?:P|S|W)\d+\]", "", line)
            line = re.sub(r"URL:\s*https?://\S+", "", line)
            lines.append(line.rstrip())
        return "\n".join(lines).strip()

    _strip_visible_sources = _strip_internal_markers


    async def _then_answer(self, interaction: discord.Interaction, title: str, user_prompt: str, prompt: str, mode: str):
        if not self._has_ai():
            await interaction.response.send_message("Tinh nang AI chua cau hinh API key.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        print(f"[debug] before_retrieval query={user_prompt[:220]!r} mode={mode}", flush=True)
        plan = Planner.build(user_prompt)
        profile = self._request_profile(user_prompt)
        retrieval_limit = max(plan.retrieval_limit, PDF_AGGREGATE_LIMIT if profile["aggregate"] or profile["quote"] else PDF_DEFAULT_LIMIT)
        pdf_meta = await self._pdf_retrieval(user_prompt, limit=retrieval_limit)
        pdf_knowledge = pdf_meta.get("context", "")
        manual_knowledge = await self._knowledge_context(user_prompt)
        feedback_knowledge = await self._feedback_context(user_prompt)
        retrieval_hit = self._retrieval_hit(user_prompt, pdf_meta)
        quote_evidence = QuoteExtractor.extract(pdf_meta, plan, user_prompt)
        self._log_top_pdf_chunks(pdf_meta)
        print(
            f"[debug] after_retrieval pdf_candidates={pdf_meta.get('candidate_count', 0)} "
            f"pdf_selected={pdf_meta.get('selected_count', 0)} top_score={pdf_meta.get('top_score', 0)} "
            f"pdf_chars={len(pdf_knowledge)} manual_chars={len(manual_knowledge)} feedback_chars={len(feedback_knowledge)} "
            f"feedback_preview={feedback_knowledge[:500]!r} RETRIEVAL_HIT={retrieval_hit} "
            f"plan={plan.intent} author_filter={plan.author_filter!r} quote_evidence={len(quote_evidence)}",
            flush=True,
        )
        has_local_context = bool(pdf_knowledge or manual_knowledge or feedback_knowledge)
        web_context = "" if plan.document_only and has_local_context else await self._web_context(user_prompt, mode, has_local_context)
        manual_count = self._retrieval_count(manual_knowledge, "S")
        feedback_count = self._retrieval_count(feedback_knowledge, "F")
        web_count = self._retrieval_count(web_context, "W")
        print(
            f"[debug] after_rerank selected_chunks={pdf_meta.get('selected_count', 0)} "
            f"scores={[c.get('score') for c in (pdf_meta.get('chunks') or [])[:5]]}",
            flush=True,
        )
        knowledge = build_context_budget(
            user_prompt,
            pdf_knowledge,
            manual_knowledge,
            web_context,
            CONTEXT_MAX_CHARS,
            teacher_feedback=feedback_knowledge,
        )
        stats = _context_part_stats(pdf_knowledge, manual_knowledge, feedback_knowledge, web_context, knowledge)
        full_prompt_preview = self._guarded_prompt(prompt, knowledge, web_context, mode)
        print(
            "[debug] prompt_build_done "
            f"prompt_chars={len(full_prompt_preview)} est_tokens={self._estimated_tokens(full_prompt_preview)} "
            f"pdf_chars={stats['pdf_chars']} manual_chars={stats['manual_chars']} feedback_chars={stats['feedback_chars']} "
            f"web_chars={stats['web_chars']} final_context_chars={stats['final_context_chars']} "
            f"context_truncated={stats['context_truncated']} retrieved_chunk_count={pdf_meta.get('selected_count', 0)} "
            f"retrieved_chunk_titles={[c.get('title') for c in (pdf_meta.get('chunks') or [])[:5]]} "
            f"feedback_count={feedback_count} RETRIEVAL_HIT={retrieval_hit}",
            flush=True,
        )
        print(
            "[ai-retrieval] "
            f"query={user_prompt[:180]!r} mode={mode} "
            f"pdf_chunks={pdf_meta.get('selected_count', 0)} pdf_candidates={pdf_meta.get('candidate_count', 0)} "
            f"pdf_top_score={pdf_meta.get('top_score', 0)} manual={manual_count} feedback={feedback_count} web={web_count}",
            flush=True,
        )
        deterministic = None
        if plan.intent == "QUOTE_SINGLE":
            deterministic = Formatter.quote_single(quote_evidence, plan)
        elif plan.intent == "QUOTE_COLLECTION":
            deterministic = Formatter.quote_collection(quote_evidence, plan)
        elif profile["quote"] or profile["aggregate"]:
            deterministic = self._deterministic_document_answer(user_prompt, pdf_meta, profile)
        if deterministic and (retrieval_hit or quote_evidence or plan.intent.startswith("QUOTE")):
            answer = deterministic
            full_prompt = self._guarded_prompt(prompt, knowledge, web_context, mode + "_deterministic_extract")
            print(
                f"[debug] deterministic_answer mode={mode} intent={plan.intent} quote={profile['quote']} aggregate={profile['aggregate']} "
                f"chunks={pdf_meta.get('selected_count', 0)} quotes={len(quote_evidence)} chars={len(answer)}",
                flush=True,
            )
            if len(answer) > MAX_DISCORD_LEN:
                answer = answer[:MAX_DISCORD_LEN] + "\n\n*(đã rút gọn để vừa Discord; dùng /hvhn_debug_retrieval để xem thêm evidence)*"
            embed = discord.Embed(title=title, description=answer, color=discord.Color.green())
            embed.set_footer(text=f"Then tra loi cho {interaction.user.display_name}. Bam feedback neu can sua.")
            await interaction.followup.send(embed=embed, view=FeedbackView(self.bot, full_prompt, answer))
            print(f"[debug] final_answer_sent deterministic=True chars={len(answer)}", flush=True)
            return
        seed = Formatter.compare_seed(quote_evidence, plan) if plan.intent in {"COMPARE", "ANALYSIS"} else ""
        if seed:
            knowledge = build_context_budget(
                user_prompt,
                seed + "\n\n" + pdf_knowledge,
                manual_knowledge,
                web_context,
                CONTEXT_MAX_CHARS,
                teacher_feedback=feedback_knowledge,
            )
        answer, full_prompt = await self._safe_generate(prompt, knowledge, web_context, mode, retrieval_hit=retrieval_hit)
        if answer is None:
            await interaction.followup.send(self._ai_error_message())
            return
        print(
            f"[debug] llm_answer_received insufficient={self._insufficient_answer(answer)} "
            f"answer_chars={len(answer)} verifier_rejected={self._last_verifier_rejected}",
            flush=True,
        )
        if self._insufficient_answer(answer):
            reason = self._reason_code(pdf_meta, manual_count, feedback_count, web_count, self._last_verifier_rejected)
            if stats["context_truncated"] and reason == "UNKNOWN":
                reason = "CONTEXT_TRUNCATED"
            if self._has_strong_evidence(pdf_meta, manual_count, feedback_count, web_count):
                if reason == "UNKNOWN":
                    reason = "PROMPT_FILTERED"
                forced = await self._force_grounded_answer(prompt, knowledge, web_context, mode)
                if forced and not self._insufficient_answer(forced):
                    print(f"[debug] refusal_suppressed_by=force_grounded original_reason={reason}", flush=True)
                    answer = forced
                    reason = ""
                else:
                    reason = "VERIFIER_REJECTED" if self._last_verifier_rejected else "LLM_REFUSED"
                    answer = self._evidence_fallback_answer(pdf_meta, manual_knowledge, web_context)
                    print(f"[debug] refusal_replaced_by=evidence_fallback original_reason={reason}", flush=True)
                    reason = ""
            if reason and "REASON_CODE:" not in answer:
                answer = answer.rstrip() + f"\n\n`REASON_CODE: {reason}`"

        if len(answer) > MAX_DISCORD_LEN:
            answer = answer[:MAX_DISCORD_LEN] + "\n\n*(da rut gon de vua Discord)*"

        embed = discord.Embed(title=title, description=answer, color=discord.Color.green())
        embed.set_footer(text=f"Then tra loi cho {interaction.user.display_name}. Bam feedback neu can sua.")
        await interaction.followup.send(embed=embed, view=FeedbackView(self.bot, full_prompt, answer))
        print(
            f"[debug] final_answer_sent insufficient={self._insufficient_answer(answer)} "
            f"chars={len(answer)} reason_code={'REASON_CODE:' in answer}",
            flush=True,
        )

    @app_commands.command(name="ai", description="Hỏi trợ giảng AI: giải đáp, gợi ý làm bài, phân tích tác phẩm")
    async def ai(self, interaction: discord.Interaction, question: str):
        prompt = (
            "Trả lời câu hỏi sau thật đúng trọng tâm. Nếu câu hỏi cần tìm Internet, hãy dùng nguồn web đã tra cứu "
            "để tổng hợp câu trả lời cụ thể, không chỉ liệt kê trang tham khảo. Ngắn khi câu hỏi đơn giản; "
            "sâu sắc, có luận điểm khi câu hỏi cần phân tích. Không bịa chi tiết không có nguồn.\n"
            f"Câu hỏi: {question}"
        )
        await self._then_answer(interaction, "Trợ giảng AI - HVHN", question, prompt, "general_safe")

    @app_commands.command(name="van_hoi", description="Hỏi Then về bài Văn, tác phẩm, luận điểm, dẫn chứng")
    async def van_hoi(self, interaction: discord.Interaction, cau_hoi: str):
        prompt = (
            "Trả lời câu hỏi Ngữ Văn sau theo phong cách HVHN: rõ trọng tâm, có chiều sâu, không sáo rỗng. "
            "Dùng nguồn web đã tra cứu để tổng hợp ý cụ thể; không trả lời bằng danh sách nguồn. "
            "Nếu hỏi về trích dẫn/chi tiết tác phẩm mà không có trong nguồn, hãy từ chối khẳng định và nói cần kiểm chứng.\n"
            f"Câu hỏi: {cau_hoi}"
        )
        await self._then_answer(interaction, "Then - Hỏi Văn", cau_hoi, prompt, "literature_qa")

    @app_commands.command(name="goi_y_mo_bai", description="Gợi ý mở bài theo đề Văn")
    async def goi_y_mo_bai(self, interaction: discord.Interaction, de_bai: str, phong_cach: str = "sâu sắc, không sáo"):
        prompt = (
            "Gợi ý 3 hướng mở bài cho đề sau. Không đưa trích dẫn/nhận định phê bình nếu không có nguồn. "
            "Mỗi hướng gồm: ý tưởng, mở bài mẫu ngắn 5-7 câu, khi nào nên dùng.\n"
            f"Phong cách mong muốn: {phong_cach}\nĐề bài: {de_bai}"
        )
        await self._then_answer(interaction, "Then - Gợi Ý Mở Bài", de_bai, prompt, "writing_suggestion")

    @app_commands.command(name="luyen_de_hom_nay", description="Then giao một bài luyện Văn hôm nay")
    async def luyen_de_hom_nay(self, interaction: discord.Interaction, chu_de: str = "nghị luận văn học"):
        prompt = (
            "Tạo một nhiệm vụ luyện Văn hôm nay. Nếu chủ đề cần tác phẩm cụ thể mà không có nguồn, hãy để ở mức mở "
            "hoặc nói cần thầy cô xác nhận. Gồm: đề bài, mục tiêu kỹ năng, dàn ý gợi mở, tiêu chí tự kiểm, bài tập 10 phút.\n"
            f"Chủ đề: {chu_de}"
        )
        await self._then_answer(interaction, "Then - Luyện Đề Hôm Nay", chu_de, prompt, "practice_task")

    @app_commands.command(name="ai_kienthuc_them", description="Thêm tri thức HVHN cho Then (Admin)")
    async def add_knowledge(self, interaction: discord.Interaction, category: str, title: str, content: str, source: str = ""):
        if not self._is_admin(interaction):
            await interaction.response.send_message("Bạn cần role HVHN Admin hoặc quyền Manage Server.", ephemeral=True)
            return
        await self.bot.db.execute(
            """
            INSERT INTO ai_knowledge (category, title, content, source, created_by)
            VALUES ($1, $2, $3, $4, $5)
            """,
            category.strip(),
            title.strip(),
            content.strip(),
            source.strip() or None,
            interaction.user.id,
        )
        await interaction.response.send_message("Đã thêm tri thức cho Then.", ephemeral=True)

    @app_commands.command(name="ai_kienthuc_tim", description="Tìm tri thức đã nạp cho Then")
    async def search_knowledge(self, interaction: discord.Interaction, tu_khoa: str):
        rows = await self.bot.db.fetch(
            """
            SELECT id, category, title, content
            FROM ai_knowledge
            WHERE approved = TRUE
              AND (lower(title) LIKE $1 OR lower(content) LIKE $1 OR lower(category) LIKE $1)
            ORDER BY created_at DESC
            LIMIT 8
            """,
            f"%{tu_khoa.lower()}%",
        )
        if not rows:
            await interaction.response.send_message("Chưa thấy tri thức phù hợp.", ephemeral=True)
            return
        embed = discord.Embed(title="Tri thức Then", color=discord.Color.blue())
        for row in rows:
            content = row["content"][:250] + ("..." if len(row["content"]) > 250 else "")
            embed.add_field(name=f"#{row['id']} [{row['category']}] {row['title']}", value=content, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _run_debug_retrieval(self, query: str) -> list[str]:
        print(f"[debug] before_retrieval query={query[:220]!r} mode=debug_command", flush=True)
        plan = Planner.build(query)
        profile = self._request_profile(query)
        retrieval_limit = max(plan.retrieval_limit, PDF_AGGREGATE_LIMIT if profile["aggregate"] or profile["quote"] else PDF_DEFAULT_LIMIT)
        pdf_meta = await self._pdf_retrieval(query, limit=retrieval_limit)
        manual_knowledge = await self._knowledge_context(query)
        feedback_knowledge = await self._feedback_context(query)
        quote_evidence = QuoteExtractor.extract(pdf_meta, plan, query)
        retrieval_hit = self._retrieval_hit(query, pdf_meta)
        self._log_top_pdf_chunks(pdf_meta)
        has_local_context = bool(pdf_meta.get("context") or manual_knowledge or feedback_knowledge)
        web_context = await self._web_context(query, "debug_retrieval", has_local_context)
        manual_count = self._retrieval_count(manual_knowledge, "S")
        feedback_count = self._retrieval_count(feedback_knowledge, "F")
        web_count = self._retrieval_count(web_context, "W")
        decision = self._reason_code(pdf_meta, manual_count, feedback_count, web_count)
        if decision == "UNKNOWN" and self._has_strong_evidence(pdf_meta, manual_count, feedback_count, web_count):
            decision = "OK"
        knowledge = build_context_budget(
            query,
            pdf_meta.get("context", ""),
            manual_knowledge,
            web_context,
            CONTEXT_MAX_CHARS,
            teacher_feedback=feedback_knowledge,
        )
        stats = _context_part_stats(pdf_meta.get("context", ""), manual_knowledge, feedback_knowledge, web_context, knowledge)
        prompt_preview = self._guarded_prompt(query, knowledge, web_context, "debug_retrieval")

        lines = [
            f"Query: `{query[:180]}`",
            f"Plan: `{plan.intent}` | author_filter: `{plan.author_filter or 'none'}` | exact_quote: `{plan.exact_quote}` | aggregate: `{plan.aggregate}`",
            f"Reason code: `{decision}`",
            f"Verifier decision: `{decision}` (debug retrieval only; no LLM/verifier call)",
            f"PDF candidates: `{pdf_meta.get('candidate_count', 0)}` | selected sent to LLM: `{pdf_meta.get('selected_count', 0)}` | top_score: `{pdf_meta.get('top_score', 0)}`",
            f"RETRIEVAL_HIT: `{retrieval_hit}`",
            f"Manual: `{manual_count}` | Feedback: `{feedback_count}` | Web sources: `{web_count}`",
            f"Quote evidence extracted: `{len(quote_evidence)}`",
            f"Prompt chars: `{len(prompt_preview)}` | est tokens: `{self._estimated_tokens(prompt_preview)}`",
            f"Chars PDF/manual/feedback/web/final: `{stats['pdf_chars']}` / `{stats['manual_chars']}` / `{stats['feedback_chars']}` / `{stats['web_chars']}` / `{stats['final_context_chars']}`",
            f"Context truncated: `{stats['context_truncated']}`",
            "",
            "Final selected PDF chunks sent to LLM:",
        ]
        chunks = pdf_meta.get("chunks") or []
        if not chunks:
            lines.append("- Khong co PDF chunk phu hop.")
        for chunk in chunks:
            first_500 = re.sub(r"\s+", " ", chunk.get("first_500") or chunk.get("excerpt", "")).strip()[:500]
            sent_excerpt = re.sub(r"\s+", " ", chunk.get("excerpt", "")).strip()[:500]
            lines.append(
                f"- P{chunk.get('index')} doc=`{chunk.get('title')}` chunk=`{chunk.get('chunk_index')}` "
                f"rank=`{chunk.get('rank')}` kw=`{chunk.get('keyword_score')}` phrase=`{chunk.get('phrase_score')}` "
                f"coverage=`{chunk.get('coverage')}` rerank_score=`{chunk.get('score')}`\n"
                f"  matched_phrases: `{chunk.get('matched_phrases')}`\n"
                f"  missing_keywords: `{chunk.get('missing_keywords')}`\n"
                f"  first500: {first_500}\n"
                f"  extracted_preview: {first_500}\n"
                f"  sent: {sent_excerpt}"
            )
        lines.append("")
        if quote_evidence:
            lines.append("Extracted quote objects:")
            for item in quote_evidence[:12]:
                lines.append(f"- author=`{item.author or 'unknown'}` doc=`{item.pdf_title}` quote={item.quote[:350]}")
            lines.append("")
        lines.append("Selected context block sent to LLM:")
        lines.append(_clip_text(knowledge, 2200))
        text = "\n".join(lines)
        pages = []
        while text:
            pages.append(text[:MAX_DISCORD_LEN])
            text = text[MAX_DISCORD_LEN:]
        return pages[:5]

    @app_commands.command(name="hvhn_debug_retrieval", description="Debug retrieval PDF/manual/feedback/web cho Then (Admin)")
    async def debug_retrieval(self, interaction: discord.Interaction, query: str):
        if not self._is_admin(interaction):
            await interaction.response.send_message("Ban can role HVHN Admin hoac quyen Manage Server.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            pages = await asyncio.wait_for(self._run_debug_retrieval(query), timeout=DEBUG_COMMAND_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            print(f"[debug] hvhn_debug_retrieval timeout query={query[:180]!r}", flush=True)
            await interaction.followup.send("Debug retrieval timeout. Xem Render logs `[debug]` de biet diem ket.", ephemeral=True)
            return
        except Exception as exc:
            print(f"[debug] hvhn_debug_retrieval exception={type(exc).__name__}: {exc}", flush=True)
            await interaction.followup.send(f"Debug retrieval loi: `{type(exc).__name__}: {str(exc)[:1200]}`", ephemeral=True)
            return
        for i, page in enumerate(pages, start=1):
            suffix = f"\n\n(page {i}/{len(pages)})" if len(pages) > 1 else ""
            await interaction.followup.send(page + suffix, ephemeral=True)

    @app_commands.command(name="debug_retrieval", description="Debug retrieval nhanh trước khi gọi LLM (Admin)")
    async def debug_retrieval_alias(self, interaction: discord.Interaction, query: str):
        if not self._is_admin(interaction):
            await interaction.response.send_message("Ban can role HVHN Admin hoac quyen Manage Server.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            pages = await asyncio.wait_for(self._run_debug_retrieval(query), timeout=DEBUG_COMMAND_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            print(f"[debug] debug_retrieval timeout query={query[:180]!r}", flush=True)
            await interaction.followup.send("Debug retrieval timeout. Xem Render logs `[debug]` de biet diem ket.", ephemeral=True)
            return
        except Exception as exc:
            print(f"[debug] debug_retrieval exception={type(exc).__name__}: {exc}", flush=True)
            await interaction.followup.send(f"Debug retrieval loi: `{type(exc).__name__}: {str(exc)[:1200]}`", ephemeral=True)
            return
        for i, page in enumerate(pages, start=1):
            suffix = f"\n\n(page {i}/{len(pages)})" if len(pages) > 1 else ""
            await interaction.followup.send(page + suffix, ephemeral=True)

    @app_commands.command(name="ai_feedback_stats", description="Xem thống kê feedback AI (Admin)")
    async def feedback_stats(self, interaction: discord.Interaction):
        if not self._is_admin(interaction):
            await interaction.response.send_message("Bạn cần role HVHN Admin hoặc quyền Manage Server.", ephemeral=True)
            return
        rows = await self.bot.db.fetch("SELECT rating, count(*) AS n FROM ai_feedback GROUP BY rating ORDER BY rating")
        total_k = await self.bot.db.fetchval("SELECT count(*) FROM ai_knowledge WHERE approved = TRUE")
        text = "\n".join(f"`{row['rating']}`: {row['n']}" for row in rows) or "Chưa có feedback."
        await interaction.response.send_message(f"Tri thức đã duyệt: `{total_k}`\nFeedback:\n{text}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AI(bot))

