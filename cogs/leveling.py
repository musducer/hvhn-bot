import discord
from discord.ext import commands
from discord import app_commands
import asyncpg


class Leveling(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db: asyncpg.Pool = bot.db

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        user_id = message.author.id
        result = await self.db.fetchrow(
            """
            INSERT INTO users (user_id, xp, level)
            VALUES ($1, 10, 1)
            ON CONFLICT (user_id) DO UPDATE
            SET xp = COALESCE(users.xp, 0) + 10,
                level = 1 + ((COALESCE(users.xp, 0) + 10) / 100)
            RETURNING xp, level
            """,
            user_id,
        )
        xp = result["xp"]
        new_level = result["level"]
        previous_level = 1 + ((xp - 10) // 100)

        if new_level > previous_level:
            guild = message.guild
            if new_level == 5:
                role = discord.utils.get(guild.roles, name="Nhà thơ mộng mơ")
                if role:
                    await message.author.add_roles(role)
                await message.channel.send(f"🎉 Chúc mừng {message.author.mention} đạt Cấp 5 và trở thành **Nhà thơ mộng mơ**!")
            elif new_level == 10:
                role = discord.utils.get(guild.roles, name="Chiến thần Nghị luận")
                if role:
                    await message.author.add_roles(role)
                await message.channel.send(f"🔥 Xuất sắc! {message.author.mention} đã đạt Cấp 10, thăng hạng **Chiến thần Nghị luận**!")

    @app_commands.command(name="rank", description="Kiểm tra cấp độ và XP hiện tại của bạn")
    async def rank(self, interaction: discord.Interaction, member: discord.Member = None):
        user = member or interaction.user
        result = await self.db.fetchrow("SELECT xp, level FROM users WHERE user_id = $1", user.id)
        if result:
            await interaction.response.send_message(f"🏆 {user.mention} đang ở **Cấp {result['level']}** với **{result['xp']} XP**.", ephemeral=True)
        else:
            await interaction.response.send_message(f"💤 {user.mention} chưa có XP nào. Hãy tương tác nhiều hơn nhé!", ephemeral=True)

    @app_commands.command(name="leaderboard", description="Xem top 5 thành viên chăm chỉ nhất máy chủ")
    async def leaderboard(self, interaction: discord.Interaction):
        results = await self.db.fetch("SELECT user_id, xp, level FROM users ORDER BY xp DESC LIMIT 5")
        if not results:
            await interaction.response.send_message("Bảng xếp hạng hiện đang trống.")
            return

        embed = discord.Embed(title="🌟 BẢNG XẾP HẠNG HVHN", color=discord.Color.gold())
        for idx, row in enumerate(results, 1):
            embed.add_field(name=f"Hạng {idx}", value=f"<@{row['user_id']}> - Cấp {row['level']} ({row['xp']} XP)", inline=False)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Leveling(bot))
