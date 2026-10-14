"""Aeon MC Bot - Discord wiring. Run: python bot.py
Checks Minecraft Java server status (players, MOTD, version, ping).
Needs DISCORD_TOKEN in .env (see ../SETUP.md). Servers behind a
playit.gg tunnel work fine - save the tunnel address."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

import discord
from discord import app_commands

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import ServerBook, parse_address, ping_server  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("aeon-mc")

BASE = Path(__file__).resolve().parent


def load_env():
    env_file = BASE / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


load_env()
TOKEN = os.environ.get("DISCORD_TOKEN", "")
book = ServerBook(BASE / "data" / "servers.json")
WATCH_FILE = BASE / "data" / "watch.json"


def load_watch() -> dict:
    try:
        return json.loads(WATCH_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_watch(data: dict):
    WATCH_FILE.parent.mkdir(exist_ok=True)
    WATCH_FILE.write_text(json.dumps(data, indent=1), encoding="utf-8")


class MCBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        self._watch_task: asyncio.Task | None = None
        self._last_state: dict[str, bool] = {}

    async def setup_hook(self):
        await self.tree.sync()
        self._watch_task = asyncio.create_task(self._watch_loop())
        log.info("slash commands synced")

    async def on_ready(self):
        log.info("Logged in as %s", self.user)

    async def _watch_loop(self):
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                watch = load_watch()
                for gid, cfg in list(watch.items()):
                    host, port = cfg["host"], cfg["port"]
                    key = f"{gid}:{host}:{port}"
                    try:
                        await asyncio.to_thread(ping_server, host, port, 5.0)
                        online = True
                    except Exception:
                        online = False
                    was = self._last_state.get(key)
                    self._last_state[key] = online
                    if was is not None and was != online:
                        channel = self.get_channel(cfg["channel_id"])
                        if channel:
                            label = cfg.get("label", host)
                            msg = (f"🟢 **{label}** is back **ONLINE**." if online
                                   else f"🔴 **{label}** just went **OFFLINE**.")
                            await channel.send(msg)
            except Exception:
                log.exception("watch loop error")
            await asyncio.sleep(300)  # check every 5 minutes


bot = MCBot()


def status_embed(label: str, status: dict | None) -> discord.Embed:
    if status is None:
        return discord.Embed(title=f"🔴 {label} — OFFLINE",
                             description="The server did not answer. It may be off, starting up, or the address changed.",
                             color=0xC0392B)
    emb = discord.Embed(title=f"🟢 {label} — ONLINE", description=status["motd"][:300], color=0x27AE60)
    emb.add_field(name="Players", value=f"{status['online']} / {status['max']}")
    emb.add_field(name="Version", value=status["version"])
    emb.add_field(name="Ping", value=f"{status.get('latency_ms', '?')} ms")
    if status["players"]:
        emb.add_field(name="Who's on", value=", ".join(status["players"][:20])[:1024], inline=False)
    return emb


@bot.tree.command(name="status", description="Check a Minecraft server (saved label or host address)")
@app_commands.describe(server="A saved label like 'horror', or an address like mc.example.com:25565")
async def status_cmd(interaction: discord.Interaction, server: str):
    await interaction.response.defer()
    saved = book.get(interaction.guild.id, server)
    if saved:
        host, port, label = saved["host"], saved["port"], server
    else:
        try:
            host, port = parse_address(server)
            label = server
        except ValueError:
            await interaction.followup.send("That doesn't look like an address, and no saved server has that label. See `/servers`.")
            return
    try:
        status = await asyncio.to_thread(ping_server, host, port, 6.0)
    except Exception:
        status = None
    await interaction.followup.send(embed=status_embed(label, status))


@bot.tree.command(name="addserver", description="Save a Minecraft server with a short label")
@app_commands.describe(label="Short name, e.g. horror", address="Host or host:port, e.g. fried-checked.tun.ply.gg")
async def add_cmd(interaction: discord.Interaction, label: str, address: str):
    try:
        book.add(interaction.guild.id, label, address)
    except ValueError:
        await interaction.response.send_message("That address doesn't look right.", ephemeral=True)
        return
    await interaction.response.send_message(f"✅ Saved **{label}** → `{address}`. Check it with `/status {label}`.")


@bot.tree.command(name="removeserver", description="Remove a saved Minecraft server")
async def remove_cmd(interaction: discord.Interaction, label: str):
    ok = book.remove(interaction.guild.id, label)
    await interaction.response.send_message("🗑️ Removed." if ok else "No saved server with that label.", ephemeral=not ok)


@bot.tree.command(name="servers", description="List saved Minecraft servers")
async def servers_cmd(interaction: discord.Interaction):
    servers = book.list(interaction.guild.id)
    if not servers:
        await interaction.response.send_message("No saved servers yet. Add one with `/addserver`.")
        return
    lines = [f"**{label}** — `{s['host']}:{s['port']}`" for label, s in servers.items()]
    await interaction.response.send_message("\n".join(lines))


@bot.tree.command(name="watch", description="(Admin) Announce in this channel when a saved server goes up/down")
@app_commands.default_permissions(administrator=True)
async def watch_cmd(interaction: discord.Interaction, label: str):
    saved = book.get(interaction.guild.id, label)
    if not saved:
        await interaction.response.send_message("Save that server first with `/addserver`.", ephemeral=True)
        return
    watch = load_watch()
    watch[str(interaction.guild.id)] = {**saved, "label": label, "channel_id": interaction.channel.id}
    save_watch(watch)
    bot._last_state.pop(f"{interaction.guild.id}:{saved['host']}:{saved['port']}", None)
    await interaction.response.send_message(f"👀 Watching **{label}** — I'll post here when it goes up or down (checked every 5 minutes).")


@bot.tree.command(name="unwatch", description="(Admin) Stop watching the server")
@app_commands.default_permissions(administrator=True)
async def unwatch_cmd(interaction: discord.Interaction):
    watch = load_watch()
    if watch.pop(str(interaction.guild.id), None):
        save_watch(watch)
        await interaction.response.send_message("Stopped watching.")
    else:
        await interaction.response.send_message("Nothing was being watched here.", ephemeral=True)


if __name__ == "__main__":
    if not TOKEN:
        print("DISCORD_TOKEN is missing. Copy .env.example to .env and paste your MC Bot token in it.")
        sys.exit(1)
    bot.run(TOKEN)
