import os
import re
import time
import uuid
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

try:
    from hvhn_batch import MIRROR_SOURCE
except Exception:
    MIRROR_SOURCE = r"D:\Mirror Files Drive\TÀI LIỆU ĐỘC QUYỀN HVHN\TÀI LIỆU ĐÃ WATERMARK CHƯA PHÂN PHỐI"


DEFAULT_MIRROR_PARENT = Path(MIRROR_SOURCE).parent
ADMIN_ROLE_ENV = "HVHN_ADMIN_ROLE"
MIRROR_PARENT_ENV = "HVHN_MIRROR_PARENT"
MAX_PDF_BYTES = 25 * 1024 * 1024


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

    @app_commands.command(name="hvhn_themtailieu", description="Thêm PDF tài liệu vào hệ thống HVHN")
    async def add_document(self, interaction: discord.Interaction, file: discord.Attachment):
        if not await self._require_admin(interaction):
            return
        if not file.filename.lower().endswith(".pdf"):
            await interaction.response.send_message("Chỉ nhận file PDF.", ephemeral=True)
            return
        if file.size and file.size > MAX_PDF_BYTES:
            await interaction.response.send_message("PDF quá lớn. Giới hạn hiện tại là 25MB.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            data = await file.read()
        except Exception as exc:
            await interaction.followup.send(f"Lỗi đọc file từ Discord: `{exc}`", ephemeral=True)
            return
        if len(data) > MAX_PDF_BYTES:
            await interaction.followup.send("PDF quá lớn. Giới hạn hiện tại là 25MB.", ephemeral=True)
            return

        job_id = await self._enqueue(
            "add_document",
            file_name=file.filename,
            file_data=data,
            requested_by=interaction.user.id,
        )

        await interaction.followup.send(
            f"Đã xếp hàng đơn #{job_id}: thêm tài liệu `{file.filename}`. Watcher sẽ watermark và phân phối cho toàn bộ khách.",
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
        failed = await self.bot.db.fetchval("SELECT count(*) FROM hvhn_doc_jobs WHERE status = 'error'")
        lines = [
            "queue DB: OK",
            f"đang chờ: {pending} | đang xử lý: {processing} | lỗi: {failed}",
            "",
            "folder local trên máy đang chạy bot:",
        ]
        lines.extend(f"{name}: {'OK' if path.exists() else 'thiếu'} - {path}" for name, path in folders.items())
        await interaction.response.send_message("\n".join(lines), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(DocumentStorage(bot))
