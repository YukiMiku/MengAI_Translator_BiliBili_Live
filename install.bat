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
REM   All the real work lives in install.ps1 (UTF-8 with BOM,
REM   so Chinese paths/names survive). This file stays pure
REM   ASCII on purpose: a .bat whose bytes are not ASCII gets
REM   mis-parsed by cmd.exe on non-UTF8 codepages.
REM
REM   Point PS1_URL at your own repository after uploading.
REM ============================================================

set "PS1_URL=https://raw.githubusercontent.com/YOUR-NAME/YOUR-REPO/main/install.ps1"

echo ============================================================
echo    MengAI Translator for BiliBili Live
echo ============================================================
echo.
echo    Installs a self-contained copy (bundled Python runtime).
echo    No admin rights needed - it goes into your own user folder.
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

REM If install.ps1 sits next to this file, use it directly
REM (works offline, and is how the local test runs).
set "LOCALPS1=%~dp0install.ps1"
if exist "%LOCALPS1%" (
    echo [1/1] Using local install.ps1 ...
    echo.
    powershell -NoProfile -ExecutionPolicy Bypass -File "%LOCALPS1%" %*
    set "RC=%errorlevel%"
    endlocal & exit /b %RC%
)

echo [1/1] Downloading installer script ...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ProgressPreference='SilentlyContinue'; try { $s = (Invoke-WebRequest -Uri '%PS1_URL%' -UseBasicParsing).Content } catch { Write-Host ''; Write-Host ('Download failed: ' + $_.Exception.Message) -ForegroundColor Red; exit 1 }; Invoke-Expression $s"
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
endlocal