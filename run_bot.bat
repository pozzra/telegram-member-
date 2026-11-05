@echo off
title Telegram License Bot - @kun_amra
echo.
echo ============================================================
echo   TELEGRAM ADDER PRO - LICENSE BOT (AUTO-RESTARTING)
echo   Admin: @kun_amra
echo ============================================================
echo.

:loop
echo Starting bot...
python bot.py
echo.
echo [!] Bot process ended. Auto-restarting in 3 seconds... (Ctrl+C to stop)
timeout /t 3 >nul
goto loop

