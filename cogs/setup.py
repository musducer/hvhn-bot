import discord
from discord.ext import commands
from discord import app_commands


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
            {"name": "Chiến thần Nghị luận", "color": discord.Color.dark_orange(), "hoist": False, "perms": discord.Permissions.none()}
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

        # 4. GỬI LẠI EMBED LUẬT VÀ XÁC NHẬN
        rules_history = [msg async for msg in rules_channel.history(limit=5)]
        if not any(msg.author == guild.me for msg in rules_history):
            rules_embed = discord.Embed(title="📜 BỘ LUẬT CHÍNH THỨC - NHÓM HỌC TẬP HVHN", color=0x2b2d31)
            rules_embed.add_field(name="Chương I", value="Tôn trọng sự đa dạng tư duy.", inline=False)
            rules_embed.add_field(name="Chương II", value="Gửi tài liệu đúng Forum phân loại.", inline=False)
            await rules_channel.send(embed=rules_embed)

        verify_history = [msg async for msg in verify_channel.history(limit=5)]
        if not any(msg.author == guild.me for msg in verify_history):
            verify_embed = discord.Embed(title="🔐 CỔNG KIỂM DUYỆT", description="Nhấn nút bên dưới để mở khóa toàn bộ các Kênh.", color=0x5865F2)
            await verify_channel.send(embed=verify_embed, view=VerifyView())

        await interaction.followup.send("✅ Hệ thống đã được rà soát. Đã đóng băng cấu hình kênh giống hệt yêu cầu của bạn.")


async def setup(bot: commands.Bot):
    bot.add_view(VerifyView())
    await bot.add_cog(Setup(bot))
