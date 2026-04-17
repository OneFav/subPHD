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
echo [sub-PHD] Resetting runtime state...
%PYTHON_CMD% -c "from pathlib import Path; from scripts.research_agent_cli import load_project_config; from scripts.research_loop_contract import bootstrap_state_artifacts, reset_runtime_state; root = Path(r'%ROOT%'); config = load_project_config(root); paths = bootstrap_state_artifacts(root, config); reset_runtime_state(paths, config, reason='start_bat_fresh_start'); print('[sub-PHD] Runtime reset complete:', paths.runtime_root)"
if errorlevel 1 (
  set "AUTOLOOP_RC=%ERRORLEVEL%"
  echo.
  echo [sub-PHD] Runtime reset failed with code %AUTOLOOP_RC%.
  pause >nul
  endlocal & exit /b %AUTOLOOP_RC%
)

echo [sub-PHD] Starting dashboard...
start "sub-PHD Dashboard" cmd /k %PYTHON_CMD% scripts\research_dashboard.py --workdir "%ROOT%" --port 0

echo [sub-PHD] Starting autoloop with --max-runs %MAX_RUNS% --hours %HOURS% --ignore-state
%PYTHON_CMD% scripts\research_autoloop.py --workdir "%ROOT%" --max-runs %MAX_RUNS% --hours %HOURS% --ignore-state
set "AUTOLOOP_RC=%ERRORLEVEL%"

if not "%AUTOLOOP_RC%"=="0" (
  echo.
  echo [sub-PHD] Autoloop exited with code %AUTOLOOP_RC%.
  echo [sub-PHD] The window will stay open so you can read the error.
  pause >nul
)

endlocal & exit /b %AUTOLOOP_RC%
