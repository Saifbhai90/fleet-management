@echo off
title Fleet Manager -- Mobile Local Server
color 0A
cd /d "%~dp0"

echo.
echo  +============================================================+
echo  ^|   MOBILE LOCAL SERVER -- USB link (no install)             ^|
echo  +============================================================+
echo.
echo    USB nikalne ke baad yahi file chalao.
echo    Ye window khuli rakho - cable wapas lagte hi server link lag jata hai.
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-mobile-local.ps1"
exit /b %ERRORLEVEL%
