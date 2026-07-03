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

MAX_DISCORD_LEN = 1900


class AI(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.groq_keys = [k.strip() for k in os.getenv("GROQ_API_KEYS", "").split(",") if k.strip()]
        self.gemini_keys = [k.strip() for k in os.getenv("GEMINI_API_KEYS", "").split(",") if k.strip()]

    async def ask_groq(self, session: aiohttp.ClientSession, key: str, prompt: str) -> tuple[bool, str]:
        """Trả về (thành_công, nội_dung_hoặc_lý_do). thành_công=False + 'RATE_LIMIT' để báo xoay key."""
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
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

    async def ask_gemini(self, session: aiohttp.ClientSession, key: str, prompt: str) -> tuple[bool, str]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={key}"
        payload = {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
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

    async def generate(self, prompt: str) -> str | None:
        async with aiohttp.ClientSession() as session:
            for key in self.groq_keys:
                try:
                    ok, content = await self.ask_groq(session, key, prompt)
                    if ok:
                        return content
                    if content != "RATE_LIMIT":
                        print(f"[ai] Groq lỗi: {content}")
                except Exception as e:
                    print(f"[ai] Groq exception: {e}")

            for key in self.gemini_keys:
                try:
                    ok, content = await self.ask_gemini(session, key, prompt)
                    if ok:
                        return content
                    if content != "RATE_LIMIT":
                        print(f"[ai] Gemini lỗi: {content}")
                except Exception as e:
                    print(f"[ai] Gemini exception: {e}")
        return None

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


async def setup(bot: commands.Bot):
    await bot.add_cog(AI(bot))
