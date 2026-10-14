"""Aeon Radio Bot - pure logic (no discord imports, fully unit-testable).

Station lookup uses the free Radio Browser directory (the same one the
Aeon Radio Android app uses) - no API key, no account. A small built-in
station list is kept as an offline fallback so the bot still works if
the directory is down.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

RADIO_BROWSER = "https://de1.api.radio-browser.info/json/stations"

# Reliable, long-lived streams (verified live for the Aeon Radio app).
BUILTIN_STATIONS = [
    {"name": "SomaFM Groove Salad", "url": "https://ice1.somafm.com/groovesalad-128-mp3",
     "genre": "ambient/chill", "country": "USA"},
    {"name": "SomaFM Lush", "url": "https://ice1.somafm.com/lush-128-mp3",
     "genre": "chill/vocals", "country": "USA"},
    {"name": "SomaFM DEF CON Radio", "url": "https://ice1.somafm.com/defcon-128-mp3",
     "genre": "electronic", "country": "USA"},
    {"name": "181.FM The Beat", "url": "https://listen.181fm.com/181-beat_128k.mp3",
     "genre": "dance", "country": "USA"},
    {"name": "Nightride FM", "url": "https://stream.nightride.fm/nightride.mp3",
     "genre": "synthwave", "country": "International"},
    {"name": "Chillhop Radio", "url": "https://streams.ilovemusic.de/iloveradio17.mp3",
     "genre": "lofi/chillhop", "country": "Germany"},
    {"name": "Radio Swiss Jazz", "url": "https://stream.srg-ssr.ch/m/rsj/mp3_128",
     "genre": "jazz", "country": "Switzerland"},
    {"name": "FIP Paris", "url": "https://icecast.radiofrance.fr/fip-midfi.mp3",
     "genre": "eclectic", "country": "France"},
    {"name": "KEXP Seattle", "url": "https://kexp.streamguys1.com/kexp160.aac",
     "genre": "alternative", "country": "USA"},
    {"name": "BBC World Service", "url": "https://stream.live.vc.bbcmedia.co.uk/bbc_world_service",
     "genre": "news/talk", "country": "UK"},
]


def pick_stream_url(station: dict) -> str:
    """Radio Browser gives url (may be a playlist/redirect) and
    url_resolved (the real stream). Always prefer url_resolved."""
    return (station.get("url_resolved") or station.get("url") or "").strip()


def normalize_station(raw: dict) -> dict | None:
    url = pick_stream_url(raw)
    name = (raw.get("name") or "").strip()
    if not url or not name or not url.startswith(("http://", "https://")):
        return None
    # Skip dead stations Radio Browser has flagged, and HLS-only entries
    # ffmpeg in discord.py handles plain streams most reliably.
    if raw.get("lastcheckok", 1) == 0:
        return None
    return {
        "name": name[:100],
        "url": url,
        "genre": (raw.get("tags") or "").strip()[:60],
        "country": (raw.get("country") or "").strip()[:60],
        "bitrate": int(raw.get("bitrate") or 0),
        "votes": int(raw.get("votes") or 0),
    }


def parse_search_results(payload: list, limit: int = 10) -> list[dict]:
    out = []
    seen = set()
    for raw in payload or []:
        st = normalize_station(raw)
        if st and st["url"] not in seen:
            seen.add(st["url"])
            out.append(st)
        if len(out) >= limit:
            break
    return out


def search_stations(query: str, limit: int = 10, fetcher=None) -> list[dict]:
    """Search Radio Browser by name. Falls back to built-ins on any
    network failure so the bot degrades instead of dying."""
    q = (query or "").strip()
    if not q:
        return list(BUILTIN_STATIONS[:limit])
    url = f"{RADIO_BROWSER}/byname/{urllib.parse.quote(q)}?order=votes&reverse=true&hidebroken=true"
    try:
        fetch = fetcher or _http_get_json
        results = parse_search_results(fetch(url), limit)
        if results:
            return results
    except Exception:
        pass
    low = q.lower()
    return [s for s in BUILTIN_STATIONS if low in s["name"].lower() or low in s["genre"].lower()][:limit]


def top_stations(limit: int = 10, fetcher=None) -> list[dict]:
    url = f"{RADIO_BROWSER}/topvote/{limit}?hidebroken=true"
    try:
        fetch = fetcher or _http_get_json
        results = parse_search_results(fetch(url), limit)
        if results:
            return results
    except Exception:
        pass
    return list(BUILTIN_STATIONS[:limit])


def _http_get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "AeonRadioBot/1.0 (discord)"})
    with urllib.request.urlopen(req, timeout=12) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def format_station_list(stations: list[dict]) -> str:
    if not stations:
        return "No stations found. Try another name or genre."
    lines = []
    for i, s in enumerate(stations, 1):
        bits = [b for b in (s.get("genre", ""), s.get("country", "")) if b]
        lines.append(f"**{i}. {s['name']}**" + (f" — {' · '.join(bits)}" if bits else ""))
    return "\n".join(lines)


def clamp_volume(v) -> float:
    try:
        v = int(v)
    except (TypeError, ValueError):
        return 0.5
    return max(0, min(100, v)) / 100.0
