import discord
from discord.ext import commands
from discord import app_commands

from bot import DAN_LANG_ROLE


def build_guide_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📖 HƯỚNG DẪN DÙNG BOT THEN",
        description=(
            "Đọc hết trước khi bấm nút cuối để nhận quyền dùng bot. "
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
        title="🎉 Chào mừng đến với Hồn Văn - Hồn Người!",
        description=f"Rất vui được đón {member_mention}. Hoàn thành 2 bước sau để mở khóa đầy đủ:",
        color=0x2ecc71,
    )
    embed.add_field(
        name="Bước 1 — Mở khóa các kênh",
        value=f"Đọc luật ở {rules_mention}, rồi vào {verify_mention} bấm nút để nhận vai trò **Thành viên**.",
        inline=False,
    )
    embed.add_field(
        name="Bước 2 — Mở khóa quyền dùng bot Then",
        value=f"Đọc {guide_mention}, rồi bấm nút xác nhận để nhận vai trò **Dân làng Hua Tát** và bắt đầu dùng bot.",
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
            await interaction.response.send_message("🎉 Chào mừng bạn đến với NHÓM HỌC TẬP HVHN! Các kênh học thuật đã được mở khóa.", ephemeral=True)


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

        # 4. CẬP NHẬT LUẬT VÀ XÁC NHẬN
        old_rules_messages = [msg async for msg in rules_channel.history(limit=20) if msg.author == guild.me]
        for msg in old_rules_messages:
            await msg.delete()

        qa_ch = discord.utils.get(guild.text_channels, name="hỏi-đáp-bài-tập") or discord.utils.get(guild.forums, name="hỏi-đáp-bài-tập")
        share_ch = discord.utils.get(guild.text_channels, name="chia-sẻ-tài-liệu") or discord.utils.get(guild.forums, name="chia-sẻ-tài-liệu")
        discuss_ch = discord.utils.get(guild.text_channels, name="thảo-luận-văn-học")
        news_ch = discord.utils.get(guild.text_channels, name="bảng-tin-thông-báo")

        def _m(ch, fallback):
            return ch.mention if ch else fallback

        rules_embed = discord.Embed(
            title="Bộ luật chính thức - Nhóm học tập HVHN",
            description="Đọc hết trước khi tham gia thảo luận hoặc dùng lệnh bot. Vi phạm bị xử lý theo Chương V.",
            color=0x2b2d31
        )
        rules_embed.add_field(
            name="Chương I. Tôn trọng thành viên",
            value=(
                "Không công kích cá nhân, không miệt thị vùng miền, giới tính hay tôn giáo. "
                "Tranh luận về đề bài, tác phẩm hay quan điểm văn học là bình thường, nhưng giữ lập luận ở mức học thuật. "
                "Không chuyển từ phản biện ý kiến sang chỉ trích người viết."
            ),
            inline=False
        )
        rules_embed.add_field(
            name="Chương II. Đăng bài đúng kênh",
            value=(
                f"Câu hỏi bài tập đăng ở {_m(qa_ch, 'hỏi-đáp-bài-tập')}. Tài liệu, đề thi, dàn ý chia sẻ ở {_m(share_ch, 'chia-sẻ-tài-liệu')}. "
                f"Thảo luận tự do về tác phẩm dùng {_m(discuss_ch, 'thảo-luận-văn-học')}. "
                "Đăng sai kênh, quản trị viên có quyền xoá và nhắc lại mà không cần giải thích thêm."
            ),
            inline=False
        )
        rules_embed.add_field(
            name="Chương III. Dùng bot có trách nhiệm",
            value=(
                "/ask dùng để hỏi câu hỏi ẩn danh thật sự cần giải đáp, không dùng để spam hoặc trêu đùa quản trị viên. "
                "/flashcard_add và /quote_add đăng công khai cho cả server xem, nội dung phải liên quan học tập hoặc là trích dẫn có giá trị. "
                "/poll dùng cho việc chung của lớp, không lạm dụng để vote chuyện cá nhân. "
                "Phòng voice tạo qua nút Tạo Phòng Mới sẽ tự xoá khi trống, không cố giữ phòng bằng tài khoản phụ ngồi im. "
                "/timer dùng để tự canh giờ học, không phải công cụ spam thông báo trong kênh chat."
            ),
            inline=False
        )
        rules_embed.add_field(
            name="Chương IV. Cấp độ và vai trò",
            value=(
                "Nhắn tin tích luỹ XP để lên cấp. Đạt cấp 5 nhận vai trò Nhà thơ mộng mơ, cấp 10 nhận vai trò Chiến thần Nghị luận. "
                "Vai trò theo cấp độ không thể xin cấp trước hạn."
            ),
            inline=False
        )
        rules_embed.add_field(
            name="Chương V. Vi phạm và xử lý",
            value=(
                "Vi phạm nhẹ nhận cảnh cáo qua /warn, xem lại lịch sử bằng /warnings. "
                "Ba cảnh cáo trong 30 ngày dẫn đến bị mute tạm thời. "
                "Vi phạm nghiêm trọng như quấy rối, spam liên tục hoặc phát tán nội dung độc hại bị kick hoặc ban ngay, không cần đủ ba cảnh cáo trước."
            ),
            inline=False
        )
        rules_embed.add_field(
            name="Chương VI. Phòng học voice",
            value=(
                "Chủ phòng riêng có quyền mời thêm người qua /add_friend, nhưng không có quyền ép người khác rời phòng chung. "
                "Không bật nhạc to hoặc gây ồn trong phòng học chung khi có người đang tập trung."
            ),
            inline=False
        )
        rules_embed.add_field(
            name="Chương VII. Điều chỉnh luật",
            value=f"Quản trị viên có quyền cập nhật bộ luật này khi cần. Thay đổi sẽ được thông báo ở {_m(news_ch, 'bảng-tin-thông-báo')}.",
            inline=False
        )
        await rules_channel.send(embed=rules_embed)

        verify_history = [msg async for msg in verify_channel.history(limit=5)]
        if not any(msg.author == guild.me for msg in verify_history):
            verify_embed = discord.Embed(title="🔐 CỔNG KIỂM DUYỆT", description="Nhấn nút bên dưới để mở khóa toàn bộ các Kênh.", color=0x5865F2)
            await verify_channel.send(embed=verify_embed, view=VerifyView())

        await interaction.followup.send("✅ Hệ thống đã được rà soát. Đã đóng băng cấu hình kênh giống hệt yêu cầu của bạn.")


async def setup(bot: commands.Bot):
    bot.add_view(VerifyView())
    bot.add_view(BotGuideView())
    await bot.add_cog(Setup(bot))
