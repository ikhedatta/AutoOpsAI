@echo off
REM =============================================================================
REM AutoOps AI — Start Application (Windows)
REM =============================================================================
setlocal EnableDelayedExpansion

cd /d "%~dp0"

set PORT=8000
set HOST=127.0.0.1
set PID_FILE=.autoops.pid

echo.
echo ===== AutoOps AI — Starting =====
echo.

REM --- Check if already running ---
if exist "%PID_FILE%" (
    set /p OLD_PID=<"%PID_FILE%"
    tasklist /FI "PID eq !OLD_PID!" 2>nul | findstr /i "python uvicorn" >nul 2>&1
    if !errorlevel! equ 0 (
        echo [!] AutoOps AI is already running ^(PID !OLD_PID!^)
        echo     Dashboard: http://%HOST%:%PORT%
        echo     Run stop.bat to stop it first.
        exit /b 1
    ) else (
        del /f "%PID_FILE%" >nul 2>&1
    )
)

REM --- Check MongoDB ---
echo Checking MongoDB...
uv run python -c "import pymongo; pymongo.MongoClient('mongodb://localhost:27017', serverSelectionTimeoutMS=3000).server_info(); print('  [OK] MongoDB running')" 2>nul
if %errorlevel% neq 0 (
    echo   [X] MongoDB not reachable at localhost:27017
    echo       Start MongoDB before running AutoOps AI.
    exit /b 1
)

REM --- Check LLM Provider ---
for /f "tokens=1,2 delims==" %%a in ('findstr /i "^LLM_PROVIDER=" .env 2^>nul') do set "LLM_PROVIDER=%%b"
if not defined LLM_PROVIDER set "LLM_PROVIDER=ollama"
if /i "!LLM_PROVIDER!"=="github" (
    echo Checking GitHub Models API...
    for /f "tokens=1,2 delims==" %%a in ('findstr /i "^GITHUB_MODELS_ENDPOINT=" .env 2^>nul') do set "GH_ENDPOINT=%%b"
    if not defined GH_ENDPOINT set "GH_ENDPOINT=https://models.inference.ai.azure.com"
    curl -sf "!GH_ENDPOINT!" >nul 2>&1
    if !errorlevel! equ 0 (
        echo   [OK] GitHub Models API reachable
    ) else (
        echo   [!] GitHub Models API not reachable ^(LLM features may be unavailable^)
    )
) else (
    echo Checking Ollama...
    for /f "tokens=1,2 delims==" %%a in ('findstr /i "^OLLAMA_HOST=" .env 2^>nul') do set "OLLAMA_URL=%%b"
    if not defined OLLAMA_URL set "OLLAMA_URL=http://localhost:11434"
    for /f "tokens=1" %%u in ("!OLLAMA_URL!") do set "OLLAMA_URL=%%u"
    curl -sf "!OLLAMA_URL!/api/tags" >nul 2>&1
    if !errorlevel! equ 0 (
        echo   [OK] Ollama running
    ) else (
        echo   [!] Ollama not reachable ^(LLM features will be unavailable^)
    )
)

REM --- Check Docker ---
echo Checking Docker...
docker info >nul 2>&1
if %errorlevel% equ 0 (
    echo   [OK] Docker running
) else (
    echo   [!] Docker not running ^(provider will operate in degraded mode^)
)

REM --- Install dependencies ---
echo.
echo Installing Python dependencies...
uv sync --quiet 2>nul
if %errorlevel% neq 0 uv sync

REM --- Build frontend ---
echo.
echo Building frontend...
if exist "frontend\package.json" (
    pushd frontend
    if not exist node_modules (
        echo   Installing npm dependencies...
        call npm install --silent >nul 2>&1
        if !errorlevel! neq 0 (
            echo   [!] npm install failed — frontend may be stale
        )
    )
    call npx vite build >nul 2>&1
    if !errorlevel! equ 0 (
        echo   [OK] Frontend built successfully
    ) else (
        echo   [!] Frontend build failed — serving last build
    )
    popd
) else (
    echo   [!] No frontend/package.json found — skipping build
)

REM --- Start server ---
echo.
echo Starting AutoOps AI server...

start /b cmd /c "uv run uvicorn agent.main:app --host %HOST% --port %PORT% > autoops.log 2>&1"

REM --- Wait for server ---
echo Waiting for server...
set READY=0
for /l %%i in (1,1,60) do (
    if !READY! equ 0 (
        curl -sf "http://%HOST%:%PORT%/api/v1/health" >nul 2>&1
        if !errorlevel! equ 0 (
            set READY=1
        ) else (
            timeout /t 2 /nobreak >nul
        )
    )
)

REM Capture PID using PowerShell (reliable)
for /f %%p in ('powershell -NoProfile -Command "(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*uvicorn*agent.main*' } | Select-Object -First 1).ProcessId"') do (
    set SERVER_PID=%%p
)

if defined SERVER_PID (
    echo %SERVER_PID%> "%PID_FILE%"
) else (
    echo unknown> "%PID_FILE%"
)

if %READY% equ 1 (
    echo.
    echo ==========================================
    echo  AutoOps AI is running!
    echo.
    echo   Dashboard:  http://%HOST%:%PORT%
    echo   API:        http://%HOST%:%PORT%/api/v1
    echo   Health:     http://%HOST%:%PORT%/api/v1/health
    echo   WebSocket:  ws://%HOST%:%PORT%/api/v1/ws/events
    if defined SERVER_PID echo   PID:        %SERVER_PID%
    echo   Logs:       type autoops.log
    echo.
    echo   Run stop.bat to stop the server.
    echo ==========================================
) else (
    echo.
    echo [X] Server failed to start within 120s
    echo     Check logs: type autoops.log
    exit /b 1
)

endlocal
