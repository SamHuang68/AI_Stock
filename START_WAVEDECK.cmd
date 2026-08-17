@echo off
setlocal EnableExtensions
cd /d "%~dp0"

REM Prefer flat wavedeck\run.py; also tolerate accidental nested wavedeck\wavedeck\
set "WD_DIR="
if exist "%~dp0wavedeck\run.py" set "WD_DIR=%~dp0wavedeck"
if not defined WD_DIR if exist "%~dp0wavedeck\wavedeck\run.py" set "WD_DIR=%~dp0wavedeck\wavedeck"
if not defined WD_DIR if exist "%~dp0run.py" set "WD_DIR=%~dp0"

if not defined WD_DIR (
  echo.
  echo  [ERR] wavedeck\run.py not found under %CD%
  echo  Re-extract the complete Stock Terminal distribution and try again.
  echo.
  pause
  exit /b 1
)

call "%WD_DIR%\START_WAVEDECK.cmd"
endlocal
