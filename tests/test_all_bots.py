"""Unit + protocol tests for the Aeon Discord Bots pack.
Run:  python -m pytest tests/ -q   (or python tests/test_all_bots.py)
Core modules have no discord dependency, so these run anywhere."""
import json
import random
import socket
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(unique_name: str, folder: str):
    import importlib.util
    spec = importlib.util.spec_from_file_location(unique_name, ROOT / folder / "core.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[unique_name] = mod
    spec.loader.exec_module(mod)
    return mod


radio = _load("radio_core", "radio-bot")
mc = _load("mc_core", "mc-bot")
guard = _load("guard_core", "guard-bot")
arcade = _load("arcade_core", "arcade-bot")

import tempfile  # noqa: E402


class RadioTests(unittest.TestCase):
    def test_pick_resolved_url(self):
        self.assertEqual(radio.pick_stream_url({"url": "a", "url_resolved": "b"}), "b")
        self.assertEqual(radio.pick_stream_url({"url": "a"}), "a")

    def test_normalize_skips_dead(self):
        self.assertIsNone(radio.normalize_station({"name": "X", "url": "https://s", "lastcheckok": 0}))
        self.assertIsNone(radio.normalize_station({"name": "", "url": "https://s"}))
        ok = radio.normalize_station({"name": "Jazz FM", "url_resolved": "https://stream",
                                      "tags": "jazz", "country": "UK", "bitrate": 128, "votes": 5})
        self.assertEqual(ok["name"], "Jazz FM")
        self.assertEqual(ok["bitrate"], 128)

    def test_parse_dedupes(self):
        payload = [{"name": "A", "url": "https://1"}, {"name": "A2", "url": "https://1"},
                   {"name": "B", "url": "https://2"}]
        out = radio.parse_search_results(payload)
        self.assertEqual([s["name"] for s in out], ["A", "B"])

    def test_search_fallback_offline(self):
        def boom(url):
            raise OSError("no net")
        out = radio.search_stations("groove", fetcher=boom)
        self.assertTrue(any("Groove Salad" in s["name"] for s in out))
        out2 = radio.search_stations("", fetcher=boom)
        self.assertEqual(len(out2), len(radio.BUILTIN_STATIONS))

    def test_search_uses_directory(self):
        fake = lambda url: [{"name": "Found", "url_resolved": "https://x", "votes": 9}]
        self.assertEqual(radio.search_stations("found", fetcher=fake)[0]["name"], "Found")

    def test_volume_clamp(self):
        self.assertEqual(radio.clamp_volume(150), 1.0)
        self.assertEqual(radio.clamp_volume(-3), 0.0)
        self.assertEqual(radio.clamp_volume("junk"), 0.5)
        self.assertEqual(radio.clamp_volume(25), 0.25)

    def test_format_list(self):
        self.assertIn("No stations", radio.format_station_list([]))
        self.assertIn("1. A", radio.format_station_list([{"name": "A", "genre": "jazz", "country": "UK"}]))


class FakeMCServer(threading.Thread):
    """Minimal SLP server speaking just enough protocol for ping_server."""

    def __init__(self):
        super().__init__(daemon=True)
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.sock.listen(1)

    def run(self):
        conn, _ = self.sock.accept()
        buf = bytearray()

        def read_exact(n):
            while len(buf) < n:
                chunk = conn.recv(65536)
                if not chunk:
                    raise ConnectionError("closed")
                buf.extend(chunk)
            out = bytes(buf[:n])
            del buf[:n]
            return out

        def read_varint():
            num = 0
            for i in range(5):
                b = read_exact(1)[0]
                num |= (b & 0x7F) << (7 * i)
                if not (b & 0x80):
                    return num
            raise ValueError("varint")

        def read_packet():
            length = read_varint()
            return read_exact(length)

        read_packet()  # handshake
        read_packet()  # status request
        status = {"description": {"text": "§aFake World", "extra": [{"text": " rocks"}]},
                  "players": {"online": 2, "max": 20, "sample": [{"name": "rockcrusherG"}, {"name": "Friend"}]},
                  "version": {"name": "1.18.2", "protocol": 758}}
        payload = mc.encode_string(json.dumps(status))
        conn.sendall(mc.make_packet(0x00, payload))
        ping_packet = read_packet()  # packet id byte + 8-byte token
        conn.sendall(mc.make_packet(0x01, ping_packet[1:9]))
        import time as _t
        _t.sleep(0.2)
        conn.close()
        self.sock.close()


class MCTests(unittest.TestCase):
    def test_parse_address(self):
        self.assertEqual(mc.parse_address("example.com"), ("example.com", 25565))
        self.assertEqual(mc.parse_address("example.com:25566"), ("example.com", 25566))
        self.assertEqual(mc.parse_address("fried-checked.tun.ply.gg"), ("fried-checked.tun.ply.gg", 25565))
        self.assertEqual(mc.parse_address("[::1]:25570"), ("::1", 25570))
        with self.assertRaises(ValueError):
            mc.parse_address("  ")

    def test_varint_roundtrip(self):
        for value in (0, 1, 127, 128, 25565, 754, 2**31 - 1):
            data = mc.encode_varint(value)
            it = iter(data)
            self.assertEqual(mc.decode_varint(lambda: next(it)), value)

    def test_flatten_and_strip(self):
        node = {"text": "§cRed ", "extra": [{"text": "§bBlue"}]}
        self.assertEqual(mc.strip_formatting(mc.flatten_text(node)), "Red Blue")
        self.assertEqual(mc.flatten_text("plain"), "plain")

    def test_parse_status(self):
        out = mc.parse_status({"description": "Hi", "players": {"online": 1, "max": 5},
                               "version": {"name": "1.20"}})
        self.assertEqual((out["online"], out["max"], out["version"]), (1, 5, "1.20"))

    def test_ping_fake_server_end_to_end(self):
        server = FakeMCServer()
        server.start()
        status = mc.ping_server("127.0.0.1", server.port, timeout=5)
        self.assertEqual(status["motd"], "Fake World rocks")
        self.assertEqual(status["online"], 2)
        self.assertEqual(status["players"], ["rockcrusherG", "Friend"])
        self.assertEqual(status["version"], "1.18.2")
        self.assertGreaterEqual(status["latency_ms"], 0)

    def test_ping_offline_raises(self):
        with self.assertRaises(OSError):
            mc.ping_server("127.0.0.1", 1, timeout=2)

    def test_server_book(self):
        with tempfile.TemporaryDirectory() as d:
            book = mc.ServerBook(Path(d) / "s.json")
            book.add(42, "Horror", "fried-checked.tun.ply.gg")
            book.add(42, "Normal", "mc.example.com:25566")
            self.assertEqual(book.get(42, "horror")["port"], 25565)
            self.assertEqual(book.get(42, "normal")["port"], 25566)
            book2 = mc.ServerBook(Path(d) / "s.json")
            self.assertEqual(len(book2.list(42)), 2)
            self.assertTrue(book2.remove(42, "horror"))
            self.assertFalse(book2.remove(42, "horror"))


class GuardTests(unittest.TestCase):
    def test_duration(self):
        self.assertEqual(guard.parse_duration("10m"), 600)
        self.assertEqual(guard.parse_duration("2h"), 7200)
        self.assertEqual(guard.parse_duration("1d"), 86400)
        self.assertEqual(guard.parse_duration("99w"), 28 * 86400)  # clamp
        self.assertIsNone(guard.parse_duration("soon"))
        self.assertIsNone(guard.parse_duration("0m"))

    def test_word_filter_and_leet(self):
        self.assertEqual(guard.find_blocked_word("you b4dw0rd person", ["badword"]), "badword")
        self.assertIsNone(guard.find_blocked_word("a perfectly fine message", ["badword"]))
        self.assertIsNone(guard.find_blocked_word("badwordsmith is a job", ["badword"]))  # whole word

    def test_spam_flood(self):
        tracker = guard.SpamTracker(max_msgs=5, window_seconds=5)
        hit = None
        for i in range(5):
            hit = tracker.check(1, 2, f"msg {i}", now=100 + i * 0.5)
        self.assertEqual(hit, "flood")

    def test_spam_repeat(self):
        tracker = guard.SpamTracker(max_msgs=99, repeat_limit=3)
        hit = None
        for i in range(3):
            hit = tracker.check(1, 2, "same", now=100 + i * 10)
        self.assertEqual(hit, "repeat")

    def test_spam_normal_traffic_ok(self):
        tracker = guard.SpamTracker()
        for i in range(3):
            self.assertIsNone(tracker.check(1, 2, f"hello {i}", now=100 + i * 10))

    def test_store(self):
        with tempfile.TemporaryDirectory() as d:
            store = guard.GuardStore(Path(d) / "g.json")
            self.assertEqual(store.add_warning(1, 9, "spam", 5), 1)
            self.assertEqual(store.add_warning(1, 9, "caps", 5), 2)
            self.assertEqual([w["reason"] for w in store.get_warnings(1, 9)], ["spam", "caps"])
            store2 = guard.GuardStore(Path(d) / "g.json")
            self.assertEqual(len(store2.get_warnings(1, 9)), 2)
            self.assertEqual(store2.clear_warnings(1, 9), 2)
            self.assertTrue(store.add_blocked_word(1, "dang"))
            self.assertFalse(store.add_blocked_word(1, "DANG"))
            self.assertTrue(store.remove_blocked_word(1, "dang"))
            store.set_setting(1, "welcome_channel", 777)
            self.assertEqual(store.get_setting(1, "welcome_channel"), 777)


class ArcadeTests(unittest.TestCase):
    def test_dice(self):
        rng = random.Random(7)
        out = arcade.roll_dice("2d6+3", rng)
        self.assertEqual(len(out["rolls"]), 2)
        self.assertEqual(out["total"], sum(out["rolls"]) + 3)
        self.assertTrue(all(1 <= r <= 6 for r in out["rolls"]))
        self.assertEqual(arcade.roll_dice("d20", random.Random(1))["modifier"], 0)
        with self.assertRaises(ValueError):
            arcade.roll_dice("not dice")
        with self.assertRaises(ValueError):
            arcade.roll_dice("100d6")
        with self.assertRaises(ValueError):
            arcade.roll_dice("1d1")

    def test_rps_matrix(self):
        self.assertEqual(arcade.rps_result("rock", "scissors"), "win")
        self.assertEqual(arcade.rps_result("rock", "paper"), "lose")
        self.assertEqual(arcade.rps_result("paper", "paper"), "tie")

    def test_trivia_integrity(self):
        self.assertGreaterEqual(len(arcade.TRIVIA), 20)
        for q, answers, correct in arcade.TRIVIA:
            self.assertEqual(len(answers), 4)
            self.assertTrue(0 <= correct < 4)
        rng = random.Random(3)
        for _ in range(30):
            t = arcade.pick_trivia(rng)
            self.assertEqual(len(t["answers"]), 4)
            self.assertTrue(0 <= t["correct_index"] < 4)

    def test_eight_ball(self):
        self.assertIn(arcade.eight_ball(random.Random(1)), arcade.EIGHT_BALL)

    def test_remind_parse(self):
        self.assertEqual(arcade.parse_remind_after("30m"), 1800)
        self.assertIsNone(arcade.parse_remind_after("5s"))   # too soon
        self.assertIsNone(arcade.parse_remind_after("99d"))  # too far
        self.assertIsNone(arcade.parse_remind_after("later"))

    def test_poll(self):
        self.assertEqual(arcade.parse_poll_options(" a | b || c "), ["a", "b", "c"])
        self.assertEqual(arcade.parse_poll_options("x|y|z|w|v|u"), ["x", "y", "z", "w", "v"])
        text = arcade.tally_poll(["a", "b"], [3, 1])
        self.assertIn("75%", text)

    def test_store_scores_and_reminders(self):
        with tempfile.TemporaryDirectory() as d:
            store = arcade.ArcadeStore(Path(d) / "a.json")
            self.assertEqual(store.add_points(1, 9, "Isaiah", 10), 10)
            self.assertEqual(store.add_points(1, 9, "Isaiah", 5), 15)
            store.add_points(1, 8, "Friend", 20)
            board = store.leaderboard(1)
            self.assertEqual([r["name"] for r in board], ["Friend", "Isaiah"])
            rem = store.add_reminder(9, 55, "start the server", due_ts=1000)
            self.assertEqual(store.due_reminders(now=999), [])
            self.assertEqual(len(store.due_reminders(now=1000)), 1)
            self.assertTrue(store.cancel_reminder(9, rem["id"]))
            store.add_reminder(9, 55, "again", due_ts=500)
            popped = store.pop_due(now=600)
            self.assertEqual(len(popped), 1)
            self.assertEqual(store.list_reminders(9), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
