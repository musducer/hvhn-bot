import discord
from discord.ext import commands
from discord import app_commands

ADMIN_ONLY_COMMANDS = {
    "giverole", "removerole", "clear", "lock", "unlock", "answer", "setup",
    "warn", "mute", "unmute", "kick", "ban", "slowmode", "addbadword", "removebadword",
}


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Xem danh sách toàn bộ lệnh bạn có thể dùng")
    async def help_command(self, interaction: discord.Interaction):
        commands_list = [
            cmd for cmd in self.bot.tree.get_commands()
            if isinstance(cmd, app_commands.Command) and cmd.name not in ADMIN_ONLY_COMMANDS
        ]
        commands_list.sort(key=lambda c: c.name)

        embed = discord.Embed(
            title="📖 DANH SÁCH LỆNH - NHÓM HỌC TẬP HVHN",
            description="Dưới đây là các lệnh bạn có thể sử dụng.",
            color=discord.Color.blurple()
        )
        for cmd in commands_list:
            embed.add_field(name=f"/{cmd.name}", value=cmd.description or "Không có mô tả.", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))
