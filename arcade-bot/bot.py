"""Aeon Arcade - Discord wiring. Run: python bot.py
Games, trivia with a server leaderboard, polls, and reminders.
Needs DISCORD_TOKEN in .env (see ../SETUP.md)."""
from __future__ import annotations

import asyncio
import logging
import os
import random
import sys
import time
from pathlib import Path

import discord
from discord import app_commands

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import (ArcadeStore, eight_ball, parse_poll_options,  # noqa: E402
                  parse_remind_after, pick_trivia, roll_dice, rps_result, tally_poll)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("aeon-arcade")

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
store = ArcadeStore(BASE / "data" / "arcade.json")
open_polls: dict[int, dict] = {}  # message_id -> {question, options, channel_id}


class ArcadeBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        self._reminder_task: asyncio.Task | None = None

    async def setup_hook(self):
        await self.tree.sync()
        self._reminder_task = asyncio.create_task(self._reminder_loop())
        log.info("slash commands synced")

    async def on_ready(self):
        log.info("Logged in as %s", self.user)

    async def _reminder_loop(self):
        await self.wait_until_ready()
        while not self.is_closed():
            for rem in store.pop_due():
                channel = self.get_channel(rem["channel_id"])
                if channel:
                    try:
                        await channel.send(f"⏰ <@{rem['user_id']}> reminder: **{rem['text']}**")
                    except discord.HTTPException:
                        pass
            await asyncio.sleep(15)


bot = ArcadeBot()


@bot.tree.command(name="roll", description="Roll dice, e.g. 2d6, d20, 3d8+2")
async def roll_cmd(interaction: discord.Interaction, dice: str = "1d6"):
    try:
        result = roll_dice(dice)
    except ValueError as exc:
        await interaction.response.send_message(str(exc), ephemeral=True)
        return
    rolls = ", ".join(str(r) for r in result["rolls"])
    mod = f" {'+' if result['modifier'] >= 0 else '-'} {abs(result['modifier'])}" if result["modifier"] else ""
    await interaction.response.send_message(f"🎲 {interaction.user.display_name} rolled **{result['total']}** ({rolls}{mod})")


@bot.tree.command(name="flip", description="Flip a coin")
async def flip_cmd(interaction: discord.Interaction):
    await interaction.response.send_message(f"🪙 **{random.choice(['Heads', 'Tails'])}**")


@bot.tree.command(name="choose", description="Let the bot choose between options separated by |")
async def choose_cmd(interaction: discord.Interaction, options: str):
    opts = parse_poll_options(options)
    if len(opts) < 2:
        await interaction.response.send_message("Give me at least 2 options separated by `|` — e.g. `pizza | tacos | burgers`.", ephemeral=True)
        return
    await interaction.response.send_message(f"🤔 I choose: **{random.choice(opts)}**")


@bot.tree.command(name="8ball", description="Ask the magic 8-ball a question")
async def eightball_cmd(interaction: discord.Interaction, question: str):
    await interaction.response.send_message(f"🎱 *{question}*\n**{eight_ball()}**")


@bot.tree.command(name="rps", description="Rock paper scissors against the bot")
@app_commands.choices(choice=[
    app_commands.Choice(name="rock", value="rock"),
    app_commands.Choice(name="paper", value="paper"),
    app_commands.Choice(name="scissors", value="scissors"),
])
async def rps_cmd(interaction: discord.Interaction, choice: str):
    mine = random.choice(["rock", "paper", "scissors"])
    result = rps_result(choice, mine)
    verb = {"win": "You win! 🎉", "lose": "I win! 😎", "tie": "It's a tie."}[result]
    if result == "win":
        total = store.add_points(interaction.guild.id, interaction.user.id, interaction.user.display_name, 1)
        verb += f" (+1 arcade point, you have {total})"
    await interaction.response.send_message(f"You: **{choice}** · Me: **{mine}** — {verb}")


class TriviaView(discord.ui.View):
    def __init__(self, trivia: dict, asker: discord.User):
        super().__init__(timeout=25)
        self.trivia = trivia
        self.asker = asker
        self.answered = False
        for i, answer in enumerate(trivia["answers"]):
            btn = discord.ui.Button(label=answer[:80], style=discord.ButtonStyle.primary)
            btn.callback = self._make_callback(i)
            self.add_item(btn)

    def _make_callback(self, idx: int):
        async def callback(interaction: discord.Interaction):
            if self.answered:
                await interaction.response.send_message("Already answered!", ephemeral=True)
                return
            self.answered = True
            for child in self.children:
                child.disabled = True
            correct = self.trivia["correct_index"]
            right = self.trivia["answers"][correct]
            if idx == correct:
                total = store.add_points(interaction.guild.id, interaction.user.id,
                                         interaction.user.display_name, 10)
                text = f"✅ {interaction.user.mention} got it — **{right}**! +10 points (total {total})."
            else:
                text = f"❌ {interaction.user.mention} — nope. The answer was **{right}**."
            await interaction.response.edit_message(view=self)
            await interaction.followup.send(text)
            self.stop()
        return callback


@bot.tree.command(name="trivia", description="Answer a trivia question for points (25 second timer)")
async def trivia_cmd(interaction: discord.Interaction):
    trivia = pick_trivia()
    view = TriviaView(trivia, interaction.user)
    await interaction.response.send_message(f"❓ **Trivia:** {trivia['question']}\nFirst to tap the right answer wins 10 points.", view=view)


@bot.tree.command(name="leaderboard", description="Arcade points leaderboard for this server")
async def leaderboard_cmd(interaction: discord.Interaction):
    rows = store.leaderboard(interaction.guild.id)
    if not rows:
        await interaction.response.send_message("No points yet. Play `/trivia` or `/rps` to get on the board.")
        return
    medals = ["🥇", "🥈", "🥉"]
    lines = [f"{medals[i] if i < 3 else f'{i + 1}.'} **{r['name']}** — {r['points']} pts" for i, r in enumerate(rows)]
    await interaction.response.send_message("🏆 **Arcade Leaderboard**\n" + "\n".join(lines))


@bot.tree.command(name="poll", description="Start a poll - options separated by | (up to 5)")
async def poll_cmd(interaction: discord.Interaction, question: str, options: str):
    opts = parse_poll_options(options)
    if len(opts) < 2:
        await interaction.response.send_message("Give at least 2 options separated by `|`.", ephemeral=True)
        return
    from core import POLL_EMOJI
    body = "\n".join(f"{POLL_EMOJI[i]} {o}" for i, o in enumerate(opts))
    await interaction.response.send_message(f"📊 **{question}**\n{body}\n\nVote with the reactions below — `/endpoll` closes it.")
    msg = await interaction.original_response()
    open_polls[msg.id] = {"question": question, "options": opts, "channel_id": interaction.channel.id}
    for i in range(len(opts)):
        await msg.add_reaction(POLL_EMOJI[i])


@bot.tree.command(name="endpoll", description="Close the most recent poll in this channel and show results")
async def endpoll_cmd(interaction: discord.Interaction):
    from core import POLL_EMOJI
    target = None
    for mid, poll in list(open_polls.items()):
        if poll["channel_id"] == interaction.channel.id:
            target = (mid, poll)
    if not target:
        await interaction.response.send_message("No open poll in this channel.", ephemeral=True)
        return
    mid, poll = target
    msg = await interaction.channel.fetch_message(mid)
    counts = []
    for i in range(len(poll["options"])):
        reaction = discord.utils.get(msg.reactions, emoji=POLL_EMOJI[i])
        counts.append(max(0, (reaction.count if reaction else 1) - 1))  # minus the bot's own
    del open_polls[mid]
    await interaction.response.send_message(f"📊 **Results: {poll['question']}**\n" + tally_poll(poll["options"], counts))


@bot.tree.command(name="remind", description="Remind you later, e.g. after=30m, after=2h")
@app_commands.describe(after="How long from now: 10s, 30m, 2h, 1d (min 10s, max 30d)", text="What to remind you about")
async def remind_cmd(interaction: discord.Interaction, after: str, text: str):
    seconds = parse_remind_after(after)
    if seconds is None:
        await interaction.response.send_message("Use a time like `10s`, `30m`, `2h`, or `1d` (between 10 seconds and 30 days).", ephemeral=True)
        return
    rem = store.add_reminder(interaction.user.id, interaction.channel.id, text[:300], time.time() + seconds)
    await interaction.response.send_message(f"⏰ Got it — reminder #{rem['id']} in **{after}**: {text[:300]}")


@bot.tree.command(name="reminders", description="Your pending reminders")
async def reminders_cmd(interaction: discord.Interaction):
    rems = store.list_reminders(interaction.user.id)
    if not rems:
        await interaction.response.send_message("You have no pending reminders.", ephemeral=True)
        return
    lines = [f"#{r['id']} — <t:{int(r['due'])}:R>: {r['text']}" for r in rems]
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@bot.tree.command(name="cancelreminder", description="Cancel one of your reminders by its # number")
async def cancel_cmd(interaction: discord.Interaction, number: int):
    ok = store.cancel_reminder(interaction.user.id, number)
    await interaction.response.send_message("✅ Cancelled." if ok else "No reminder with that number.", ephemeral=True)


if __name__ == "__main__":
    if not TOKEN:
        print("DISCORD_TOKEN is missing. Copy .env.example to .env and paste your Arcade Bot token in it.")
        sys.exit(1)
    bot.run(TOKEN)
