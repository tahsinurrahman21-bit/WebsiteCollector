@echo off
setlocal
cd /d "%~dp0"
set "TEMP=%~dp0temp"
set "TMP=%~dp0temp"
set "PLAYWRIGHT_BROWSERS_PATH=%~dp0browser_data\browsers"
set "PYTHONUTF8=1"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m app.diagnostics
pause
