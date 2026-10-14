@echo off
cd /d %~dp0
if not exist .env (
  echo Copy .env.example to .env and put your Arcade Bot token in it first.
  pause
  exit /b 1
)
python -m pip install -r requirements.txt
python bot.py
pause
