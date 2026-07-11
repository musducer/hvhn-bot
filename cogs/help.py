import discord
from discord import app_commands
from discord.ext import commands

ADMIN_ONLY_COMMANDS = {
    "giverole", "removerole", "clear", "lock", "unlock", "answer", "questions", "setup",
    "warn", "mute", "unmute", "kick", "ban", "unban", "slowmode", "addbadword", "removebadword",
    "announce", "hvhn_themkhach", "hvhn_tailieu_khach", "hvhn_tailieu_khach_link", "hvhn_xoakhach", "hvhn_xoatailieu",
    "hvhn_status_full", "hvhn_retry_failed", "hvhn_khach", "hvhn_giahan",
    "hvhn_debug_retrieval", "ai_kienthuc_them", "ai_feedback_stats", "hvhn_embed_backfill",
    "ai_feedback_duyet",
}

PAGE_SIZE = 20


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _is_admin(self, interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member):
            return False
        return interaction.user.guild_permissions.manage_guild

    def _visible_commands(self, interaction: discord.Interaction) -> list[app_commands.Command]:
        is_admin = self._is_admin(interaction)
        commands_list = []
        for cmd in self.bot.tree.get_commands():
            if not isinstance(cmd, app_commands.Command):
                continue
            if cmd.name in ADMIN_ONLY_COMMANDS and not is_admin:
                continue
            commands_list.append(cmd)
        return sorted(commands_list, key=lambda c: c.name)

    @app_commands.command(name="help", description="Xem danh sách toàn bộ lệnh bạn có thể dùng")
    async def help_command(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        commands_list = self._visible_commands(interaction)
        if not commands_list:
            await interaction.followup.send("Chưa có lệnh nào để hiển thị.", ephemeral=True)
            return

        chunks = [
            commands_list[i:i + PAGE_SIZE]
            for i in range(0, len(commands_list), PAGE_SIZE)
        ]
        embeds = []
        for index, chunk in enumerate(chunks, start=1):
            embed = discord.Embed(
                title=f"Danh sách lệnh HVHN ({index}/{len(chunks)})",
                description="Các lệnh bạn có thể dùng trong server này.",
                color=discord.Color.blurple(),
            )
            for cmd in chunk:
                embed.add_field(
                    name=f"/{cmd.name}",
                    value=cmd.description or "Không có mô tả.",
                    inline=False,
                )
            embeds.append(embed)

        await interaction.followup.send(embed=embeds[0], ephemeral=True)
        for embed in embeds[1:]:
            await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))
