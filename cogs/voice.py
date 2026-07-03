import discord
from discord.ext import commands
from discord import app_commands


class Voice(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.custom_voice_rooms: dict[int, int] = {}

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        guild = member.guild

        if after.channel is not None and after.channel.name == "➕ Tạo Phòng Mới":
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
            await member.move_to(new_channel)
            self.custom_voice_rooms[new_channel.id] = member.id

        if before.channel is not None and before.channel.id in self.custom_voice_rooms:
            if len(before.channel.members) == 0:
                await before.channel.delete(reason="Phòng trống tự động dọn dẹp")
                del self.custom_voice_rooms[before.channel.id]

    @app_commands.command(name="add_friend", description="Thêm bạn vào phòng Voice riêng")
    async def add_friend(self, interaction: discord.Interaction, user: discord.Member):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("❌ Bạn chưa ở trong Voice.", ephemeral=True)
            return
        channel = interaction.user.voice.channel
        if channel.id not in self.custom_voice_rooms or self.custom_voice_rooms[channel.id] != interaction.user.id:
            await interaction.response.send_message("❌ Bạn không phải chủ phòng.", ephemeral=True)
            return
        await channel.set_permissions(user, connect=True, view_channel=True)
        await interaction.response.send_message(f"✅ Đã mời {user.mention}!", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Voice(bot))
