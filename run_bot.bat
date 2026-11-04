@echo off
title Telegram License Bot - @kun_amra
echo.
echo ============================================================
echo   TELEGRAM ADDER PRO - LICENSE BOT
echo   Admin: @kun_amra
echo ============================================================
echo.

REM Check if .env exists
if not exist ".env" (
    echo [!] .env file not found!
    echo     Copy .env.example to .env and add your BOT_TOKEN
    echo.
    pause
    exit /b 1
)

echo Starting bot...
python bot.py
echo.
pause

