@echo off
title Fleet Manager -- Install LOCAL app
color 0A
cd /d "%~dp0"

echo.
echo  +============================================================+
echo  ^|   LOCAL SERVER APP -- USB phone pe install                 ^|
echo  +============================================================+
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-mobile-app.ps1" -Mode Local -Pause
exit /b %ERRORLEVEL%
