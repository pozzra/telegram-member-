@echo off
title Install Telegram Bot 24/7 Windows Auto-Startup
color 0A
echo.
echo ============================================================
echo   TELEGRAM ADDER PRO - 24/7 WINDOWS AUTO-STARTUP INSTALLER
echo   Bot: @tg_adder_ativations_key_bot  ^|  Admin: @kun_amra
echo ============================================================
echo.

set SCRIPT_DIR=%~dp0
set VBS_TARGET=%SCRIPT_DIR%run_bot_silent_247.vbs
set STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
set SHORTCUT_PATH=%STARTUP_FOLDER%\TelegramBot247.lnk

echo [1/3] Checking silent background runner...
if not exist "%VBS_TARGET%" (
    echo [ERROR] run_bot_silent_247.vbs not found in %SCRIPT_DIR%!
    pause
    exit /b 1
)
echo [OK] Silent runner ready.

echo.
echo [2/3] Registering auto-start in Windows Startup folder...
powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%SHORTCUT_PATH%'); $s.TargetPath = 'wscript.exe'; $s.Arguments = '\"%VBS_TARGET%\"'; $s.WorkingDirectory = '%SCRIPT_DIR%'; $s.WindowStyle = 7; $s.Save();"

if exist "%SHORTCUT_PATH%" (
    echo [OK] Auto-startup shortcut created successfully!
) else (
    echo [WARNING] Could not create shortcut automatically.
)

echo.
echo [3/3] Launching background bot right now...
wscript "%VBS_TARGET%"
echo.
echo ============================================================
echo  SUCCESS! Telegram License Bot is now running 24/7 in background!
echo  It will automatically start whenever your computer turns on.
echo ============================================================
echo.
pause

