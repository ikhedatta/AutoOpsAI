@echo off
REM =============================================================================
REM AutoOps AI — Stop Application (Windows)
REM =============================================================================
setlocal EnableDelayedExpansion

cd /d "%~dp0"

set PID_FILE=.autoops.pid

echo.
echo ===== AutoOps AI — Stopping =====
echo.

REM --- Try PID file first ---
if exist "%PID_FILE%" (
    set /p PID=<"%PID_FILE%"
    if "!PID!"=="unknown" goto :killbyname
    echo Stopping server ^(PID !PID!^)...
    taskkill /PID !PID! /T /F >nul 2>&1
    if !errorlevel! equ 0 (
        echo [OK] Process !PID! stopped
    ) else (
        echo [!] Process !PID! was not running
    )
    del /f "%PID_FILE%" >nul 2>&1
)

:killbyname
REM --- Kill any uvicorn processes for our app using PowerShell ---
echo Cleaning up any remaining processes...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*uvicorn*agent.main*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Write-Host \"  Stopped PID $($_.ProcessId)\" }"

if exist "%PID_FILE%" del /f "%PID_FILE%" >nul 2>&1

echo.
echo ==========================================
echo  AutoOps AI stopped
echo ==========================================
echo.

endlocal
