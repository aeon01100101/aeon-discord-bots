@echo off
rem Starts every bot that has a .env file, each in its own window.
cd /d %~dp0
for %%B in (radio-bot mc-bot guard-bot arcade-bot) do (
  if exist "%%B\.env" (
    start "%%B" cmd /k "cd /d %~dp0%%B && python -m pip install -q -r requirements.txt && python bot.py"
  ) else (
    echo Skipping %%B - no .env file yet ^(see SETUP.md^)
  )
)
echo.
echo Bots with a .env file were started in their own windows.
pause
