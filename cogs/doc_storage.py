import os
import re
import time
import uuid
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from pdf_knowledge import pdf_knowledge_stats

try:
    from hvhn_batch import MIRROR_SOURCE
except Exception:
    MIRROR_SOURCE = r"D:\Mirror Files Drive\TÀI LIỆU ĐỘC QUYỀN HVHN\TÀI LIỆU ĐÃ WATERMARK CHƯA PHÂN PHỐI"


DEFAULT_MIRROR_PARENT = Path(MIRROR_SOURCE).parent
ADMIN_ROLE_ENV = "HVHN_ADMIN_ROLE"
MIRROR_PARENT_ENV = "HVHN_MIRROR_PARENT"
MAX_PDF_BYTES = int(os.getenv("HVHN_MAX_PDF_MB", "300")) * 1024 * 1024
PDF_URL_PATTERN = re.compile(r"^https?://", re.I)


def _safe_stem(value: str, fallback: str = "don") -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value).strip(" ._")
    value = re.sub(r"\s+", " ", value)
    return value[:120] or fallback


def _job_name(prefix: str, label: str, suffix: str) -> str:
    ts = time.strftime("%Y%m%d_%H%M%S")
    nonce = uuid.uuid4().hex[:8]
    return f"{prefix}_{ts}_{_safe_stem(label)}_{nonce}{suffix}"


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".part")
    with open(tmp_path, "wb") as f:
        f.write(data)
    os.replace(tmp_path, path)


class DocumentStorage(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.mirror_parent = Path(os.getenv(MIRROR_PARENT_ENV, str(DEFAULT_MIRROR_PARENT)))
        self.jobs_add_client = self.mirror_parent / "_don_them_khach"
        self.jobs_add_doc = self.mirror_parent / "_don_them_tai_lieu"
        self.jobs_remove_client = self.mirror_parent / "_don_xoa_khach"
        self.jobs_remove_doc = self.mirror_parent / "_don_xoa_tai_lieu"

    def _is_admin(self, interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member):
            return False
        role_name = os.getenv(ADMIN_ROLE_ENV, "HVHN Admin").strip()
        has_role = any(role.name == role_name for role in interaction.user.roles)
        return has_role or interaction.user.guild_permissions.manage_guild

    async def _require_admin(self, interaction: discord.Interaction) -> bool:
        if self._is_admin(interaction):
            return True
        await interaction.response.send_message(
            "Bạn cần role HVHN Admin hoặc quyền Manage Server để dùng lệnh này.",
            ephemeral=True,
        )
        return False

    async def _enqueue(
        self,
        job_type: str,
        *,
        text_payload: str | None = None,
        file_name: str | None = None,
        file_data: bytes | None = None,
        requested_by: int | None = None,
    ) -> int:
        return await self.bot.db.fetchval(
            """
            INSERT INTO hvhn_doc_jobs (job_type, text_payload, file_name, file_data, requested_by)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            job_type,
            text_payload,
            file_name,
            file_data,
            requested_by,
        )

    async def _status_map(self) -> dict[str, str]:
        rows = await self.bot.db.fetch("SELECT key, value FROM hvhn_runtime_status")
        return {row["key"]: row["value"] for row in rows}

    @staticmethod
    def _clean_email(email: str) -> str:
        return email.strip().lower()

    @staticmethod
    def _validate_pdf_attachment(file: discord.Attachment) -> str | None:
        if not file.filename.lower().endswith(".pdf"):
            return "chỉ nhận PDF"
        if file.size and file.size > MAX_PDF_BYTES:
            return f"quá {MAX_PDF_BYTES // 1024 // 1024}MB"
        return None

    async def _enqueue_client_pdf(
        self,
        file: discord.Attachment,
        requested_by: int,
    ) -> tuple[int | None, str | None]:
        # Chi xep hang watermark/phan phoi cho khach; AI khong index PDF nua (kho tri thuc la .md).
        error = self._validate_pdf_attachment(file)
        if error:
            return None, error

        try:
            data = await file.read()
        except Exception as exc:
            return None, f"lỗi đọc file: {exc}"
        if len(data) > MAX_PDF_BYTES:
            return None, f"quá {MAX_PDF_BYTES // 1024 // 1024}MB"

        job_id = await self._enqueue(
            "add_document",
            file_name=file.filename,
            file_data=data,
            requested_by=requested_by,
        )
        return job_id, None

    async def _enqueue_pdf_url(
        self,
        url: str,
        file_name: str,
        requested_by: int,
    ) -> int | None:
        url = url.strip()
        if not PDF_URL_PATTERN.match(url):
            return None
        safe_file_name = _safe_stem(Path(file_name).stem or "tai_lieu") + ".pdf"
        return await self._enqueue(
            "add_document_url",
            text_payload=url,
            file_name=safe_file_name,
            requested_by=requested_by,
        )

    @app_commands.command(name="hvhn_themkhach", description="Thêm khách vào hệ thống tài liệu HVHN")
    async def add_client(self, interaction: discord.Interaction, ten: str, email: str):
        if not await self._require_admin(interaction):
            return
        email = email.strip().lower()
        ten = ten.strip()
        if not ten or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            await interaction.response.send_message("Tên hoặc email không hợp lệ.", ephemeral=True)
            return

        payload = f"{ten}\t{email}"
        job_id = await self._enqueue("add_client", text_payload=payload, requested_by=interaction.user.id)
        await interaction.response.send_message(
            f"Đã xếp hàng đơn #{job_id}: thêm khách `{ten} <{email}>`. PC bật lên watcher sẽ xử lý.",
            ephemeral=True,
        )

    @app_commands.command(name="hvhn_tailieu_khach", description="Thêm PDF vào kho độc quyền và phân phối cho khách")
    async def add_client_document(self, interaction: discord.Interaction, file: discord.Attachment):
        if not await self._require_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        job_id, error = await self._enqueue_client_pdf(file, interaction.user.id)
        if not job_id:
            await interaction.followup.send(f"Không nhận `{file.filename}`: {error}.", ephemeral=True)
            return
        await interaction.followup.send(
            f"Đã xếp hàng đơn #{job_id}: thêm `{file.filename}` vào kho độc quyền cho khách. "
            "Watcher sẽ watermark và phân phối. (Kho tri thức AI giờ chỉ nhận file .md qua Google Form.)",
            ephemeral=True,
        )

    @app_commands.command(name="hvhn_tailieu_khach_link", description="Nạp PDF lớn bằng link Drive vào kho khách và phân phối")
    async def add_client_document_link(self, interaction: discord.Interaction, url: str, ten_file: str):
        if not await self._require_admin(interaction):
            return
        job_id = await self._enqueue_pdf_url(url, ten_file, interaction.user.id)
        if not job_id:
            await interaction.response.send_message("Link không hợp lệ. Cần link bắt đầu bằng http/https.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"Đã xếp hàng đơn #{job_id}: watcher sẽ tải `{ten_file}.pdf`, watermark và phân phối cho khách.",
            ephemeral=True,
        )

    @app_commands.command(name="hvhn_xoakhach", description="Xóa khách khỏi kho render HVHN")
    async def remove_client(self, interaction: discord.Interaction, email: str):
        if not await self._require_admin(interaction):
            return
        email = email.strip().lower()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            await interaction.response.send_message("Email không hợp lệ.", ephemeral=True)
            return

        job_id = await self._enqueue("remove_client", text_payload=email, requested_by=interaction.user.id)
        await interaction.response.send_message(
            f"Đã xếp hàng đơn #{job_id}: xóa khách `{email}` khỏi `clients.csv`.",
            ephemeral=True,
        )

    @app_commands.command(name="hvhn_xoatailieu", description="Xóa tài liệu khỏi kho render HVHN")
    async def remove_document(self, interaction: discord.Interaction, ten_tai_lieu: str):
        if not await self._require_admin(interaction):
            return
        doc_base = Path(ten_tai_lieu.strip()).stem
        if not doc_base:
            await interaction.response.send_message("Tên tài liệu không hợp lệ.", ephemeral=True)
            return

        job_id = await self._enqueue("remove_document", text_payload=doc_base, requested_by=interaction.user.id)
        await interaction.response.send_message(
            f"Đã xếp hàng đơn #{job_id}: xóa tài liệu `{doc_base}` khỏi `docs/`.",
            ephemeral=True,
        )

    @app_commands.command(name="hvhn_trangthai", description="Kiểm tra kết nối bot với folder đơn HVHN")
    async def status(self, interaction: discord.Interaction):
        if not await self._require_admin(interaction):
            return
        folders = {
            "mirror": self.mirror_parent,
            "thêm khách": self.jobs_add_client,
            "thêm tài liệu": self.jobs_add_doc,
            "xóa khách": self.jobs_remove_client,
            "xóa tài liệu": self.jobs_remove_doc,
        }
        pending = await self.bot.db.fetchval("SELECT count(*) FROM hvhn_doc_jobs WHERE status = 'pending'")
        processing = await self.bot.db.fetchval("SELECT count(*) FROM hvhn_doc_jobs WHERE status = 'processing'")
        failed = await self.bot.db.fetchval("SELECT count(*) FROM hvhn_doc_jobs WHERE status IN ('error', 'download_failed', 'db_failed', 'ocr_failed')")
        lines = [
            "queue DB: OK",
            f"đang chờ: {pending} | đang xử lý: {processing} | lỗi: {failed}",
            "",
            "folder local trên máy đang chạy bot:",
        ]
        lines.extend(f"{name}: {'OK' if path.exists() else 'thiếu'} - {path}" for name, path in folders.items())
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @app_commands.command(name="hvhn_status_full", description="Xem trạng thái đầy đủ của hệ HVHN")
    async def status_full(self, interaction: discord.Interaction):
        if not await self._require_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        status = await self._status_map()
        pending = await self.bot.db.fetchval("SELECT count(*) FROM hvhn_doc_jobs WHERE status = 'pending'")
        processing = await self.bot.db.fetchval("SELECT count(*) FROM hvhn_doc_jobs WHERE status = 'processing'")
        failed = await self.bot.db.fetchval("SELECT count(*) FROM hvhn_doc_jobs WHERE status IN ('error', 'download_failed', 'db_failed', 'ocr_failed')")
        sheet_clients = await self.bot.db.fetchval("SELECT count(*) FROM hvhn_sheet_clients")
        sheet_docs = await self.bot.db.fetchval("SELECT count(*) FROM hvhn_sheet_docs")
        failed_rows = await self.bot.db.fetch(
            """
            SELECT id, job_type, coalesce(error, '') AS error
            FROM hvhn_doc_jobs
            WHERE status IN ('error', 'download_failed', 'db_failed', 'ocr_failed', 'zero_chunks')
            ORDER BY id DESC
            LIMIT 5
            """
        )

        embed = discord.Embed(title="HVHN - Trạng thái hệ thống", color=discord.Color.blue())
        embed.add_field(
            name="Watcher",
            value=(
                f"Heartbeat: `{status.get('watcher_heartbeat', 'chua co')}`\n"
                f"Mirror: `{status.get('mirror_ready', 'unknown')}`\n"
                f"Sheet snapshot: `{status.get('sheet_status_exported_at', 'chua co')}`\n"
                f"DB latency: `{status.get('watcher_db_latency_ms', 'n/a')}ms` | DNS: `{status.get('watcher_db_dns_ms', 'n/a')}ms` | connect: `{status.get('watcher_db_connect_ms', 'n/a')}ms`\n"
                f"DB last ok: `{status.get('watcher_db_last_success', 'chua co')}` | reconnects: `{status.get('watcher_db_reconnect_count', '0')}`\n"
                f"DB pool: `{status.get('watcher_db_pool_state', 'unknown')}`"
            ),
            inline=False,
        )

        embed.add_field(
            name="Dữ liệu",
            value=(
                f"Local clients/docs: `{status.get('clients_count', '0')}` / `{status.get('docs_count', '0')}`\n"
                f"Sheet clients/docs: `{sheet_clients}` / `{sheet_docs}`\n"
                f"AI PDF: `{status.get('ai_pdf_docs_indexed', '0')}` file "
                f"(độc quyền `{status.get('ai_pdf_exclusive_docs_indexed', '0')}`, bot `{status.get('ai_pdf_bot_docs_indexed', '0')}`) "
                f"| sync: `{status.get('ai_pdf_last_sync', 'chưa có')}`"
            ),
            inline=False,
        )
        embed.add_field(
            name="Queue DB",
            value=f"Chờ: `{pending}` | Đang xử lý: `{processing}` | Lỗi: `{failed}`",
            inline=False,
        )
        local_queue = [
            f"thêm khách `{status.get('queue_add_client', '0')}`",
            f"thêm tài liệu `{status.get('queue_add_document', '0')}`",
            f"tài liệu bot `{status.get('bot_docs_count', '0')}`",
            f"xóa khách `{status.get('queue_remove_client', '0')}`",
            f"xóa tài liệu `{status.get('queue_remove_document', '0')}`",
            f"sheet xóa khách `{status.get('queue_sheet_remove_client', '0')}`",
            f"sheet xóa tài liệu `{status.get('queue_sheet_remove_document', '0')}`",
            f"sheet gia hạn `{status.get('queue_sheet_renew_client', '0')}`",
        ]
        embed.add_field(name="Queue local", value=" | ".join(local_queue), inline=False)
        if failed_rows:
            embed.add_field(
                name="Lỗi gần nhất",
                value="\n".join(f"#{r['id']} `{r['job_type']}` - {r['error'][:80]}" for r in failed_rows),
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="hvhn_retry_failed", description="Cho chạy lại các đơn HVHN bị lỗi")
    async def retry_failed(self, interaction: discord.Interaction, limit: int = 20):
        if not await self._require_admin(interaction):
            return
        limit = max(1, min(limit, 100))
        rows = await self.bot.db.fetch(
            """
            SELECT id FROM hvhn_doc_jobs
            WHERE status IN ('error', 'download_failed', 'db_failed', 'ocr_failed')
            ORDER BY id ASC
            LIMIT $1
            """,
            limit,
        )
        ids = [r["id"] for r in rows]
        if ids:
            await self.bot.db.execute(
                """
                UPDATE hvhn_doc_jobs
                SET status = 'pending', error = NULL, processed_at = NULL
                WHERE id = ANY($1::int[])
                """,
                ids,
            )
        await interaction.response.send_message(f"Đã đưa `{len(ids)}` đơn lỗi về hàng chờ.", ephemeral=True)

    @app_commands.command(name="hvhn_ai_pdf_audit", description="Kiểm tra AI đã đọc/OCR kho PDF chưa")
    async def ai_pdf_audit(self, interaction: discord.Interaction):
        if not await self._require_admin(interaction):
            return
        stats = await pdf_knowledge_stats(self.bot.db)
        exclusive = stats["by_source"].get("exclusive", {"docs": 0, "chunks": 0})
        bot_only = stats["by_source"].get("bot", {"docs": 0, "chunks": 0})
        lines = [
            f"Tổng: `{stats['total_docs']}` PDF | `{stats['total_chunks']}` đoạn AI đọc được",
            f"Kho khách: `{exclusive['docs']}` PDF | `{exclusive['chunks']}` đoạn",
            f"Kho bot: `{bot_only['docs']}` PDF | `{bot_only['chunks']}` đoạn",
        ]
        if stats["zero_docs"]:
            lines.append("")
            lines.append("PDF chưa đọc được nội dung/OCR ra 0 đoạn:")
            lines.extend(f"- `{row['title']}`" for row in stats["zero_docs"][:15])
        else:
            lines.append("")
            lines.append("Không có PDF nào đang ở trạng thái 0 đoạn.")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @app_commands.command(name="hvhn_khach", description="Xem trạng thái một khách theo email")
    async def client_status(self, interaction: discord.Interaction, email: str):
        if not await self._require_admin(interaction):
            return
        email = self._clean_email(email)
        row = await self.bot.db.fetchrow(
            "SELECT * FROM hvhn_sheet_clients WHERE email = $1",
            email,
        )
        local = await self.bot.db.fetchrow(
            "SELECT * FROM hvhn_clients_cache WHERE email = $1",
            email,
        )
        jobs = await self.bot.db.fetch(
            """
            SELECT id, job_type, status, created_at, coalesce(error, '') AS error
            FROM hvhn_doc_jobs
            WHERE lower(coalesce(text_payload, '')) LIKE $1
            ORDER BY id DESC
            LIMIT 5
            """,
            f"%{email}%",
        )
        if not row and not local:
            await interaction.response.send_message("Không thấy khách này trong cache. Kiểm tra email hoặc đợi watcher sync.", ephemeral=True)
            return

        title_name = (row and row["name"]) or (local and local["name"]) or email
        embed = discord.Embed(title=f"Khách HVHN - {title_name}", color=discord.Color.green())
        embed.add_field(name="Email", value=email, inline=False)
        if row:
            embed.add_field(
                name="Sheet",
                value=(
                    f"Ngày cấp: `{row['grant_date'] or 'trống'}`\n"
                    f"Hết hạn: `{row['expiry_date'] or 'trống'}`\n"
                    f"Còn lại: `{row['days_left'] if row['days_left'] is not None else 'trống'}` ngày\n"
                    f"Trạng thái: `{row['status'] or 'trống'}`\n"
                    f"Số tài liệu: `{row['doc_count']}`"
                ),
                inline=False,
            )
        if local:
            embed.add_field(name="PC render", value=f"Có trong `clients.csv`; kho hiện có `{local['doc_count']}` tài liệu.", inline=False)
        if jobs:
            embed.add_field(
                name="Đơn gần đây",
                value="\n".join(f"#{j['id']} `{j['job_type']}` - `{j['status']}`" for j in jobs),
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="hvhn_giahan", description="Gia hạn khách từ Discord")
    async def renew_client(self, interaction: discord.Interaction, email: str, so_ngay: int = 30):
        if not await self._require_admin(interaction):
            return
        email = self._clean_email(email)
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            await interaction.response.send_message("Email không hợp lệ.", ephemeral=True)
            return
        so_ngay = max(1, min(so_ngay, 365))
        job_id = await self._enqueue("renew_client", text_payload=f"{email}\t{so_ngay}", requested_by=interaction.user.id)
        await interaction.response.send_message(
            f"Đã xếp hàng đơn #{job_id}: gia hạn `{email}` thêm `{so_ngay}` ngày.",
            ephemeral=True,
        )

    @app_commands.command(name="hvhn_baocao", description="Báo cáo nhanh hệ thống HVHN")
    async def report(self, interaction: discord.Interaction):
        if not await self._require_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        total_clients = await self.bot.db.fetchval("SELECT count(*) FROM hvhn_sheet_clients")
        active = await self.bot.db.fetchval("SELECT count(*) FROM hvhn_sheet_clients WHERE coalesce(status, '') = 'Còn hạn'")
        warning = await self.bot.db.fetchval("SELECT count(*) FROM hvhn_sheet_clients WHERE coalesce(status, '') = 'Sắp hết'")
        expired = await self.bot.db.fetchval("SELECT count(*) FROM hvhn_sheet_clients WHERE coalesce(status, '') LIKE 'Hết hạn%' OR coalesce(status, '') = 'Đã gỡ quyền'")
        docs = await self.bot.db.fetchval("SELECT count(*) FROM hvhn_sheet_docs")
        pending = await self.bot.db.fetchval("SELECT count(*) FROM hvhn_doc_jobs WHERE status = 'pending'")
        failed = await self.bot.db.fetchval("SELECT count(*) FROM hvhn_doc_jobs WHERE status IN ('error', 'download_failed', 'db_failed', 'ocr_failed')")
        soon = await self.bot.db.fetch(
            """
            SELECT name, email, days_left
            FROM hvhn_sheet_clients
            WHERE days_left IS NOT NULL AND days_left <= 3
            ORDER BY days_left ASC
            LIMIT 8
            """
        )

        embed = discord.Embed(title="Báo cáo HVHN", color=discord.Color.gold())
        embed.add_field(
            name="Khách",
            value=f"Tổng `{total_clients}` | Còn hạn `{active}` | Sắp hết `{warning}` | Hết/gỡ `{expired}`",
            inline=False,
        )
        embed.add_field(name="Tài liệu", value=f"`{docs}` tài liệu trong Sheet", inline=False)
        embed.add_field(name="Đơn hệ thống", value=f"Chờ `{pending}` | Lỗi `{failed}`", inline=False)
        if soon:
            embed.add_field(
                name="Cần chú ý",
                value="\n".join(f"{r['name']} - `{r['days_left']}` ngày - {r['email']}" for r in soon),
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(DocumentStorage(bot))
