import os
import re
import unicodedata
from pathlib import Path
from html import unescape
from urllib.parse import parse_qs, unquote, urlparse

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from pdf_knowledge import search_pdf_knowledge

GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
MAX_DISCORD_LEN = 3800
WEB_RESULT_LIMIT = 5
WEB_CONTEXT_LIMIT = 7
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
    if len(text) > 6000:
        text = text[:6000] + "\n...(đã rút gọn chỉ thị hệ thống vì quá dài)"
    return text


LITERATURE_SYSTEM_INSTRUCTIONS = _load_literature_system_instructions()

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


class AI(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.groq_keys = [k.strip() for k in os.getenv("GROQ_API_KEYS", "").split(",") if k.strip()]
        self.gemini_keys = [k.strip() for k in os.getenv("GEMINI_API_KEYS", "").split(",") if k.strip()]
        self.serper_key = os.getenv("SERPER_API_KEY", "").strip()
        self.tavily_key = os.getenv("TAVILY_API_KEY", "").strip()
        self.last_ai_errors: list[str] = []

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
            "body": (body or "")[:2000],
            "exception": repr(exc) if exc else "",
        }

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
            f"status={status} body={(body or '')[:1000]!r} exception={repr(exc) if exc else ''}"
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
        print(
            "[ai-api] "
            f"event=generate_start groq_keys={len(self.groq_keys)} gemini_keys={len(self.gemini_keys)} "
            f"groq_model={GROQ_MODEL} gemini_model={GEMINI_MODEL} prompt_chars={len(prompt)}"
        )
        async with aiohttp.ClientSession() as session:
            for index, key in enumerate(self.groq_keys, start=1):
                self._log_api_event(
                    "try",
                    provider="groq",
                    model=GROQ_MODEL,
                    key=key,
                    key_index=index,
                    total_keys=len(self.groq_keys),
                )
                try:
                    ok, content = await self.ask_groq(session, key, prompt, system_prompt, temperature)
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
                        errors.append(f"Groq {content.get('status')}: {content.get('body', '')[:300]}")
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

            for index, key in enumerate(self.gemini_keys, start=1):
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
                        errors.append(f"Gemini {content.get('status')}: {content.get('body', '')[:300]}")
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
            f"errors={self.last_ai_errors!r}"
        )
        return None


    def _has_ai(self) -> bool:
        return bool(self.groq_keys or self.gemini_keys)

    def _ai_error_message(self) -> str:
        joined = " | ".join(self.last_ai_errors)
        lowered = joined.lower()
        if not joined:
            return "AI loi API nhung chua co chi tiet trong log."
        if "401" in lowered or "403" in lowered or "api key" in lowered:
            reason = "API key sai hoac het quyen."
        elif "429" in lowered or "rate_limit" in lowered:
            reason = "API key het quota hoac bi rate limit."
        elif "404" in lowered or "model" in lowered:
            reason = "Ten model khong hop le hoac model da doi."
        elif "timeout" in lowered:
            reason = "API phan hoi qua cham/timeout."
        else:
            reason = "API provider tra loi."
        return f"{reason} Xem Render logs dong `[ai] ...` de biet chi tiet."


    def _is_admin(self, interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member):
            return False
        role_name = os.getenv("HVHN_ADMIN_ROLE", "HVHN Admin").strip()
        return any(role.name == role_name for role in interaction.user.roles) or interaction.user.guild_permissions.manage_guild

    async def _pdf_knowledge_context(self, query: str) -> str:
        try:
            return await search_pdf_knowledge(self.bot.db, query, limit=16)
        except Exception as exc:
            print(f"[ai] PDF knowledge exception: {exc}")
            return ""

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
                print(f"[ai] manual knowledge FTS fallback: {exc}")
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

    async def _feedback_context(self, query: str, limit: int = 4) -> str:
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
        return "\n\n".join(f"[F{i}] Loi giao vien da sua:\n{row['correction']}" for i, row in enumerate(rows, 1))


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
        return "".join(ch for ch in value if unicodedata.category(ch) != "Mn").lower()

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
            print(f"[ai] web=skip mode={mode} local={has_local_context}")
            return ""

        async with aiohttp.ClientSession() as session:
            try:
                results = []
                results.extend(await self._search_serper(session, query))
                results.extend(await self._search_tavily(session, query))
                if not results:
                    results = await self._search_duckduckgo(session, query)
            except Exception as exc:
                print(f"[ai] Web search exception: {exc}")
                return ""

        deduped = {}
        for item in results:
            deduped.setdefault(item["url"], item)
        results = list(deduped.values())
        print(f"[ai] web_results={len(results[:WEB_CONTEXT_LIMIT])}")

        chunks = []
        for index, item in enumerate(results[:WEB_CONTEXT_LIMIT], start=1):
            snippet = item["snippet"][:850]
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
            "- Chi dat trong ngoac kep neu thay nguyen van trong van ban/context.\n"
            "- Neu context khong du de khang dinh, phai noi ro: chua du du lieu de khang dinh.\n"
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

    async def _verify_answer(self, answer: str, prompt: str, knowledge: str, web_context: str, mode: str) -> str:
        if not answer:
            return answer
        verifier_prompt = (
            "Kiem chung cau tra loi sau bang dung context duoc cung cap. "
            "Hay giu cau dung, xoa hoac viet lai moi khang dinh khong du can cu thanh 'chua du du lieu de khang dinh'. "
            "Tuyet doi khong them tac gia/tac pham/nam/trich dan/nhan dinh moi. "
            "Khong hien ma noi bo [P1]/[S1]/[W1] hoac URL dai. Tra lai ban da sua, tieng Viet.\n\n"
            f"CAU HOI/PROMPT:\n{prompt}\n\n"
            f"CONTEXT HVHN:\n{knowledge or 'KHONG CO'}\n\n"
            f"WEB:\n{web_context or 'KHONG CO'}\n\n"
            f"CAU TRA LOI CAN KIEM:\n{answer}"
        )
        verified = await self.generate(verifier_prompt, THEN_SYSTEM_PROMPT, temperature=0.0)
        if verified:
            print(f"[ai] verifier=ok mode={mode}")
            return verified
        print(f"[ai] verifier=skipped mode={mode}")
        return answer

    async def _safe_generate(self, prompt: str, knowledge: str, web_context: str, mode: str) -> tuple[str | None, str]:
        full_prompt = self._guarded_prompt(prompt, knowledge, web_context, mode)
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
            answer = await self._verify_answer(answer, prompt, knowledge, web_context, mode)
            answer = self._strip_internal_markers(answer)
        return answer, full_prompt


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
            await interaction.response.send_message("Tính năng AI chưa cấu hình API key.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        pdf_knowledge = await self._pdf_knowledge_context(user_prompt)
        manual_knowledge = await self._knowledge_context(user_prompt)
        feedback_knowledge = await self._feedback_context(user_prompt)
        knowledge_parts = []
        if pdf_knowledge:
            knowledge_parts.append("KHO PDF HVHN:\n" + pdf_knowledge)
        if manual_knowledge:
            knowledge_parts.append("TRI THUC HVHN THU CONG:\n" + manual_knowledge)
        if feedback_knowledge:
            knowledge_parts.append("GOP Y GIAO VIEN DA SUA TRUOC DAY:\n" + feedback_knowledge)
        knowledge = "\n\n".join(knowledge_parts)
        has_local_context = bool(pdf_knowledge or manual_knowledge or feedback_knowledge)
        web_context = await self._web_context(user_prompt, mode, has_local_context)
        print(f"[ai] query={user_prompt[:120]!r} mode={mode} pdf={bool(pdf_knowledge)} manual={bool(manual_knowledge)} feedback={bool(feedback_knowledge)} web={bool(web_context)}")
        answer, full_prompt = await self._safe_generate(prompt, knowledge, web_context, mode)
        if answer is None:
            await interaction.followup.send(self._ai_error_message())
            return

        if len(answer) > MAX_DISCORD_LEN:
            answer = answer[:MAX_DISCORD_LEN] + "\n\n*(đã rút gọn để vừa Discord)*"

        embed = discord.Embed(title=title, description=answer, color=discord.Color.green())
        embed.set_footer(text=f"Then trả lời cho {interaction.user.display_name}. Bấm feedback nếu cần sửa.")
        await interaction.followup.send(embed=embed, view=FeedbackView(self.bot, full_prompt, answer))

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
