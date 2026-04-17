@echo off
setlocal

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
cd /d "%ROOT%"

set "MAX_RUNS=100"
set "HOURS=8"

if not "%~1"=="" set "MAX_RUNS=%~1"
if not "%~2"=="" set "HOURS=%~2"

set "PYTHON_CMD=python"
where python >nul 2>nul
if errorlevel 1 (
  set "PYTHON_CMD=py -3"
)

echo [sub-PHD] Root: %ROOT%
echo [sub-PHD] Resuming existing runtime state...

echo [sub-PHD] Starting dashboard...
start "sub-PHD Dashboard" cmd /k %PYTHON_CMD% scripts\research_dashboard.py --workdir "%ROOT%" --port 0

echo [sub-PHD] Resuming autoloop with --max-runs %MAX_RUNS% --hours %HOURS%
%PYTHON_CMD% scripts\research_autoloop.py --workdir "%ROOT%" --max-runs %MAX_RUNS% --hours %HOURS%
set "AUTOLOOP_RC=%ERRORLEVEL%"

if not "%AUTOLOOP_RC%"=="0" (
  echo.
  echo [sub-PHD] Autoloop exited with code %AUTOLOOP_RC%.
  echo [sub-PHD] The window will stay open so you can read the error.
  pause >nul
)

endlocal & exit /b %AUTOLOOP_RC%
