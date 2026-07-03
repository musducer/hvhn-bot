import asyncio

import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp

YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "default_search": "auto",
    "nocheckcertificate": True,
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.queues: dict[int, list[tuple[str, str]]] = {}

    def get_queue(self, guild_id: int) -> list[tuple[str, str]]:
        return self.queues.setdefault(guild_id, [])

    async def extract_track(self, query: str) -> tuple[str, str]:
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=False))
        if "entries" in data:
            data = data["entries"][0]
        return data["title"], data["url"]

    def play_next(self, guild: discord.Guild):
        queue = self.get_queue(guild.id)
        voice_client = guild.voice_client
        if not voice_client or not queue:
            return

        title, stream_url = queue.pop(0)
        source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS)

        def after_play(error):
            if error:
                print(f"Lỗi phát nhạc: {error}")
            self.play_next(guild)

        voice_client.play(source, after=after_play)

    @app_commands.command(name="play", description="Phát nhạc từ Youtube/Soundcloud trong kênh Voice")
    async def play(self, interaction: discord.Interaction, url: str):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("❌ Bạn cần vào một kênh Voice trước.", ephemeral=True)
            return

        await interaction.response.defer()

        voice_channel = interaction.user.voice.channel
        voice_client = interaction.guild.voice_client

        print(f"[music] /play: bắt đầu kết nối voice channel {voice_channel.name}...")
        try:
            if voice_client is None:
                voice_client = await asyncio.wait_for(voice_channel.connect(), timeout=15)
            elif voice_client.channel != voice_channel:
                await asyncio.wait_for(voice_client.move_to(voice_channel), timeout=15)
        except asyncio.TimeoutError:
            print("[music] /play: TIMEOUT khi kết nối voice channel (nghi ngờ UDP bị chặn trên host).")
            await interaction.followup.send("❌ Không kết nối được vào kênh Voice (timeout). Có thể do hạ tầng máy chủ chặn UDP.")
            return
        print("[music] /play: đã kết nối voice channel thành công.")

        print(f"[music] /play: bắt đầu trích xuất audio từ URL: {url}")
        try:
            title, stream_url = await asyncio.wait_for(self.extract_track(url), timeout=20)
        except asyncio.TimeoutError:
            print("[music] /play: TIMEOUT khi trích xuất audio qua yt-dlp.")
            await interaction.followup.send("❌ Không tải được nguồn nhạc từ URL này (timeout khi trích xuất).")
            return
        except Exception as e:
            print(f"[music] /play: LỖI trích xuất audio: {e}")
            await interaction.followup.send("❌ Không tải được nguồn nhạc từ URL này.")
            return
        print(f"[music] /play: trích xuất audio thành công: {title}")

        queue = self.get_queue(interaction.guild.id)
        queue.append((title, stream_url))

        if not voice_client.is_playing() and not voice_client.is_paused():
            self.play_next(interaction.guild)
            await interaction.followup.send(f"🎶 Đang phát: **{title}**")
        else:
            await interaction.followup.send(f"➕ Đã thêm vào hàng chờ: **{title}**")

    @app_commands.command(name="skip", description="Bỏ qua bài đang phát")
    async def skip(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        if not voice_client or not voice_client.is_playing():
            await interaction.response.send_message("❌ Không có bài nào đang phát.", ephemeral=True)
            return
        voice_client.stop()
        await interaction.response.send_message("⏭️ Đã bỏ qua bài hiện tại.")

    @app_commands.command(name="stop", description="Dừng phát nhạc và rời khỏi kênh Voice")
    async def stop(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        if not voice_client:
            await interaction.response.send_message("❌ Bot không ở trong kênh Voice nào.", ephemeral=True)
            return
        self.queues[interaction.guild.id] = []
        await voice_client.disconnect()
        await interaction.response.send_message("🛑 Đã dừng nhạc và rời khỏi kênh Voice.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
