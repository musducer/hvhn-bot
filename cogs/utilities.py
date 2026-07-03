import random
import asyncio
import datetime
import discord
from discord.ext import commands
from discord import app_commands
import asyncpg


class Utilities(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db: asyncpg.Pool = bot.db

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

    @app_commands.command(name="clear", description="Xóa hàng loạt tin nhắn (1-100) (Chỉ Admin)")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear(self, interaction: discord.Interaction, amount: int):
        if amount < 1 or amount > 100:
            await interaction.response.send_message("❌ Chỉ xóa được từ 1 đến 100 tin nhắn mỗi lần.", ephemeral=True)
            return
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

    @app_commands.command(name="relax", description="Gợi ý hoạt động giải lao ngắn hạn sau giờ học căng thẳng")
    async def relax(self, interaction: discord.Interaction):
        activities = [
            "Thử giải một thế cờ vua (Chess puzzle) ngắn gọn trên mạng để thay đổi luồng tư duy logic nhé!",
            "Đứng lên vươn vai, rời mắt khỏi màn hình và uống một cốc nước đầy nào.",
            "Nhắm mắt lại và nghe một bản nhạc lofi không lời trong 5 phút."
        ]
        await interaction.response.send_message(f"☕ **Đã đến giờ nghỉ ngơi:**\n{random.choice(activities)}")

    @app_commands.command(name="timer", description="Đồng hồ đếm ngược học tập (1-180 phút)")
    async def timer(self, interaction: discord.Interaction, minutes: int):
        if minutes < 1 or minutes > 180:
            await interaction.response.send_message("❌ Thời gian phải từ 1 đến 180 phút.", ephemeral=True)
            return
        channel = interaction.channel
        await interaction.response.send_message(f"⏳ Bắt đầu bộ đếm {minutes} phút. Tắt mọi thông báo và tập trung nhé!")
        await asyncio.sleep(minutes * 60)
        # Dùng channel.send thay vì followup: token interaction hết hạn sau 15 phút
        try:
            await channel.send(f"⏰ Reng reng! Đã hết {minutes} phút tập trung. Nghỉ giải lao một chút đi {interaction.user.mention}!")
        except discord.HTTPException:
            pass

    @app_commands.command(name="ask", description="Gửi câu hỏi ẩn danh")
    async def ask(self, interaction: discord.Interaction, question: str):
        admin_channel = discord.utils.get(interaction.guild.text_channels, name="duyệt-câu-hỏi")
        if not admin_channel:
            await interaction.response.send_message("❌ Kênh duyệt câu hỏi chưa thiết lập.", ephemeral=True)
            return
        question_id = await self.db.fetchval(
            "INSERT INTO questions (content, asker_id) VALUES ($1, $2) RETURNING id",
            question, interaction.user.id
        )
        embed = discord.Embed(title=f"❓ Câu hỏi ẩn danh mới (ID: {question_id})", description=question, color=discord.Color.orange())
        embed.set_footer(text=f"Trả lời bằng: /answer id:{question_id} reply:...")
        await admin_channel.send(embed=embed)
        await interaction.response.send_message(f"✅ Câu hỏi đã được gửi kín! (Mã số của bạn: **{question_id}**)", ephemeral=True)

    @app_commands.command(name="answer", description="Trả lời câu hỏi ẩn danh theo ID (Chỉ Admin)")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def answer(self, interaction: discord.Interaction, id: int, reply: str):
        row = await self.db.fetchrow("SELECT content, answered FROM questions WHERE id = $1", id)
        if not row:
            await interaction.response.send_message(f"❌ Không tìm thấy câu hỏi có ID **{id}**.", ephemeral=True)
            return

        public_channel = discord.utils.get(interaction.guild.text_channels, name="hỏi-đáp-bài-tập")
        if not public_channel:
            await interaction.response.send_message("❌ Không tìm thấy kênh hỏi-đáp-bài-tập.", ephemeral=True)
            return

        embed = discord.Embed(title=f"📝 Q&A Ẩn Danh (ID: {id})", color=discord.Color.green())
        embed.add_field(name="Hỏi:", value=row["content"], inline=False)
        embed.add_field(name="Đáp:", value=reply, inline=False)
        await public_channel.send(embed=embed)

        await self.db.execute("UPDATE questions SET answered = TRUE WHERE id = $1", id)
        note = " (câu này đã được trả lời trước đó)" if row["answered"] else ""
        await interaction.response.send_message(f"✅ Đã đăng câu trả lời cho câu hỏi ID **{id}**{note}.", ephemeral=True)

    @app_commands.command(name="questions", description="Xem các câu hỏi ẩn danh chưa được trả lời (Chỉ Admin)")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def questions(self, interaction: discord.Interaction):
        rows = await self.db.fetch(
            "SELECT id, content FROM questions WHERE answered = FALSE ORDER BY created_at ASC LIMIT 15"
        )
        if not rows:
            await interaction.response.send_message("✅ Không có câu hỏi nào đang chờ trả lời.", ephemeral=True)
            return
        embed = discord.Embed(title="❓ Câu hỏi đang chờ trả lời", color=discord.Color.orange())
        for row in rows:
            content = row["content"] if len(row["content"]) <= 200 else row["content"][:197] + "..."
            embed.add_field(name=f"ID {row['id']}", value=content, inline=False)
        embed.set_footer(text="Dùng /answer id:<số> reply:<nội dung> để trả lời.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="wordcount", description="Đếm số từ và số ký tự của một đoạn văn")
    async def wordcount(self, interaction: discord.Interaction, text: str):
        words = len(text.split())
        chars = len(text)
        chars_no_space = len(text.replace(" ", ""))
        await interaction.response.send_message(
            f"📊 **Thống kê đoạn văn:**\n"
            f"• Số từ: **{words}**\n"
            f"• Số ký tự (kể cả dấu cách): **{chars}**\n"
            f"• Số ký tự (không dấu cách): **{chars_no_space}**",
            ephemeral=True
        )

    @app_commands.command(name="remindme", description="Đặt lời nhắc cá nhân sau một số phút")
    async def remindme(self, interaction: discord.Interaction, minutes: int, content: str):
        if minutes <= 0 or minutes > 1440:
            await interaction.response.send_message("❌ Số phút phải từ 1 đến 1440 (24 giờ).", ephemeral=True)
            return
        await interaction.response.send_message(f"⏰ Đã đặt lời nhắc sau {minutes} phút.", ephemeral=True)
        await asyncio.sleep(minutes * 60)
        try:
            await interaction.user.send(f"🔔 **Nhắc nhở:** {content}")
        except discord.Forbidden:
            channel = interaction.channel
            if channel:
                await channel.send(f"🔔 {interaction.user.mention} nhắc nhở: {content}")

    @app_commands.command(name="userinfo", description="Xem thông tin của một thành viên")
    async def userinfo(self, interaction: discord.Interaction, member: discord.Member = None):
        user = member or interaction.user
        embed = discord.Embed(title=f"👤 Thông tin: {user.display_name}", color=user.color)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Tên tài khoản", value=str(user), inline=True)
        embed.add_field(name="ID", value=user.id, inline=True)
        embed.add_field(name="Ngày tạo tài khoản", value=user.created_at.strftime("%d/%m/%Y"), inline=False)
        if user.joined_at:
            embed.add_field(name="Ngày vào server", value=user.joined_at.strftime("%d/%m/%Y"), inline=False)
        roles = [r.mention for r in user.roles if r.name != "@everyone"]
        embed.add_field(name=f"Vai trò ({len(roles)})", value=" ".join(roles) if roles else "Không có", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="announce", description="Đăng thông báo vào kênh bảng-tin-thông-báo (Chỉ Admin)")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def announce(self, interaction: discord.Interaction, title: str, content: str):
        channel = discord.utils.get(interaction.guild.text_channels, name="bảng-tin-thông-báo")
        if not channel:
            await interaction.response.send_message("❌ Không tìm thấy kênh bảng-tin-thông-báo.", ephemeral=True)
            return
        embed = discord.Embed(title=f"📢 {title}", description=content, color=discord.Color.gold())
        embed.set_footer(text=f"Thông báo từ {interaction.user.display_name}")
        await channel.send(embed=embed)
        await interaction.response.send_message(f"✅ Đã đăng thông báo vào {channel.mention}.", ephemeral=True)

    @app_commands.command(name="serverinfo", description="Xem thông tin và thống kê server")
    async def serverinfo(self, interaction: discord.Interaction):
        guild = interaction.guild
        embed = discord.Embed(title=f"🏫 {guild.name}", color=discord.Color.blurple())
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(name="Số thành viên", value=guild.member_count, inline=True)
        embed.add_field(name="Số kênh chat", value=len(guild.text_channels), inline=True)
        embed.add_field(name="Số kênh voice", value=len(guild.voice_channels), inline=True)
        embed.add_field(name="Số vai trò", value=len(guild.roles), inline=True)
        if guild.owner:
            embed.add_field(name="Chủ server", value=guild.owner.mention, inline=True)
        embed.add_field(name="Ngày lập server", value=guild.created_at.strftime("%d/%m/%Y"), inline=True)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Utilities(bot))
