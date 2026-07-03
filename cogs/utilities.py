import random
import asyncio
import discord
from discord.ext import commands
from discord import app_commands


class Utilities(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="giverole", description="Cấp role cho thành viên (Chỉ Admin)")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def giverole(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        await member.add_roles(role)
        await interaction.response.send_message(f"✅ Đã cấp role **{role.name}** cho {member.mention}.", ephemeral=True)

    @app_commands.command(name="removerole", description="Thu hồi role của thành viên (Chỉ Admin)")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def removerole(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        await member.remove_roles(role)
        await interaction.response.send_message(f"✅ Đã thu hồi role **{role.name}** từ {member.mention}.", ephemeral=True)

    @app_commands.command(name="clear", description="Xóa hàng loạt tin nhắn (Chỉ Admin)")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear(self, interaction: discord.Interaction, amount: int):
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"✅ Đã dọn dẹp {len(deleted)} tin nhắn rác.")

    @app_commands.command(name="lock", description="Khóa kênh không cho mọi người chat (Chỉ Admin)")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def lock(self, interaction: discord.Interaction):
        await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=False)
        await interaction.response.send_message("🔒 Kênh đã bị khóa tạm thời.")

    @app_commands.command(name="unlock", description="Mở khóa kênh (Chỉ Admin)")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def unlock(self, interaction: discord.Interaction):
        await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=True)
        await interaction.response.send_message("🔓 Kênh đã được mở khóa.")

    @app_commands.command(name="ielts_vocab", description="Học một từ vựng Academic đắt giá cho bài nghị luận / IELTS")
    async def ielts_vocab(self, interaction: discord.Interaction):
        words = [
            "**Profound** (Sâu sắc, uyên thâm) - Rất thích hợp để phân tích tư tưởng tác giả.",
            "**Resilience** (Sự kiên cường) - Hoàn hảo cho các bài nghị luận xã hội về ý chí.",
            "**Meticulous** (Tỉ mỉ, cẩn trọng) - Dùng để mô tả cách xây dựng nhân vật tinh tế.",
            "**Paradigm** (Hệ tư tưởng, mô hình) - Dùng để nâng tầm luận điểm khi so sánh các thời kỳ văn học."
        ]
        await interaction.response.send_message(f"📚 **Từ vựng hôm nay:**\n{random.choice(words)}")

    @app_commands.command(name="relax", description="Gợi ý hoạt động giải lao ngắn hạn sau giờ học căng thẳng")
    async def relax(self, interaction: discord.Interaction):
        activities = [
            "Thử giải một thế cờ vua (Chess puzzle) ngắn gọn trên mạng để thay đổi luồng tư duy logic nhé!",
            "Đứng lên vươn vai, rời mắt khỏi màn hình và uống một cốc nước đầy nào.",
            "Nhắm mắt lại và nghe một bản nhạc lofi không lời trong 5 phút."
        ]
        await interaction.response.send_message(f"☕ **Đã đến giờ nghỉ ngơi:**\n{random.choice(activities)}")

    @app_commands.command(name="design_idea", description="Gợi ý bảng màu và phong cách thiết kế tài liệu/slide")
    async def design_idea(self, interaction: discord.Interaction):
        ideas = [
            "🎨 **Phong cách:** Hiện đại & Tối giản (Modern Minimalist). **Tông màu:** Xanh Navy & Trắng (White and Blue). Rất thanh lịch, phù hợp làm bìa sách ảnh du lịch hoặc các bảng biểu khoa học (như Bảng tuần hoàn hóa học).",
            "🎨 **Phong cách:** Cổ điển. **Tông màu:** Nâu Vintage & Vàng nhạt. Tạo cảm giác hoài cổ, cực kỳ hợp cho các bài phân tích văn học dân gian.",
            "🎨 **Phong cách:** Thanh bình. **Tông màu:** Xanh lá Pastel & Xám. Gợi sự bình tĩnh, dễ nhìn khi làm slide thuyết trình dài."
        ]
        await interaction.response.send_message(random.choice(ideas))

    @app_commands.command(name="timer", description="Đồng hồ đếm ngược học tập")
    async def timer(self, interaction: discord.Interaction, minutes: int):
        await interaction.response.send_message(f"⏳ Bắt đầu bộ đếm {minutes} phút. Tắt mọi thông báo và tập trung nhé!")
        await asyncio.sleep(minutes * 60)
        await interaction.followup.send(f"⏰ Reng reng! Đã hết {minutes} phút tập trung. Nghỉ giải lao một chút đi {interaction.user.mention}!")

    @app_commands.command(name="ask", description="Gửi câu hỏi ẩn danh")
    async def ask(self, interaction: discord.Interaction, question: str):
        admin_channel = discord.utils.get(interaction.guild.text_channels, name="duyệt-câu-hỏi")
        if not admin_channel:
            await interaction.response.send_message("❌ Kênh duyệt câu hỏi chưa thiết lập.", ephemeral=True)
            return
        embed = discord.Embed(title="❓ Câu hỏi ẩn danh mới", description=question, color=discord.Color.orange())
        embed.set_footer(text=f"Từ: {interaction.user.name}")
        await admin_channel.send(embed=embed)
        await interaction.response.send_message("✅ Câu hỏi đã được gửi kín!", ephemeral=True)

    @app_commands.command(name="answer", description="Trả lời câu hỏi ẩn danh (Chỉ Admin)")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def answer(self, interaction: discord.Interaction, question: str, reply: str):
        public_channel = discord.utils.get(interaction.guild.text_channels, name="hỏi-đáp-bài-tập")
        if not public_channel:
            await interaction.response.send_message("❌ Lỗi kênh.", ephemeral=True)
            return
        embed = discord.Embed(title="📝 Q&A Ẩn Danh", color=discord.Color.green())
        embed.add_field(name="Hỏi:", value=question, inline=False)
        embed.add_field(name="Đáp:", value=reply, inline=False)
        await public_channel.send(embed=embed)
        await interaction.response.send_message("✅ Đã đăng câu trả lời!", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Utilities(bot))
