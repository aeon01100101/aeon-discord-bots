#!/bin/sh
# Starts every bot that has a .env file, in the background.
cd "$(dirname "$0")"
for b in radio-bot mc-bot guard-bot arcade-bot; do
  if [ -f "$b/.env" ]; then
    (cd "$b" && nohup python3 bot.py > bot.log 2>&1 &)
    echo "started $b"
  else
    echo "skipping $b - no .env file yet (see SETUP.md)"
  fi
done
