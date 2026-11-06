@echo off
title Stop Telegram License Bot
echo Stopping background Telegram bot processes...
powershell -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*bot.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host 'Stopped bot process ID:' $_.ProcessId }"
echo Done.
timeout /t 2 >nul
