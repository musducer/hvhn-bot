import os
import re
from html import unescape
from urllib.parse import parse_qs, unquote, urlparse

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

GROQ_MODEL = "llama-3.3-70b-versatile"
GEMINI_MODEL = "gemini-2.0-flash"
MAX_DISCORD_LEN = 1900
WEB_RESULT_LIMIT = 5
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
    "văn bản người dùng gửi hoặc TRI THỨC HVHN LIÊN QUAN.\n"
    "3. Nếu câu hỏi cần chi tiết văn bản/tác phẩm mà không có dữ liệu xác thực, hãy nói "
    "'không đủ dữ liệu để khẳng định' và đưa cách kiểm chứng/hướng làm an toàn.\n"
    "4. Chỉ nhận xét dựa trên văn bản người dùng đưa vào; không suy diễn "
    "học sinh đã viết những ý không có trong bài.\n"
    "5. Mọi câu trả lời phải có mục 'Mức căn cứ' và 'Cần kiểm chứng'.\n"
    "Giọng văn: sắc, ấm, có chiều sâu, tránh sáo rỗng. Không viết thay toàn bộ bài trừ khi "
    "người dùng yêu cầu một đoạn mẫu ngắn."
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

    async def ask_groq(
        self,
        session: aiohttp.ClientSession,
        key: str,
        prompt: str,
        system_prompt: str = SYSTEM_PROMPT,
        temperature: float = 0.2,
    ) -> tuple[bool, str]:
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
            if resp.status == 429:
                return False, "RATE_LIMIT"
            if resp.status != 200:
                return False, f"HTTP {resp.status}"
            data = await resp.json()
            return True, data["choices"][0]["message"]["content"].strip()

    async def ask_gemini(
        self,
        session: aiohttp.ClientSession,
        key: str,
        prompt: str,
        system_prompt: str = SYSTEM_PROMPT,
        temperature: float = 0.2,
    ) -> tuple[bool, str]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={key}"
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature, "topP": 0.4},
        }
        async with session.post(url, json=payload, timeout=60) as resp:
            if resp.status == 429:
                return False, "RATE_LIMIT"
            if resp.status != 200:
                return False, f"HTTP {resp.status}"
            data = await resp.json()
            try:
                return True, data["candidates"][0]["content"]["parts"][0]["text"].strip()
            except (KeyError, IndexError):
                return False, "EMPTY"

    async def generate(
        self,
        prompt: str,
        system_prompt: str = SYSTEM_PROMPT,
        temperature: float = 0.2,
    ) -> str | None:
        async with aiohttp.ClientSession() as session:
            for key in self.groq_keys:
                try:
                    ok, content = await self.ask_groq(session, key, prompt, system_prompt, temperature)
                    if ok:
                        return content
                    if content != "RATE_LIMIT":
                        print(f"[ai] Groq error: {content}")
                except Exception as exc:
                    print(f"[ai] Groq exception: {exc}")

            for key in self.gemini_keys:
                try:
                    ok, content = await self.ask_gemini(session, key, prompt, system_prompt, temperature)
                    if ok:
                        return content
                    if content != "RATE_LIMIT":
                        print(f"[ai] Gemini error: {content}")
                except Exception as exc:
                    print(f"[ai] Gemini exception: {exc}")
        return None

    def _has_ai(self) -> bool:
        return bool(self.groq_keys or self.gemini_keys)

    def _is_admin(self, interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member):
            return False
        role_name = os.getenv("HVHN_ADMIN_ROLE", "HVHN Admin").strip()
        return any(role.name == role_name for role in interaction.user.roles) or interaction.user.guild_permissions.manage_guild

    async def _knowledge_context(self, query: str, limit: int = 6) -> str:
        terms = [t for t in query.lower().split() if len(t) >= 3][:8]
        if not terms:
            rows = await self.bot.db.fetch(
                "SELECT category, title, content FROM ai_knowledge WHERE approved = TRUE ORDER BY created_at DESC LIMIT $1",
                limit,
            )
        else:
            patterns = [f"%{term}%" for term in terms[:5]]
            rows = await self.bot.db.fetch(
                """
                SELECT category, title, content
                FROM ai_knowledge
                WHERE approved = TRUE
                  AND (
                    lower(title) LIKE ANY($1::text[])
                    OR lower(content) LIKE ANY($1::text[])
                    OR lower(category) LIKE ANY($1::text[])
                  )
                ORDER BY created_at DESC
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

    async def _web_context(self, query: str, mode: str) -> str:
        if mode == "user_text_only":
            return ""

        async with aiohttp.ClientSession() as session:
            try:
                results = await self._search_serper(session, query)
                if not results:
                    results = await self._search_tavily(session, query)
                if not results:
                    results = await self._search_duckduckgo(session, query)
            except Exception as exc:
                print(f"[ai] Web search exception: {exc}")
                return ""

        deduped = {}
        for item in results:
            deduped.setdefault(item["url"], item)
        results = sorted(deduped.values(), key=lambda item: self._source_score(item["url"]), reverse=True)

        chunks = []
        for index, item in enumerate(results[:WEB_RESULT_LIMIT], start=1):
            snippet = item["snippet"][:600]
            trust = "ưu tiên" if self._source_score(item["url"]) else "cần kiểm chứng"
            chunks.append(f"[W{index}] {item['title']}\nURL: {item['url']}\nĐộ tin cậy: {trust}\nTóm tắt: {snippet}")
        return "\n\n".join(chunks)

    @staticmethod
    def _guarded_prompt(prompt: str, knowledge: str, web_context: str, mode: str) -> str:
        source_block = knowledge or "KHÔNG CÓ TRI THỨC HVHN PHÙ HỢP ĐƯỢC NẠP."
        web_block = web_context or "KHÔNG CÓ NGUỒN WEB ĐƯỢC TRUY XUẤT."
        return (
            "ĐÂY LÀ LỆNH CẦN TRẢ LỜI AN TOÀN, CHỐNG HALLUCINATION.\n"
            f"CHẾ ĐỘ: {mode}\n\n"
            "TRI THỨC HVHN LIÊN QUAN:\n"
            f"{source_block}\n\n"
            "NGUỒN WEB VỪA TRA CỨU:\n"
            f"{web_block}\n\n"
            "QUY TẮC TRẢ LỜI BẮT BUỘC:\n"
            "- Chỉ đưa chi tiết/sự kiện khi nó có trong TRI THỨC HVHN, NGUỒN WEB, hoặc văn bản người dùng đã đưa.\n"
            "- Mọi khẳng định lấy từ web phải gắn nhãn nguồn dạng [W1], [W2]...\n"
            "- Nếu nguồn web chỉ là snippet/tóm tắt, không trích dẫn nguyên văn và không khẳng định quá mức.\n"
            "- Kiến thức phổ thông chỉ được dùng cho khái niệm/hướng làm bài chung; không dùng để khẳng định "
            "chi tiết tác phẩm, trích dẫn, năm tháng, hoàn cảnh sáng tác, nhân vật, hay nhận định phê bình nếu không có nguồn.\n"
            "- Không trích dẫn nguyên văn nếu không có nguồn trong prompt.\n"
            "- Nếu câu hỏi yêu cầu một thông tin mà dữ liệu không có, hãy nói không đủ dữ liệu.\n"
            "- Cuối câu trả lời bắt buộc có 2 dòng:\n"
            "  Mức căn cứ: <Văn bản người dùng / Tri thức HVHN / Nguồn web [W...] / Kiến thức phổ thông cần kiểm chứng / Không đủ dữ liệu>\n"
            "  Cần kiểm chứng: <không có / liệt kê các điểm cần kiểm chứng>\n\n"
            "YÊU CẦU NGƯỜI DÙNG:\n"
            f"{prompt}"
        )

    @staticmethod
    def _has_grounding_footer(answer: str) -> bool:
        lowered = answer.lower()
        return ("mức căn cứ:" in lowered or "muc can cu:" in lowered) and (
            "cần kiểm chứng:" in lowered or "can kiem chung:" in lowered
        )

    async def _safe_generate(self, prompt: str, knowledge: str, web_context: str, mode: str) -> tuple[str | None, str]:
        full_prompt = self._guarded_prompt(prompt, knowledge, web_context, mode)
        answer = await self.generate(full_prompt, THEN_SYSTEM_PROMPT, temperature=0.15)
        if answer and not self._has_grounding_footer(answer):
            repair_prompt = (
                "Sửa câu trả lời sau để tuân thủ quy tắc chống hallucination. "
                "Không thêm thông tin mới. Bắt buộc thêm 'Mức căn cứ' và 'Cần kiểm chứng'.\n\n"
                f"CÂU TRẢ LỜI CẦN SỬA:\n{answer}"
            )
            repaired = await self.generate(
                self._guarded_prompt(repair_prompt, knowledge, web_context, "repair"),
                THEN_SYSTEM_PROMPT,
                temperature=0.0,
            )
            if repaired:
                answer = repaired
        return answer, full_prompt

    async def _then_answer(self, interaction: discord.Interaction, title: str, user_prompt: str, prompt: str, mode: str):
        if not self._has_ai():
            await interaction.response.send_message("Tính năng AI chưa cấu hình API key.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        knowledge = await self._knowledge_context(user_prompt)
        web_context = await self._web_context(user_prompt, mode)
        answer, full_prompt = await self._safe_generate(prompt, knowledge, web_context, mode)
        if answer is None:
            await interaction.followup.send("AI đang quá tải hoặc lỗi API. Thử lại sau ít phút.")
            return

        if len(answer) > MAX_DISCORD_LEN:
            answer = answer[:MAX_DISCORD_LEN] + "\n\n*(đã rút gọn để vừa Discord)*"

        embed = discord.Embed(title=title, description=answer, color=discord.Color.green())
        embed.set_footer(text=f"Then trả lời cho {interaction.user.display_name}. Bấm feedback nếu cần sửa.")
        await interaction.followup.send(embed=embed, view=FeedbackView(self.bot, full_prompt, answer))

    @app_commands.command(name="ai", description="Hỏi trợ giảng AI: giải đáp, gợi ý làm bài, phân tích tác phẩm")
    async def ai(self, interaction: discord.Interaction, question: str):
        prompt = (
            "Trả lời câu hỏi sau. Nếu câu hỏi cần thông tin văn bản/tác phẩm/trích dẫn mà không có nguồn, "
            "không được bịa; hãy đưa cách kiểm chứng.\n"
            f"Câu hỏi: {question}"
        )
        await self._then_answer(interaction, "Trợ giảng AI - HVHN", question, prompt, "general_safe")

    @app_commands.command(name="van_hoi", description="Hỏi Then về bài Văn, tác phẩm, luận điểm, dẫn chứng")
    async def van_hoi(self, interaction: discord.Interaction, cau_hoi: str):
        prompt = (
            "Trả lời câu hỏi Ngữ Văn sau theo phong cách HVHN: rõ trọng tâm, có chiều sâu, không sáo rỗng. "
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
