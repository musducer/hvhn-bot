import json
import os

import discord
from discord import app_commands
from discord.ext import commands, tasks
from env_utils import env_int

from internet_curator import ensure_internet_schema, scan_sources
from md_knowledge import index_md_bytes


AUTO_SCAN_ENABLED = os.getenv("HVHN_INTERNET_CURATOR_AUTO", "1").strip().lower() not in {"0", "false", "no", "off"}
AUTO_SCAN_HOURS = env_int("HVHN_INTERNET_CURATOR_HOURS", 24, minimum=1, maximum=8760)
AUTO_MAX_PER_SOURCE = env_int("HVHN_INTERNET_CURATOR_AUTO_PER_SOURCE", 3, minimum=1, maximum=100)
DEFAULT_MIN_SCORE = env_int("HVHN_INTERNET_CURATOR_MIN_SCORE", 55, minimum=1, maximum=100)


def _clip(value: str, limit: int = 950) -> str:
    value = (value or "").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


class InternetCurator(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._scan_running = False
        self.internet_auto_scan.change_interval(hours=AUTO_SCAN_HOURS)

    def _is_admin(self, interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member):
            return False
        role_name = os.getenv("HVHN_ADMIN_ROLE", "HVHN Admin").strip()
        has_role = any(role.name == role_name for role in interaction.user.roles)
        return has_role or interaction.user.guild_permissions.manage_guild

    async def _require_admin(self, interaction: discord.Interaction) -> bool:
        if self._is_admin(interaction):
            return True
        await interaction.response.send_message(
            "Ban can role HVHN Admin hoac quyen Manage Server de dung lenh nay.",
            ephemeral=True,
        )
        return False

    async def cog_load(self) -> None:
        await ensure_internet_schema(self.bot.db)
        if AUTO_SCAN_ENABLED and not self.internet_auto_scan.is_running():
            self.internet_auto_scan.start()

    async def cog_unload(self) -> None:
        if self.internet_auto_scan.is_running():
            self.internet_auto_scan.cancel()

    async def _run_scan(
        self,
        *,
        max_sources: int = 0,
        max_per_source: int = AUTO_MAX_PER_SOURCE,
        min_score: int = DEFAULT_MIN_SCORE,
    ) -> dict:
        if self._scan_running:
            return {"running": True}
        self._scan_running = True
        try:
            return await scan_sources(
                self.bot.db,
                max_sources=max_sources,
                max_per_source=max_per_source,
                min_score=min_score,
            )
        finally:
            self._scan_running = False

    async def _approve_row(self, row, reviewer_id: int) -> dict:
        result = await index_md_bytes(
            self.bot.db,
            row["title"],
            row["markdown"].encode("utf-8"),
            source=row["url"],
            author=row["author"] or "",
            created_by=reviewer_id,
        )
        await self.bot.db.execute(
            """
            UPDATE ai_internet_items
            SET status = 'approved', reviewed_at = now(), reviewed_by = $2, imported_doc_key = $3
            WHERE id = $1
            """,
            row["id"],
            reviewer_id,
            result.get("doc_key"),
        )
        return result

    @tasks.loop(hours=24)
    async def internet_auto_scan(self):
        result = await self._run_scan(max_per_source=AUTO_MAX_PER_SOURCE, min_score=DEFAULT_MIN_SCORE)
        if result.get("running"):
            return
        await self.bot.db.execute(
            """
            INSERT INTO hvhn_runtime_status (key, value, updated_at)
            VALUES ('internet_curator_last_scan', $1, now())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
            """,
            json.dumps(
                {
                    "sources": result.get("sources", 0),
                    "discovered": result.get("discovered", 0),
                    "examined": result.get("examined", 0),
                    "inserted": result.get("inserted", 0),
                },
                ensure_ascii=False,
            ),
        )

    @internet_auto_scan.before_loop
    async def before_internet_auto_scan(self):
        await self.bot.wait_until_ready()

    @app_commands.command(
        name="internet_scan",
        description="(admin) Quet cac nguon chinh thong, dao sau danh muc/RSS/sitemap va dua bai moi vao pending",
    )
    @app_commands.describe(
        so_nguon="So nguon dau tien muon quet; 0 = tat ca",
        moi_nguon="So bai toi da moi nguon",
        diem_toi_thieu="Diem loc toi thieu 1-100",
    )
    async def internet_scan(
        self,
        interaction: discord.Interaction,
        so_nguon: int = 0,
        moi_nguon: int = 5,
        diem_toi_thieu: int = DEFAULT_MIN_SCORE,
    ):
        if not await self._require_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await self._run_scan(
            max_sources=max(0, min(so_nguon, 50)),
            max_per_source=max(1, min(moi_nguon, 20)),
            min_score=max(1, min(diem_toi_thieu, 100)),
        )
        if result.get("running"):
            await interaction.followup.send("Dang co mot lan quet internet chay nen. Doi xong roi bam lai.", ephemeral=True)
            return

        lines = [
            "Da quet xong.",
            f"Nguon: `{result.get('sources', 0)}` | link tim thay: `{result.get('discovered', 0)}` | bai da doc: `{result.get('examined', 0)}` | pending moi: `{result.get('inserted', 0)}`",
            "",
            "Chi tiet nhanh:",
        ]
        for report in result.get("reports", [])[:12]:
            lines.append(
                f"- {report['source']}: link `{report['discovered']}`, moi `{report['fresh']}`, dat loc `{report['accepted']}`, them `{report['inserted']}`"
            )
        await interaction.followup.send(_clip("\n".join(lines), 1900), ephemeral=True)

    @app_commands.command(name="internet_pending", description="(admin) Xem cac bai internet dang cho duyet")
    async def internet_pending(self, interaction: discord.Interaction, limit: int = 10):
        if not await self._require_admin(interaction):
            return
        limit = max(1, min(limit, 20))
        rows = await self.bot.db.fetch(
            """
            SELECT id, source_name, title, quality_score, url, discovered_at
            FROM ai_internet_items
            WHERE status = 'pending_review'
            ORDER BY quality_score DESC, discovered_at DESC
            LIMIT $1
            """,
            limit,
        )
        if not rows:
            await interaction.response.send_message("Chua co bai nao dang cho duyet.", ephemeral=True)
            return
        lines = ["Bai dang cho duyet:"]
        for row in rows:
            lines.append(
                f"#{row['id']} [{row['quality_score']}/100] {row['source_name']} - {row['title']}\n{row['url']}"
            )
        await interaction.response.send_message(_clip("\n\n".join(lines), 1900), ephemeral=True)

    @app_commands.command(name="internet_xem", description="(admin) Xem tom tat mot bai internet pending")
    async def internet_xem(self, interaction: discord.Interaction, item_id: int):
        if not await self._require_admin(interaction):
            return
        row = await self.bot.db.fetchrow(
            """
            SELECT id, source_name, title, author, published_at, language, excerpt,
                   quality_score, quality_notes, url, content, status
            FROM ai_internet_items
            WHERE id = $1
            """,
            item_id,
        )
        if not row:
            await interaction.response.send_message("Khong thay muc nay.", ephemeral=True)
            return
        notes = ""
        try:
            notes = "; ".join(json.loads(row["quality_notes"] or "[]"))
        except Exception:
            notes = row["quality_notes"] or ""
        body = "\n".join(
            [
                f"#{row['id']} [{row['status']}] [{row['quality_score']}/100] {row['title']}",
                f"Nguon: {row['source_name']} | URL: {row['url']}",
                f"Tac gia: {row['author'] or 'chua ro'} | Ngay: {row['published_at'] or 'chua ro'} | Ngon ngu: {row['language'] or 'chua ro'}",
                f"Loc: {notes}",
                "",
                "Tom tat/excerpt:",
                row["excerpt"] or _clip(row["content"], 700),
            ]
        )
        await interaction.response.send_message(_clip(body, 1900), ephemeral=True)

    @app_commands.command(name="internet_duyet", description="(admin) Duyet va nhap mot bai pending vao kho tri thuc MD/RAG")
    async def internet_duyet(self, interaction: discord.Interaction, item_id: int):
        if not await self._require_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        row = await self.bot.db.fetchrow(
            """
            SELECT *
            FROM ai_internet_items
            WHERE id = $1 AND status = 'pending_review'
            """,
            item_id,
        )
        if not row:
            await interaction.followup.send("Khong thay bai pending nay, hoac bai da duoc xu ly.", ephemeral=True)
            return
        result = await self._approve_row(row, interaction.user.id)
        await interaction.followup.send(
            f"Da duyet #{item_id} va nhap kho RAG: `{result.get('title')}` | passages `{result.get('passages')}` | changed `{result.get('changed')}`.",
            ephemeral=True,
        )

    @app_commands.command(name="internet_duyet_all", description="(admin) Duyet hang loat bai internet pending dat diem loc")
    @app_commands.describe(
        limit="So bai toi da se duyet trong mot lan",
        diem_toi_thieu="Chi duyet bai co quality_score tu muc nay tro len",
    )
    async def internet_duyet_all(
        self,
        interaction: discord.Interaction,
        limit: int = 10,
        diem_toi_thieu: int = 70,
    ):
        if not await self._require_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        limit = max(1, min(limit, 50))
        diem_toi_thieu = max(1, min(diem_toi_thieu, 100))
        rows = await self.bot.db.fetch(
            """
            SELECT *
            FROM ai_internet_items
            WHERE status = 'pending_review' AND quality_score >= $1
            ORDER BY quality_score DESC, discovered_at ASC
            LIMIT $2
            """,
            diem_toi_thieu,
            limit,
        )
        if not rows:
            await interaction.followup.send(
                f"Khong co bai pending nao dat tu `{diem_toi_thieu}/100` tro len.",
                ephemeral=True,
            )
            return

        approved = []
        failed = []
        for row in rows:
            try:
                result = await self._approve_row(row, interaction.user.id)
                approved.append((row["id"], result.get("title") or row["title"], result.get("passages", 0)))
            except Exception as exc:
                failed.append((row["id"], str(exc)[:120]))

        lines = [
            f"Da duyet `{len(approved)}` bai internet pending dat tu `{diem_toi_thieu}/100` tro len.",
        ]
        if approved:
            lines.append("")
            lines.append("Da nhap:")
            for item_id, title, passages in approved[:12]:
                lines.append(f"- #{item_id} `{passages}` doan - {title}")
        if failed:
            lines.append("")
            lines.append("Loi:")
            for item_id, error in failed[:8]:
                lines.append(f"- #{item_id}: {error}")
        await interaction.followup.send(_clip("\n".join(lines), 1900), ephemeral=True)

    @app_commands.command(name="internet_tuchoi", description="(admin) Tu choi mot bai internet pending")
    async def internet_tuchoi(self, interaction: discord.Interaction, item_id: int, ly_do: str = ""):
        if not await self._require_admin(interaction):
            return
        n = await self.bot.db.fetchval(
            """
            UPDATE ai_internet_items
            SET status = 'rejected', reviewed_at = now(), reviewed_by = $2,
                quality_notes = coalesce(quality_notes, '') || $3
            WHERE id = $1 AND status = 'pending_review'
            RETURNING id
            """,
            item_id,
            interaction.user.id,
            ("\nreject_reason: " + ly_do.strip()) if ly_do.strip() else "",
        )
        if not n:
            await interaction.response.send_message("Khong thay bai pending nay, hoac bai da duoc xu ly.", ephemeral=True)
            return
        await interaction.response.send_message(f"Da tu choi #{item_id}.", ephemeral=True)

    @app_commands.command(name="internet_status", description="(admin) Xem trang thai curator internet")
    async def internet_status(self, interaction: discord.Interaction):
        if not await self._require_admin(interaction):
            return
        rows = await self.bot.db.fetch(
            """
            SELECT status, count(*) AS n
            FROM ai_internet_items
            GROUP BY status
            ORDER BY status
            """
        )
        last_scan = await self.bot.db.fetchval(
            "SELECT value FROM hvhn_runtime_status WHERE key = 'internet_curator_last_scan'"
        )
        counts = " | ".join(f"{row['status']}: `{row['n']}`" for row in rows) or "chua co du lieu"
        await interaction.response.send_message(
            "\n".join(
                [
                    f"Auto scan: `{'on' if AUTO_SCAN_ENABLED else 'off'}` moi `{AUTO_SCAN_HOURS}` gio",
                    f"Dang scan: `{'yes' if self._scan_running else 'no'}`",
                    f"Trang thai bai: {counts}",
                    f"Lan scan cuoi: `{last_scan or 'chua co'}`",
                ]
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(InternetCurator(bot))
