# -*- coding: utf-8 -*-
"""
Vòng đời khách HVHN trên Discord (Pha 0 + 1).

Pha 0 — mắt xích Discord <-> khách: bảng hvhn_members lưu discord_id + email + hạn.
Pha 1 — tự động hết hạn: task chạy mỗi giờ; khách hết hạn -> gỡ role + DM nhắc gia hạn +
        xếp hàng thu hồi tài liệu (remove_client cho watcher); sau ÂN HẠN -> tự kick.

Pha 2 (onboarding invite-1-lần + modal) và Pha 3 (tự nhận chuyển khoản) — xem PHASE_2_3_HANDOFF.md.
"""
import os
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

# Role cấp cho khách khi kích hoạt / gia hạn, và GỠ khi hết hạn (khách hết quyền dùng Then + kho).
GRANT_ROLES = [r.strip() for r in os.getenv("HVHN_KHACH_ROLES", "Dân làng Hua Tát").split(",") if r.strip()]
GRACE_DAYS = int(os.getenv("HVHN_KHACH_GRACE_DAYS", "3"))          # số ngày ân hạn trước khi kick
DEFAULT_DURATION_DAYS = int(os.getenv("HVHN_KHACH_DURATION_DAYS", "30"))
GUILD_ID = int(os.getenv("HVHN_GUILD_ID", "0"))                    # 0 = dùng guild đầu tiên bot ở


# ==== LOGIC THUẦN (không phụ thuộc Discord/DB) — dễ test ====
def compute_new_expiry(now: datetime, current_expires, days: int) -> datetime:
    """Gia hạn cộng dồn: nếu còn hạn thì cộng tiếp từ hạn cũ, nếu đã hết thì tính từ bây giờ."""
    base = current_expires if (current_expires and current_expires > now) else now
    return base + timedelta(days=days)


def is_expired(expires_at, now: datetime) -> bool:
    return expires_at is not None and expires_at <= now


def kick_due(expires_at, now: datetime, grace_days: int) -> bool:
    return expires_at is not None and (expires_at + timedelta(days=grace_days)) <= now


def _fmt_ts(dt) -> str:
    if dt is None:
        return "—"
    return f"<t:{int(dt.timestamp())}:R> (<t:{int(dt.timestamp())}:d>)"


class Membership(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.expiry_loop.start()

    def cog_unload(self):
        self.expiry_loop.cancel()

    # ---- tiện ích ----
    def _is_admin(self, interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member):
            return False
        role_name = os.getenv("HVHN_ADMIN_ROLE", "HVHN Admin").strip()
        has_role = any(role.name == role_name for role in interaction.user.roles)
        return has_role or interaction.user.guild_permissions.manage_guild

    async def _require_admin(self, interaction: discord.Interaction) -> bool:
        if self._is_admin(interaction):
            return True
        await interaction.response.send_message("Bạn cần role HVHN Admin hoặc quyền Manage Server.", ephemeral=True)
        return False

    def _guild(self) -> discord.Guild | None:
        if GUILD_ID:
            g = self.bot.get_guild(GUILD_ID)
            if g:
                return g
        guilds = getattr(self.bot, "guilds", None) or []
        return guilds[0] if guilds else None

    async def _enqueue(self, job_type: str, text_payload: str, requested_by: int | None = None) -> int:
        return await self.bot.db.fetchval(
            "INSERT INTO hvhn_doc_jobs (job_type, text_payload, requested_by) VALUES ($1,$2,$3) RETURNING id",
            job_type, text_payload, requested_by,
        )

    async def _grant_roles(self, member: discord.Member) -> None:
        roles = [discord.utils.get(member.guild.roles, name=r) for r in GRANT_ROLES]
        roles = [r for r in roles if r and r not in member.roles]
        if roles:
            try:
                await member.add_roles(*roles, reason="Khách HVHN kích hoạt/gia hạn")
            except discord.HTTPException as exc:
                print(f"[debug] khach_grant_roles_failed id={member.id} err={exc}", flush=True)

    async def _revoke_roles(self, member: discord.Member) -> None:
        roles = [discord.utils.get(member.guild.roles, name=r) for r in GRANT_ROLES]
        roles = [r for r in roles if r and r in member.roles]
        if roles:
            try:
                await member.remove_roles(*roles, reason="Khách HVHN hết hạn")
            except discord.HTTPException as exc:
                print(f"[debug] khach_revoke_roles_failed id={member.id} err={exc}", flush=True)

    # ---- lớp DB vòng đời ----
    async def _register(self, discord_id: int, name, email, days: int, created_by: int) -> tuple[int, datetime]:
        now = datetime.now(timezone.utc)
        row = await self.bot.db.fetchrow(
            "SELECT id, expires_at FROM hvhn_members WHERE discord_id=$1 AND status IN ('active','expired') "
            "ORDER BY id DESC LIMIT 1", discord_id)
        expires = compute_new_expiry(now, row["expires_at"] if row else None, days)
        if row:
            await self.bot.db.execute(
                "UPDATE hvhn_members SET name=COALESCE($2,name), email=COALESCE($3,email), duration_days=$4, "
                "granted_at=COALESCE(granted_at,$5), expires_at=$6, status='active', notified_expiry=FALSE WHERE id=$1",
                row["id"], name, email, days, now, expires)
            return row["id"], expires
        rid = await self.bot.db.fetchval(
            "INSERT INTO hvhn_members(discord_id,name,email,duration_days,granted_at,expires_at,status,created_by) "
            "VALUES($1,$2,$3,$4,$5,$6,'active',$7) RETURNING id",
            discord_id, name, email, days, now, expires, created_by)
        return rid, expires

    # ---- lệnh admin ----
    @app_commands.command(name="hvhn_capkhach",
                          description="(Admin) Ghi nhận/gia hạn một khách trên Discord: cấp role, đặt hạn, xếp hàng cấp tài liệu")
    @app_commands.describe(thanh_vien="Thành viên Discord của khách", so_ngay="Số ngày sử dụng",
                           email="Email nhận tài liệu (bỏ trống nếu chỉ quản lý trên Discord)", ten="Họ tên (mặc định lấy tên Discord)")
    async def capkhach(self, interaction: discord.Interaction, thanh_vien: discord.Member,
                       so_ngay: int = DEFAULT_DURATION_DAYS, email: str | None = None, ten: str | None = None):
        if not await self._require_admin(interaction):
            return
        if so_ngay <= 0 or so_ngay > 3650:
            await interaction.response.send_message("`so_ngay` phải trong khoảng 1–3650.", ephemeral=True)
            return
        email_clean = email.strip().lower() if email else None
        name = (ten or thanh_vien.display_name).strip()
        rid, expires = await self._register(thanh_vien.id, name, email_clean, so_ngay, interaction.user.id)
        await self._grant_roles(thanh_vien)
        note = ""
        if email_clean:
            jid = await self._enqueue("add_client", f"{name}\t{email_clean}", interaction.user.id)
            note = f" · đã xếp đơn cấp tài liệu #{jid} (watcher xử lý khi PC bật)"
        await interaction.response.send_message(
            f"✅ Đã ghi nhận khách **{name}** ({thanh_vien.mention}). Hết hạn {_fmt_ts(expires)}. "
            f"Hết hạn sẽ tự gỡ quyền + nhắc; sau {GRACE_DAYS} ngày ân hạn tự kick.{note}",
            ephemeral=True)

    @app_commands.command(name="hvhn_giahankhach", description="(Admin) Gia hạn một khách trên Discord (cộng dồn)")
    @app_commands.describe(thanh_vien="Thành viên khách", so_ngay="Số ngày gia hạn thêm")
    async def giahankhach(self, interaction: discord.Interaction, thanh_vien: discord.Member, so_ngay: int = 30):
        if not await self._require_admin(interaction):
            return
        if so_ngay <= 0 or so_ngay > 3650:
            await interaction.response.send_message("`so_ngay` phải trong khoảng 1–3650.", ephemeral=True)
            return
        row = await self.bot.db.fetchrow(
            "SELECT id, email, expires_at FROM hvhn_members WHERE discord_id=$1 AND status IN ('active','expired') "
            "ORDER BY id DESC LIMIT 1", thanh_vien.id)
        if row is None:
            await interaction.response.send_message("Khách này chưa có trong hệ thống. Dùng /hvhn_capkhach trước.", ephemeral=True)
            return
        now = datetime.now(timezone.utc)
        expires = compute_new_expiry(now, row["expires_at"], so_ngay)
        await self.bot.db.execute(
            "UPDATE hvhn_members SET expires_at=$2, status='active', notified_expiry=FALSE WHERE id=$1", row["id"], expires)
        await self._grant_roles(thanh_vien)
        note = ""
        if row["email"]:
            jid = await self._enqueue("renew_client", f"{row['email']}\t{so_ngay}\tngay", interaction.user.id)
            note = f" · đã xếp đơn gia hạn tài liệu #{jid}"
        await interaction.response.send_message(
            f"✅ Đã gia hạn {thanh_vien.mention} thêm {so_ngay} ngày. Hết hạn mới {_fmt_ts(expires)}.{note}", ephemeral=True)

    @app_commands.command(name="hvhn_huykhach", description="(Admin) Thu hồi quyền một khách ngay: gỡ role + thu hồi tài liệu")
    @app_commands.describe(thanh_vien="Thành viên khách", kick="Kick khỏi server luôn không?")
    async def huykhach(self, interaction: discord.Interaction, thanh_vien: discord.Member, kick: bool = False):
        if not await self._require_admin(interaction):
            return
        row = await self.bot.db.fetchrow(
            "SELECT id, email FROM hvhn_members WHERE discord_id=$1 ORDER BY id DESC LIMIT 1", thanh_vien.id)
        if row is None:
            await interaction.response.send_message("Khách này không có trong hệ thống.", ephemeral=True)
            return
        await self.bot.db.execute("UPDATE hvhn_members SET status='kicked' WHERE id=$1", row["id"])
        await self._revoke_roles(thanh_vien)
        note = ""
        if row["email"]:
            jid = await self._enqueue("remove_client", row["email"], interaction.user.id)
            note = f" · đã xếp đơn thu hồi tài liệu #{jid}"
        if kick:
            try:
                await thanh_vien.kick(reason="Khách HVHN bị thu hồi quyền")
                note += " · đã kick khỏi server"
            except discord.HTTPException as exc:
                note += f" · kick lỗi: {exc}"
        await interaction.response.send_message(f"🗑️ Đã thu hồi quyền {thanh_vien.mention}.{note}", ephemeral=True)

    @app_commands.command(name="hvhn_khach_ds", description="(Admin) Danh sách khách và hạn sử dụng")
    async def khach_ds(self, interaction: discord.Interaction):
        if not await self._require_admin(interaction):
            return
        rows = await self.bot.db.fetch(
            "SELECT discord_id, name, email, expires_at, status FROM hvhn_members "
            "WHERE status IN ('active','expired') ORDER BY expires_at NULLS LAST LIMIT 40")
        if not rows:
            await interaction.response.send_message("Chưa có khách nào đang hoạt động.", ephemeral=True)
            return
        lines = []
        for r in rows:
            tag = "🟢" if r["status"] == "active" else "🔴"
            who = f"<@{r['discord_id']}>" if r["discord_id"] else (r["email"] or r["name"] or "?")
            lines.append(f"{tag} {who} · {r['name'] or ''} · hết hạn {_fmt_ts(r['expires_at'])}")
        await interaction.response.send_message("📋 Khách HVHN:\n" + "\n".join(lines), ephemeral=True)

    @app_commands.command(name="hvhn_khach_check", description="(Admin) Chạy ngay vòng kiểm hết hạn (gỡ quyền/kick)")
    async def khach_check(self, interaction: discord.Interaction):
        if not await self._require_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        expired_n, kicked_n = await self._run_expiry_tick()
        await interaction.followup.send(
            f"Đã kiểm tra: {expired_n} khách vừa hết hạn (gỡ quyền + nhắc), {kicked_n} khách bị kick sau ân hạn.",
            ephemeral=True)

    # ---- vòng lặp tự động ----
    @tasks.loop(hours=1)
    async def expiry_loop(self):
        try:
            await self._run_expiry_tick()
        except Exception as exc:
            print(f"[debug] khach_expiry_loop_failed err={type(exc).__name__}: {exc}", flush=True)

    @expiry_loop.before_loop
    async def _before_expiry(self):
        await self.bot.wait_until_ready()

    async def _run_expiry_tick(self) -> tuple[int, int]:
        """Trả (số vừa hết hạn, số bị kick)."""
        db = getattr(self.bot, "db", None)
        guild = self._guild()
        if db is None or guild is None:
            return 0, 0
        now = datetime.now(timezone.utc)
        expired_n = kicked_n = 0

        # 1) Vừa hết hạn: gỡ quyền + DM + thu hồi tài liệu.
        for r in await db.fetch("SELECT id, discord_id, name, email, expires_at FROM hvhn_members "
                                "WHERE status='active' AND expires_at IS NOT NULL AND expires_at <= $1", now):
            await db.execute("UPDATE hvhn_members SET status='expired', notified_expiry=TRUE WHERE id=$1", r["id"])
            expired_n += 1
            member = guild.get_member(r["discord_id"]) if r["discord_id"] else None
            if member:
                await self._revoke_roles(member)
                try:
                    await member.send(
                        f"Xin chào {r['name'] or member.display_name}, gói trải nghiệm/tài liệu HVHN của bạn đã hết hạn. "
                        f"Bạn sẽ được giữ lại trong server thêm {GRACE_DAYS} ngày; gia hạn để tiếp tục dùng Then và nhận tài liệu nhé. "
                        "Liên hệ quản trị viên để gia hạn.")
                except discord.HTTPException:
                    pass
            if r["email"]:
                await self._enqueue("remove_client", r["email"])

        # 2) Quá ân hạn: kick.
        grace_cutoff = now
        for r in await db.fetch("SELECT id, discord_id, name, expires_at FROM hvhn_members WHERE status='expired'"):
            if not kick_due(r["expires_at"], now, GRACE_DAYS):
                continue
            member = guild.get_member(r["discord_id"]) if r["discord_id"] else None
            if member:
                try:
                    await member.send("Gói HVHN đã hết hạn quá thời gian ân hạn nên bạn được đưa ra khỏi server. "
                                      "Cảm ơn bạn đã trải nghiệm — quay lại bất cứ lúc nào khi muốn gia hạn nhé!")
                except discord.HTTPException:
                    pass
                try:
                    await member.kick(reason="Khách HVHN hết hạn quá ân hạn")
                except discord.HTTPException as exc:
                    print(f"[debug] khach_kick_failed id={r['discord_id']} err={exc}", flush=True)
            await db.execute("UPDATE hvhn_members SET status='kicked' WHERE id=$1", r["id"])
            kicked_n += 1
        return expired_n, kicked_n


async def setup(bot: commands.Bot):
    await bot.add_cog(Membership(bot))
