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
    "Ban la tro giang mon Ngu Van cho cong dong HVHN. Tra loi bang tieng Viet, "
    "ro trong tam, uu tien giup hoc sinh tu suy nghi. Tuyet doi khong bia thong tin. "
    "Neu khong du can cu, phai noi ro khong du du lieu thay vi doan bua."
)

THEN_SYSTEM_PROMPT = (
    "Ban la Then, tro giang Ngu Van cua Hon Van - Hon Nguoi.\n"
    "LUAT BAT BUOC:\n"
    "1. Khong duoc bia tac gia, tac pham, nhan vat, nam sang tac, hoan canh sang tac, "
    "trich dan, nhan dinh phe binh, so lieu, hay noi dung bai hoc.\n"
    "2. Khong dat trong dau ngoac kep bat ky cau nao neu cau do khong xuat hien trong "
    "van ban nguoi dung gui hoac TRI THUC HVHN LIEN QUAN.\n"
    "3. Neu cau hoi can chi tiet van ban/tac pham ma khong co du lieu xac thuc, hay noi "
    "'khong du du lieu de khang dinh' va dua cach kiem chung/huong lam an toan.\n"
    "4. Khi cham/sua bai, chi nhan xet dua tren van ban nguoi dung dua vao; khong suy dien "
    "hoc sinh da viet nhung y khong co trong bai.\n"
    "5. Moi cau tra loi phai co muc 'Muc can cu' va 'Can kiem chung'.\n"
    "Giong van: sac, am, co chieu sau, tranh sao rong. Khong viet thay toan bo bai tru khi "
    "nguoi dung yeu cau mot doan mau ngan."
)


class FeedbackModal(discord.ui.Modal, title="Sua cau tra loi cho Then"):
    correction = discord.ui.TextInput(
        label="Cau sua / gop y cua giao vien",
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
            "Da luu gop y. Then se dung du lieu nay de mai prompt/kho tri thuc.",
            ephemeral=True,
        )


class FeedbackView(discord.ui.View):
    def __init__(self, bot: commands.Bot, prompt: str, answer: str):
        super().__init__(timeout=86400)
        self.bot = bot
        self.prompt = prompt
        self.answer = answer

    @discord.ui.button(label="Dung", style=discord.ButtonStyle.success)
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
        await interaction.response.send_message("Da luu danh gia tot.", ephemeral=True)

    @discord.ui.button(label="Can sua", style=discord.ButtonStyle.danger)
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
            trust = "uu tien" if self._source_score(item["url"]) else "can kiem chung"
            chunks.append(f"[W{index}] {item['title']}\nURL: {item['url']}\nDo tin cay: {trust}\nTom tat: {snippet}")
        return "\n\n".join(chunks)

    @staticmethod
    def _guarded_prompt(prompt: str, knowledge: str, web_context: str, mode: str) -> str:
        source_block = knowledge or "KHONG CO TRI THUC HVHN PHU HOP DUOC NAP."
        web_block = web_context or "KHONG CO NGUON WEB DUOC TRUY XUAT."
        return (
            "DAY LA LENH CAN TRA LOI AN TOAN, CHONG HALLUCINATION.\n"
            f"CHE DO: {mode}\n\n"
            "TRI THUC HVHN LIEN QUAN:\n"
            f"{source_block}\n\n"
            "NGUON WEB VUA TRA CUU:\n"
            f"{web_block}\n\n"
            "QUY TAC TRA LOI BAT BUOC:\n"
            "- Chi dua chi tiet/su kien khi no co trong TRI THUC HVHN, NGUON WEB, hoac van ban nguoi dung da dua.\n"
            "- Moi khang dinh lay tu web phai gan nhan nguon dang [W1], [W2]...\n"
            "- Neu nguon web chi la snippet/tom tat, khong trich dan nguyen van va khong khang dinh qua muc.\n"
            "- Kien thuc pho thong chi duoc dung cho khai niem/huong lam bai chung; khong dung de khang dinh "
            "chi tiet tac pham, trich dan, nam thang, hoan canh sang tac, nhan vat, hay nhan dinh phe binh neu khong co nguon.\n"
            "- Khong trich dan nguyen van neu khong co nguon trong prompt.\n"
            "- Neu cau hoi yeu cau mot thong tin ma du lieu khong co, hay noi khong du du lieu.\n"
            "- Cuoi cau tra loi bat buoc co 2 dong:\n"
            "  Muc can cu: <Van ban nguoi dung / Tri thuc HVHN / Nguon web [W...] / Kien thuc pho thong can kiem chung / Khong du du lieu>\n"
            "  Can kiem chung: <khong co / liet ke cac diem can kiem chung>\n\n"
            "YEU CAU NGUOI DUNG:\n"
            f"{prompt}"
        )

    @staticmethod
    def _has_grounding_footer(answer: str) -> bool:
        lowered = answer.lower()
        return "muc can cu:" in lowered and "can kiem chung:" in lowered

    async def _safe_generate(self, prompt: str, knowledge: str, web_context: str, mode: str) -> tuple[str | None, str]:
        full_prompt = self._guarded_prompt(prompt, knowledge, web_context, mode)
        answer = await self.generate(full_prompt, THEN_SYSTEM_PROMPT, temperature=0.15)
        if answer and not self._has_grounding_footer(answer):
            repair_prompt = (
                "Sua cau tra loi sau de tuan thu quy tac chong hallucination. "
                "Khong them thong tin moi. Bat buoc them 'Muc can cu' va 'Can kiem chung'.\n\n"
                f"CAU TRA LOI CAN SUA:\n{answer}"
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
            await interaction.response.send_message("Tinh nang AI chua cau hinh API key.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        knowledge = await self._knowledge_context(user_prompt)
        web_context = await self._web_context(user_prompt, mode)
        answer, full_prompt = await self._safe_generate(prompt, knowledge, web_context, mode)
        if answer is None:
            await interaction.followup.send("AI dang qua tai hoac loi API. Thu lai sau it phut.")
            return

        if len(answer) > MAX_DISCORD_LEN:
            answer = answer[:MAX_DISCORD_LEN] + "\n\n*(da rut gon de vua Discord)*"

        embed = discord.Embed(title=title, description=answer, color=discord.Color.green())
        embed.set_footer(text=f"Then tra loi cho {interaction.user.display_name}. Bam feedback neu can sua.")
        await interaction.followup.send(embed=embed, view=FeedbackView(self.bot, full_prompt, answer))

    @app_commands.command(name="ai", description="Hoi tro giang AI: giai dap, goi y lam bai, phan tich tac pham")
    async def ai(self, interaction: discord.Interaction, question: str):
        prompt = (
            "Tra loi cau hoi sau. Neu cau hoi can thong tin van ban/tac pham/trich dan ma khong co nguon, "
            "khong duoc bia; hay dua cach kiem chung.\n"
            f"Cau hoi: {question}"
        )
        await self._then_answer(interaction, "Tro giang AI - HVHN", question, prompt, "general_safe")

    @app_commands.command(name="van_hoi", description="Hoi Then ve bai Van, tac pham, luan diem, dan chung")
    async def van_hoi(self, interaction: discord.Interaction, cau_hoi: str):
        prompt = (
            "Tra loi cau hoi Ngu Van sau theo phong cach HVHN: ro trong tam, co chieu sau, khong sao rong. "
            "Neu hoi ve trich dan/chi tiet tac pham ma khong co trong nguon, hay tu choi khang dinh va noi can kiem chung.\n"
            f"Cau hoi: {cau_hoi}"
        )
        await self._then_answer(interaction, "Then - Hoi Van", cau_hoi, prompt, "literature_qa")

    @app_commands.command(name="cham_bai", description="Then cham va gop y mot bai/doan van")
    async def cham_bai(self, interaction: discord.Interaction, bai_lam: str):
        prompt = (
            "Cham bai/doan van sau. Chi dua vao bai lam duoc cung cap, khong suy dien y hoc sinh chua viet. "
            "Tra ve: Nhan xet chung, Diem manh, Loi lon nhat, Cach sua uu tien, Diem du kien /10.\n\n"
            f"Bai lam:\n{bai_lam}"
        )
        await self._then_answer(interaction, "Then - Cham Bai", bai_lam, prompt, "user_text_only")

    @app_commands.command(name="sua_doan", description="Then sua mot doan van cho sac hon nhung giu y cua hoc sinh")
    async def sua_doan(self, interaction: discord.Interaction, doan_van: str):
        prompt = (
            "Sua doan van sau cho mach lac va co luc phan tich hon. Chi sua dua tren noi dung da co; "
            "khong them dan chung/tac pham/nhan dinh moi neu nguoi dung khong dua. "
            "Tra ve: Ban sua, Vi sao sua nhu vay, 3 luu y.\n\n"
            f"Doan van:\n{doan_van}"
        )
        await self._then_answer(interaction, "Then - Sua Doan", doan_van, prompt, "user_text_only")

    @app_commands.command(name="goi_y_mo_bai", description="Goi y mo bai theo de Van")
    async def goi_y_mo_bai(self, interaction: discord.Interaction, de_bai: str, phong_cach: str = "sau sac, khong sao"):
        prompt = (
            "Goi y 3 huong mo bai cho de sau. Khong dua trich dan/nhan dinh phe binh neu khong co nguon. "
            "Moi huong gom: y tuong, mo bai mau ngan 5-7 cau, khi nao nen dung.\n"
            f"Phong cach mong muon: {phong_cach}\nDe bai: {de_bai}"
        )
        await self._then_answer(interaction, "Then - Goi Y Mo Bai", de_bai, prompt, "writing_suggestion")

    @app_commands.command(name="luyen_de_hom_nay", description="Then giao mot bai luyen Van hom nay")
    async def luyen_de_hom_nay(self, interaction: discord.Interaction, chu_de: str = "nghi luan van hoc"):
        prompt = (
            "Tao mot nhiem vu luyen Van hom nay. Neu chu de can tac pham cu the ma khong co nguon, hay de o muc mo "
            "hoac noi can thay co xac nhan. Gom: de bai, muc tieu ky nang, dan y goi mo, tieu chi tu kiem, bai tap 10 phut.\n"
            f"Chu de: {chu_de}"
        )
        await self._then_answer(interaction, "Then - Luyen De Hom Nay", chu_de, prompt, "practice_task")

    @app_commands.command(name="ai_kienthuc_them", description="Them tri thuc HVHN cho Then (Admin)")
    async def add_knowledge(self, interaction: discord.Interaction, category: str, title: str, content: str, source: str = ""):
        if not self._is_admin(interaction):
            await interaction.response.send_message("Ban can role HVHN Admin hoac quyen Manage Server.", ephemeral=True)
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
        await interaction.response.send_message("Da them tri thuc cho Then.", ephemeral=True)

    @app_commands.command(name="ai_kienthuc_tim", description="Tim tri thuc da nap cho Then")
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
            await interaction.response.send_message("Chua thay tri thuc phu hop.", ephemeral=True)
            return
        embed = discord.Embed(title="Tri thuc Then", color=discord.Color.blue())
        for row in rows:
            content = row["content"][:250] + ("..." if len(row["content"]) > 250 else "")
            embed.add_field(name=f"#{row['id']} [{row['category']}] {row['title']}", value=content, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="ai_feedback_stats", description="Xem thong ke feedback AI (Admin)")
    async def feedback_stats(self, interaction: discord.Interaction):
        if not self._is_admin(interaction):
            await interaction.response.send_message("Ban can role HVHN Admin hoac quyen Manage Server.", ephemeral=True)
            return
        rows = await self.bot.db.fetch("SELECT rating, count(*) AS n FROM ai_feedback GROUP BY rating ORDER BY rating")
        total_k = await self.bot.db.fetchval("SELECT count(*) FROM ai_knowledge WHERE approved = TRUE")
        text = "\n".join(f"`{row['rating']}`: {row['n']}" for row in rows) or "Chua co feedback."
        await interaction.response.send_message(f"Tri thuc da duyet: `{total_k}`\nFeedback:\n{text}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AI(bot))
