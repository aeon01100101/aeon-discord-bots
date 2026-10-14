# Setup — plain-language walkthrough

You do this **once per bot** (4 times total, about 3 minutes each).
Discord requires every bot to be its own "application" with its own
token — that's why there are 4 tokens, not 1. Your friend doesn't need
to do any of this; only the server owner invites the bots, and only
**your PC** runs them.

## 1. Create a bot in the Developer Portal

For each bot (suggested names in brackets):

1. Go to https://discord.com/developers/applications and sign in.
2. **New Application** → name it [Aeon Radio / Aeon MC / Aeon Guard / Aeon Arcade] → Create.
3. Left sidebar → **Bot** → **Reset Token** → copy the token.
   ⚠️ Treat the token like a password. Never post it in the server.
4. **Only for Aeon Guard:** on that same Bot page, scroll to
   **Privileged Gateway Intents** and turn ON **Server Members Intent**
   and **Message Content Intent**, then Save.
5. Left sidebar → **OAuth2** → **URL Generator**:
   - Scopes: tick **bot** and **applications.commands**.
   - Bot Permissions: tick these per bot:
     - *Radio:* Connect, Speak, Send Messages, View Channel
     - *MC:* Send Messages, View Channel, Embed Links
     - *Guard:* Kick Members, Ban Members, Moderate Members,
       Manage Messages, Read Message History, Send Messages, View Channel
     - *Arcade:* Send Messages, View Channel, Add Reactions, Embed Links
   - Copy the generated URL, open it, pick **your server**, Authorize.
     (Your friend can also invite them to his server the same way —
     he'll need the Manage Server permission there.)

## 2. Put the token in the bot's folder

In the bot's folder, copy `.env.example` and rename the copy to `.env`.
Open `.env` in Notepad and paste the token after `DISCORD_TOKEN=`.
Save. One token per folder — don't mix them up.

## 3. Run it

- **One bot:** double-click its `run.bat`. First run installs what it
  needs (Python must be installed — tick "Add Python to PATH" when
  installing Python from python.org).
- **All bots at once:** double-click `start-all.bat` in this pack
  folder. It opens one window per bot that has a `.env` file.
- Leave the windows open while you want the bots online. Closing a
  window takes that bot offline — same deal as the AeonAI bot.

## 4. First-run checklist in Discord

- **Radio:** join a voice channel, then `/play lofi` — it should join
  you and start playing.
- **MC:** `/addserver label:horror address:fried-checked.tun.ply.gg`
  (use your real server/tunnel address), then `/status horror`.
  In the channel where you want up/down news: `/watch horror`.
- **Guard:** in your welcome channel run `/setwelcome`, in your
  mod-log channel run `/setlog`, then add any filter words with
  `/blockword`. Give the **Aeon Guard** role a position *above* the
  roles it should moderate (Server Settings → Roles → drag it up) —
  Discord won't let a bot kick/timeout someone with a higher role.
- **Arcade:** `/trivia` starts a game; `/remind after:10m text:test`
  proves reminders work.

## 5. ffmpeg for the Radio Bot (Windows, 1 minute)

The Radio Bot needs ffmpeg to play audio:

1. Open PowerShell and run: `winget install ffmpeg`
2. Close and reopen the bot's window.

No winget? Download the "full build" zip from gyan.dev/ffmpeg/builds,
unzip it, and add its `bin` folder to your PATH.

## Troubleshooting

- **Bot is online but slash commands don't appear:** wait a minute
  (first sync can lag), or kick and re-invite with both scopes ticked
  in §1 step 5 — missing `applications.commands` is the usual cause.
- **"DISCORD_TOKEN is missing":** the file must be named exactly `.env`
  (not `.env.txt` — in Notepad use Save As → All Files).
- **Guard can't timeout/kick someone:** role order — see §4.
- **Radio joins but no sound:** ffmpeg missing (§5), or the station is
  dead — try `/play` with a different search.
- **MC says OFFLINE but the server is up:** check the address/port, and
  that it's a **Java Edition** server (Bedrock uses a different
  protocol). Tunnel addresses must be the *public* playit.gg address.
