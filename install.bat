@echo off
chcp 65001 >nul 2>&1
title MengAI Translator Installer
setlocal

REM ============================================================
REM   MengAI Translator for BiliBili Live - tiny portable installer
REM
REM   Downloads the portable package (bundled Python runtime,
REM   no Python required), unpacks it, creates a desktop
REM   shortcut, and asks whether to install Pillow.
REM
REM   It installs into a "MengAI-chan" folder created next to
REM   this install.bat, so put install.bat in the folder where
REM   you want the app to live. -BaseDir passes that folder to
REM   install.ps1 (needed because the remote copy of install.ps1
REM   runs from a temp file and cannot work it out by itself).
REM   Override with -Dest "D:\MengAI"; also -Pillow Yes|No|Ask,
REM   -NoShortcut, -ShortcutDir, -ShortcutName.
REM
REM   All the real work lives in install.ps1. That file is UTF-8
REM   WITH BOM, because Windows PowerShell reads BOM-less files as
REM   ANSI and would garble the Japanese text inside it.
REM
REM   That BOM is also why the remote copy is saved to a temp file
REM   and then run with -File, instead of being piped into
REM   Invoke-Expression: .Content keeps the BOM as the first
REM   character, and Invoke-Expression then fails to recognise the
REM   leading <# ... #> comment block and tries to parse the
REM   Japanese comment text as code. Running it as a file also
REM   lets -Dest / -Pillow and friends reach install.ps1's
REM   param() block properly.
REM
REM   This file stays pure ASCII on purpose: a .bat whose bytes are
REM   not ASCII gets mis-parsed by cmd.exe on non-UTF8 codepages.
REM
REM   PS1_URL points at this repository (install.ps1 from raw).
REM ============================================================

set "PS1_URL=https://raw.githubusercontent.com/YukiMiku/MengAI_Translator_BiliBili_Live/main/install.ps1"

echo ============================================================
echo    MengAI Translator for BiliBili Live
echo ============================================================
echo.
echo    Installs a self-contained copy (bundled Python runtime).
echo    It installs into a new folder beside this install.bat.
echo    Nothing else needs to be installed beforehand.
echo.

where powershell.exe >nul 2>&1
if errorlevel 1 (
    echo [ERROR] powershell.exe was not found.
    echo         Windows 10 or newer is required.
    echo.
    pause
    exit /b 1
)

REM %~dp0 always ends with a backslash. Passing that straight into
REM   -BaseDir "C:\path\"   makes PowerShell read the \" as an
REM escaped quote, so the string never closes and every following
REM argument gets swallowed. Strip the trailing backslash first.
set "BASEDIR=%~dp0"
if "%BASEDIR:~-1%"=="\" set "BASEDIR=%BASEDIR:~0,-1%"
REM In a drive root (D:\) keep one backslash, or Join-Path breaks.
if "%BASEDIR:~-1%"==":" set "BASEDIR=%BASEDIR%\"

REM If install.ps1 sits next to this file, use it directly
REM (works offline, and is how the local test runs).
set "LOCALPS1=%~dp0install.ps1"
if exist "%LOCALPS1%" (
    echo [1/1] Using local install.ps1 ...
    echo.
    powershell -NoProfile -ExecutionPolicy Bypass -File "%LOCALPS1%" -BaseDir "%BASEDIR%" %*
    set "RC=%errorlevel%"
    endlocal & exit /b %RC%
)

echo [1/2] Downloading installer script ...
set "TMPPS1=%TEMP%\mengai-install-%RANDOM%.ps1"
if exist "%TMPPS1%" del "%TMPPS1%" >nul 2>&1

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ProgressPreference='SilentlyContinue'; try { Invoke-WebRequest -Uri '%PS1_URL%' -UseBasicParsing -OutFile '%TMPPS1%' } catch { Write-Host ''; Write-Host ('Download failed: ' + $_.Exception.Message) -ForegroundColor Red; exit 1 }"

if errorlevel 1 (
    echo.
    echo [ERROR] Could not fetch the installer script.
    echo         URL: %PS1_URL%
    echo.
    echo         If you already downloaded the portable zip manually,
    echo         just unpack it and run the launcher inside.
    echo.
    pause
    exit /b 1
)

if not exist "%TMPPS1%" (
    echo.
    echo [ERROR] The installer script could not be saved.
    echo.
    pause
    exit /b 1
)

echo [2/2] Running installer ...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%TMPPS1%" -BaseDir "%BASEDIR%" %*
set "RC=%errorlevel%"
del "%TMPPS1%" >nul 2>&1
endlocal & exit /b %RC%
