import os
import asyncio

import aiosqlite
import discord
from discord.ext import commands
from dotenv import load_dotenv

from keep_alive import keep_alive

load_dotenv()

INITIAL_EXTENSIONS = [
    "cogs.setup",
    "cogs.leveling",
    "cogs.voice",
    "cogs.utilities",
]


class HVHNBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.voice_states = True
        super().__init__(command_prefix="!", intents=intents)
        self.db: aiosqlite.Connection | None = None

    async def setup_hook(self):
        self.db = await aiosqlite.connect("xp.db")
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, xp INTEGER, level INTEGER)"
        )
        await self.db.commit()

        for extension in INITIAL_EXTENSIONS:
            await self.load_extension(extension)

        await self.tree.sync()
        print("Bot HVHN đã khởi động và đồng bộ hệ thống lệnh!")

    async def close(self):
        if self.db is not None:
            await self.db.close()
        await super().close()


async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("Thiếu DISCORD_TOKEN trong file .env")

    keep_alive()

    bot = HVHNBot()
    async with bot:
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
