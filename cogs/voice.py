import discord
from discord.ext import commands
from discord import app_commands


class Voice(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.custom_voice_rooms: dict[int, int] = {}

    @staticmethod
    def _owner_from_overwrites(channel: discord.VoiceChannel) -> int | None:
        if not channel.name.startswith("Phòng của "):
            return None
        default_overwrite = channel.overwrites_for(channel.guild.default_role)
        if default_overwrite.connect is not False:
            return None
        for target, overwrite in channel.overwrites.items():
            if isinstance(target, discord.Member) and not target.bot and overwrite.manage_channels is True:
                return target.id
        return None

    def _owner_id(self, channel: discord.VoiceChannel) -> int | None:
        owner_id = self.custom_voice_rooms.get(channel.id)
        if owner_id is None:
            owner_id = self._owner_from_overwrites(channel)
            if owner_id is not None:
                self.custom_voice_rooms[channel.id] = owner_id
        return owner_id

    @commands.Cog.listener()
    async def on_ready(self):
        self.custom_voice_rooms.clear()
        for guild in self.bot.guilds:
            for channel in guild.voice_channels:
                owner_id = self._owner_from_overwrites(channel)
                if owner_id is None:
                    continue
                if channel.members:
                    self.custom_voice_rooms[channel.id] = owner_id
                else:
                    try:
                        await channel.delete(reason="Dọn phòng riêng trống sau khi bot khởi động lại")
                    except discord.HTTPException:
                        pass

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        guild = member.guild

        if after.channel is not None and after.channel.name == "➕ Tạo Phòng Mới":
            existing = next(
                (channel for channel in guild.voice_channels if self._owner_id(channel) == member.id),
                None,
            )
            if existing is not None:
                await member.move_to(existing)
                return
            category = after.channel.category
            room_name = f"Phòng của {member.display_name}"

            overwrites = {
                guild.default_role: discord.PermissionOverwrite(connect=False, view_channel=True),
                member: discord.PermissionOverwrite(connect=True, manage_channels=True, manage_permissions=True, speak=True),
                guild.me: discord.PermissionOverwrite(connect=True, manage_channels=True, manage_permissions=True)
            }

            admin_role = discord.utils.get(guild.roles, name="Quản trị viên")
            if admin_role:
                overwrites[admin_role] = discord.PermissionOverwrite(connect=True, manage_channels=True)

            new_channel = await guild.create_voice_channel(name=room_name, category=category, overwrites=overwrites)
            self.custom_voice_rooms[new_channel.id] = member.id
            try:
                await member.move_to(new_channel)
            except discord.HTTPException:
                self.custom_voice_rooms.pop(new_channel.id, None)
                try:
                    await new_channel.delete(reason="Không thể chuyển chủ phòng vào phòng mới")
                except discord.HTTPException:
                    pass
                raise

        if before.channel is not None and self._owner_id(before.channel) is not None:
            if len(before.channel.members) == 0:
                try:
                    await before.channel.delete(reason="Phòng trống tự động dọn dẹp")
                finally:
                    self.custom_voice_rooms.pop(before.channel.id, None)

    @app_commands.command(name="add_friend", description="Thêm bạn vào phòng Voice riêng")
    async def add_friend(self, interaction: discord.Interaction, user: discord.Member):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("❌ Bạn chưa ở trong Voice.", ephemeral=True)
            return
        channel = interaction.user.voice.channel
        if self._owner_id(channel) != interaction.user.id:
            await interaction.response.send_message("❌ Bạn không phải chủ phòng.", ephemeral=True)
            return
        await channel.set_permissions(user, connect=True, view_channel=True)
        await interaction.response.send_message(f"✅ Đã mời {user.mention}!", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Voice(bot))
