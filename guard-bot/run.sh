#!/bin/sh
cd "$(dirname "$0")"
[ -f .env ] || { echo "Copy .env.example to .env and put your Guard Bot token in it first."; exit 1; }
exec python3 bot.py
