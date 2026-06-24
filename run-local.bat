@echo off
title Fleet Management -- Local Dev Server
color 0A

:: Navigate to project directory
cd /d "%~dp0"

echo.
echo  +============================================================+
echo  ^|     FLEET MANAGEMENT -- Local Development Launcher         ^|
echo  ^|     Production Sync + Local Server (One Click)             ^|
echo  +============================================================+
echo.

:: Check Python
where python >nul 2>&1
if ERRORLEVEL 1 (
    echo  [ERROR] Python not found in PATH. Please install Python 3.10+
    pause
    exit /b 1
)

:: Create required directories
if not exist "db" mkdir db
if not exist "logs" mkdir logs

:: Check .env.local
if not exist ".env.local" (
    echo  [ERROR] .env.local not found!
    echo  Create .env.local and fill in your Render DB URL.
    pause
    exit /b 1
)

:: ================================================================
::  STEP 1: USER MODE SELECTION
:: ================================================================
echo  ------------------------------------------------------------
echo   SELECT STARTUP MODE:
echo  ------------------------------------------------------------
echo.
echo    1) FAST RUN   - Skip sync, use existing local DB instantly
echo    2) FULL SYNC  - Pull latest data from Render, then start
echo.

choice /C 12 /N /M "  Enter choice (1 or 2): "
set USER_MODE=%ERRORLEVEL%

:: Read LOCAL_PORT from .env.local (default 5050)
set LOCAL_PORT=5050
for /f "usebackq tokens=1,2 delims==" %%a in (".env.local") do (
    if /i "%%a"=="LOCAL_PORT" (
        set "LOCAL_PORT=%%b"
    )
)

:: Read SECRET_KEY from .env.local
set SECRET_KEY=local-dev-secret-key
for /f "usebackq tokens=1,2 delims==" %%a in (".env.local") do (
    if /i "%%a"=="SECRET_KEY" (
        set "SECRET_KEY=%%b"
    )
)

:: ── Set environment for local development (SINGLE SOURCE OF TRUTH) ──
set DATABASE_URL=sqlite:///db/local.db
set FLASK_DEBUG=1
set SESSION_COOKIE_SECURE=false
set LOCAL_DB_GUARANTEED=1

:: ── Detect rogue DB files (warn user) ──
set ROGUE_FOUND=0
if exist "instance\local_test.db" set ROGUE_FOUND=1
if exist "company_management.db" set ROGUE_FOUND=1
if exist "instance\company_management.db" set ROGUE_FOUND=1
if %ROGUE_FOUND%==1 (
    echo.
    echo  [WARNING] Rogue database files detected!
    echo  These old DB files can cause confusion:
    if exist "instance\local_test.db" echo    - instance\local_test.db
    if exist "company_management.db" echo    - company_management.db
    if exist "instance\company_management.db" echo    - instance\company_management.db
    echo  ONLY db\local.db is used. You can safely delete the above files.
    echo.
)

:: ================================================================
::  ROUTE BASED ON USER CHOICE
:: ================================================================
if %USER_MODE%==1 goto :FAST_RUN
if %USER_MODE%==2 goto :FULL_SYNC

:: ================================================================
::  OPTION 1: FAST RUN (no sync)
:: ================================================================
:FAST_RUN
echo.
echo  [FAST RUN] Skipping sync -- using existing local DB
echo.

:: Check if local DB exists
if not exist "db\local.db" (
    echo  [ERROR] db\local.db does not exist!
    echo  You must run FULL SYNC at least once first.
    echo.
    echo  Switching to FULL SYNC mode...
    echo.
    goto :FULL_SYNC
)

set RUN_MODE=FAST RUN
goto :START_SERVER

:: ================================================================
::  OPTION 2: FULL SYNC (smart incremental from Render)
:: ================================================================
:FULL_SYNC
echo.
echo  ------------------------------------------------------------
echo   STEP: Syncing from Render production DB...
echo  ------------------------------------------------------------
echo.

:: Read FULL_RESET flag
set FULL_RESET_FLAG=
for /f "usebackq tokens=1,2 delims==" %%a in (".env.local") do (
    if /i "%%a"=="FULL_RESET" (
        set "FULL_RESET_FLAG=%%b"
    )
)

if /i "%FULL_RESET_FLAG%"=="true" (
    echo  [MODE] Full Reset -- rebuilding local DB from scratch
    python services\sync_master.py --full-reset
) else (
    echo  [MODE] Smart Sync -- fetching only new/updated records
    python services\sync_master.py
)

if ERRORLEVEL 1 (
    echo.
    echo  [WARNING] Sync encountered errors. Check logs/ for details.
    echo  Press any key to start server anyway, or Ctrl+C to abort...
    pause >nul
)

set RUN_MODE=FULL SYNC
goto :START_SERVER

:: ================================================================
::  START LOCAL SERVER
:: ================================================================
:START_SERVER

:: Get last sync time for debug banner
set LAST_SYNC=Never
if exist "sync_state.json" (
    for /f "tokens=2 delims=:," %%a in ('findstr "last_sync_time" sync_state.json') do (
        set "LAST_SYNC=%%~a"
    )
)

:: ── DEBUG BANNER ──
echo.
echo  ============================================================
echo   LOCAL ENV DEBUG
echo  ============================================================
echo   DB PATH  : %~dp0db\local.db
echo   LAST SYNC: %LAST_SYNC%
echo   MODE     : %RUN_MODE%
echo   PORT     : %LOCAL_PORT%
echo  ============================================================
echo.
echo  Server: http://127.0.0.1:%LOCAL_PORT%
echo  Press Ctrl+C to stop
echo.

:: Open browser after short delay
start "" cmd /c "timeout /t 3 /nobreak >nul && start http://127.0.0.1:%LOCAL_PORT%"

:: Start Flask (fresh process ensures no stale DB connections)
python -c "from app import app; app.run(debug=True, port=%LOCAL_PORT%, use_reloader=False)"

echo.
echo  Server stopped.
pause
