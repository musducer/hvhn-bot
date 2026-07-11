import os
import asyncio

import asyncpg
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

from keep_alive import keep_alive
from pdf_knowledge import PDF_KNOWLEDGE_SCHEMA
from md_knowledge import MD_KNOWLEDGE_SCHEMA

load_dotenv()

INITIAL_EXTENSIONS = [
    "cogs.setup",
    "cogs.leveling",
    "cogs.voice",
    "cogs.utilities",
    "cogs.study",
    "cogs.moderation",
    "cogs.fun",
    "cogs.ai",
    "cogs.doc_storage",
    "cogs.help",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, xp INTEGER, level INTEGER);

CREATE TABLE IF NOT EXISTS flashcards (
    id SERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    author_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS quotes (
    id SERIAL PRIMARY KEY,
    content TEXT NOT NULL,
    author_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS deadlines (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    due_date DATE NOT NULL,
    created_by BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS warnings (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    moderator_id BIGINT NOT NULL,
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS banned_words (
    word TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS questions (
    id SERIAL PRIMARY KEY,
    content TEXT NOT NULL,
    asker_id BIGINT NOT NULL,
    answered BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hvhn_doc_jobs (
    id SERIAL PRIMARY KEY,
    job_type TEXT NOT NULL,
    text_payload TEXT,
    file_name TEXT,
    file_data BYTEA,
    requested_by BIGINT,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS hvhn_runtime_status (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hvhn_clients_cache (
    email TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    doc_count INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hvhn_docs_cache (
    doc_name TEXT PRIMARY KEY,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hvhn_sheet_clients (
    email TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    grant_date TEXT,
    expiry_date TEXT,
    days_left INTEGER,
    status TEXT,
    doc_count INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hvhn_sheet_docs (
    doc_name TEXT PRIMARY KEY,
    client_count INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ai_knowledge (
    id SERIAL PRIMARY KEY,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT,
    approved BOOLEAN NOT NULL DEFAULT TRUE,
    created_by BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ai_feedback (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    prompt TEXT NOT NULL,
    answer TEXT NOT NULL,
    rating TEXT NOT NULL,
    correction TEXT,
    approved BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE ai_feedback ADD COLUMN IF NOT EXISTS approved BOOLEAN NOT NULL DEFAULT FALSE;
"""

SCHEMA += PDF_KNOWLEDGE_SCHEMA
SCHEMA += MD_KNOWLEDGE_SCHEMA


DAN_LANG_ROLE = "Dân làng Hua Tát"


def can_use_bot(user) -> bool:
    perms = getattr(user, "guild_permissions", None)
    if perms is not None and getattr(perms, "administrator", False):
        return True
    roles = getattr(user, "roles", None) or []
    return any(getattr(role, "name", None) == DAN_LANG_ROLE for role in roles)


class GatedCommandTree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if can_use_bot(interaction.user):
            return True
        guide = None
        if interaction.guild is not None:
            guide = discord.utils.get(interaction.guild.text_channels, name="hướng-dẫn-dùng-bot")
        where = guide.mention if guide else "#hướng-dẫn-dùng-bot"
        try:
            await interaction.response.send_message(
                f"Bạn cần đọc {where} và bấm xác nhận để nhận vai trò \"{DAN_LANG_ROLE}\" trước khi dùng bot.",
                ephemeral=True,
            )
        except discord.InteractionResponded:
            pass
        return False

    async def on_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.CheckFailure):
            return
        await super().on_error(interaction, error)


class HVHNBot(commands.Bot):
    def __init__(self, database_url: str):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.voice_states = True
        super().__init__(command_prefix="!", intents=intents, tree_cls=GatedCommandTree)
        self.database_url = database_url
        self.db: asyncpg.Pool | None = None

    async def setup_hook(self):
        self.db = await asyncpg.create_pool(self.database_url)
        await self.db.execute(SCHEMA)

        for extension in INITIAL_EXTENSIONS:
            await self.load_extension(extension)

        await self.tree.sync()
        print("Bot HVHN đã khởi động và đồng bộ hệ thống lệnh!", flush=True)

    async def close(self):
        if self.db is not None:
            await self.db.close()
        await super().close()


async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("Thiếu DISCORD_TOKEN trong file .env")

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("Thiếu DATABASE_URL trong file .env")

    keep_alive()

    bot = HVHNBot(database_url)
    async with bot:
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
