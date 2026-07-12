# -*- coding: utf-8 -*-
"""
Vòng đời khách HVHN trên Discord (Pha 0 + 1).

Pha 0 — mắt xích Discord <-> khách: bảng hvhn_members lưu discord_id + email + hạn.
Pha 1 — tự động hết hạn: task chạy mỗi giờ; khách hết hạn -> gỡ role + DM nhắc gia hạn +
        xếp hàng thu hồi tài liệu (remove_client cho watcher); sau ÂN HẠN -> tự kick.

Pha 2 (onboarding invite-1-lần + modal) và Pha 3 (tự nhận chuyển khoản) — xem PHASE_2_3_HANDOFF.md.
"""
import os
import re
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

# Role cấp cho khách khi kích hoạt / gia hạn, và GỠ khi hết hạn (khách hết quyền dùng Then + kho).
GRANT_ROLES = [r.strip() for r in os.getenv("HVHN_KHACH_ROLES", "Dân làng Hua Tát").split(",") if r.strip()]
GRACE_DAYS = int(os.getenv("HVHN_KHACH_GRACE_DAYS", "3"))          # số ngày ân hạn trước khi kick
DEFAULT_DURATION_DAYS = int(os.getenv("HVHN_KHACH_DURATION_DAYS", "30"))
GUILD_ID = int(os.getenv("HVHN_GUILD_ID", "0"))                    # 0 = dùng guild đầu tiên bot ở
INVITE_HOURS = int(os.getenv("HVHN_KHACH_INVITE_HOURS", "72"))
ONBOARDING_CLEANUP_HOURS = int(os.getenv("HVHN_KHACH_ONBOARDING_CLEANUP_HOURS", str(INVITE_HOURS)))
INVITE_CHANNEL_ID = int(os.getenv("HVHN_KHACH_INVITE_CHANNEL_ID", "0"))
ACTIVATE_CHANNEL_ID = int(os.getenv("HVHN_KHACH_ACTIVATE_CHANNEL_ID", "0"))
ACTIVATE_CUSTOM_ID = "hvhn_customer_activate:v1"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ==== LOGIC THUẦN (không phụ thuộc Discord/DB) — dễ test ====
def compute_new_expiry(now: datetime, current_expires, days: int) -> datetime:
    """Gia hạn cộng dồn: nếu còn hạn thì cộng tiếp từ hạn cũ, nếu đã hết thì tính từ bây giờ."""
    base = current_expires if (current_expires and current_expires > now) else now
    return base + timedelta(days=days)


def is_expired(expires_at, now: datetime) -> bool:
    return expires_at is not None and expires_at <= now


def kick_due(expires_at, now: datetime, grace_days: int) -> bool:
    return expires_at is not None and (expires_at + timedelta(days=grace_days)) <= now


def valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match((email or "").strip().lower()))


def _invite_code_uses(invite) -> tuple[str | None, int]:
    if isinstance(invite, dict):
        return invite.get("code"), int(invite.get("uses") or 0)
    return getattr(invite, "code", None), int(getattr(invite, "uses", 0) or 0)


def match_used_invite(before: dict[str, int], after: list) -> str | None:
    """Tìm invite vừa được dùng bằng diff uses.

    Discord đôi khi vẫn trả invite max_uses=1 với uses tăng, đôi khi invite biến mất khỏi
    guild.invites(). Vì vậy xử lý cả hai nhánh; nếu mơ hồ thì trả None để không gán nhầm khách.
    """
    after_map = {}
    for invite in after or []:
        code, uses = _invite_code_uses(invite)
        if code:
            after_map[code] = uses

    increased = [code for code, uses in after_map.items() if code in before and uses > int(before.get(code) or 0)]
    if len(increased) == 1:
        return increased[0]

    disappeared = [code for code in before if code not in after_map]
    if len(disappeared) == 1:
        return disappeared[0]
    return None


def _fmt_ts(dt) -> str:
    if dt is None:
        return "—"
    return f"<t:{int(dt.timestamp())}:R> (<t:{int(dt.timestamp())}:d>)"


class CustomerActivationModal(discord.ui.Modal, title="Kích hoạt trải nghiệm HVHN"):
    def __init__(self, membership: "Membership"):
        super().__init__(timeout=300)
        self.membership = membership
        self.name = discord.ui.TextInput(
            label="Họ tên",
            placeholder="Ví dụ: Nguyễn Văn A",
            min_length=2,
            max_length=120,
        )
        self.email = discord.ui.TextInput(
            label="Email nhận tài liệu",
            placeholder="ten@example.com",
            min_length=5,
            max_length=180,
        )
        self.add_item(self.name)
        self.add_item(self.email)

    async def on_submit(self, interaction: discord.Interaction):
        name = str(self.name.value).strip()
        email = str(self.email.value).strip().lower()
        if not valid_email(email):
            await interaction.response.send_message(
                "Email chưa hợp lệ. Bạn bấm lại nút **Kích hoạt trải nghiệm** và nhập lại giúp mình nhé.",
                ephemeral=True,
            )
            return
        try:
            expires, job_note, corrected = await self.membership._activate_customer(
                interaction.user, name, email, interaction.user.id
            )
        except LookupError:
            await interaction.response.send_message(
                "Mình chưa tìm thấy lượt mời đang chờ kích hoạt của bạn. Nhờ bạn báo quản trị viên kiểm tra lại invite.",
                ephemeral=True,
            )
            return

        action = "Đã cập nhật thông tin" if corrected else "Đã kích hoạt trải nghiệm"
        await interaction.response.send_message(
            f"✅ {action} cho **{name}**. Hạn dùng: {_fmt_ts(expires)}.\n"
            f"Tài liệu sẽ được cấp qua email **{email}** khi watcher trên máy chủ tài liệu xử lý hàng đợi.{job_note}",
            ephemeral=True,
        )


class CustomerActivationView(discord.ui.View):
    def __init__(self, membership: "Membership"):
        super().__init__(timeout=None)
        self.membership = membership

    @discord.ui.button(
        label="Kích hoạt trải nghiệm",
        style=discord.ButtonStyle.success,
        emoji="🎓",
        custom_id=ACTIVATE_CUSTOM_ID,
    )
    async def activate_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CustomerActivationModal(self.membership))


class Membership(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.invite_uses: dict[int, dict[str, int]] = {}
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

    async def _fetch_invite_uses(self, guild: discord.Guild) -> dict[str, int]:
        try:
            invites = await guild.invites()
        except (discord.Forbidden, discord.HTTPException) as exc:
            print(f"[debug] khach_invite_fetch_failed guild={guild.id} err={type(exc).__name__}: {exc}", flush=True)
            return {}
        result = {}
        for invite in invites:
            code, uses = _invite_code_uses(invite)
            if code:
                result[code] = uses
        return result

    async def _refresh_invite_cache(self, guild: discord.Guild) -> dict[str, int]:
        self.invite_uses[guild.id] = await self._fetch_invite_uses(guild)
        return self.invite_uses[guild.id]

    async def _invite_channel(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            return None
        if INVITE_CHANNEL_ID:
            channel = guild.get_channel(INVITE_CHANNEL_ID)
            if channel and hasattr(channel, "create_invite"):
                return channel
        channel = interaction.channel
        if channel and hasattr(channel, "create_invite"):
            return channel
        for name in ("cổng-xác-nhận", "sảnh-chào-mừng", "hướng-dẫn-dùng-bot"):
            found = discord.utils.get(guild.text_channels, name=name)
            if found:
                return found
        return guild.system_channel or (guild.text_channels[0] if guild.text_channels else None)

    def _activation_channel(self, guild: discord.Guild):
        if ACTIVATE_CHANNEL_ID:
            channel = guild.get_channel(ACTIVATE_CHANNEL_ID)
            if channel and hasattr(channel, "send"):
                return channel
        for name in ("kích-hoạt-khách", "kich-hoat-khach", "sảnh-chào-mừng", "cổng-xác-nhận"):
            found = discord.utils.get(guild.text_channels, name=name)
            if found:
                return found
        return guild.system_channel or (guild.text_channels[0] if guild.text_channels else None)

    async def _enqueue(self, job_type: str, text_payload: str, requested_by: int | None = None) -> int:
        return await self.bot.db.fetchval(
            "INSERT INTO hvhn_doc_jobs (job_type, text_payload, requested_by) VALUES ($1,$2,$3) RETURNING id",
            job_type, text_payload, requested_by,
        )

    async def _create_pending_invite(self, invite_code: str, days: int, created_by: int) -> int:
        return await self.bot.db.fetchval(
            "INSERT INTO hvhn_members(invite_code,duration_days,status,created_by) "
            "VALUES($1,$2,'pending',$3) RETURNING id",
            invite_code, days, created_by,
        )

    async def _mark_invite_joined(self, invite_code: str, discord_id: int) -> dict | None:
        return await self.bot.db.fetchrow(
            "UPDATE hvhn_members SET discord_id=$2, status='joined' "
            "WHERE id=(SELECT id FROM hvhn_members WHERE invite_code=$1 AND status='pending' ORDER BY id DESC LIMIT 1) "
            "RETURNING id, duration_days",
            invite_code, discord_id,
        )

    async def _activate_customer(self, member: discord.Member, name: str, email: str, requested_by: int | None = None):
        """joined -> active. Nếu đã active, cho bấm nút lại để sửa tên/email và đồng bộ job bù."""
        now = datetime.now(timezone.utc)
        row = await self.bot.db.fetchrow(
            "SELECT id, email, duration_days, expires_at, status FROM hvhn_members "
            "WHERE discord_id=$1 AND status IN ('joined','active') ORDER BY id DESC LIMIT 1",
            member.id,
        )
        if row is None:
            raise LookupError("no joined/active customer")

        corrected = row["status"] == "active"
        old_email = (row["email"] or "").strip().lower()
        if corrected:
            expires = row["expires_at"] or compute_new_expiry(now, None, row["duration_days"])
            await self.bot.db.execute(
                "UPDATE hvhn_members SET name=$2, email=$3, expires_at=$4, status='active', notified_expiry=FALSE WHERE id=$1",
                row["id"], name, email, expires,
            )
        else:
            expires = compute_new_expiry(now, None, row["duration_days"])
            await self.bot.db.execute(
                "UPDATE hvhn_members SET name=$2, email=$3, granted_at=$4, expires_at=$5, status='active', "
                "notified_expiry=FALSE WHERE id=$1",
                row["id"], name, email, now, expires,
            )

        await self._grant_roles(member)
        notes = []
        if corrected and old_email and old_email != email:
            jid_remove = await self._enqueue("remove_client", old_email, requested_by)
            notes.append(f" Đã xếp thu hồi email cũ #{jid_remove}.")
        if (not corrected) or old_email != email:
            jid_add = await self._enqueue("add_client", f"{name}\t{email}", requested_by)
            notes.append(f" Đã xếp cấp tài liệu #{jid_add}.")
        return expires, "".join(notes), corrected

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

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in getattr(self.bot, "guilds", None) or []:
            await self._refresh_invite_cache(guild)
        print(f"[debug] khach_invite_cache_ready guilds={len(self.invite_uses)}", flush=True)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        before = dict(self.invite_uses.get(guild.id) or {})
        after_invites = []
        try:
            after_invites = await guild.invites()
        except (discord.Forbidden, discord.HTTPException) as exc:
            print(f"[debug] khach_join_invite_fetch_failed guild={guild.id} member={member.id} err={exc}", flush=True)
            return
        used_code = match_used_invite(before, after_invites)
        self.invite_uses[guild.id] = {
            code: uses for invite in after_invites for code, uses in [_invite_code_uses(invite)] if code
        }
        if not used_code:
            return

        row = await self._mark_invite_joined(used_code, member.id)
        if row is None:
            return
        view = CustomerActivationView(self)
        message = (
            f"Chào {member.mention}, bạn đã vào server bằng invite trải nghiệm HVHN.\n\n"
            "Bấm **Kích hoạt trải nghiệm** để nhập họ tên + email nhận tài liệu. "
            "Quyền Discord được mở ngay sau khi kích hoạt; tài liệu sẽ được watcher cấp qua email khi máy xử lý tài liệu bật."
        )
        try:
            await member.send(message, view=view)
            return
        except discord.HTTPException:
            pass
        channel = self._activation_channel(guild)
        if channel:
            try:
                await channel.send(message, view=view)
            except discord.HTTPException as exc:
                print(f"[debug] khach_activation_fallback_failed member={member.id} err={exc}", flush=True)

    # ---- lệnh admin ----
    @app_commands.command(name="hvhn_moikhach", description="(Admin) Tạo invite 1 lần cho khách tự kích hoạt bằng tên/email")
    @app_commands.describe(thoi_han="Số ngày trải nghiệm", ghi_chu="Ghi chú nội bộ để admin nhớ khách này")
    async def moikhach(self, interaction: discord.Interaction, thoi_han: int = DEFAULT_DURATION_DAYS, ghi_chu: str | None = None):
        if not await self._require_admin(interaction):
            return
        if interaction.guild is None:
            await interaction.response.send_message("Lệnh này chỉ dùng trong server HVHN.", ephemeral=True)
            return
        if thoi_han <= 0 or thoi_han > 3650:
            await interaction.response.send_message("`thoi_han` phải trong khoảng 1–3650 ngày.", ephemeral=True)
            return
        channel = await self._invite_channel(interaction)
        if channel is None:
            await interaction.response.send_message("Không tìm thấy kênh để tạo invite.", ephemeral=True)
            return
        max_age = max(60, INVITE_HOURS * 3600)
        try:
            invite = await channel.create_invite(
                max_uses=1,
                max_age=max_age,
                unique=True,
                reason=f"HVHN customer invite by {interaction.user} ({interaction.user.id})",
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            await interaction.response.send_message(
                f"Không tạo được invite. Bot cần quyền Create Invite/Manage Server ở kênh {channel.mention}. Lỗi: `{exc}`",
                ephemeral=True,
            )
            return
        rid = await self._create_pending_invite(invite.code, thoi_han, interaction.user.id)
        await self._refresh_invite_cache(interaction.guild)
        note = f"\nGhi chú: {ghi_chu.strip()}" if ghi_chu else ""
        await interaction.response.send_message(
            f"✅ Đã tạo invite khách #{rid}, dùng 1 lần, hết hạn sau {INVITE_HOURS} giờ, thời hạn gói {thoi_han} ngày.\n"
            f"Link gửi khách: {invite.url}{note}\n\n"
            "Nhắc khách: vào server xong bấm **Kích hoạt trải nghiệm** để nhập họ tên/email. "
            "Tài liệu được cấp sau khi watcher xử lý hàng đợi, không phải ngay tức thì.",
            ephemeral=True,
        )

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
        await self._cleanup_stale_onboarding(guild, now)

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

    async def _cleanup_stale_onboarding(self, guild: discord.Guild, now: datetime) -> int:
        cutoff = now - timedelta(hours=ONBOARDING_CLEANUP_HOURS)
        rows = await self.bot.db.fetch(
            "SELECT id, discord_id, status FROM hvhn_members "
            "WHERE status IN ('pending','joined') AND created_at <= $1",
            cutoff,
        )
        cleaned = 0
        for r in rows:
            member = guild.get_member(r["discord_id"]) if r["discord_id"] else None
            if member and r["status"] == "joined":
                try:
                    await member.send(
                        "Invite trải nghiệm HVHN của bạn đã quá thời gian kích hoạt nên lượt này được huỷ. "
                        "Nhờ bạn liên hệ quản trị viên để nhận invite mới nếu vẫn muốn tham gia nhé."
                    )
                except discord.HTTPException:
                    pass
                try:
                    await member.kick(reason="Khách HVHN không kích hoạt sau khi vào bằng invite trải nghiệm")
                except discord.HTTPException as exc:
                    print(f"[debug] khach_stale_join_kick_failed id={r['discord_id']} err={exc}", flush=True)
            await self.bot.db.execute("UPDATE hvhn_members SET status='kicked' WHERE id=$1", r["id"])
            cleaned += 1
        if cleaned:
            print(f"[debug] khach_onboarding_cleanup cleaned={cleaned}", flush=True)
        return cleaned


async def setup(bot: commands.Bot):
    cog = Membership(bot)
    await bot.add_cog(cog)
    bot.add_view(CustomerActivationView(cog))
