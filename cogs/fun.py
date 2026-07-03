import random

import discord
from discord.ext import commands
from discord import app_commands


class Fun(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="coinflip", description="Tung đồng xu ngẫu nhiên")
    async def coinflip(self, interaction: discord.Interaction):
        result = random.choice(["Ngửa 🌕", "Sấp 🌑"])
        await interaction.response.send_message(f"🪙 Kết quả: **{result}**")

    @app_commands.command(name="8ball", description="Hỏi quả cầu tiên tri một câu hỏi Yes/No")
    async def eight_ball(self, interaction: discord.Interaction, question: str):
        answers = [
            "Chắc chắn rồi.", "Có thể lắm.", "Không nên đâu.", "Hỏi lại sau nhé.",
            "Tôi không chắc.", "Hoàn toàn không.", "Xu hướng là có.", "Đừng trông đợi vào điều đó."
        ]
        await interaction.response.send_message(f"🎱 **Câu hỏi:** {question}\n**Trả lời:** {random.choice(answers)}")


async def setup(bot: commands.Bot):
    await bot.add_cog(Fun(bot))
