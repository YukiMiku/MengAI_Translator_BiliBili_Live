@echo off
setlocal
cd /d "%~dp0"
title MengAI Translator v1.2.0 (set by app.py)

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY (
  where py >nul 2>nul && set "PY=py"
)

if not defined PY (
  echo.
  echo ============================================================
  echo  [ERROR] Python not found
  echo ============================================================
  echo.
  echo Please install OFFICIAL Python 3.9+ from python.org
  echo   https://www.python.org/downloads/windows/
  echo.
  echo During setup check BOTH boxes:
  echo   [x] tcl/tk and IDLE
  echo   [x] Add python.exe to PATH
  echo.
  echo Then run start.bat again.
  echo.
  pause
  exit /b 1
)

echo Using Python: %PY%
%PY% -c "import sys;print('Python',sys.version.split()[0]);print(sys.executable)"
echo.
echo Starting MengAI Translator v1.2.0 ... keep this window open, errors will show here.
echo ------------------------------------------------------------
%PY% app.py
if errorlevel 1 echo [ERROR] app.py exited with a non-zero code.
echo ------------------------------------------------------------
echo.
echo Program exited. If an error is shown above, screenshot it.
echo.
pause
exit /b 0
