import os
import re
from html import unescape
from urllib.parse import parse_qs, unquote, urlparse

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from pdf_knowledge import search_pdf_knowledge

GROQ_MODEL = "llama-3.3-70b-versatile"
GEMINI_MODEL = "gemini-2.0-flash"
MAX_DISCORD_LEN = 1900
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
    "Giọng văn: sắc, ấm, có chiều sâu, tránh sáo rỗng. Câu hỏi đơn giản thì trả lời gọn; "
    "câu hỏi cần phân tích thì đi sâu có lớp lang."
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

    async def _pdf_knowledge_context(self, query: str) -> str:
        try:
            return await search_pdf_knowledge(self.bot.db, query, limit=10)
        except Exception as exc:
            print(f"[ai] PDF knowledge exception: {exc}")
            return ""

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
            "include_answer": True,
        }
        async with session.post("https://api.tavily.com/search", json=payload, timeout=15) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
        results = []
        answer = self._clean_text(data.get("answer") or "")
        if answer:
            results.append({
                "title": "Tavily tổng hợp nhanh",
                "url": "https://tavily.com/",
                "snippet": answer[:700],
            })
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
        results = sorted(deduped.values(), key=lambda item: self._source_score(item["url"]), reverse=True)

        chunks = []
        for index, item in enumerate(results[:WEB_CONTEXT_LIMIT], start=1):
            snippet = item["snippet"][:850]
            trust = "ưu tiên" if self._source_score(item["url"]) else "cần kiểm chứng"
            chunks.append(f"[W{index}] {item['title']}\nURL: {item['url']}\nĐộ tin cậy: {trust}\nTóm tắt: {snippet}")
        return "\n\n".join(chunks)

    @staticmethod
    def _guarded_prompt(prompt: str, knowledge: str, web_context: str, mode: str) -> str:
        source_block = knowledge or "KHÔNG CÓ KHO PDF/TRI THỨC HVHN PHÙ HỢP ĐƯỢC NẠP."
        web_block = web_context or "KHÔNG CÓ NGUỒN WEB ĐƯỢC TRUY XUẤT."
        return (
            "ĐÂY LÀ LỆNH CẦN TRẢ LỜI HAY, ĐÚNG TRỌNG TÂM, CÓ CĂN CỨ.\n"
            f"CHẾ ĐỘ: {mode}\n\n"
            "KHO PDF/TRI THỨC HVHN ĐÃ ĐỌC TRƯỚC KHI SEARCH WEB:\n"
            f"{source_block}\n\n"
            "NGUỒN WEB VỪA TRA CỨU:\n"
            f"{web_block}\n\n"
            "QUY TẮC TRẢ LỜI BẮT BUỘC:\n"
            "- Dòng/đoạn đầu tiên phải trả lời thẳng vào câu hỏi của người dùng, không mở bằng 'có thể tham khảo'.\n"
            "- Không được chỉ liệt kê nguồn. Phải tổng hợp thành câu trả lời có nội dung cụ thể.\n"
            "- Ưu tiên nguồn [P...] từ PDF/kho HVHN hơn nguồn web. Nếu [P...] đã đủ, trả lời dựa trên [P...] và chỉ dùng web để bổ sung/kiểm chứng.\n"
            "- Nếu người dùng hỏi gợi ý/danh sách, hãy đưa danh sách cụ thể kèm lý do ngắn cho từng mục.\n"
            "- Câu đơn giản: trả lời 3-7 dòng. Câu cần phân tích: trả lời sâu hơn, có luận điểm rõ.\n"
            "- Mọi khẳng định quan trọng lấy từ kho PDF/HVHN phải gắn nguồn dạng [P1], [P2] hoặc [S1] ngay sau ý liên quan.\n"
            "- Mọi khẳng định quan trọng lấy từ web phải gắn nguồn dạng [W1], [W2] ngay sau ý liên quan.\n"
            "- Nếu nguồn web chỉ là snippet/tóm tắt, không trích dẫn nguyên văn và không khẳng định quá mức.\n"
            "- Kiến thức phổ thông chỉ được dùng cho khái niệm/hướng làm bài chung; không dùng để khẳng định "
            "chi tiết tác phẩm, trích dẫn, năm tháng, hoàn cảnh sáng tác, nhân vật, hay nhận định phê bình nếu không có nguồn.\n"
            "- Không trích dẫn nguyên văn nếu không có nguồn trong prompt.\n"
            "- Nếu câu hỏi yêu cầu một thông tin mà dữ liệu không có, hãy nói không đủ dữ liệu.\n"
            "- Cuối câu trả lời chỉ thêm một dòng ngắn: Nguồn: [P1], [S1], [W1]... Nếu không có nguồn thì ghi: Nguồn: chưa đủ dữ liệu.\n"
            "- Không thêm mục 'Mức căn cứ'/'Cần kiểm chứng' trừ khi thật sự cần cảnh báo rủi ro.\n\n"
            "YÊU CẦU NGƯỜI DÙNG:\n"
            f"{prompt}"
        )

    @staticmethod
    def _has_grounding_footer(answer: str) -> bool:
        lowered = answer.lower()
        return "nguồn:" in lowered or "nguon:" in lowered or "chưa đủ dữ liệu" in lowered or "chua du du lieu" in lowered

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

    async def _safe_generate(self, prompt: str, knowledge: str, web_context: str, mode: str) -> tuple[str | None, str]:
        full_prompt = self._guarded_prompt(prompt, knowledge, web_context, mode)
        answer = await self.generate(full_prompt, THEN_SYSTEM_PROMPT, temperature=0.15)
        needs_repair = bool(answer) and (
            not self._has_grounding_footer(answer)
            or self._looks_like_source_dump(answer)
            or (bool(knowledge) and "[P" in knowledge and "[P" not in answer)
            or (bool(web_context) and "[W" not in answer)
        )
        if answer and needs_repair:
            repair_prompt = (
                "Sửa câu trả lời sau để trả lời đúng trọng tâm, không bịa, không chỉ liệt kê nguồn. "
                "Không thêm thông tin mới ngoài KHO PDF/TRI THỨC HVHN/NGUỒN WEB đã cung cấp. "
                "Mở đầu bằng câu trả lời trực tiếp. Nếu câu hỏi xin gợi ý/danh sách, đưa mục cụ thể và lý do. "
                "Gắn [P...]/[S...] sau ý dùng từ PDF/HVHN, gắn [W...] sau ý dùng từ web, rồi thêm dòng cuối 'Nguồn: [P...], [S...], [W...]'.\n\n"
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
        pdf_knowledge = await self._pdf_knowledge_context(user_prompt)
        manual_knowledge = await self._knowledge_context(user_prompt)
        knowledge_parts = []
        if pdf_knowledge:
            knowledge_parts.append("KHO PDF HVHN:\n" + pdf_knowledge)
        if manual_knowledge:
            knowledge_parts.append("TRI THỨC HVHN THỦ CÔNG:\n" + manual_knowledge)
        knowledge = "\n\n".join(knowledge_parts)
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
