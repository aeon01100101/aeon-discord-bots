"""Aeon Arcade - pure logic: dice, games, trivia bank + scores, polls,
reminders. No discord imports so all of it is unit-testable."""
from __future__ import annotations

import json
import os
import random
import re
import time

# ---------- dice & simple games ----------

_DICE_RE = re.compile(r"^\s*(\d*)\s*d\s*(\d+)\s*([+-]\s*\d+)?\s*$", re.IGNORECASE)


def roll_dice(spec: str, rng: random.Random | None = None) -> dict:
    """'2d6+3', 'd20', '3d8-1' -> {rolls, modifier, total}. Limits keep
    one command from spamming the channel: max 50 dice, max d1000."""
    rng = rng or random
    m = _DICE_RE.match(spec or "")
    if not m:
        raise ValueError("Use a dice spec like 2d6, d20, or 3d8+2.")
    count = int(m.group(1) or 1)
    sides = int(m.group(2))
    modifier = int((m.group(3) or "0").replace(" ", ""))
    if not (1 <= count <= 50):
        raise ValueError("Roll between 1 and 50 dice.")
    if not (2 <= sides <= 1000):
        raise ValueError("Dice need between 2 and 1000 sides.")
    rolls = [rng.randint(1, sides) for _ in range(count)]
    return {"rolls": rolls, "modifier": modifier, "total": sum(rolls) + modifier}


EIGHT_BALL = [
    "Yes, definitely.", "It is certain.", "Signs point to yes.",
    "Most likely.", "Absolutely.", "Ask again later.",
    "Cannot predict now.", "Better not tell you yet.",
    "Don't count on it.", "No. Just no.", "Outlook not so good.",
    "Very doubtful.", "Maybe - flip a coin.", "The swarm says yes.",
]


def eight_ball(rng: random.Random | None = None) -> str:
    return (rng or random).choice(EIGHT_BALL)


RPS_BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}


def rps_result(player: str, bot: str) -> str:
    player, bot = player.lower(), bot.lower()
    if player == bot:
        return "tie"
    return "win" if RPS_BEATS[player] == bot else "lose"


# ---------- trivia ----------

TRIVIA = [
    ("What is the capital of France?", ["Paris", "London", "Berlin", "Madrid"], 0),
    ("How many hearts does an octopus have?", ["One", "Two", "Three", "Four"], 2),
    ("Which planet is known as the Red Planet?", ["Venus", "Mars", "Jupiter", "Saturn"], 1),
    ("What is 15% of 200?", ["20", "25", "30", "35"], 2),
    ("Who painted the Mona Lisa?", ["Van Gogh", "Picasso", "Da Vinci", "Rembrandt"], 2),
    ("What does 'HTTP' stand for in a web address - the 'P'?", ["Protocol", "Program", "Page", "Portal"], 0),
    ("In Minecraft, what do you need to make a Nether Portal frame?", ["Obsidian", "Bedrock", "End Stone", "Crying Glass"], 0),
    ("How many sides does a hexagon have?", ["Five", "Six", "Seven", "Eight"], 1),
    ("Which gas do plants absorb from the air?", ["Oxygen", "Nitrogen", "Carbon dioxide", "Helium"], 2),
    ("What is the largest ocean on Earth?", ["Atlantic", "Indian", "Arctic", "Pacific"], 3),
    ("How many minutes are in a full week?", ["10080", "1440", "7200", "10008"], 0),
    ("What colour do you get mixing blue and yellow paint?", ["Purple", "Green", "Orange", "Brown"], 1),
    ("In computing, how many bits are in a byte?", ["4", "8", "16", "32"], 1),
    ("Which animal is known as man's best friend?", ["Cat", "Horse", "Dog", "Parrot"], 2),
    ("What is the freezing point of water in Fahrenheit?", ["0 F", "32 F", "50 F", "100 F"], 1),
    ("How many continents are there on Earth?", ["5", "6", "7", "8"], 2),
    ("Which instrument measures earthquakes?", ["Barometer", "Seismograph", "Thermometer", "Altimeter"], 1),
    ("What is the main ingredient in guacamole?", ["Tomato", "Avocado", "Onion", "Pepper"], 1),
    ("In Minecraft, creepers are scared of which animal?", ["Wolves", "Ocelots", "Pigs", "Foxes"], 1),
    ("What year did the first Moon landing happen?", ["1959", "1969", "1975", "1981"], 1),
    ("Which language has the most native speakers?", ["English", "Hindi", "Mandarin Chinese", "Spanish"], 2),
    ("How many legs does a spider have?", ["6", "8", "10", "12"], 1),
    ("What is H2O more commonly known as?", ["Salt", "Oxygen", "Water", "Hydrogen"], 2),
    ("Which chess piece can only move diagonally?", ["Rook", "Knight", "Bishop", "Queen's pawn"], 2),
    ("What does DNA stand for - first word?", ["Deoxyribonucleic", "Dinucleic", "Deoxyribose", "Dual"], 0),
]


def pick_trivia(rng: random.Random | None = None) -> dict:
    rng = rng or random
    q, answers, correct = rng.choice(TRIVIA)
    order = list(range(len(answers)))
    rng.shuffle(order)
    return {
        "question": q,
        "answers": [answers[i] for i in order],
        "correct_index": order.index(correct),
    }


# ---------- persistent scores + reminders ----------

class ArcadeStore:
    def __init__(self, path):
        self.path = str(path)
        self.data = self._load()

    def _load(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=1)
        os.replace(tmp, self.path)

    # trivia scores per guild: {guild: {user: points}}
    def add_points(self, guild_id: int, user_id: int, name: str, points: int) -> int:
        guild = self.data.setdefault("scores", {}).setdefault(str(guild_id), {})
        entry = guild.setdefault(str(user_id), {"name": name, "points": 0})
        entry["name"] = name
        entry["points"] += points
        self.save()
        return entry["points"]

    def leaderboard(self, guild_id: int, limit: int = 10) -> list[dict]:
        guild = self.data.get("scores", {}).get(str(guild_id), {})
        rows = [{"user_id": k, **v} for k, v in guild.items()]
        return sorted(rows, key=lambda r: -r["points"])[:limit]

    # reminders: list of dicts that survive restarts
    def add_reminder(self, user_id: int, channel_id: int, text: str, due_ts: float) -> dict:
        rems = self.data.setdefault("reminders", [])
        rem = {"id": (max([r["id"] for r in rems], default=0) + 1),
               "user_id": user_id, "channel_id": channel_id,
               "text": text, "due": due_ts}
        rems.append(rem)
        self.save()
        return rem

    def due_reminders(self, now: float | None = None) -> list[dict]:
        now = time.time() if now is None else now
        return [r for r in self.data.get("reminders", []) if r["due"] <= now]

    def pop_due(self, now: float | None = None) -> list[dict]:
        due = self.due_reminders(now)
        ids = {r["id"] for r in due}
        self.data["reminders"] = [r for r in self.data.get("reminders", []) if r["id"] not in ids]
        if due:
            self.save()
        return due

    def list_reminders(self, user_id: int) -> list[dict]:
        return [r for r in self.data.get("reminders", []) if r["user_id"] == user_id]

    def cancel_reminder(self, user_id: int, rem_id: int) -> bool:
        rems = self.data.get("reminders", [])
        kept = [r for r in rems if not (r["id"] == rem_id and r["user_id"] == user_id)]
        if len(kept) == len(rems):
            return False
        self.data["reminders"] = kept
        self.save()
        return True


# ---------- durations for /remind ----------

_REMIND_RE = re.compile(r"^\s*(\d+)\s*([smhd])\s*$", re.IGNORECASE)
_REMIND_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_remind_after(text: str) -> int | None:
    m = _REMIND_RE.match(text or "")
    if not m:
        return None
    seconds = int(m.group(1)) * _REMIND_UNITS[m.group(2).lower()]
    if seconds < 10 or seconds > 30 * 86400:
        return None
    return seconds


# ---------- polls ----------

POLL_EMOJI = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]


def parse_poll_options(text: str) -> list[str]:
    opts = [o.strip() for o in (text or "").split("|")]
    return [o[:80] for o in opts if o][:5]


def tally_poll(options: list[str], counts: list[int]) -> str:
    total = sum(counts)
    lines = []
    for opt, n in zip(options, counts):
        pct = round(100 * n / total) if total else 0
        bar = "█" * round(pct / 10)
        lines.append(f"**{opt}** — {n} vote(s) ({pct}%) {bar}")
    return "\n".join(lines) if lines else "No options."
