"""Aeon Radio Bot - Discord wiring. Run: python bot.py
Plays internet radio into a voice channel. Needs ffmpeg on this PC
and DISCORD_TOKEN in .env (see ../SETUP.md)."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

import discord
from discord import app_commands

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import clamp_volume, format_station_list, search_stations, top_stations  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("aeon-radio")


def load_env():
    env_file = Path(__file__).resolve().parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


load_env()
TOKEN = os.environ.get("DISCORD_TOKEN", "")
FFMPEG_OPTS = {"before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
               "options": "-vn"}


class RadioState:
    def __init__(self):
        self.now: dict[int, dict] = {}      # guild_id -> station
        self.queue: dict[int, list] = {}    # guild_id -> [station]
        self.volume: dict[int, float] = {}


class RadioBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        self.state = RadioState()

    async def setup_hook(self):
        await self.tree.sync()
        log.info("slash commands synced")

    async def on_ready(self):
        log.info("Logged in as %s", self.user)


bot = RadioBot()


async def _ensure_voice(interaction: discord.Interaction) -> discord.VoiceClient | None:
    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.followup.send("Join a voice channel first, then ask me to play something.", ephemeral=True)
        return None
    channel = interaction.user.voice.channel
    vc = interaction.guild.voice_client
    if vc is None:
        vc = await channel.connect()
    elif vc.channel != channel:
        await vc.move_to(channel)
    return vc


def _play_next(guild: discord.Guild):
    vc = guild.voice_client
    if vc is None:
        return
    state = bot.state
    queue = state.queue.get(guild.id, [])
    if not queue:
        state.now.pop(guild.id, None)
        return
    station = queue.pop(0)
    state.now[guild.id] = station
    source = discord.FFmpegPCMAudio(station["url"], **FFMPEG_OPTS)
    source = discord.PCMVolumeTransformer(source, volume=state.volume.get(guild.id, 0.5))
    vc.play(source, after=lambda e: bot.loop.call_soon_threadsafe(
        lambda: asyncio.create_task(_after_track(guild))))


async def _after_track(guild: discord.Guild):
    _play_next(guild)


async def _enqueue_and_play(interaction, station):
    vc = await _ensure_voice(interaction)
    if vc is None:
        return
    bot.state.queue.setdefault(interaction.guild.id, []).append(station)
    if not vc.is_playing():
        _play_next(interaction.guild)
        await interaction.followup.send(f"▶️ Now playing **{station['name']}**")
    else:
        await interaction.followup.send(f"➕ Queued **{station['name']}**")


@bot.tree.command(name="search", description="Search radio stations by name or genre")
@app_commands.describe(query="e.g. jazz, lofi, soma, news")
async def search_cmd(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    stations = await asyncio.to_thread(search_stations, query, 10)
    text = format_station_list(stations)
    text += "\n\nPlay one with `/play <name>`."
    await interaction.followup.send(text[:1990])


@bot.tree.command(name="stations", description="Top voted radio stations right now")
async def stations_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    stations = await asyncio.to_thread(top_stations, 10)
    await interaction.followup.send(format_station_list(stations)[:1990])


@bot.tree.command(name="play", description="Play the first station matching your search")
@app_commands.describe(query="Station name or genre, e.g. 'SomaFM Groove Salad' or 'jazz'")
async def play_cmd(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    stations = await asyncio.to_thread(search_stations, query, 1)
    if not stations:
        await interaction.followup.send("No playable station found for that. Try `/search` first.")
        return
    await _enqueue_and_play(interaction, stations[0])


@bot.tree.command(name="nowplaying", description="What is playing right now")
async def now_cmd(interaction: discord.Interaction):
    station = bot.state.now.get(interaction.guild.id)
    if not station:
        await interaction.response.send_message("Nothing is playing. Try `/play jazz`.")
    else:
        q = len(bot.state.queue.get(interaction.guild.id, []))
        await interaction.response.send_message(f"🎵 **{station['name']}**" + (f" — {q} more in queue" if q else ""))


@bot.tree.command(name="stop", description="Stop the radio and clear the queue")
async def stop_cmd(interaction: discord.Interaction):
    bot.state.queue[interaction.guild.id] = []
    bot.state.now.pop(interaction.guild.id, None)
    vc = interaction.guild.voice_client
    if vc and vc.is_playing():
        vc.stop()
    await interaction.response.send_message("⏹️ Stopped.")


@bot.tree.command(name="leave", description="Leave the voice channel")
async def leave_cmd(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc:
        await vc.disconnect()
    bot.state.now.pop(interaction.guild.id, None)
    await interaction.response.send_message("👋 Left the voice channel.")


@bot.tree.command(name="volume", description="Set volume 0-100")
@app_commands.describe(level="0 to 100")
async def volume_cmd(interaction: discord.Interaction, level: int):
    vol = clamp_volume(level)
    bot.state.volume[interaction.guild.id] = vol
    vc = interaction.guild.voice_client
    if vc and vc.source and hasattr(vc.source, "volume"):
        vc.source.volume = vol
    await interaction.response.send_message(f"🔊 Volume set to {round(vol * 100)}% (applies fully to the next station).")


if __name__ == "__main__":
    if not TOKEN:
        print("DISCORD_TOKEN is missing. Copy .env.example to .env and paste your Radio Bot token in it.")
        sys.exit(1)
    bot.run(TOKEN)
