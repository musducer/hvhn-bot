import os

import aiohttp
import discord
from discord.ext import commands
from discord import app_commands

GROQ_MODEL = "llama-3.3-70b-versatile"
GEMINI_MODEL = "gemini-2.0-flash"

SYSTEM_PROMPT = (
    "Bạn là trợ giảng môn Ngữ Văn cho một cộng đồng học sinh Việt Nam tên là Nhóm học tập HVHN. "
    "Nhiệm vụ của bạn là giải đáp thắc mắc, gợi ý cách làm bài, gợi ý hướng phân tích tác phẩm, "
    "giải thích khái niệm văn học và tiếng Việt. "
    "Hãy trả lời bằng tiếng Việt, rõ ràng, có trọng tâm. "
    "Với câu hỏi làm bài, hãy gợi ý hướng đi và luận điểm để học sinh tự phát triển, "
    "không viết hộ toàn bộ bài văn. "
    "Nếu không chắc chắn về một dẫn chứng hay chi tiết tác phẩm, hãy nói rõ là cần kiểm chứng lại, "
    "không bịa đặt thông tin. Câu trả lời gọn trong khoảng 1500 ký tự."
)

THEN_SYSTEM_PROMPT = (
    "Bạn là Then, trợ giảng Ngữ Văn của Hồn Văn - Hồn Người. "
    "Giọng văn: sắc, ấm, có chiều sâu, tránh sáo rỗng, không bịa dẫn chứng. "
    "Ưu tiên giúp học sinh tự nghĩ tốt hơn: chỉ ra hướng, cấu trúc, lỗi, cách nâng cấp. "
    "Nếu có tri thức HVHN được cung cấp, hãy dùng nó làm nền; nếu thiếu dữ kiện, nói rõ cần kiểm chứng. "
    "Không viết thay toàn bộ bài trừ khi người dùng yêu cầu một đoạn mẫu ngắn."
)

MAX_DISCORD_LEN = 1900


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
        await interaction.response.send_message("Đã lưu góp ý. Then sẽ dùng dữ liệu này để mài prompt/kho tri thức.", ephemeral=True)


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

    async def ask_groq(self, session: aiohttp.ClientSession, key: str, prompt: str, system_prompt: str = SYSTEM_PROMPT) -> tuple[bool, str]:
        """Trả về (thành_công, nội_dung_hoặc_lý_do). thành_công=False + 'RATE_LIMIT' để báo xoay key."""
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
        }
        async with session.post(url, headers=headers, json=payload, timeout=60) as resp:
            if resp.status == 429:
                return False, "RATE_LIMIT"
            if resp.status != 200:
                return False, f"HTTP {resp.status}"
            data = await resp.json()
            return True, data["choices"][0]["message"]["content"].strip()

    async def ask_gemini(self, session: aiohttp.ClientSession, key: str, prompt: str, system_prompt: str = SYSTEM_PROMPT) -> tuple[bool, str]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={key}"
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"parts": [{"text": prompt}]}],
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

    async def generate(self, prompt: str, system_prompt: str = SYSTEM_PROMPT) -> str | None:
        async with aiohttp.ClientSession() as session:
            for key in self.groq_keys:
                try:
                    ok, content = await self.ask_groq(session, key, prompt, system_prompt)
                    if ok:
                        return content
                    if content != "RATE_LIMIT":
                        print(f"[ai] Groq lỗi: {content}")
                except Exception as e:
                    print(f"[ai] Groq exception: {e}")

            for key in self.gemini_keys:
                try:
                    ok, content = await self.ask_gemini(session, key, prompt, system_prompt)
                    if ok:
                        return content
                    if content != "RATE_LIMIT":
                        print(f"[ai] Gemini lỗi: {content}")
                except Exception as e:
                    print(f"[ai] Gemini exception: {e}")
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
            pattern = "%" + "%".join(terms[:3]) + "%"
            rows = await self.bot.db.fetch(
                """
                SELECT category, title, content
                FROM ai_knowledge
                WHERE approved = TRUE
                  AND (lower(title) LIKE $1 OR lower(content) LIKE $1 OR lower(category) LIKE $1)
                ORDER BY created_at DESC
                LIMIT $2
                """,
                pattern,
                limit,
            )
        if not rows:
            return ""
        chunks = []
        for r in rows:
            content = r["content"]
            if len(content) > 900:
                content = content[:900] + "..."
            chunks.append(f"[{r['category']}] {r['title']}\n{content}")
        return "\n\n".join(chunks)

    async def _then_answer(self, interaction: discord.Interaction, title: str, user_prompt: str, prompt: str):
        if not self._has_ai():
            await interaction.response.send_message("Tính năng AI chưa cấu hình API key.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        knowledge = await self._knowledge_context(user_prompt)
        full_prompt = prompt
        if knowledge:
            full_prompt = "TRI THỨC HVHN LIÊN QUAN:\n" + knowledge + "\n\nYÊU CẦU:\n" + prompt
        answer = await self.generate(full_prompt, THEN_SYSTEM_PROMPT)
        if answer is None:
            await interaction.followup.send("AI đang quá tải hoặc lỗi API. Thử lại sau ít phút.")
            return
        if len(answer) > MAX_DISCORD_LEN:
            answer = answer[:MAX_DISCORD_LEN] + "\n\n*(đã rút gọn để vừa Discord)*"
        embed = discord.Embed(title=title, description=answer, color=discord.Color.green())
        embed.set_footer(text=f"Then trả lời cho {interaction.user.display_name}. Hãy bấm feedback để mài AI.")
        await interaction.followup.send(embed=embed, view=FeedbackView(self.bot, full_prompt, answer))

    @app_commands.command(name="ai", description="Hỏi trợ giảng AI: giải đáp, gợi ý làm bài, gợi ý phân tích tác phẩm")
    async def ai(self, interaction: discord.Interaction, question: str):
        if not self.groq_keys and not self.gemini_keys:
            await interaction.response.send_message(
                "❌ Tính năng AI chưa được cấu hình (thiếu API key). Liên hệ quản trị viên.", ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)
        answer = await self.generate(question)

        if answer is None:
            await interaction.followup.send("❌ Xin lỗi, hiện AI đang quá tải hoặc gặp lỗi. Thử lại sau ít phút nhé.")
            return

        if len(answer) > MAX_DISCORD_LEN:
            answer = answer[:MAX_DISCORD_LEN] + "\n\n*(câu trả lời đã được rút gọn)*"

        embed = discord.Embed(
            title="🤖 Trợ giảng AI - HVHN",
            description=answer,
            color=discord.Color.green()
        )
        embed.add_field(name="❓ Câu hỏi", value=question[:1000], inline=False)
        embed.set_footer(text=f"Hỏi bởi {interaction.user.display_name} • AI có thể sai, hãy kiểm chứng lại.")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="van_hoi", description="Hỏi Then về bài Văn, tác phẩm, luận điểm, dẫn chứng")
    async def van_hoi(self, interaction: discord.Interaction, cau_hoi: str):
        prompt = (
            "Trả lời câu hỏi Ngữ Văn sau theo phong cách HVHN: rõ trọng tâm, có chiều sâu, không sáo.\n"
            f"Câu hỏi: {cau_hoi}"
        )
        await self._then_answer(interaction, "Then - Hỏi Văn", cau_hoi, prompt)

    @app_commands.command(name="cham_bai", description="Then chấm và góp ý một bài/đoạn văn")
    async def cham_bai(self, interaction: discord.Interaction, bai_lam: str):
        prompt = (
            "Chấm bài/đoạn văn sau theo rubric HVHN. Trả về các mục: Nhận xét chung, Điểm mạnh, "
            "Lỗi lớn nhất, Cách sửa theo thứ tự ưu tiên, Điểm dự kiến /10. Không khen sáo.\n\n"
            f"Bài làm:\n{bai_lam}"
        )
        await self._then_answer(interaction, "Then - Chấm Bài", bai_lam, prompt)

    @app_commands.command(name="sua_doan", description="Then sửa một đoạn văn cho sắc hơn nhưng giữ ý của học sinh")
    async def sua_doan(self, interaction: discord.Interaction, doan_van: str):
        prompt = (
            "Sửa đoạn văn sau cho mạch lạc, giàu lực phân tích hơn nhưng không biến thành văn mẫu xa lạ. "
            "Trả về: Bản sửa, Vì sao sửa như vậy, 3 lưu ý cho học sinh.\n\n"
            f"Đoạn văn:\n{doan_van}"
        )
        await self._then_answer(interaction, "Then - Sửa Đoạn", doan_van, prompt)

    @app_commands.command(name="goi_y_mo_bai", description="Gợi ý mở bài theo đề Văn")
    async def goi_y_mo_bai(self, interaction: discord.Interaction, de_bai: str, phong_cach: str = "sâu sắc, không sáo"):
        prompt = (
            "Gợi ý 3 hướng mở bài cho đề sau. Mỗi hướng gồm: ý tưởng, mở bài mẫu ngắn 5-7 câu, "
            "khi nào nên dùng. Tránh công thức đại trà.\n"
            f"Phong cách mong muốn: {phong_cach}\nĐề bài: {de_bai}"
        )
        await self._then_answer(interaction, "Then - Gợi Ý Mở Bài", de_bai, prompt)

    @app_commands.command(name="luyen_de_hom_nay", description="Then giao một bài luyện Văn hôm nay")
    async def luyen_de_hom_nay(self, interaction: discord.Interaction, chu_de: str = "nghị luận văn học"):
        prompt = (
            "Tạo một nhiệm vụ luyện Văn hôm nay. Gồm: đề bài, mục tiêu kỹ năng, dàn ý gợi mở, "
            "tiêu chí tự kiểm, bài tập nhỏ 10 phút. Không cần lời mở đầu dài.\n"
            f"Chủ đề: {chu_de}"
        )
        await self._then_answer(interaction, "Then - Luyện Đề Hôm Nay", chu_de, prompt)

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
        for r in rows:
            content = r["content"][:250] + ("..." if len(r["content"]) > 250 else "")
            embed.add_field(name=f"#{r['id']} [{r['category']}] {r['title']}", value=content, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="ai_feedback_stats", description="Xem thống kê feedback AI (Admin)")
    async def feedback_stats(self, interaction: discord.Interaction):
        if not self._is_admin(interaction):
            await interaction.response.send_message("Bạn cần role HVHN Admin hoặc quyền Manage Server.", ephemeral=True)
            return
        rows = await self.bot.db.fetch("SELECT rating, count(*) AS n FROM ai_feedback GROUP BY rating ORDER BY rating")
        total_k = await self.bot.db.fetchval("SELECT count(*) FROM ai_knowledge WHERE approved = TRUE")
        text = "\n".join(f"`{r['rating']}`: {r['n']}" for r in rows) or "Chưa có feedback."
        await interaction.response.send_message(f"Tri thức đã duyệt: `{total_k}`\nFeedback:\n{text}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AI(bot))
