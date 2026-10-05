@echo off
rem Same as the Chinese-named launcher; ASCII-only on purpose.
setlocal
cd /d "%~dp0"
title Launch browser in debug mode

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY (
  where py >nul 2>nul && set "PY=py"
)

if not defined PY (
  echo [ERROR] Python not found.
  echo Install official Python 3.9+ from python.org
  pause
  exit /b 1
)

%PY% launch_browser.py
echo.
pause
exit /b 0
