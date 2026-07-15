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
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks
from env_utils import env_int

# Role cấp cho khách khi kích hoạt / gia hạn, và GỠ khi hết hạn (khách hết quyền dùng Then + kho).
GRANT_ROLES = [r.strip() for r in os.getenv("HVHN_KHACH_ROLES", "Dân làng Hua Tát").split(",") if r.strip()]
GRACE_DAYS = env_int("HVHN_KHACH_GRACE_DAYS", 3, minimum=0, maximum=365)
DEFAULT_DURATION_DAYS = env_int("HVHN_KHACH_DURATION_DAYS", 30, minimum=1, maximum=3650)
GUILD_ID = env_int("HVHN_GUILD_ID", 0, minimum=0, maximum=2**63 - 1)
INVITE_HOURS = env_int("HVHN_KHACH_INVITE_HOURS", 72, minimum=1, maximum=8760)
ONBOARDING_CLEANUP_HOURS = env_int(
    "HVHN_KHACH_ONBOARDING_CLEANUP_HOURS", INVITE_HOURS, minimum=1, maximum=8760,
)
INVITE_CHANNEL_ID = env_int("HVHN_KHACH_INVITE_CHANNEL_ID", 0, minimum=0, maximum=2**63 - 1)
ACTIVATE_CHANNEL_ID = env_int("HVHN_KHACH_ACTIVATE_CHANNEL_ID", 0, minimum=0, maximum=2**63 - 1)
ACTIVATE_CUSTOM_ID = "hvhn_customer_activate:v1"
ACTIVATE_CHANNEL_NAME = "truy-cập-tài-liệu"
ACTIVATE_PANEL_TITLE = "📚 KÍCH HOẠT QUYỀN TRUY CẬP TÀI LIỆU"
EMAIL_LOCAL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+$")
EMAIL_DOMAIN_LABEL_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
ORDER_CODE_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


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
    clean = (email or "").strip().lower()
    if not clean or len(clean) > 254 or clean[0] in "=+-@" or clean.count("@") != 1:
        return False
    local, domain = clean.rsplit("@", 1)
    if not local or len(local) > 64 or local.startswith(".") or local.endswith(".") or ".." in local:
        return False
    labels = domain.split(".")
    return (
        bool(EMAIL_LOCAL_RE.fullmatch(local))
        and len(labels) >= 2
        and all(EMAIL_DOMAIN_LABEL_RE.fullmatch(label) for label in labels)
    )


def valid_person_name(name: str) -> bool:
    clean = (name or "").strip()
    return 2 <= len(clean) <= 120 and clean[0] not in "=+-@"


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


class CustomerActivationModal(discord.ui.Modal, title="Kích hoạt quyền truy cập tài liệu"):
    def __init__(self, membership: "Membership", default_name: str | None = None, default_email: str | None = None):
        super().__init__(timeout=300)
        self.membership = membership
        self.name = discord.ui.TextInput(
            label="Họ tên",
            placeholder="Ví dụ: Nguyễn Văn A",
            min_length=2,
            max_length=120,
            default=(default_name or None),
        )
        self.email = discord.ui.TextInput(
            label="Email nhận tài liệu",
            placeholder="ten@example.com",
            min_length=5,
            max_length=180,
            default=(default_email or None),
        )
        self.add_item(self.name)
        self.add_item(self.email)

    async def on_submit(self, interaction: discord.Interaction):
        name = str(self.name.value).strip()
        email = str(self.email.value).strip().lower()
        if not valid_email(email):
            await interaction.response.send_message(
                "Email chưa hợp lệ. Bạn bấm lại nút **Kích hoạt quyền truy cập tài liệu** và nhập lại giúp mình nhé.",
                ephemeral=True,
            )
            return
        try:
            expires, job_note, corrected = await self.membership._activate_customer(
                interaction.user.id, name, email, interaction.user.id
            )
        except LookupError:
            await interaction.response.send_message(
                "Then chưa nối được tài khoản Discord này với lượt mời của bạn. Nếu bạn vừa vào từ link HVHN, "
                "bạn thử bấm lại sau ít giây nhé; nếu vẫn chưa được, hãy nhờ quản trị viên kiểm tra giúp bạn.",
                ephemeral=True,
            )
            return
        except RuntimeError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        except Exception as exc:
            print(f"[debug] khach_activation_submit_failed user={interaction.user.id} err={type(exc).__name__}: {exc}", flush=True)
            await interaction.response.send_message(
                "Mình gặp lỗi khi kích hoạt. Thông tin bạn nhập không sai; nhờ bạn báo quản trị viên thử lại sau khi bot được cập nhật.",
                ephemeral=True,
            )
            return

        action = "Đã cập nhật thông tin" if corrected else "Đã kích hoạt quyền truy cập tài liệu"
        await interaction.response.send_message(
            f"✅ {action} cho **{name}**. Hạn dùng: {_fmt_ts(expires)}.\n"
            f"Tài liệu và quyền dùng [Then trên web](https://opal.google/open/1I_L8b8U0y7mBx6IW_MGIOAo1lgV8eXr4) "
            f"sẽ được cấp theo email **{email}** khi watcher trên máy chủ tài liệu xử lý hàng đợi. "
            f"Hãy mở Then trên web bằng đúng tài khoản Google này.{job_note}",
            ephemeral=True,
        )


class CustomerActivationView(discord.ui.View):
    def __init__(self, membership: "Membership"):
        super().__init__(timeout=None)
        self.membership = membership

    @discord.ui.button(
        label="Kích hoạt quyền truy cập tài liệu",
        style=discord.ButtonStyle.success,
        emoji="🎓",
        custom_id=ACTIVATE_CUSTOM_ID,
    )
    async def activate_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        name, email = await self.membership._prefill_for(interaction.user.id)
        await interaction.response.send_modal(CustomerActivationModal(self.membership, name, email))


class Membership(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.invite_uses: dict[int, dict[str, int]] = {}
        # Webhook có thể bị PayOS gửi lại đồng thời. Khoá này bảo đảm cùng một bot chỉ
        # tạo tối đa một invite cho một đơn, kể cả trước khi DB kịp thấy dòng pending.
        self._mint_lock = asyncio.Lock()
        # Một tài khoản có thể bấm cùng lúc ở nhiều thiết bị/tab. Khóa theo Discord
        # ID để không biến hai lần submit thành hai email nhận tài liệu.
        self._activation_locks: dict[int, asyncio.Lock] = {}
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

    def _pick_invite_channel(self, guild: discord.Guild, prefer=None):
        """Chọn kênh tạo invite từ guild (không cần interaction — dùng cho cả webhook Phase 3)."""
        if guild is None:
            return None
        if INVITE_CHANNEL_ID:
            channel = guild.get_channel(INVITE_CHANNEL_ID)
            if channel and hasattr(channel, "create_invite"):
                return channel
        if prefer is not None and hasattr(prefer, "create_invite"):
            return prefer
        for name in ("cổng-xác-nhận", "sảnh-chào-mừng", "hướng-dẫn-dùng-bot"):
            found = discord.utils.get(guild.text_channels, name=name)
            if found:
                return found
        return guild.system_channel or (guild.text_channels[0] if guild.text_channels else None)

    async def _invite_channel(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return None
        return self._pick_invite_channel(interaction.guild, prefer=interaction.channel)

    def _activation_channel(self, guild: discord.Guild):
        # Kênh cố định, dễ tìm cho người mới dùng Discord. Ưu tiên nó hơn cấu hình
        # cũ để không quay lại luồng DM/"kích-hoạt-khách" trước đây.
        portal = discord.utils.get(guild.text_channels, name=ACTIVATE_CHANNEL_NAME)
        if portal:
            return portal
        if ACTIVATE_CHANNEL_ID:
            channel = guild.get_channel(ACTIVATE_CHANNEL_ID)
            if channel and hasattr(channel, "send"):
                return channel
        for name in ("kích-hoạt-khách", "kich-hoat-khach", "cổng-xác-nhận", "sảnh-chào-mừng"):
            found = discord.utils.get(guild.text_channels, name=name)
            if found:
                return found
        return guild.system_channel or (guild.text_channels[0] if guild.text_channels else None)

    @staticmethod
    def _activation_portal_embed() -> discord.Embed:
        return discord.Embed(
            title=ACTIVATE_PANEL_TITLE,
            description=(
                "Chào bạn, nếu bạn đến với HVHN qua link mời để nhận học liệu, mình mời bạn dành một phút "
                "hoàn tất bước xác nhận ở đây.\n\n"
                "Bấm nút bên dưới; một form nhỏ sẽ hiện ra ngay trong Discord để bạn điền **Họ tên** và "
                "**Email nhận tài liệu**. Then sẽ tiếp nhận thông tin; hệ thống sẽ cấp học liệu và quyền dùng "
                "[Then trên web](https://opal.google/open/1I_L8b8U0y7mBx6IW_MGIOAo1lgV8eXr4) theo đúng email ấy. "
                "Khi mở Then trên web, bạn hãy đăng nhập bằng chính tài khoản Google đã khai báo.\n\n"
                "Bạn không cần nhắn tin riêng cho bot. Mỗi tài khoản Discord chỉ xác nhận một lần, để quyền "
                "truy cập của mỗi người luôn được bảo đảm rõ ràng."
            ),
            color=0x5865F2,
        )

    async def ensure_activation_portal(self, guild: discord.Guild):
        """Tạo đúng một cổng kích hoạt cố định và giữ nguyên các kênh cũ.

        Kênh chỉ nhận tin từ bot; mọi người vẫn bấm nút/modal được. Không xóa,
        đổi tên hoặc ghi đè quyền của bất kỳ kênh đã có nào.
        """
        channel = discord.utils.get(guild.text_channels, name=ACTIVATE_CHANNEL_NAME)
        if channel is None:
            info_category = discord.utils.get(guild.categories, name="📌 THÔNG TIN CHUNG")
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=False),
            }
            if guild.me:
                overwrites[guild.me] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, embed_links=True,
                )
            try:
                channel = await guild.create_text_channel(
                    ACTIVATE_CHANNEL_NAME,
                    category=info_category,
                    overwrites=overwrites,
                    topic="Bấm nút để điền Họ tên và Email, kích hoạt quyền truy cập tài liệu HVHN.",
                )
                print(f"[debug] khach_activation_portal_created guild={guild.id} channel={channel.id}", flush=True)
            except (discord.Forbidden, discord.HTTPException) as exc:
                print(f"[debug] khach_activation_portal_create_failed guild={guild.id} err={exc}", flush=True)
                return self._activation_channel(guild)

        panel_message = None
        try:
            async for message in channel.history(limit=25):
                if message.author != guild.me:
                    continue
                if any(embed.title == ACTIVATE_PANEL_TITLE for embed in message.embeds):
                    panel_message = message
                    break
            if panel_message:
                # Sửa ngay bảng cũ khi bot khởi động/chạy /setup, không tạo thêm bài hướng dẫn.
                await panel_message.edit(embed=self._activation_portal_embed(), view=CustomerActivationView(self))
            else:
                await channel.send(embed=self._activation_portal_embed(), view=CustomerActivationView(self))
        except (discord.Forbidden, discord.HTTPException) as exc:
            print(f"[debug] khach_activation_portal_post_failed guild={guild.id} err={exc}", flush=True)
        return channel

    async def _enqueue(self, job_type: str, text_payload: str, requested_by: int | None = None, db=None) -> int:
        store = db or self.bot.db
        return await store.fetchval(
            "INSERT INTO hvhn_doc_jobs (job_type, text_payload, requested_by) VALUES ($1,$2,$3) RETURNING id",
            job_type, text_payload, requested_by,
        )

    async def _has_add_client_job(self, email: str) -> bool:
        return bool(await self.bot.db.fetchval(
            "SELECT 1 FROM hvhn_doc_jobs "
            "WHERE job_type='add_client' AND lower(coalesce(text_payload,'')) LIKE '%' || lower($1) || '%' "
            "LIMIT 1",
            email,
        ))

    async def _create_pending_invite(self, invite_code: str, days: int, created_by: int) -> int:
        return await self.bot.db.fetchval(
            "INSERT INTO hvhn_members(invite_code,duration_days,status,created_by) "
            "VALUES($1,$2,'pending',$3) RETURNING id",
            invite_code, days, created_by,
        )

    async def _create_pending_order(self, invite_code: str, days: int, order_code: str,
                                    name: str | None, email: str | None, db=None) -> int:
        """Phase 3: dòng pending có sẵn tên/email từ form đặt mua (modal Phase 2 chỉ cần xác nhận)."""
        store = db or self.bot.db
        return await store.fetchval(
            "INSERT INTO hvhn_members(invite_code,duration_days,status,order_code,name,email) "
            "VALUES($1,$2,'pending',$3,$4,$5) RETURNING id",
            invite_code, days, order_code, name, email,
        )

    async def mint_invite_for_order(self, order_code: str, name: str, email: str, days: int) -> dict:
        """Phase 3 (Cách A): Apps Script gọi sau khi khớp chuyển khoản.

        Tạo invite-1-lần + ghi dòng pending gắn order_code. Idempotent theo order_code để chống
        double-credit: nếu đơn đã có, trả lại link cũ thay vì tạo mới. Raise ValueError với input sai.
        """
        # Một process bot chỉ cần serial hoá đoạn check-then-create. Nếu webhook retry
        # sau đó, truy vấn existing bên trong sẽ trả chính invite đã tạo.
        lock = getattr(self, "_mint_lock", None)
        if lock is None:  # hỗ trợ object khởi tạo tối giản trong test/maintenance tools
            lock = self._mint_lock = asyncio.Lock()
        async with lock:
            return await self._mint_invite_for_order_locked(order_code, name, email, days)

    async def _mint_invite_for_order_locked(self, order_code: str, name: str, email: str, days: int) -> dict:
        order_code = (order_code or "").strip()
        name = (name or "").strip()
        email = (email or "").strip().lower()
        if not ORDER_CODE_RE.fullmatch(order_code):
            raise ValueError("order_code không hợp lệ")
        if not valid_person_name(name):
            raise ValueError("Họ tên không hợp lệ")
        if not valid_email(email):
            raise ValueError("Email không hợp lệ")
        if days <= 0 or days > 3650:
            raise ValueError("duration_days phải trong khoảng 1–3650")

        store = self.bot.db
        acquire = getattr(store, "acquire", None)
        if callable(acquire):
            # asyncio.Lock chỉ bảo vệ một process. Advisory lock trong Postgres còn
            # chặn hai bot instance/deploy cùng mint một order_code.
            async with acquire() as conn:
                async with conn.transaction():
                    await conn.execute(
                        "SELECT pg_advisory_xact_lock(1213614158, hashtext($1))",
                        order_code,
                    )
                    return await self._mint_invite_for_order_with_store(
                        conn, order_code, name, email, days,
                    )
        return await self._mint_invite_for_order_with_store(store, order_code, name, email, days)

    async def _mint_invite_for_order_with_store(self, store, order_code: str,
                                                 name: str, email: str, days: int) -> dict:
        existing = await store.fetchrow(
            "SELECT invite_code, status FROM hvhn_members WHERE order_code=$1 ORDER BY id DESC LIMIT 1",
            order_code,
        )
        if existing is not None:
            code = existing["invite_code"]
            return {
                "order_code": order_code,
                "invite_url": f"https://discord.gg/{code}" if code else None,
                "reused": True,
                "status": existing["status"],
            }

        guild = self._guild()
        if guild is None:
            raise RuntimeError("Bot chưa sẵn sàng: không xác định được guild")
        channel = self._pick_invite_channel(guild)
        if channel is None:
            raise RuntimeError("Không tìm thấy kênh để tạo invite")
        max_age = max(60, INVITE_HOURS * 3600)
        invite = await channel.create_invite(
            max_uses=1, max_age=max_age, unique=True, reason=f"HVHN order {order_code}",
        )
        try:
            rid = await self._create_pending_order(invite.code, days, order_code, name, email, db=store)
        except Exception:
            # Nếu DB từ chối insert sau khi Discord đã tạo invite, thu hồi link
            # mồ côi. Lần retry sau sẽ tạo một link sạch.
            try:
                await invite.delete(reason=f"HVHN order {order_code} database rollback")
            except (AttributeError, discord.HTTPException):
                pass
            raise
        print(f"[debug] mint_invite_ok order={order_code} member_row={rid} days={days}", flush=True)
        return {
            "order_code": order_code,
            "invite_url": invite.url,
            "reused": False,
            "member_id": rid,
            "invite_hours": INVITE_HOURS,
            "duration_days": days,
        }

    async def _mark_invite_joined(self, invite_code: str, discord_id: int) -> dict | None:
        return await self.bot.db.fetchrow(
            "UPDATE hvhn_members SET discord_id=$2, status='joined', joined_at=now() "
            "WHERE id=(SELECT id FROM hvhn_members WHERE invite_code=$1 AND status='pending' ORDER BY id DESC LIMIT 1) "
            "RETURNING id, duration_days",
            invite_code, discord_id,
        )

    async def _recover_pending_order_by_email(self, discord_id: int, email: str, db=None) -> dict | None:
        """Tự chữa trường hợp bot bỏ lỡ event invite lúc khách vừa vào server.

        Chỉ áp dụng cho invite PayOS/pre-order đã có order_code và email đã chốt. UPDATE
        có điều kiện + RETURNING là thao tác claim nguyên tử: một email pending chỉ có thể
        gắn với một Discord account, kể cả hai người cùng bấm form.
        """
        store = db or self.bot.db
        return await store.fetchrow(
            "UPDATE hvhn_members SET discord_id=$2, status='joined', joined_at=now() "
            "WHERE id=(SELECT id FROM hvhn_members "
            "WHERE lower(email)=lower($1) AND status='pending' AND order_code IS NOT NULL "
            "ORDER BY id DESC LIMIT 1) "
            "RETURNING id, duration_days, name, email, order_code",
            email, discord_id,
        )

    async def _prefill_for(self, discord_id: int) -> tuple[str | None, str | None]:
        """Lấy tên/email đã có sẵn (từ form đặt mua Phase 3) để điền sẵn modal cho khách xác nhận."""
        row = await self.bot.db.fetchrow(
            "SELECT name, email FROM hvhn_members WHERE discord_id=$1 AND status IN ('joined','active') "
            "ORDER BY id DESC LIMIT 1",
            discord_id,
        )
        if row is None:
            return None, None
        return row["name"], row["email"]

    async def _member_for_customer(self, discord_id: int) -> discord.Member | None:
        guild = self._guild()
        if guild is None:
            return None
        member = guild.get_member(discord_id)
        if member is not None:
            return member
        try:
            return await guild.fetch_member(discord_id)
        except discord.HTTPException:
            return None

    @staticmethod
    async def _member_for_lifecycle(guild: discord.Guild, discord_id: int | None) -> discord.Member | None:
        """Resolve a member without treating a transient Discord error as absence."""
        if not discord_id:
            return None
        member = guild.get_member(discord_id)
        if member is not None:
            return member
        try:
            return await guild.fetch_member(discord_id)
        except discord.NotFound:
            return None

    def _activation_lock_for(self, discord_id: int) -> asyncio.Lock:
        locks = getattr(self, "_activation_locks", None)
        if locks is None:  # hỗ trợ object tối giản trong test/maintenance tools
            locks = self._activation_locks = {}
        lock = locks.get(discord_id)
        if lock is None:
            lock = locks[discord_id] = asyncio.Lock()
        return lock

    @asynccontextmanager
    async def _lifecycle_store(self, discord_id: int):
        """Serialize every state transition for one Discord customer.

        The in-process lock keeps local tasks ordered. PostgreSQL's advisory
        transaction lock extends that guarantee across overlapping deploys.
        Callers may safely keep the context open while applying Discord side
        effects; a concurrent renewal cannot overtake an older expiry action.
        """
        async with self._activation_lock_for(discord_id):
            store = self.bot.db
            acquire = getattr(store, "acquire", None)
            if callable(acquire):
                async with acquire() as conn:
                    async with conn.transaction():
                        await conn.execute(
                            "SELECT pg_advisory_xact_lock(1213614159, hashtext($1))",
                            str(discord_id),
                        )
                        yield conn
                return
            yield store

    async def _activate_customer(self, member_or_id, name: str, email: str, requested_by: int | None = None):
        """Cho mỗi Discord account kích hoạt đúng một lần, gắn với đúng một email."""
        discord_id = member_or_id if isinstance(member_or_id, int) else member_or_id.id
        async with self._lifecycle_store(discord_id) as store:
            return await self._activate_customer_once(
                member_or_id, name, email, requested_by, db=store,
            )

    async def _activate_customer_once(self, member_or_id, name: str, email: str,
                                      requested_by: int | None = None, db=None):
        discord_id = member_or_id if isinstance(member_or_id, int) else member_or_id.id
        name = (name or "").strip()
        email = (email or "").strip().lower()
        if not valid_person_name(name) or not valid_email(email):
            raise RuntimeError("Họ tên hoặc email chưa hợp lệ.")
        member = member_or_id if isinstance(member_or_id, discord.Member) else await self._member_for_customer(discord_id)
        if member is None:
            raise RuntimeError(
                "Mình đã nhận được thông tin, nhưng chưa thấy bạn còn ở trong server HVHN để cấp quyền. "
                "Bạn vào lại server bằng invite rồi bấm kích hoạt lại nhé."
            )

        async def activate_with_store(store):
            now = datetime.now(timezone.utc)
            # The active check and provisioning enqueue run in one database
            # transaction in production, guarded across bot processes.
            already_active = await store.fetchrow(
                "SELECT id, email, expires_at FROM hvhn_members "
                "WHERE discord_id=$1 AND status='active' ORDER BY id DESC LIMIT 1",
                discord_id,
            )
            if already_active is not None:
                active_email = str(already_active["email"] or "").strip().lower()
                if active_email and active_email == email:
                    if not await self._grant_roles(member):
                        raise RuntimeError(
                            "Không thể cấp đủ role khách HVHN. Hãy kiểm tra cấu hình role/quyền bot rồi thử lại."
                        )
                    return already_active["expires_at"], None, True
                raise RuntimeError(
                    "Tài khoản Discord này đã kích hoạt quyền truy cập tài liệu rồi. "
                    "Để bảo vệ quyền học liệu, mỗi tài khoản chỉ được liên kết với một email; "
                    "nếu cần sửa thông tin, hãy liên hệ quản trị viên."
                )

            row = await store.fetchrow(
                "SELECT id, email, duration_days, expires_at, status FROM hvhn_members "
                "WHERE discord_id=$1 AND status='joined' ORDER BY id DESC LIMIT 1",
                discord_id,
            )
            if row is None:
                recovered = await self._recover_pending_order_by_email(discord_id, email, db=store)
                if recovered is None:
                    raise LookupError("no joined/active customer")
                print(
                    f"[debug] khach_activation_recovered_pending discord_id={discord_id} "
                    f"order={recovered.get('order_code') if hasattr(recovered, 'get') else 'unknown'}",
                    flush=True,
                )
                row = await store.fetchrow(
                    "SELECT id, email, duration_days, expires_at, status FROM hvhn_members "
                    "WHERE discord_id=$1 AND status='joined' ORDER BY id DESC LIMIT 1",
                    discord_id,
                )
                if row is None:
                    raise LookupError("pending claim did not produce joined customer")
            bound_email = (row["email"] or "").strip().lower()
            if bound_email and email != bound_email:
                raise RuntimeError(
                    "Lượt mời này đã được gắn với một email khác. Để bảo vệ quyền học liệu, "
                    "bạn hãy dùng đúng email đã đăng ký hoặc liên hệ quản trị viên."
                )

            if not await self._grant_roles(member):
                raise RuntimeError(
                    "Không thể cấp đủ role khách HVHN. Hãy kiểm tra cấu hình role/quyền bot rồi thử lại."
                )

            expires = compute_new_expiry(now, None, row["duration_days"])
            activated = await store.fetchrow(
                "UPDATE hvhn_members SET name=$2, email=$3, granted_at=$4, expires_at=$5, status='active', "
                "notified_expiry=FALSE WHERE id=$1 AND status='joined' RETURNING id",
                row["id"], name, email, now, expires,
            )
            if activated is None:
                raise RuntimeError("Lượt kích hoạt vừa thay đổi trạng thái; vui lòng bấm lại để kiểm tra.")
            jid_add = await self._enqueue("add_client", f"{name}\t{email}", requested_by, db=store)
            return expires, jid_add, False

        expires, jid_add, already_active = await activate_with_store(db or self.bot.db)

        if already_active:
            return expires, " Quyền hiện có đã được kiểm tra lại; hệ thống không tạo đơn trùng.", True
        return expires, f" Đã xếp cấp tài liệu #{jid_add}.", False

    async def _grant_roles(self, member: discord.Member) -> bool:
        resolved = [(name, discord.utils.get(member.guild.roles, name=name)) for name in GRANT_ROLES]
        missing = [name for name, role in resolved if role is None]
        if missing:
            print(
                f"[debug] khach_grant_roles_missing id={member.id} roles={','.join(missing)}",
                flush=True,
            )
            return False
        roles = [role for _, role in resolved if role not in member.roles]
        if roles:
            try:
                await member.add_roles(*roles, reason="Khách HVHN kích hoạt/gia hạn")
            except discord.HTTPException as exc:
                print(f"[debug] khach_grant_roles_failed id={member.id} err={exc}", flush=True)
                return False
        return True

    async def _revoke_roles(self, member: discord.Member) -> bool:
        roles = [discord.utils.get(member.guild.roles, name=r) for r in GRANT_ROLES]
        roles = [r for r in roles if r and r in member.roles]
        if roles:
            try:
                await member.remove_roles(*roles, reason="Khách HVHN hết hạn")
            except discord.HTTPException as exc:
                print(f"[debug] khach_revoke_roles_failed id={member.id} err={exc}", flush=True)
                return False
        return True

    # ---- lớp DB vòng đời ----
    async def _register(self, discord_id: int, name, email, days: int, created_by: int) -> tuple[int, datetime]:
        async with self._lifecycle_store(discord_id) as store:
            return await self._register_with_store(store, discord_id, name, email, days, created_by)

    async def _register_with_store(self, store, discord_id: int, name, email,
                                   days: int, created_by: int) -> tuple[int, datetime]:
        now = datetime.now(timezone.utc)
        row = await store.fetchrow(
            "SELECT id, expires_at FROM hvhn_members WHERE discord_id=$1 AND status IN ('active','expired') "
            "ORDER BY id DESC LIMIT 1", discord_id)
        expires = compute_new_expiry(now, row["expires_at"] if row else None, days)
        if row:
            await store.execute(
                "UPDATE hvhn_members SET name=COALESCE($2,name), email=COALESCE($3,email), duration_days=$4, "
                "granted_at=COALESCE(granted_at,$5), expires_at=$6, status='active', notified_expiry=FALSE WHERE id=$1",
                row["id"], name, email, days, now, expires)
            return row["id"], expires
        rid = await store.fetchval(
            "INSERT INTO hvhn_members(discord_id,name,email,duration_days,granted_at,expires_at,status,created_by) "
            "VALUES($1,$2,$3,$4,$5,$6,'active',$7) RETURNING id",
            discord_id, name, email, days, now, expires, created_by)
        return rid, expires

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in getattr(self.bot, "guilds", None) or []:
            await self._refresh_invite_cache(guild)
            await self.ensure_activation_portal(guild)
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
        channel = await self.ensure_activation_portal(guild)
        message = (
            f"Chào {member.mention}, rất vui vì bạn đã đến với HVHN.\n\n"
            "Bạn có thể bấm **Kích hoạt quyền truy cập tài liệu** ngay bên dưới để điền Họ tên và Email. "
            "Then sẽ xác nhận quyền của bạn; học liệu và quyền dùng Then trên web sẽ được cấp theo email bạn đã đăng ký."
        )
        if channel:
            try:
                await channel.send(message, view=CustomerActivationView(self))
            except discord.HTTPException as exc:
                print(f"[debug] khach_activation_channel_post_failed member={member.id} err={exc}", flush=True)

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
            "Nhắc khách: vào #truy-cập-tài-liệu rồi bấm **Kích hoạt quyền truy cập tài liệu** để nhập họ tên/email. "
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
        if email_clean and not valid_email(email_clean):
            await interaction.response.send_message("Email không hợp lệ.", ephemeral=True)
            return
        if not valid_person_name(name):
            await interaction.response.send_message("Họ tên phải dài từ 2 đến 120 ký tự.", ephemeral=True)
            return
        note = ""
        grant_failed = False
        async with self._lifecycle_store(thanh_vien.id) as store:
            grant_failed = not await self._grant_roles(thanh_vien)
            if not grant_failed:
                _, expires = await self._register_with_store(
                    store, thanh_vien.id, name, email_clean, so_ngay, interaction.user.id,
                )
                if email_clean:
                    jid = await self._enqueue(
                        "add_client", f"{name}\t{email_clean}", interaction.user.id, db=store,
                    )
                    note = f" · đã xếp đơn cấp tài liệu #{jid} (watcher xử lý khi PC bật)"
        if grant_failed:
            await interaction.response.send_message(
                "Không cấp được đủ role khách. Hệ thống chưa ghi nhận hay xếp đơn tài liệu; "
                "hãy kiểm tra tên role và quyền bot rồi thử lại.",
                ephemeral=True,
            )
            return
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
        note = ""
        grant_failed = False
        async with self._lifecycle_store(thanh_vien.id) as store:
            row = await store.fetchrow(
                "SELECT id, email, expires_at FROM hvhn_members WHERE discord_id=$1 "
                "AND status IN ('active','expired') ORDER BY id DESC LIMIT 1",
                thanh_vien.id,
            )
            if row is not None:
                grant_failed = not await self._grant_roles(thanh_vien)
                if not grant_failed:
                    now = datetime.now(timezone.utc)
                    expires = compute_new_expiry(now, row["expires_at"], so_ngay)
                    await store.execute(
                        "UPDATE hvhn_members SET expires_at=$2, status='active', notified_expiry=FALSE WHERE id=$1",
                        row["id"], expires,
                    )
                    if row["email"]:
                        jid = await self._enqueue(
                            "renew_client", f"{row['email']}\t{so_ngay}\tngay",
                            interaction.user.id, db=store,
                        )
                        note = f" · đã xếp đơn gia hạn tài liệu #{jid}"
        if row is None:
            await interaction.response.send_message("Khách này chưa có trong hệ thống. Dùng /hvhn_capkhach trước.", ephemeral=True)
            return
        if grant_failed:
            await interaction.response.send_message(
                "Không cấp được đủ role khách nên hệ thống chưa gia hạn hay xếp đơn tài liệu. "
                "Hãy kiểm tra tên role và quyền bot rồi thử lại.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            f"✅ Đã gia hạn {thanh_vien.mention} thêm {so_ngay} ngày. Hết hạn mới {_fmt_ts(expires)}.{note}", ephemeral=True)

    @app_commands.command(name="hvhn_huykhach", description="(Admin) Thu hồi quyền một khách ngay: gỡ role + thu hồi tài liệu")
    @app_commands.describe(thanh_vien="Thành viên khách", kick="Kick khỏi server luôn không?")
    async def huykhach(self, interaction: discord.Interaction, thanh_vien: discord.Member, kick: bool = False):
        if not await self._require_admin(interaction):
            return
        note = ""
        revoke_failed = False
        async with self._lifecycle_store(thanh_vien.id) as store:
            row = await store.fetchrow(
                "SELECT id, email FROM hvhn_members WHERE discord_id=$1 ORDER BY id DESC LIMIT 1",
                thanh_vien.id,
            )
            if row is not None:
                revoke_failed = not await self._revoke_roles(thanh_vien)
                if not revoke_failed:
                    await store.execute("UPDATE hvhn_members SET status='kicked' WHERE id=$1", row["id"])
                    if row["email"]:
                        jid = await self._enqueue(
                            "remove_client", row["email"], interaction.user.id, db=store,
                        )
                        note = f" · đã xếp đơn thu hồi tài liệu #{jid}"
                    if kick:
                        try:
                            await thanh_vien.kick(reason="Khách HVHN bị thu hồi quyền")
                            note += " · đã kick khỏi server"
                        except discord.HTTPException as exc:
                            note += f" · kick lỗi: {exc}"
        if row is None:
            await interaction.response.send_message("Khách này không có trong hệ thống.", ephemeral=True)
            return
        if revoke_failed:
            await interaction.response.send_message(
                "Không gỡ được role khách nên hệ thống chưa đổi trạng thái hay thu hồi tài liệu. Hãy kiểm tra quyền bot rồi thử lại.",
                ephemeral=True,
            )
            return
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
            member = None
            current = None
            lock_id = r["discord_id"] or -int(r["id"])
            try:
                async with self._lifecycle_store(lock_id) as store:
                    current = await store.fetchrow(
                        "SELECT id, discord_id, name, email, expires_at FROM hvhn_members "
                        "WHERE id=$1 AND status='active' AND expires_at <= $2 FOR UPDATE",
                        r["id"], now,
                    )
                    if current is None:
                        continue
                    member = await self._member_for_lifecycle(guild, current["discord_id"])
                    if member is not None and not await self._revoke_roles(member):
                        continue
                    claimed = await store.fetchrow(
                        "UPDATE hvhn_members SET status='expired', notified_expiry=TRUE "
                        "WHERE id=$1 AND status='active' AND expires_at <= $2 RETURNING id",
                        current["id"], now,
                    )
                    if claimed is None:
                        continue
                    if current["email"]:
                        await self._enqueue("remove_client", current["email"], db=store)
                    if member is not None:
                        try:
                            await member.send(
                                f"Xin chào {current['name'] or member.display_name}, gói trải nghiệm/tài liệu HVHN của bạn đã hết hạn. "
                                f"Bạn sẽ được giữ lại trong server thêm {GRACE_DAYS} ngày; gia hạn để tiếp tục dùng Then và nhận tài liệu nhé. "
                                "Liên hệ quản trị viên để gia hạn."
                            )
                        except discord.HTTPException:
                            pass
            except discord.HTTPException as exc:
                print(f"[debug] khach_expiry_member_lookup_failed id={r['discord_id']} err={exc}", flush=True)
                continue
            expired_n += 1

        # 2) Quá ân hạn: kick.
        for r in await db.fetch("SELECT id, discord_id, name, expires_at FROM hvhn_members WHERE status='expired'"):
            if not kick_due(r["expires_at"], now, GRACE_DAYS):
                continue
            member = None
            lock_id = r["discord_id"] or -int(r["id"])
            try:
                async with self._lifecycle_store(lock_id) as store:
                    current = await store.fetchrow(
                        "SELECT id, discord_id FROM hvhn_members WHERE id=$1 AND status='expired' "
                        "AND expires_at <= $2 FOR UPDATE",
                        r["id"], now - timedelta(days=GRACE_DAYS),
                    )
                    if current is None:
                        continue
                    member = await self._member_for_lifecycle(guild, current["discord_id"])
                    if member is not None:
                        try:
                            await member.kick(reason="Khách HVHN hết hạn quá ân hạn")
                        except discord.HTTPException as exc:
                            print(f"[debug] khach_kick_failed id={r['discord_id']} err={exc}", flush=True)
                            continue
                    claimed = await store.fetchrow(
                        "UPDATE hvhn_members SET status='kicked' "
                        "WHERE id=$1 AND status='expired' AND expires_at <= $2 RETURNING id",
                        current["id"], now - timedelta(days=GRACE_DAYS),
                    )
                    if claimed is None:
                        continue
            except discord.HTTPException as exc:
                print(f"[debug] khach_kick_member_lookup_failed id={r['discord_id']} err={exc}", flush=True)
                continue
            if member is not None:
                try:
                    await member.send("Gói HVHN đã hết hạn quá thời gian ân hạn nên bạn được đưa ra khỏi server. "
                                      "Cảm ơn bạn đã trải nghiệm — quay lại bất cứ lúc nào khi muốn gia hạn nhé!")
                except discord.HTTPException:
                    pass
            kicked_n += 1
        return expired_n, kicked_n

    async def _cleanup_stale_onboarding(self, guild: discord.Guild, now: datetime) -> int:
        cutoff = now - timedelta(hours=ONBOARDING_CLEANUP_HOURS)
        rows = await self.bot.db.fetch(
            "SELECT id, discord_id, status FROM hvhn_members "
            "WHERE (status='pending' AND created_at <= $1) "
            "OR (status='joined' AND COALESCE(joined_at, created_at) <= $1)",
            cutoff,
        )
        cleaned = 0
        for r in rows:
            member = None
            lock_id = r["discord_id"] or -int(r["id"])
            try:
                async with self._lifecycle_store(lock_id) as store:
                    current = await store.fetchrow(
                        "SELECT id, discord_id, status FROM hvhn_members WHERE id=$1 AND status=$2 "
                        "AND ((status='pending' AND created_at <= $3) OR "
                        "(status='joined' AND COALESCE(joined_at, created_at) <= $3)) FOR UPDATE",
                        r["id"], r["status"], cutoff,
                    )
                    if current is None:
                        continue
                    if current["status"] == "joined":
                        member = await self._member_for_lifecycle(guild, current["discord_id"])
                        if member is not None:
                            try:
                                await member.kick(
                                    reason="Khách HVHN không kích hoạt sau khi vào bằng invite trải nghiệm",
                                )
                            except discord.HTTPException as exc:
                                print(
                                    f"[debug] khach_stale_join_kick_failed id={r['discord_id']} err={exc}",
                                    flush=True,
                                )
                                continue
                    claimed = await store.fetchrow(
                        "UPDATE hvhn_members SET status='kicked' "
                        "WHERE id=$1 AND status=$2 RETURNING id",
                        current["id"], current["status"],
                    )
                    if claimed is None:
                        continue
            except discord.HTTPException as exc:
                print(f"[debug] khach_stale_member_lookup_failed id={r['discord_id']} err={exc}", flush=True)
                continue
            if member is not None:
                try:
                    await member.send(
                        "Invite trải nghiệm HVHN của bạn đã quá thời gian kích hoạt nên lượt này được huỷ. "
                        "Nhờ bạn liên hệ quản trị viên để nhận invite mới nếu vẫn muốn tham gia nhé."
                    )
                except discord.HTTPException:
                    pass
            cleaned += 1
        if cleaned:
            print(f"[debug] khach_onboarding_cleanup cleaned={cleaned}", flush=True)
        return cleaned


async def setup(bot: commands.Bot):
    cog = Membership(bot)
    await bot.add_cog(cog)
    bot.add_view(CustomerActivationView(cog))
