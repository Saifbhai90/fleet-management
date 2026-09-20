@echo off
title Fleet Manager -- Install Mobile App
color 0A
cd /d "%~dp0"

echo.
echo  +============================================================+
echo  ^|   FLEET MANAGER -- Phone pe app install (USB)              ^|
echo  +============================================================+
echo.
echo    1) LOCAL   - laptop server + local app
echo    2) ONLINE  - Render server + online app
echo.

choice /C 12 /N /M "  Kaunsi app? (1=Local, 2=Online): "
if errorlevel 2 (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-mobile-app.ps1" -Mode Online -Pause
    exit /b %ERRORLEVEL%
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-mobile-app.ps1" -Mode Local -Pause
exit /b %ERRORLEVEL%
