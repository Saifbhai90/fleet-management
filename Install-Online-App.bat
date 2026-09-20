@echo off
title Fleet Manager -- Install ONLINE app
color 0B
cd /d "%~dp0"

echo.
echo  +============================================================+
echo  ^|   ONLINE SERVER APP -- USB phone pe install                ^|
echo  +============================================================+
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-mobile-app.ps1" -Mode Online -Pause
exit /b %ERRORLEVEL%
