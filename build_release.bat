@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_release.ps1" %*
if errorlevel 1 (
  echo.
  echo The release build failed. Read the message above.
  pause
  exit /b 1
)
echo.
echo Release build finished. The ZIP is in the "release" folder.
pause
