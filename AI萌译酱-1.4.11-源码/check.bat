@echo off
rem Same as the Chinese-named diagnostic launcher; kept ASCII-only on purpose.
setlocal
cd /d "%~dp0"
title AI MengYiJiang self-check

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY (
  where py >nul 2>nul && set "PY=py"
)

if not defined PY (
  echo.
  echo [ERROR] Python not found.
  echo Install official Python 3.9+ from python.org
  echo and check "Add python.exe to PATH".
  echo.
  pause
  exit /b 1
)

%PY% selfcheck.py
echo.
pause
exit /b 0
