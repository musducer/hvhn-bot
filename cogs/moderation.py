import datetime
import re

import discord
from discord.ext import commands
from discord import app_commands
import asyncpg


MAX_TIMEOUT_MINUTES = 28 * 24 * 60
MAX_SLOWMODE_SECONDS = 21600


def _clip(value, limit=1000):
    text = str(value or "")
    return text if len(text) <= limit else text[:limit - 3] + "..."


def contains_banned_word(content, words):
    """Match complete words/phrases; blank entries can never match every message."""
    text = str(content or "").casefold()
    for raw_word in words:
        word = str(raw_word or "").strip().casefold()
        if word and re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text):
            return True
    return False


def _valid_reason(reason):
    return bool(str(reason or "").strip()) and len(str(reason)) <= 400


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db: asyncpg.Pool = bot.db
        self.banned_words_cache: set[str] = set()

    async def cog_load(self):
        rows = await self.db.fetch("SELECT word FROM banned_words")
        self.banned_words_cache = {
            str(row["word"] or "").strip().casefold()
            for row in rows
            if str(row["word"] or "").strip()
        }

    def log_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        return discord.utils.get(guild.text_channels, name="lưu-trữ-logs")

    # ---------------- Warn system ----------------
    @app_commands.command(name="warn", description="Cảnh cáo một thành viên (Chỉ Admin)")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        reason = reason.strip()
        if not _valid_reason(reason):
            await interaction.response.send_message("❌ Lý do phải có nội dung và không quá 400 ký tự.", ephemeral=True)
            return
        await self.db.execute(
            "INSERT INTO warnings (user_id, moderator_id, reason) VALUES ($1, $2, $3)",
            member.id, interaction.user.id, reason
        )
        await interaction.response.send_message(f"⚠️ Đã cảnh cáo {member.mention}. Lý do: {reason}")

        log_channel = self.log_channel(interaction.guild)
        if log_channel:
            await log_channel.send(f"⚠️ {interaction.user.mention} đã cảnh cáo {member.mention}. Lý do: {reason}")

    @app_commands.command(name="warnings", description="Xem danh sách cảnh cáo của một thành viên")
    async def warnings(self, interaction: discord.Interaction, member: discord.Member = None):
        user = member or interaction.user
        if user.id != interaction.user.id and not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("❌ Bạn chỉ có thể xem cảnh cáo của chính mình.", ephemeral=True)
            return
        rows = await self.db.fetch(
            "SELECT reason, created_at FROM warnings WHERE user_id = $1 ORDER BY created_at DESC LIMIT 10",
            user.id
        )
        if not rows:
            await interaction.response.send_message(f"✅ {user.mention} chưa có cảnh cáo nào.", ephemeral=True)
            return
        embed = discord.Embed(title=f"⚠️ Cảnh cáo của {user.display_name}", color=discord.Color.orange())
        for row in rows:
            embed.add_field(
                name=row["created_at"].strftime("%d/%m/%Y %H:%M"),
                value=_clip(row["reason"]),
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ---------------- Mute / Unmute ----------------
    @app_commands.command(name="mute", description="Cấm chat tạm thời một thành viên (Chỉ Admin)")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def mute(self, interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str = "Không rõ lý do"):
        if minutes < 1 or minutes > MAX_TIMEOUT_MINUTES:
            await interaction.response.send_message(
                "❌ Thời gian cấm chat phải từ 1 phút đến 28 ngày.", ephemeral=True,
            )
            return
        reason = reason.strip()
        if not _valid_reason(reason):
            await interaction.response.send_message("❌ Lý do phải có nội dung và không quá 400 ký tự.", ephemeral=True)
            return
        duration = datetime.timedelta(minutes=minutes)
        await member.timeout(duration, reason=reason)
        await interaction.response.send_message(f"🔇 Đã cấm chat {member.mention} trong {minutes} phút. Lý do: {reason}")

        log_channel = self.log_channel(interaction.guild)
        if log_channel:
            await log_channel.send(f"🔇 {interaction.user.mention} đã mute {member.mention} ({minutes} phút). Lý do: {reason}")

    @app_commands.command(name="unmute", description="Gỡ cấm chat cho một thành viên (Chỉ Admin)")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def unmute(self, interaction: discord.Interaction, member: discord.Member):
        await member.timeout(None)
        await interaction.response.send_message(f"🔊 Đã gỡ cấm chat cho {member.mention}.")

    # ---------------- Kick / Ban ----------------
    @app_commands.command(name="kick", description="Kick một thành viên khỏi server (Chỉ Admin)")
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Không rõ lý do"):
        reason = reason.strip()
        if not _valid_reason(reason):
            await interaction.response.send_message("❌ Lý do phải có nội dung và không quá 400 ký tự.", ephemeral=True)
            return
        await member.kick(reason=reason)
        await interaction.response.send_message(f"👢 Đã kick {member.mention}. Lý do: {reason}")

        log_channel = self.log_channel(interaction.guild)
        if log_channel:
            await log_channel.send(f"👢 {interaction.user.mention} đã kick {member.mention}. Lý do: {reason}")

    @app_commands.command(name="ban", description="Ban một thành viên khỏi server (Chỉ Admin)")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Không rõ lý do"):
        reason = reason.strip()
        if not _valid_reason(reason):
            await interaction.response.send_message("❌ Lý do phải có nội dung và không quá 400 ký tự.", ephemeral=True)
            return
        await member.ban(reason=reason)
        await interaction.response.send_message(f"🔨 Đã ban {member.mention}. Lý do: {reason}")

        log_channel = self.log_channel(interaction.guild)
        if log_channel:
            await log_channel.send(f"🔨 {interaction.user.mention} đã ban {member.mention}. Lý do: {reason}")

    @app_commands.command(name="unban", description="Gỡ ban cho một người dùng theo User ID (Chỉ Admin)")
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction, user_id: str):
        user_id = user_id.strip()
        if not user_id.isdigit() or len(user_id) > 22:
            await interaction.response.send_message("❌ User ID phải là một dãy số hợp lệ.", ephemeral=True)
            return
        try:
            uid = int(user_id)
        except ValueError:
            await interaction.response.send_message("❌ User ID phải là một dãy số. Bật Developer Mode để copy ID.", ephemeral=True)
            return

        try:
            user = await self.bot.fetch_user(uid)
        except discord.NotFound:
            await interaction.response.send_message("❌ Không tìm thấy người dùng với ID này.", ephemeral=True)
            return

        try:
            await interaction.guild.unban(user)
        except discord.NotFound:
            await interaction.response.send_message(f"❌ {user} không nằm trong danh sách bị ban.", ephemeral=True)
            return

        await interaction.response.send_message(f"✅ Đã gỡ ban cho **{user}**.")
        log_channel = self.log_channel(interaction.guild)
        if log_channel:
            await log_channel.send(f"♻️ {interaction.user.mention} đã gỡ ban cho {user} (ID: {uid}).")

    # ---------------- Slowmode ----------------
    @app_commands.command(name="slowmode", description="Đặt chế độ chat chậm cho kênh hiện tại (giây, 0 để tắt) (Chỉ Admin)")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def slowmode(self, interaction: discord.Interaction, seconds: int):
        if seconds < 0 or seconds > MAX_SLOWMODE_SECONDS:
            await interaction.response.send_message(
                "❌ Slowmode phải từ 0 đến 21.600 giây.", ephemeral=True,
            )
            return
        await interaction.channel.edit(slowmode_delay=seconds)
        if seconds == 0:
            await interaction.response.send_message("✅ Đã tắt chế độ chat chậm.")
        else:
            await interaction.response.send_message(f"🐢 Đã đặt chat chậm {seconds} giây cho kênh này.")

    # ---------------- Banned words ----------------
    @app_commands.command(name="addbadword", description="Thêm từ cấm vào bộ lọc tự động (Chỉ Admin)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def addbadword(self, interaction: discord.Interaction, word: str):
        word = word.casefold().strip()
        if not word:
            await interaction.response.send_message("❌ Từ cấm không được để trống.", ephemeral=True)
            return
        if len(word) > 100:
            await interaction.response.send_message("❌ Từ/cụm từ cấm tối đa 100 ký tự.", ephemeral=True)
            return
        await self.db.execute("INSERT INTO banned_words (word) VALUES ($1) ON CONFLICT DO NOTHING", word)
        self.banned_words_cache.add(word)
        await interaction.response.send_message("✅ Đã thêm từ cấm vào bộ lọc.", ephemeral=True)

    @app_commands.command(name="removebadword", description="Gỡ một từ cấm khỏi bộ lọc (Chỉ Admin)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def removebadword(self, interaction: discord.Interaction, word: str):
        word = word.casefold().strip()
        if not word:
            await interaction.response.send_message("❌ Từ cấm không được để trống.", ephemeral=True)
            return
        await self.db.execute("DELETE FROM banned_words WHERE word = $1", word)
        self.banned_words_cache.discard(word)
        await interaction.response.send_message("✅ Đã gỡ từ cấm khỏi bộ lọc.", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not self.banned_words_cache:
            return

        if contains_banned_word(message.content, self.banned_words_cache):
            await message.delete()
            await self.db.execute(
                "INSERT INTO warnings (user_id, moderator_id, reason) VALUES ($1, $2, $3)",
                message.author.id, self.bot.user.id, "Vi phạm bộ lọc từ cấm (tự động)"
            )
            try:
                await message.author.send("⚠️ Tin nhắn của bạn đã bị xóa vì chứa từ ngữ không phù hợp.")
            except discord.Forbidden:
                pass

            log_channel = self.log_channel(message.guild)
            if log_channel:
                await log_channel.send(f"🚫 Tự động xóa tin nhắn của {message.author.mention} (chứa từ cấm).")

    # ---------------- Mod log ----------------
    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        log_channel = self.log_channel(message.guild)
        if log_channel:
            content = _clip(message.content or "(không có nội dung chữ)", 1400).replace("\n", "\n> ")
            await log_channel.send(
                f"🗑️ Tin nhắn của {message.author.mention} tại {message.channel.mention} đã bị xóa:\n> {content}",
                allowed_mentions=discord.AllowedMentions.none(),
            )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        log_channel = self.log_channel(member.guild)
        if log_channel:
            await log_channel.send(f"📥 {member.mention} vừa tham gia server.")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        log_channel = self.log_channel(member.guild)
        if log_channel:
            await log_channel.send(f"📤 {member.mention} vừa rời server.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
