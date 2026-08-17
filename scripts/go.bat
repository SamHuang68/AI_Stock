@echo off
REM Compatibility shim. Canonical Windows logic lives in scripts\go.ps1.
REM This file is ASCII-only and never runs Git commands itself.
setlocal EnableExtensions
cd /d "%~dp0.."
if errorlevel 1 exit /b 1

set "PS_ARGS="
if /I "%~1"=="pull" set "PS_ARGS=-UpdateOnly"
if /I "%~1"=="update" set "PS_ARGS=-UpdateOnly"
if /I "%~1"=="rebuild" set "PS_ARGS=-RebuildOnly"
if /I "%~1"=="run" set "PS_ARGS="

if not "%~2"=="" (
  echo [FAIL] Branch switching is no longer accepted by go.bat.
  echo        Update TIP_BRANCH deliberately, then run go.bat update.
  exit /b 2
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\scripts\go.ps1" %PS_ARGS%
exit /b %ERRORLEVEL%
