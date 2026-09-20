@echo off
setlocal
set PORT=%~1
if "%PORT%"=="" set PORT=5050
title Fleet Local Server :%PORT%
cd /d "%~dp0.."

if not exist "db\local.db" (
    echo [ERROR] db\local.db missing. Pehle run-local.bat Fast Run chalao.
    pause
    exit /b 1
)

set DATABASE_URL=sqlite:///db/local.db
set LOCAL_DB_GUARANTEED=1
set SESSION_COOKIE_SECURE=false
set FLASK_DEBUG=0
set TEMPLATES_AUTO_RELOAD=1
set FLEET_MOBILE_DEV=1
set LOCAL_FAST_BOOT=1
set SKIP_STARTUP_TASKS=1
set PORT=%PORT%

echo.
echo ============================================================
echo  Fleet Local Server  http://127.0.0.1:%PORT%
echo  USB app isi window ke through phone pe khulti hai.
echo  Band mat karo jab tak phone use kar rahe ho.
echo ============================================================
echo.

python -u app.py
set ERR=%ERRORLEVEL%
echo.
if not "%ERR%"=="0" echo [ERROR] Server crash / band ho gaya. Code: %ERR%
pause
exit /b %ERR%
