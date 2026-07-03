import datetime

import discord
from discord.ext import commands
from discord import app_commands
import asyncpg


class RevealAnswerView(discord.ui.View):
    def __init__(self, answer: str):
        super().__init__(timeout=60)
        self.answer = answer

    @discord.ui.button(label="Xem đáp án", style=discord.ButtonStyle.primary, emoji="🔎")
    async def reveal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(f"📖 **Đáp án:** {self.answer}", ephemeral=True)


class Study(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db: asyncpg.Pool = bot.db

    # ---------------- Flashcards ----------------
    @app_commands.command(name="flashcard_add", description="Thêm một flashcard câu hỏi/đáp án cho môn Ngữ Văn")
    async def flashcard_add(self, interaction: discord.Interaction, question: str, answer: str):
        await self.db.execute(
            "INSERT INTO flashcards (question, answer, author_id) VALUES ($1, $2, $3)",
            question, answer, interaction.user.id
        )
        await interaction.response.send_message("✅ Đã thêm flashcard mới!", ephemeral=True)

    @app_commands.command(name="flashcard", description="Random một flashcard để ôn tập")
    async def flashcard(self, interaction: discord.Interaction):
        row = await self.db.fetchrow("SELECT question, answer FROM flashcards ORDER BY random() LIMIT 1")
        if not row:
            await interaction.response.send_message("📭 Chưa có flashcard nào. Dùng `/flashcard_add` để thêm nhé!", ephemeral=True)
            return
        await interaction.response.send_message(
            f"🧠 **Câu hỏi:** {row['question']}",
            view=RevealAnswerView(row["answer"])
        )

    # ---------------- Quotes ----------------
    @app_commands.command(name="quote_add", description="Đóng góp một trích dẫn hay cho server")
    async def quote_add(self, interaction: discord.Interaction, content: str):
        await self.db.execute(
            "INSERT INTO quotes (content, author_id) VALUES ($1, $2)", content, interaction.user.id
        )
        await interaction.response.send_message("✅ Đã lưu trích dẫn!", ephemeral=True)

    @app_commands.command(name="quote", description="Random một trích dẫn đã được đóng góp")
    async def quote(self, interaction: discord.Interaction):
        row = await self.db.fetchrow("SELECT content, author_id FROM quotes ORDER BY random() LIMIT 1")
        if not row:
            await interaction.response.send_message("📭 Chưa có trích dẫn nào. Dùng `/quote_add` để đóng góp nhé!", ephemeral=True)
            return
        await interaction.response.send_message(f"💬 *\"{row['content']}\"*\n— <@{row['author_id']}>")

    # ---------------- Deadlines ----------------
    @app_commands.command(name="deadline_add", description="Thêm một mốc deadline/kiểm tra (định dạng ngày: YYYY-MM-DD)")
    async def deadline_add(self, interaction: discord.Interaction, name: str, date: str):
        try:
            due_date = datetime.date.fromisoformat(date)
        except ValueError:
            await interaction.response.send_message("❌ Sai định dạng ngày. Dùng YYYY-MM-DD, ví dụ 2026-08-15.", ephemeral=True)
            return
        await self.db.execute(
            "INSERT INTO deadlines (name, due_date, created_by) VALUES ($1, $2, $3)",
            name, due_date, interaction.user.id
        )
        await interaction.response.send_message(f"✅ Đã thêm deadline **{name}** vào {due_date.isoformat()}.")

    @app_commands.command(name="deadlines", description="Xem danh sách deadline sắp tới")
    async def deadlines(self, interaction: discord.Interaction):
        rows = await self.db.fetch(
            "SELECT name, due_date FROM deadlines WHERE due_date >= CURRENT_DATE ORDER BY due_date ASC LIMIT 10"
        )
        if not rows:
            await interaction.response.send_message("📭 Không có deadline nào sắp tới.")
            return
        embed = discord.Embed(title="📅 DEADLINE SẮP TỚI", color=discord.Color.blue())
        for row in rows:
            embed.add_field(name=row["name"], value=row["due_date"].isoformat(), inline=False)
        await interaction.response.send_message(embed=embed)

    # ---------------- Poll ----------------
    @app_commands.command(name="poll", description="Tạo một cuộc bình chọn nhanh (tối đa 5 lựa chọn, cách nhau bởi dấu phẩy)")
    async def poll(self, interaction: discord.Interaction, question: str, options: str):
        choices = [opt.strip() for opt in options.split(",") if opt.strip()][:5]
        if len(choices) < 2:
            await interaction.response.send_message("❌ Cần ít nhất 2 lựa chọn, cách nhau bởi dấu phẩy.", ephemeral=True)
            return

        number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
        description = "\n".join(f"{number_emojis[i]} {choice}" for i, choice in enumerate(choices))
        embed = discord.Embed(title=f"📊 {question}", description=description, color=discord.Color.teal())
        embed.set_footer(text=f"Tạo bởi {interaction.user.display_name}")

        await interaction.response.send_message(embed=embed)
        message = await interaction.original_response()
        for i in range(len(choices)):
            await message.add_reaction(number_emojis[i])

    # ---------------- Essay outline ----------------
    @app_commands.command(name="essay_outline", description="Sinh dàn ý khung cho bài nghị luận theo chủ đề bạn nhập")
    async def essay_outline(self, interaction: discord.Interaction, topic: str):
        embed = discord.Embed(title=f"📝 Dàn ý nghị luận: {topic}", color=discord.Color.purple())
        embed.add_field(
            name="I. Mở bài",
            value="Dẫn dắt vào vấn đề, giới thiệu khái quát chủ đề, nêu luận điểm chính sẽ triển khai.",
            inline=False
        )
        embed.add_field(
            name="II. Thân bài",
            value=(
                "1. Giải thích khái niệm/vấn đề liên quan đến chủ đề.\n"
                "2. Luận điểm 1 + dẫn chứng, phân tích.\n"
                "3. Luận điểm 2 + dẫn chứng, phân tích.\n"
                "4. Bàn luận mở rộng: phản đề hoặc góc nhìn khác.\n"
                "5. Liên hệ thực tế/bản thân."
            ),
            inline=False
        )
        embed.add_field(
            name="III. Kết bài",
            value="Khẳng định lại luận điểm, rút ra bài học hoặc thông điệp.",
            inline=False
        )
        embed.set_footer(text="Đây là khung dàn ý tổng quát — cần tự điền dẫn chứng/luận điểm cụ thể phù hợp đề bài.")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Study(bot))
