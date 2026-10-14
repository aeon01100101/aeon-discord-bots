# Aeon Discord Bots Pack v1.0

Four self-hosted Discord bots for you and your friend's server.
They run on **your PC** — no paid services, no accounts to rent, no telemetry.
Each bot is its own folder with its own Discord token, so you can run
one, some, or all of them. Together with the AeonAI bot you already have,
that's a full 5-bot crew.

| Bot | Folder | What it does |
|---|---|---|
| 🎵 **Aeon Radio** | `radio-bot/` | Plays internet radio in a voice channel — search the same Radio Browser directory the Aeon Radio app uses, queue stations, volume control |
| ⛏️ **Aeon MC** | `mc-bot/` | Minecraft server status: who's online, MOTD, version, ping. Save servers by label (playit.gg tunnel addresses work), optional up/down announcements every 5 min |
| 🛡️ **Aeon Guard** | `guard-bot/` | Moderation: warn / kick / ban / timeout / clear / slowmode, welcome messages, mod-log channel, blocked-word filter, anti-spam |
| 🕹️ **Aeon Arcade** | `arcade-bot/` | Trivia with a server leaderboard, rock-paper-scissors, dice, polls, reminders, 8-ball |

## Quick start (full walkthrough in SETUP.md)

1. In the Discord Developer Portal, make **one application per bot**
   (Discord makes each bot its own account — that's normal).
2. In each bot's folder, copy `.env.example` to `.env` and paste that
   bot's token in.
3. Double-click that bot's `run.bat` (Windows) — or run `start-all.bat`
   here in the pack folder to launch every bot you've set up.

## Good to know

- **ffmpeg** must be installed on the PC for the Radio Bot
  (SETUP.md §5 shows the 1-minute install). The other bots don't need it.
- The Guard Bot needs two switches ON in the Developer Portal:
  **Server Members Intent** and **Message Content Intent**.
- Everything the bots remember (warnings, saved MC servers, trivia
  points, reminders) lives in plain JSON files in each bot's `data/`
  folder on your PC. Nothing leaves your machine except Discord itself.
- Reminders and trivia points survive restarts. Radio queues don't
  (they're just music).

## Commands at a glance

**Radio:** `/play` `/search` `/stations` `/nowplaying` `/stop` `/leave` `/volume`
**MC:** `/status` `/addserver` `/removeserver` `/servers` `/watch` `/unwatch`
**Guard:** `/warn` `/warnings` `/clearwarnings` `/kick` `/ban` `/timeout` `/clear` `/slowmode` `/setwelcome` `/setlog` `/blockword` `/unblockword` `/automod`
**Arcade:** `/trivia` `/leaderboard` `/rps` `/roll` `/flip` `/choose` `/8ball` `/poll` `/endpoll` `/remind` `/reminders` `/cancelreminder`
