@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
if errorlevel 1 (
  echo.
  echo Setup did not finish. Read the message above, then run setup.bat again.
  pause
  exit /b 1
)
echo.
echo Setup finished. Double-click run.bat to open Website Collector.
pause
