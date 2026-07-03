import discord
from discord.ext import commands
from discord import app_commands
import aiosqlite


class Leveling(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db: aiosqlite.Connection = bot.db

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        user_id = message.author.id
        async with self.db.execute("SELECT xp, level FROM users WHERE user_id = ?", (user_id,)) as cursor:
            result = await cursor.fetchone()

        if result is None:
            await self.db.execute("INSERT INTO users (user_id, xp, level) VALUES (?, ?, ?)", (user_id, 10, 1))
            await self.db.commit()
            return

        xp = result[0] + 10
        current_level = result[1]
        new_level = 1 + (xp // 100)

        if new_level > current_level:
            await self.db.execute("UPDATE users SET level = ?, xp = ? WHERE user_id = ?", (new_level, xp, user_id))
            await self.db.commit()

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
        else:
            await self.db.execute("UPDATE users SET xp = ? WHERE user_id = ?", (xp, user_id))
            await self.db.commit()

    @app_commands.command(name="rank", description="Kiểm tra cấp độ và XP hiện tại của bạn")
    async def rank(self, interaction: discord.Interaction, member: discord.Member = None):
        user = member or interaction.user
        async with self.db.execute("SELECT xp, level FROM users WHERE user_id = ?", (user.id,)) as cursor:
            result = await cursor.fetchone()
        if result:
            await interaction.response.send_message(f"🏆 {user.mention} đang ở **Cấp {result[1]}** với **{result[0]} XP**.", ephemeral=True)
        else:
            await interaction.response.send_message(f"💤 {user.mention} chưa có XP nào. Hãy tương tác nhiều hơn nhé!", ephemeral=True)

    @app_commands.command(name="leaderboard", description="Xem top 5 thành viên chăm chỉ nhất máy chủ")
    async def leaderboard(self, interaction: discord.Interaction):
        async with self.db.execute("SELECT user_id, xp, level FROM users ORDER BY xp DESC LIMIT 5") as cursor:
            results = await cursor.fetchall()
        if not results:
            await interaction.response.send_message("Bảng xếp hạng hiện đang trống.")
            return

        embed = discord.Embed(title="🌟 BẢNG XẾP HẠNG HVHN", color=discord.Color.gold())
        for idx, row in enumerate(results, 1):
            embed.add_field(name=f"Hạng {idx}", value=f"<@{row[0]}> - Cấp {row[2]} ({row[1]} XP)", inline=False)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Leveling(bot))
