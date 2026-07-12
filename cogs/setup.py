import re

import discord
from discord.ext import commands
from discord import app_commands

from bot import DAN_LANG_ROLE


# ==== BỘ LUẬT: lưu DB (server_rules), sửa bằng lệnh /luat_*; kênh được gắn link động lúc đăng ====
# Mỗi phần tử = (tiêu đề, nội dung). Số chương ("Chương I.") sinh tự động theo thứ tự. Trong nội dung
# dùng "#tên-kênh" để bot tự thay bằng mention thật lúc đăng (đổi kênh/thread không làm hỏng luật nữa).
DEFAULT_RULES: list[tuple[str, str]] = [
    (
        "Tôn trọng thành viên",
        "• Không công kích cá nhân; không miệt thị vùng miền, giới tính, tôn giáo, ngoại hình hay hoàn cảnh.\n"
        "• Tranh luận về đề bài, tác phẩm, quan điểm văn học được khuyến khích — nhưng hãy đối thoại với *ý kiến*, "
        "không tấn công *người viết*.\n"
        "• Góp ý mang tính xây dựng; không mỉa mai hay hạ thấp bài của người khác.\n"
        "• Không quấy rối, không spam/flood, không tag hàng loạt, không đăng nội dung 18+, cờ bạc, chính trị "
        "nhạy cảm hay quảng cáo.",
    ),
    (
        "Đăng bài đúng kênh",
        "• Câu hỏi bài tập → #hỏi-đáp-bài-tập (mỗi câu mở một bài/thread riêng, tiêu đề ghi rõ tác phẩm hoặc dạng đề).\n"
        "• Tài liệu, đề thi, dàn ý → #chia-sẻ-tài-liệu.\n"
        "• Cảm nhận, tranh luận, bàn về tác phẩm → #thảo-luận-văn-học.\n"
        "• Tra cứu, lưu trữ tài liệu chung → #thư-viện-tài-liệu.\n"
        "• Gõ lệnh bot để trò chuyện → #lệnh-bot-chung, tránh làm loãng kênh học.\n"
        "Đăng sai kênh, quản trị viên có quyền dời hoặc xoá và nhắc lại mà không cần giải thích thêm.",
    ),
    (
        "Dùng bot tiện ích có trách nhiệm",
        "• /ask — hỏi ẩn danh câu thật sự cần giải đáp; không spam hay trêu quản trị viên.\n"
        "• /flashcard_add, /quote_add — đăng công khai cho cả server, nội dung phải liên quan học tập hoặc là "
        "trích dẫn có giá trị.\n"
        "• /poll — dùng cho việc chung của lớp, không lạm dụng để vote chuyện cá nhân.\n"
        "• /timer, /remindme — tự canh giờ học, nhắc việc; không dùng để spam kênh.\n"
        "• Phòng voice tạo qua nút ➕ Tạo Phòng Mới sẽ tự xoá khi trống; không giữ phòng bằng tài khoản phụ ngồi im.",
    ),
    (
        "Trợ giảng Then (AI) và giới hạn lượt",
        "• Then là trợ giảng AI: hỏi bài, phân tích tác phẩm, gợi ý dàn ý/luận điểm qua /van_hoi, /ai, "
        "/goi_y_mo_bai, /luyen_de_hom_nay. Đọc kỹ #hướng-dẫn-dùng-bot trước khi dùng.\n"
        "• Mỗi Dân làng Hua Tát được hỏi Then tối đa **7 lượt / 24 giờ** và **30 lượt / 7 ngày** (tính từ lượt đầu "
        "của mỗi chu kỳ). Chỉ trừ lượt khi Then trả lời thành công; lỗi hay quá giờ không tính. Hết lượt vui lòng "
        "đợi chu kỳ reset, không lách bằng tài khoản phụ.\n"
        "• Then hỗ trợ tư duy, KHÔNG làm thay bài: đừng chép nguyên câu trả lời đem nộp.\n"
        "• AI có thể sai hoặc \"ảo giác\": luôn đối chiếu SGK và tác phẩm gốc. Bấm 👍 hoặc \"Cần sửa\" để giúp Then tốt hơn.",
    ),
    (
        "Cấp độ và vai trò",
        "• Nhắn tin và tham gia học tập để tích luỹ XP và lên cấp.\n"
        "• Đạt cấp 5 → vai trò **Nhà thơ mộng mơ**; cấp 10 → vai trò **Chiến thần Nghị luận**.\n"
        "• Vai trò theo cấp độ được trao tự động, không xin cấp trước hạn.\n"
        "• Vai trò **Diễn giả** dành cho thành viên đóng góp nổi bật, do quản trị viên trao.",
    ),
    (
        "Vi phạm và xử lý",
        "• Vi phạm nhẹ: nhắc nhở hoặc cảnh cáo qua /warn; xem lại lịch sử bằng /warnings.\n"
        "• Ba cảnh cáo trong 30 ngày → mute tạm thời.\n"
        "• Vi phạm nghiêm trọng (quấy rối, spam liên tục, phát tán nội dung độc hại, lừa đảo) → kick hoặc ban ngay, "
        "không cần đủ ba cảnh cáo trước.\n"
        "• Quyết định của quản trị viên là quyết định cuối; khiếu nại nhắn riêng, không tranh cãi công khai trong kênh.",
    ),
    (
        "Phòng học voice",
        "• Chủ phòng riêng có thể mời thêm người qua /add_friend, nhưng không được ép người khác rời phòng chung.\n"
        "• Giữ trật tự trong phòng học chung: không bật nhạc to, không gây ồn khi có người đang tập trung.\n"
        "• Ai cần yên tĩnh có thể tự tạo phòng riêng qua nút ➕ Tạo Phòng Mới.",
    ),
    (
        "Điều chỉnh luật",
        "• Quản trị viên có thể cập nhật bộ luật bằng /luat_sua, /luat_them, /luat_xoa rồi /luat_dang để đăng lại "
        "(không cần chạy /setup).\n"
        "• Thay đổi quan trọng sẽ được thông báo ở #bảng-tin-thông-báo.\n"
        "• Chưa đọc hoặc không biết luật không phải là lý do miễn trừ vi phạm.",
    ),
]

_ROMAN = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
          "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX"]


def _roman(n: int) -> str:
    return _ROMAN[n] if 0 <= n < len(_ROMAN) else str(n)


def _link_channels(guild, text: str) -> str:
    """Thay '#tên-kênh' bằng mention thật (tìm cả text/forum/voice/thread). Không thấy -> giữ nguyên
    '#tên-kênh' dạng chữ (không bao giờ hiện '# unknown')."""
    if not text:
        return text or ""
    if guild is None:
        return text

    def repl(match: "re.Match") -> str:
        slug = match.group(1)
        ch = discord.utils.get(guild.channels, name=slug)
        if ch is None:
            ch = discord.utils.get(getattr(guild, "threads", []) or [], name=slug)
        return ch.mention if ch is not None else match.group(0)

    return re.sub(r"#([0-9A-Za-zÀ-ỹĐđ_-]+)", repl, text)


def build_rules_embed(chapters: list[tuple[str, str]], guild=None) -> discord.Embed:
    embed = discord.Embed(
        title="📜 Bộ luật chính thức — Nhóm học tập Hồn Văn · Hồn Người",
        description=(
            "Đọc kỹ trước khi tham gia thảo luận hoặc dùng bot Then. Tham gia server nghĩa là bạn đồng ý tuân thủ "
            "bộ luật này. Vi phạm được xử lý theo chương \"Vi phạm và xử lý\"."
        ),
        color=0x2b2d31,
    )
    for i, (title, body) in enumerate(chapters, start=1):
        value = _link_channels(guild, body)[:1024]
        embed.add_field(name=f"Chương {_roman(i)}. {title}"[:256], value=value or "​", inline=False)
    embed.set_footer(text="Quản trị viên cập nhật luật bằng /luat_sua, /luat_them, /luat_xoa rồi /luat_dang.")
    return embed


async def load_rules(db) -> list[tuple[int, str, str]]:
    rows = await db.fetch("SELECT idx, title, body FROM server_rules ORDER BY idx")
    return [(r["idx"], r["title"], r["body"]) for r in rows]


async def seed_default_rules(db) -> None:
    async with db.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM server_rules")
            for i, (title, body) in enumerate(DEFAULT_RULES, start=1):
                await conn.execute("INSERT INTO server_rules(idx, title, body) VALUES($1,$2,$3)", i, title, body)


async def ensure_rules(db) -> list[tuple[int, str, str]]:
    rows = await load_rules(db)
    if not rows:
        await seed_default_rules(db)
        rows = await load_rules(db)
    return rows


async def _renumber_rules(db) -> None:
    """Ghi lại idx liên tục 1..N theo thứ tự hiện có (sau khi thêm/xoá)."""
    rows = await load_rules(db)
    async with db.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM server_rules")
            for i, (_, title, body) in enumerate(rows, start=1):
                await conn.execute("INSERT INTO server_rules(idx, title, body) VALUES($1,$2,$3)", i, title, body)


async def render_rules_to_channel(guild, db, rules_channel) -> None:
    rows = await ensure_rules(db)
    chapters = [(t, b) for (_, t, b) in rows]
    embed = build_rules_embed(chapters, guild)
    old = [m async for m in rules_channel.history(limit=30) if m.author == guild.me]
    for m in old:
        try:
            await m.delete()
        except discord.HTTPException:
            pass
    await rules_channel.send(embed=embed)


def build_guide_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📖 HƯỚNG DẪN DÙNG BOT THEN",
        description=(
            "Chào bạn, trước khi cùng Then rong ruổi trên những trang văn, hãy dành một chút thời gian đọc hết nội dung "
            "bên dưới rồi bấm nút cuối để nhận quyền dùng bot nhé. "
            "Hiểu đúng khả năng và giới hạn của Then giúp bạn khai thác tối đa sức mạnh AI."
        ),
        color=0x1abc9c,
    )
    embed.add_field(
        name="Then làm được gì",
        value=(
            "• Hỏi đáp, phân tích tác phẩm, tác giả, nhận định văn học.\n"
            "• Lập dàn ý chi tiết cho nghị luận xã hội và nghị luận văn học (cả mức HSG).\n"
            "• Gợi ý hệ thống luận điểm, lí lẽ, dẫn chứng và hướng phản biện.\n"
            "• Tra nhận định/trích dẫn trong kho tài liệu đã nạp."
        ),
        inline=False,
    )
    embed.add_field(
        name="Hạn chế — đọc kỹ",
        value=(
            "• AI có thể sai hoặc \"ảo giác\": luôn tự kiểm chứng lại kiến thức trước khi dùng.\n"
            "• Không chép nguyên văn trích dẫn nếu không có trong tài liệu; đừng tin tuyệt đối trí nhớ của AI.\n"
            "• Then hỗ trợ tư duy, KHÔNG làm thay bài của bạn; hãy tự viết dựa trên gợi ý.\n"
            "• Kiến thức ngoài kho tài liệu có thể thiếu chính xác."
        ),
        inline=False,
    )
    embed.add_field(
        name="Mẹo đặt prompt khai thác tối đa",
        value=(
            "• Nêu rõ dạng đề: nghị luận xã hội hay văn học, mức thường hay HSG.\n"
            "• Nói rõ bạn cần gì: dàn ý hay viết bài, phân tích khía cạnh nào.\n"
            "• Cung cấp ngữ liệu/đoạn trích khi hỏi về một văn bản cụ thể.\n"
            "• Hỏi từng bước, đào sâu dần thay vì một câu chung chung."
        ),
        inline=False,
    )
    embed.set_footer(text="Bấm nút bên dưới để xác nhận đã đọc và mở khóa quyền dùng bot.")
    return embed


def build_welcome_embed(member_mention: str, rules_mention: str, verify_mention: str, guide_mention: str) -> discord.Embed:
    embed = discord.Embed(
        title="🌾 Chào mừng đến với Hồn Văn - Hồn Người!",
        description=(
            f"Xin chào {member_mention}, thật vui vì bạn đã tìm đến ngôi nhà nhỏ này của những người yêu chữ nghĩa. 📖✨\n"
            "Ở đây có những trang văn được nâng niu, những buổi thảo luận say sưa và cả một cộng đồng luôn sẵn lòng "
            "lắng nghe từng cảm nhận của bạn. Chỉ cần 2 bước nhỏ nữa thôi là bạn có thể an tâm dạo bước khắp mọi góc nhỏ nơi đây:"
        ),
        color=0x2ecc71,
    )
    embed.add_field(
        name="🚪 Bước 1 — Mở cánh cửa vào nhà",
        value=(
            f"Ghé đọc vài dòng tâm tình ở {rules_mention} để hiểu thêm về nếp nhà mình, "
            f"rồi thong thả bước sang {verify_mention} và bấm nút để chính thức trở thành **Thành viên** nhé."
        ),
        inline=False,
    )
    embed.add_field(
        name="🕯️ Bước 2 — Thắp sáng cây bút cùng bot Then",
        value=(
            f"Đọc qua {guide_mention} để làm quen với Then — người bạn đồng hành nhỏ giúp bạn viết văn, "
            "gợi ý luận điểm và trò chuyện văn chương. Xác nhận xong, bạn sẽ nhận vai trò **Dân làng Hua Tát** "
            "và chính thức được dùng bot cùng cả nhà."
        ),
        inline=False,
    )
    return embed


class BotGuideView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Tôi đã đọc — Nhận quyền dùng bot", style=discord.ButtonStyle.success, emoji="🤖", custom_id="confirm_bot_guide")
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        role = discord.utils.get(interaction.guild.roles, name=DAN_LANG_ROLE)
        if not role:
            await interaction.response.send_message(f"Lỗi hệ thống: chưa có vai trò \"{DAN_LANG_ROLE}\". Nhờ admin chạy /setup.", ephemeral=True)
            return
        if role in interaction.user.roles:
            await interaction.response.send_message("Bạn đã có quyền dùng bot Then rồi!", ephemeral=True)
        else:
            await interaction.user.add_roles(role)
            await interaction.response.send_message(f"🤖 Đã mở khóa quyền dùng bot Then. Chào mừng \"Dân làng Hua Tát\"!", ephemeral=True)


class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Đọc Nội Quy & Nhận Quyền Truy Cập", style=discord.ButtonStyle.success, emoji="🎓", custom_id="verify_member")
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member_role = discord.utils.get(interaction.guild.roles, name="Thành viên")
        if not member_role:
            await interaction.response.send_message("Lỗi hệ thống: Không tìm thấy role 'Thành viên'.", ephemeral=True)
            return

        if member_role in interaction.user.roles:
            await interaction.response.send_message("Bạn đã là thành viên chính thức rồi!", ephemeral=True)
        else:
            await interaction.user.add_roles(member_role)
            await interaction.response.send_message("🎉 Chào mừng bạn đến với Hồn Văn - Hồn Người! Các kênh học thuật đã được mở khóa.", ephemeral=True)


class Setup(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        welcome = discord.utils.get(guild.text_channels, name="sảnh-chào-mừng")
        if welcome is None:
            return
        rules = discord.utils.get(guild.text_channels, name="luật-lệ")
        verify = discord.utils.get(guild.text_channels, name="cổng-xác-nhận")
        guide = discord.utils.get(guild.text_channels, name="hướng-dẫn-dùng-bot")
        embed = build_welcome_embed(
            member.mention,
            rules.mention if rules else "#luật-lệ",
            verify.mention if verify else "#cổng-xác-nhận",
            guide.mention if guide else "#hướng-dẫn-dùng-bot",
        )
        try:
            await welcome.send(content=member.mention, embed=embed)
        except discord.Forbidden:
            pass

    @app_commands.command(name="setup", description="Kiểm tra và khôi phục các kênh gốc (Không tạo kênh rác)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_server(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        guild = interaction.guild

        # 1. THIẾT LẬP ROLES
        roles_to_create = [
            {"name": "Quản trị viên", "color": discord.Color.red(), "hoist": True, "perms": discord.Permissions.all()},
            {"name": "Diễn giả", "color": discord.Color.gold(), "hoist": True, "perms": discord.Permissions.none()},
            {"name": "Thành viên", "color": discord.Color.blue(), "hoist": True, "perms": discord.Permissions.none()},
            {"name": "Nhà thơ mộng mơ", "color": discord.Color.purple(), "hoist": False, "perms": discord.Permissions.none()},
            {"name": "Chiến thần Nghị luận", "color": discord.Color.dark_orange(), "hoist": False, "perms": discord.Permissions.none()},
            {"name": "Dân làng Hua Tát", "color": discord.Color.teal(), "hoist": False, "perms": discord.Permissions.none()}
        ]

        created_roles = {}
        for r_data in roles_to_create:
            existing = discord.utils.get(guild.roles, name=r_data["name"])
            if not existing:
                created_roles[r_data["name"]] = await guild.create_role(name=r_data["name"], color=r_data["color"], hoist=r_data["hoist"], permissions=r_data["perms"])
            else:
                created_roles[r_data["name"]] = existing

        member_role = created_roles["Thành viên"]
        admin_role = created_roles["Quản trị viên"]
        everyone_role = guild.default_role

        # 2. OVERWRITES
        private_admin = {everyone_role: discord.PermissionOverwrite(view_channel=False), admin_role: discord.PermissionOverwrite(view_channel=True)}
        public_read_only = {everyone_role: discord.PermissionOverwrite(view_channel=True, send_messages=False, add_reactions=False)}
        member_only = {everyone_role: discord.PermissionOverwrite(view_channel=False), member_role: discord.PermissionOverwrite(view_channel=True, send_messages=True)}
        welcome_perms = {everyone_role: discord.PermissionOverwrite(view_channel=True, send_messages=False), guild.me: discord.PermissionOverwrite(send_messages=True, embed_links=True)}

        async def get_or_create_category(name, overwrites):
            cat = discord.utils.get(guild.categories, name=name)
            if not cat:
                cat = await guild.create_category(name, overwrites=overwrites)
            return cat

        async def get_or_create_text(cat, name, overwrites=None, position=None):
            channel = discord.utils.get(guild.text_channels, name=name, category=cat)
            if not channel:
                if overwrites is not None:
                    channel = await guild.create_text_channel(name, category=cat, overwrites=overwrites)
                else:
                    channel = await guild.create_text_channel(name, category=cat)
                if position is not None:
                    await channel.edit(position=position)
            return channel

        async def get_or_create_forum(cat, name, overwrites=None):
            if hasattr(guild, 'create_forum_channel'):
                channel = discord.utils.get(guild.forums, name=name, category=cat)
                if not channel:
                    if overwrites is not None:
                        channel = await guild.create_forum_channel(name, category=cat, overwrites=overwrites)
                    else:
                        channel = await guild.create_forum_channel(name, category=cat)
                return channel
            else:
                channel = discord.utils.get(guild.text_channels, name=name, category=cat)
                if not channel:
                    if overwrites is not None:
                        channel = await guild.create_text_channel(name, category=cat, overwrites=overwrites)
                    else:
                        channel = await guild.create_text_channel(name, category=cat)
                return channel

        async def get_or_create_voice(cat, name, user_limit=None):
            channel = discord.utils.get(guild.voice_channels, name=name, category=cat)
            if not channel:
                channel = await guild.create_voice_channel(name, category=cat)
                if user_limit:
                    await channel.edit(user_limit=user_limit)
            return channel

        # 3. TIẾN HÀNH TẠO KÊNH
        admin_cat = await get_or_create_category("👑 KHU VỰC QUẢN TRỊ", private_admin)
        await get_or_create_text(admin_cat, "admin-bot-commands")
        await get_or_create_text(admin_cat, "lưu-trữ-logs")
        await get_or_create_text(admin_cat, "duyệt-câu-hỏi")

        info_cat = await get_or_create_category("📌 THÔNG TIN CHUNG", public_read_only)
        await get_or_create_text(info_cat, "sảnh-chào-mừng", overwrites=welcome_perms, position=0)
        rules_channel = await get_or_create_text(info_cat, "luật-lệ")
        verify_channel = await get_or_create_text(info_cat, "cổng-xác-nhận")
        await get_or_create_text(info_cat, "bảng-tin-thông-báo")
        guide_channel = await get_or_create_text(info_cat, "hướng-dẫn-dùng-bot", overwrites=welcome_perms)
        guide_history = [msg async for msg in guide_channel.history(limit=5)]
        if not any(msg.author == guild.me for msg in guide_history):
            await guide_channel.send(embed=build_guide_embed(), view=BotGuideView())

        study_cat = await get_or_create_category("📚 GÓC HỌC TẬP - NGỮ VĂN", member_only)
        await get_or_create_forum(study_cat, "hỏi-đáp-bài-tập")
        await get_or_create_forum(study_cat, "chia-sẻ-tài-liệu")
        await get_or_create_text(study_cat, "thảo-luận-văn-học")
        await get_or_create_text(study_cat, "thư-viện-tài-liệu")
        await get_or_create_text(study_cat, "kho-tài-liệu-độc-quyền")

        bot_cat = await get_or_create_category("🤖 TRẠM BOT", member_only)
        await get_or_create_text(bot_cat, "lệnh-bot-chung")

        voice_cat = await get_or_create_category("🎙️ PHÒNG HỌC MỞ", member_only)
        await get_or_create_voice(voice_cat, "Phòng học chung 1")
        await get_or_create_voice(voice_cat, "Phòng học chung 2")
        await get_or_create_voice(voice_cat, "➕ Tạo Phòng Mới", user_limit=1)

        await get_or_create_category("🎉 SỰ KIỆN & WORKSHOP", member_only)

        # 4. CẬP NHẬT LUẬT VÀ XÁC NHẬN — dùng chung bộ luật lưu DB (sửa bằng /luat_*).
        await render_rules_to_channel(guild, self.bot.db, rules_channel)

        verify_history = [msg async for msg in verify_channel.history(limit=5)]
        if not any(msg.author == guild.me for msg in verify_history):
            verify_embed = discord.Embed(title="🔐 CỔNG KIỂM DUYỆT", description="Nhấn nút bên dưới để mở khóa toàn bộ các Kênh.", color=0x5865F2)
            await verify_channel.send(embed=verify_embed, view=VerifyView())

        await interaction.followup.send("✅ Hệ thống đã được rà soát. Đã đóng băng cấu hình kênh giống hệt yêu cầu của bạn.")

    # ==== QUẢN LÝ BỘ LUẬT (không cần chạy /setup, không tạo kênh thừa) ====
    @staticmethod
    def _rules_admin(interaction: discord.Interaction) -> bool:
        perms = getattr(interaction.user, "guild_permissions", None)
        return bool(perms and (getattr(perms, "administrator", False) or getattr(perms, "manage_guild", False)))

    async def _repost_rules(self, interaction: discord.Interaction) -> bool:
        """Đăng lại luật vào #luật-lệ hiện có (KHÔNG tạo kênh). Trả về True nếu đăng được."""
        rules_channel = discord.utils.get(interaction.guild.text_channels, name="luật-lệ")
        if rules_channel is None:
            return False
        await render_rules_to_channel(interaction.guild, self.bot.db, rules_channel)
        return True

    @app_commands.command(name="luat_dang", description="(Admin) Đăng/cập nhật lại bộ luật vào kênh luật-lệ (không tạo kênh mới)")
    async def luat_dang(self, interaction: discord.Interaction):
        if not self._rules_admin(interaction):
            await interaction.response.send_message("Cần quyền Manage Server để dùng lệnh này.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        if await self._repost_rules(interaction):
            await interaction.followup.send("✅ Đã đăng lại bộ luật vào #luật-lệ (kênh được gắn link lại theo hiện trạng).", ephemeral=True)
        else:
            await interaction.followup.send("Không tìm thấy kênh #luật-lệ. Hãy tạo kênh tên `luật-lệ` rồi thử lại.", ephemeral=True)

    @app_commands.command(name="luat_xem", description="(Admin) Xem danh sách các chương luật và số thứ tự để chỉnh")
    async def luat_xem(self, interaction: discord.Interaction):
        if not self._rules_admin(interaction):
            await interaction.response.send_message("Cần quyền Manage Server để dùng lệnh này.", ephemeral=True)
            return
        rows = await ensure_rules(self.bot.db)
        lines = [f"**{i}.** {t}  ·  {len(b)} ký tự" for (i, t, b) in rows]
        await interaction.response.send_message(
            "📜 Các chương luật hiện tại:\n" + "\n".join(lines) +
            "\n\nSửa: `/luat_sua chuong:<số> noi_dung:...` · Thêm: `/luat_them` · Xoá: `/luat_xoa chuong:<số>` · "
            "Đăng lại: `/luat_dang` · Khôi phục mặc định: `/luat_reset`.\n"
            "Trong nội dung, dùng `\\n` để xuống dòng và `#tên-kênh` để tự gắn link.",
            ephemeral=True,
        )

    @app_commands.command(name="luat_sua", description="(Admin) Sửa một chương luật rồi tự đăng lại")
    @app_commands.describe(
        chuong="Số thứ tự chương (xem bằng /luat_xem)",
        noi_dung="Nội dung mới. Dùng \\n để xuống dòng, #tên-kênh để tự gắn link.",
        tieu_de="Tiêu đề mới (bỏ trống = giữ nguyên)")
    async def luat_sua(self, interaction: discord.Interaction, chuong: int, noi_dung: str, tieu_de: str | None = None):
        if not self._rules_admin(interaction):
            await interaction.response.send_message("Cần quyền Manage Server để dùng lệnh này.", ephemeral=True)
            return
        await ensure_rules(self.bot.db)
        body = noi_dung.replace("\\n", "\n")
        if len(body) > 1024:
            await interaction.response.send_message(f"Nội dung dài {len(body)} ký tự, vượt giới hạn 1024 của một chương. Rút gọn hoặc tách thành 2 chương.", ephemeral=True)
            return
        row = await self.bot.db.fetchrow("SELECT idx FROM server_rules WHERE idx=$1", chuong)
        if row is None:
            await interaction.response.send_message(f"Không có chương số {chuong}. Dùng /luat_xem để kiểm tra.", ephemeral=True)
            return
        if tieu_de:
            await self.bot.db.execute("UPDATE server_rules SET title=$2, body=$3 WHERE idx=$1", chuong, tieu_de.strip()[:200], body)
        else:
            await self.bot.db.execute("UPDATE server_rules SET body=$2 WHERE idx=$1", chuong, body)
        await interaction.response.defer(ephemeral=True)
        posted = await self._repost_rules(interaction)
        await interaction.followup.send(
            f"✅ Đã sửa Chương {chuong}." + (" Đã đăng lại vào #luật-lệ." if posted else " (Chưa thấy #luật-lệ để đăng — chạy /luat_dang sau.)"),
            ephemeral=True)

    @app_commands.command(name="luat_them", description="(Admin) Thêm một chương luật mới vào cuối rồi tự đăng lại")
    @app_commands.describe(tieu_de="Tiêu đề chương", noi_dung="Nội dung. Dùng \\n để xuống dòng, #tên-kênh để tự gắn link.")
    async def luat_them(self, interaction: discord.Interaction, tieu_de: str, noi_dung: str):
        if not self._rules_admin(interaction):
            await interaction.response.send_message("Cần quyền Manage Server để dùng lệnh này.", ephemeral=True)
            return
        await ensure_rules(self.bot.db)
        body = noi_dung.replace("\\n", "\n")
        if len(body) > 1024:
            await interaction.response.send_message(f"Nội dung dài {len(body)} ký tự, vượt giới hạn 1024 của một chương.", ephemeral=True)
            return
        next_idx = (await self.bot.db.fetchval("SELECT COALESCE(MAX(idx),0)+1 FROM server_rules"))
        await self.bot.db.execute("INSERT INTO server_rules(idx, title, body) VALUES($1,$2,$3)", next_idx, tieu_de.strip()[:200], body)
        await interaction.response.defer(ephemeral=True)
        posted = await self._repost_rules(interaction)
        await interaction.followup.send(
            f"✅ Đã thêm Chương {next_idx}: {tieu_de.strip()}." + (" Đã đăng lại." if posted else " (Chạy /luat_dang để đăng.)"),
            ephemeral=True)

    @app_commands.command(name="luat_xoa", description="(Admin) Xoá một chương luật rồi tự đăng lại")
    @app_commands.describe(chuong="Số thứ tự chương cần xoá (xem bằng /luat_xem)")
    async def luat_xoa(self, interaction: discord.Interaction, chuong: int):
        if not self._rules_admin(interaction):
            await interaction.response.send_message("Cần quyền Manage Server để dùng lệnh này.", ephemeral=True)
            return
        await ensure_rules(self.bot.db)
        row = await self.bot.db.fetchrow("SELECT title FROM server_rules WHERE idx=$1", chuong)
        if row is None:
            await interaction.response.send_message(f"Không có chương số {chuong}.", ephemeral=True)
            return
        await self.bot.db.execute("DELETE FROM server_rules WHERE idx=$1", chuong)
        await _renumber_rules(self.bot.db)
        await interaction.response.defer(ephemeral=True)
        posted = await self._repost_rules(interaction)
        await interaction.followup.send(
            f"🗑️ Đã xoá Chương {chuong} ({row['title']})." + (" Đã đăng lại." if posted else " (Chạy /luat_dang để đăng.)"),
            ephemeral=True)

    @app_commands.command(name="luat_reset", description="(Admin) Khôi phục bộ luật về bản mặc định rồi tự đăng lại")
    async def luat_reset(self, interaction: discord.Interaction):
        if not self._rules_admin(interaction):
            await interaction.response.send_message("Cần quyền Manage Server để dùng lệnh này.", ephemeral=True)
            return
        await seed_default_rules(self.bot.db)
        await interaction.response.defer(ephemeral=True)
        posted = await self._repost_rules(interaction)
        await interaction.followup.send(
            "♻️ Đã khôi phục bộ luật mặc định." + (" Đã đăng lại." if posted else " (Chạy /luat_dang để đăng.)"),
            ephemeral=True)


async def setup(bot: commands.Bot):
    bot.add_view(VerifyView())
    bot.add_view(BotGuideView())
    await bot.add_cog(Setup(bot))
