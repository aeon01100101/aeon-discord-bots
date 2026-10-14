"""Aeon MC Bot - pure logic: Minecraft Server List Ping (SLP) protocol.

Implements the modern (1.7+) status ping by hand with only the stdlib:
handshake -> status request -> JSON response -> ping/pong latency.
Works with Java Edition servers, including ones behind playit.gg tunnels
(just use the tunnel address as the host). No third-party library needed.
"""
from __future__ import annotations

import json
import socket
import struct
import time

DEFAULT_PORT = 25565


# ---------- address parsing ----------

def parse_address(text: str) -> tuple[str, int]:
    """'play.example.com', 'host:25565', '[::1]:25565' -> (host, port)"""
    text = (text or "").strip()
    if not text:
        raise ValueError("empty address")
    if text.startswith("["):
        host, _, rest = text[1:].partition("]")
        port = int(rest[1:]) if rest.startswith(":") and rest[1:].isdigit() else DEFAULT_PORT
        return host, port
    if text.count(":") == 1:
        host, _, p = text.partition(":")
        if p.isdigit():
            return host.strip(), int(p)
    return text, DEFAULT_PORT


# ---------- protocol primitives ----------

def encode_varint(value: int) -> bytes:
    out = bytearray()
    v = value & 0xFFFFFFFF
    while True:
        b = v & 0x7F
        v >>= 7
        if v:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def decode_varint(read_byte) -> int:
    num = 0
    for i in range(5):
        b = read_byte()
        if b is None:
            raise ConnectionError("connection closed mid-varint")
        num |= (b & 0x7F) << (7 * i)
        if not (b & 0x80):
            return num
    raise ValueError("varint too long")


def make_packet(packet_id: int, payload: bytes = b"") -> bytes:
    body = encode_varint(packet_id) + payload
    return encode_varint(len(body)) + body


def encode_string(s: str) -> bytes:
    data = s.encode("utf-8")
    return encode_varint(len(data)) + data


# ---------- response parsing ----------

def flatten_text(node) -> str:
    """Minecraft chat components can be a string, a dict with 'text',
    or a list with nested 'extra' parts. Flatten to plain text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, (int, float)):
        return str(node)
    if isinstance(node, list):
        return "".join(flatten_text(x) for x in node)
    if isinstance(node, dict):
        parts = [flatten_text(node.get("text", ""))]
        parts.append(flatten_text(node.get("extra", [])))
        return "".join(parts)
    return ""


def strip_formatting(text: str) -> str:
    """Remove section-sign colour codes (e.g. '§aGreen' -> 'Green')."""
    out, skip = [], False
    for ch in text or "":
        if skip:
            skip = False
            continue
        if ch == "§":
            skip = True
            continue
        out.append(ch)
    return "".join(out).strip()


def parse_status(payload: dict) -> dict:
    players = payload.get("players") or {}
    sample = []
    for p in players.get("sample") or []:
        name = (p or {}).get("name")
        if name:
            sample.append(strip_formatting(str(name)))
    version = payload.get("version") or {}
    return {
        "motd": strip_formatting(flatten_text(payload.get("description"))) or "A Minecraft server",
        "online": int(players.get("online") or 0),
        "max": int(players.get("max") or 0),
        "players": sample,
        "version": str(version.get("name") or "unknown"),
    }


# ---------- the ping itself ----------

def ping_server(host: str, port: int = DEFAULT_PORT, timeout: float = 6.0) -> dict:
    """Ping one Java server. Returns parse_status() + latency_ms.
    Raises OSError/ConnectionError/ValueError when the server is down."""
    started = time.time()
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        buf = bytearray()

        def read_byte():
            while not buf:
                chunk = sock.recv(4096)
                if not chunk:
                    return None
                buf.extend(chunk)
            return buf.pop(0)

        def read_exact(n: int) -> bytes:
            while len(buf) < n:
                chunk = sock.recv(4096)
                if not chunk:
                    raise ConnectionError("connection closed")
                buf.extend(chunk)
            out = bytes(buf[:n])
            del buf[:n]
            return out

        handshake = (
            encode_varint(754)  # protocol version (arbitrary for status)
            + encode_string(host)
            + struct.pack(">H", port)
            + encode_varint(1)  # next state: status
        )
        sock.sendall(make_packet(0x00, handshake))
        sock.sendall(make_packet(0x00))  # status request

        length = decode_varint(read_byte)
        packet_id = decode_varint(read_byte)
        if packet_id != 0x00:
            raise ValueError(f"unexpected packet id {packet_id}")
        str_len = decode_varint(read_byte)
        raw = read_exact(str_len)
        status = parse_status(json.loads(raw.decode("utf-8", "replace")))

        token = struct.pack(">q", 123456789)
        t0 = time.time()
        sock.sendall(make_packet(0x01, token))
        decode_varint(read_byte)
        decode_varint(read_byte)
        read_exact(8)
        status["latency_ms"] = round((time.time() - t0) * 1000)
        status["host"], status["port"] = host, port
        status["checked_in_ms"] = round((time.time() - started) * 1000)
        return status


# ---------- saved server list ----------

class ServerBook:
    """Per-guild saved servers, stored as plain JSON on the host PC."""

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
        import os
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=1)
        os.replace(tmp, self.path)

    def add(self, guild_id: int, label: str, address: str) -> None:
        host, port = parse_address(address)
        guild = self.data.setdefault(str(guild_id), {})
        guild[label.strip().lower()] = {"host": host, "port": port}
        self.save()

    def remove(self, guild_id: int, label: str) -> bool:
        guild = self.data.get(str(guild_id), {})
        if label.strip().lower() in guild:
            del guild[label.strip().lower()]
            self.save()
            return True
        return False

    def list(self, guild_id: int) -> dict:
        return dict(self.data.get(str(guild_id), {}))

    def get(self, guild_id: int, label: str) -> dict | None:
        return self.data.get(str(guild_id), {}).get(label.strip().lower())
