"""Aeon Guard - Discord wiring. Run: python bot.py
Moderation + welcome + anti-spam for a friends server.
Needs DISCORD_TOKEN in .env and the Server Members + Message Content
privileged intents ON in the Developer Portal (see ../SETUP.md)."""
from __future__ import annotations

import logging
import os
import sys
from datetime import timedelta
from pathlib import Path

import discord
from discord import app_commands

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import GuardStore, SpamTracker, find_blocked_word, human_duration, parse_duration  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("aeon-guard")

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
store = GuardStore(BASE / "data" / "guard.json")
spam = SpamTracker()


class GuardBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        log.info("slash commands synced")

    async def on_ready(self):
        log.info("Logged in as %s", self.user)

    async def log_to_guild(self, guild: discord.Guild, text: str):
        channel_id = store.get_setting(guild.id, "log_channel")
        if channel_id:
            channel = guild.get_channel(channel_id)
            if channel:
                try:
                    await channel.send(text[:1990])
                except discord.HTTPException:
                    pass

    async def on_member_join(self, member: discord.Member):
        channel_id = store.get_setting(member.guild.id, "welcome_channel")
        template = store.get_setting(member.guild.id, "welcome_message",
                                     "👋 Welcome to the server, {user}! Glad you're here.")
        if channel_id:
            channel = member.guild.get_channel(channel_id)
            if channel:
                await channel.send(template.replace("{user}", member.mention).replace("{server}", member.guild.name))
        await self.log_to_guild(member.guild, f"📥 {member.mention} joined the server.")

    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if message.author.guild_permissions.manage_messages:
            return  # mods are exempt from automod
        gid = message.guild.id
        if store.get_setting(gid, "automod", True):
            word = find_blocked_word(message.content, store.get_blocked_words(gid))
            if word:
                await message.delete()
                await message.channel.send(f"{message.author.mention} — that word isn't allowed here.", delete_after=6)
                await self.log_to_guild(message.guild, f"🛡️ Deleted a message from {message.author.mention} (blocked word).")
                return
            hit = spam.check(gid, message.author.id, message.content)
            if hit:
                await message.delete()
                spam.reset(gid, message.author.id)
                await message.channel.send(f"{message.author.mention} — slow down a bit (anti-spam).", delete_after=6)
                await self.log_to_guild(message.guild, f"🛡️ Anti-spam ({hit}) triggered by {message.author.mention}.")
                return


bot = GuardBot()
admin = app_commands.default_permissions(manage_messages=True)


@bot.tree.command(name="warn", description="(Mod) Warn a member")
@admin
async def warn_cmd(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason given"):
    count = store.add_warning(interaction.guild.id, member.id, reason, interaction.user.id)
    await interaction.response.send_message(f"⚠️ {member.mention} warned ({count} total): {reason}")
    await bot.log_to_guild(interaction.guild, f"⚠️ {member.mention} warned by {interaction.user.mention}: {reason} (warning #{count})")


@bot.tree.command(name="warnings", description="See a member's warnings")
async def warnings_cmd(interaction: discord.Interaction, member: discord.Member):
    warns = store.get_warnings(interaction.guild.id, member.id)
    if not warns:
        await interaction.response.send_message(f"{member.display_name} has no warnings. Clean record ✨", ephemeral=True)
        return
    lines = [f"{i}. {w['reason']}" for i, w in enumerate(warns, 1)]
    await interaction.response.send_message(f"**{member.display_name}** — {len(warns)} warning(s):\n" + "\n".join(lines), ephemeral=True)


@bot.tree.command(name="clearwarnings", description="(Mod) Clear a member's warnings")
@admin
async def clearwarnings_cmd(interaction: discord.Interaction, member: discord.Member):
    n = store.clear_warnings(interaction.guild.id, member.id)
    await interaction.response.send_message(f"🧹 Cleared {n} warning(s) for {member.mention}.")


@bot.tree.command(name="kick", description="(Mod) Kick a member")
@admin
async def kick_cmd(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason given"):
    await member.kick(reason=reason)
    await interaction.response.send_message(f"👢 Kicked {member.mention}: {reason}")
    await bot.log_to_guild(interaction.guild, f"👢 {member.mention} kicked by {interaction.user.mention}: {reason}")


@bot.tree.command(name="ban", description="(Admin) Ban a member")
@app_commands.default_permissions(ban_members=True)
async def ban_cmd(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason given"):
    await member.ban(reason=reason)
    await interaction.response.send_message(f"🔨 Banned {member.mention}: {reason}")
    await bot.log_to_guild(interaction.guild, f"🔨 {member.mention} banned by {interaction.user.mention}: {reason}")


@bot.tree.command(name="timeout", description="(Mod) Timeout a member, e.g. 10m, 2h, 1d")
@admin
async def timeout_cmd(interaction: discord.Interaction, member: discord.Member, duration: str, reason: str = "No reason given"):
    seconds = parse_duration(duration)
    if seconds is None:
        await interaction.response.send_message("Use a duration like `10m`, `2h`, or `1d` (max 28d).", ephemeral=True)
        return
    await member.timeout(discord.utils.utcnow() + timedelta(seconds=seconds), reason=reason)
    await interaction.response.send_message(f"🔇 {member.mention} timed out for {human_duration(seconds)}: {reason}")
    await bot.log_to_guild(interaction.guild, f"🔇 {member.mention} timed out {human_duration(seconds)} by {interaction.user.mention}: {reason}")


@bot.tree.command(name="clear", description="(Mod) Delete the last N messages in this channel (1-100)")
@admin
async def clear_cmd(interaction: discord.Interaction, count: int):
    count = max(1, min(100, count))
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=count)
    await interaction.followup.send(f"🧹 Deleted {len(deleted)} message(s).", ephemeral=True)
    await bot.log_to_guild(interaction.guild, f"🧹 {interaction.user.mention} cleared {len(deleted)} messages in {interaction.channel.mention}")


@bot.tree.command(name="slowmode", description="(Mod) Set slowmode seconds on this channel (0 = off)")
@admin
async def slowmode_cmd(interaction: discord.Interaction, seconds: int):
    seconds = max(0, min(21600, seconds))
    await interaction.channel.edit(slowmode_delay=seconds)
    await interaction.response.send_message(f"🐢 Slowmode set to {seconds}s.")


@bot.tree.command(name="setwelcome", description="(Admin) Use this channel for welcome messages")
@app_commands.default_permissions(administrator=True)
async def setwelcome_cmd(interaction: discord.Interaction, message: str = ""):
    store.set_setting(interaction.guild.id, "welcome_channel", interaction.channel.id)
    if message:
        store.set_setting(interaction.guild.id, "welcome_message", message)
    await interaction.response.send_message("✅ Welcome messages will post in this channel. Use `{user}` in the message for a mention.")


@bot.tree.command(name="setlog", description="(Admin) Use this channel as the mod log")
@app_commands.default_permissions(administrator=True)
async def setlog_cmd(interaction: discord.Interaction):
    store.set_setting(interaction.guild.id, "log_channel", interaction.channel.id)
    await interaction.response.send_message("✅ Mod actions will be logged in this channel.")


@bot.tree.command(name="blockword", description="(Admin) Add a word to the filter")
@app_commands.default_permissions(administrator=True)
async def blockword_cmd(interaction: discord.Interaction, word: str):
    ok = store.add_blocked_word(interaction.guild.id, word)
    await interaction.response.send_message("✅ Added to the filter." if ok else "That word is already filtered.", ephemeral=True)


@bot.tree.command(name="unblockword", description="(Admin) Remove a word from the filter")
@app_commands.default_permissions(administrator=True)
async def unblockword_cmd(interaction: discord.Interaction, word: str):
    ok = store.remove_blocked_word(interaction.guild.id, word)
    await interaction.response.send_message("✅ Removed." if ok else "That word wasn't in the filter.", ephemeral=True)


@bot.tree.command(name="automod", description="(Admin) Turn anti-spam + word filter on or off")
@app_commands.default_permissions(administrator=True)
async def automod_cmd(interaction: discord.Interaction, enabled: bool):
    store.set_setting(interaction.guild.id, "automod", enabled)
    await interaction.response.send_message(f"🛡️ Automod {'ON' if enabled else 'OFF'}.")


if __name__ == "__main__":
    if not TOKEN:
        print("DISCORD_TOKEN is missing. Copy .env.example to .env and paste your Guard Bot token in it.")
        sys.exit(1)
    bot.run(TOKEN)
