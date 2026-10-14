"""Aeon Guard - pure logic: warnings store, spam detection, word filter,
duration parsing. No discord imports so all of it is unit-testable."""
from __future__ import annotations

import json
import os
import re
import time

# ---------- durations ----------

_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
_DURATION_RE = re.compile(r"^\s*(\d+)\s*([smhdw])\s*$", re.IGNORECASE)


def parse_duration(text: str) -> int | None:
    """'10m', '2h', '1d' -> seconds. None when unparseable.
    Clamped to Discord's 28-day timeout maximum."""
    m = _DURATION_RE.match(text or "")
    if not m:
        return None
    seconds = int(m.group(1)) * _UNITS[m.group(2).lower()]
    if seconds <= 0:
        return None
    return min(seconds, 28 * 86400)


def human_duration(seconds: int) -> str:
    for unit, size in (("w", 604800), ("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        if seconds >= size and seconds % size == 0:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


# ---------- word filter ----------

def normalize(text: str) -> str:
    """Lowercase + collapse leet speak so 'b4dw0rd' still matches."""
    table = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})
    return re.sub(r"[^a-z ]", " ", (text or "").lower().translate(table))


def find_blocked_word(text: str, blocked: list[str]) -> str | None:
    norm_text = " " + normalize(text) + " "
    for word in blocked or []:
        w = normalize(word).strip()
        if w and f" {w} " in norm_text:
            return word
    return None


# ---------- spam detection ----------

class SpamTracker:
    """Flags a user sending too many messages too fast, or repeating
    the same message. Pure in-memory, per (guild, user)."""

    def __init__(self, max_msgs: int = 5, window_seconds: float = 5.0, repeat_limit: int = 3):
        self.max_msgs = max_msgs
        self.window = window_seconds
        self.repeat_limit = repeat_limit
        self._events: dict[tuple, list[tuple[float, str]]] = {}

    def check(self, guild_id: int, user_id: int, content: str, now: float | None = None) -> str | None:
        now = time.time() if now is None else now
        key = (guild_id, user_id)
        events = [(t, c) for (t, c) in self._events.get(key, []) if now - t <= self.window * 4]
        events.append((now, (content or "").strip().lower()))
        self._events[key] = events
        recent = [e for e in events if now - e[0] <= self.window]
        if len(recent) >= self.max_msgs:
            return "flood"
        same = [e for e in events if e[1] and e[1] == events[-1][1]]
        if len(same) >= self.repeat_limit and events[-1][1]:
            return "repeat"
        return None

    def reset(self, guild_id: int, user_id: int):
        self._events.pop((guild_id, user_id), None)


# ---------- persistent per-guild state ----------

class GuardStore:
    """Warnings + settings (welcome channel/message, log channel,
    blocked words, automod toggles) in one JSON file on the host PC."""

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

    def _guild(self, guild_id: int) -> dict:
        return self.data.setdefault(str(guild_id), {"warnings": {}, "settings": {}})

    # warnings
    def add_warning(self, guild_id: int, user_id: int, reason: str, mod_id: int) -> int:
        g = self._guild(guild_id)
        lst = g["warnings"].setdefault(str(user_id), [])
        lst.append({"reason": reason, "mod": mod_id, "at": int(time.time())})
        self.save()
        return len(lst)

    def get_warnings(self, guild_id: int, user_id: int) -> list[dict]:
        return list(self._guild(guild_id)["warnings"].get(str(user_id), []))

    def clear_warnings(self, guild_id: int, user_id: int) -> int:
        g = self._guild(guild_id)
        n = len(g["warnings"].pop(str(user_id), []))
        self.save()
        return n

    # settings
    def set_setting(self, guild_id: int, key: str, value):
        self._guild(guild_id)["settings"][key] = value
        self.save()

    def get_setting(self, guild_id: int, key: str, default=None):
        return self._guild(guild_id)["settings"].get(key, default)

    def get_blocked_words(self, guild_id: int) -> list[str]:
        return list(self.get_setting(guild_id, "blocked_words", []))

    def add_blocked_word(self, guild_id: int, word: str) -> bool:
        words = self.get_blocked_words(guild_id)
        if word.lower() in [w.lower() for w in words]:
            return False
        words.append(word)
        self.set_setting(guild_id, "blocked_words", words)
        return True

    def remove_blocked_word(self, guild_id: int, word: str) -> bool:
        words = self.get_blocked_words(guild_id)
        kept = [w for w in words if w.lower() != word.lower()]
        if len(kept) == len(words):
            return False
        self.set_setting(guild_id, "blocked_words", kept)
        return True
