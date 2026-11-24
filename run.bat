@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo Please double-click setup.bat first. It prepares Website Collector.
  pause
  exit /b 1
)
if not exist "%~dp0temp" mkdir "%~dp0temp"
set "TEMP=%~dp0temp"
set "TMP=%~dp0temp"
set "TMPDIR=%~dp0temp"
set "PLAYWRIGHT_BROWSERS_PATH=%~dp0browser_data\browsers"
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONUTF8=1"
"%~dp0.venv\Scripts\python.exe" -m app.main --root "%~dp0."
if errorlevel 1 pause
