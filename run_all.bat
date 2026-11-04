@echo off
title Telegram Adder Pro - Launcher
echo ============================================================
echo   Starting Telegram Adder Pro: Web Server + License Bot
echo ============================================================
start "Telegram License Bot" cmd /k "python bot.py"
python start_server.py
pause

