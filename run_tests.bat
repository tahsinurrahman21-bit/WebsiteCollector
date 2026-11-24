@echo off
setlocal
cd /d "%~dp0"
set "TEMP=%~dp0temp"
set "TMP=%~dp0temp"
set "PLAYWRIGHT_BROWSERS_PATH=%~dp0browser_data\browsers"
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONUTF8=1"
set "QT_QPA_PLATFORM=offscreen"
".venv\Scripts\python.exe" -m unittest discover -s tests -v
pause
