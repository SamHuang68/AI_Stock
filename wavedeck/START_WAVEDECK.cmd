@echo off
setlocal EnableExtensions
REM ASCII-only messages (Windows cmd codepage-safe)
cd /d "%~dp0"

REM Resolve WaveDeck home (handles AI_Stock\ or nested wavedeck\wavedeck\)
set "WD_HOME=%CD%"
if exist "%WD_HOME%\run.py" goto home_ok
if exist "%WD_HOME%\wavedeck\run.py" (
  set "WD_HOME=%WD_HOME%\wavedeck"
  goto home_ok
)
if exist "%~dp0run.py" (
  set "WD_HOME=%~dp0"
  goto home_ok
)
echo [ERR] run.py not found. Run this from the wavedeck folder.
echo       Expected: ^<project-folder^>\wavedeck\START_WAVEDECK.cmd
pause
exit /b 1

:home_ok
cd /d "%WD_HOME%"
echo.
echo  ============================================
echo   WaveDeck  http://127.0.0.1:PORT/
echo   home: %CD%
echo  ============================================
echo.

set "PYEXE="
where py >nul 2>nul && set "PYEXE=py -3"
if not defined PYEXE (
  where python >nul 2>nul && set "PYEXE=python"
)
if not defined PYEXE (
  echo [ERR] Python not found. Install Python 3.10+ with PATH enabled.
  pause
  exit /b 1
)

if not exist "data" mkdir "data"
del /q "data\wavedeck.port" >nul 2>nul

echo [1/3] Starting server window...
start "WaveDeck Server" cmd /k cd /d "%CD%" ^& %PYEXE% run.py

echo [2/3] Waiting for /health (auto port fallback if 18433 blocked)...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$homePath = '%CD%';" ^
  "$portFile = Join-Path $homePath 'data\wavedeck.port';" ^
  "$ports = @(18433,18434,18765,28765,38433,8765);" ^
  "$deadline = (Get-Date).AddSeconds(30);" ^
  "while ((Get-Date) -lt $deadline) {" ^
  "  if (Test-Path $portFile) { $p = (Get-Content $portFile -Raw).Trim(); if ($p -match '^\d+$') { try { $r = Invoke-WebRequest -UseBasicParsing -Uri ('http://127.0.0.1:'+$p+'/health') -TimeoutSec 1; if ($r.StatusCode -eq 200) { exit 0 } } catch {} } }" ^
  "  foreach ($p in $ports) { try { $r = Invoke-WebRequest -UseBasicParsing -Uri ('http://127.0.0.1:'+$p+'/health') -TimeoutSec 1; if ($r.StatusCode -eq 200) { New-Item -ItemType Directory -Force -Path (Split-Path $portFile) | Out-Null; Set-Content -Path $portFile -Value $p -Encoding ascii; exit 0 } } catch {} }" ^
  "  Start-Sleep -Milliseconds 700" ^
  "}; exit 1"

if errorlevel 1 goto fail

set /p WD_PORT=<"data\wavedeck.port"
if not defined WD_PORT set WD_PORT=18433

echo [3/3] Opening http://127.0.0.1:%WD_PORT%/
start "" "http://127.0.0.1:%WD_PORT%/"
echo.
echo  Ready. Keep the WaveDeck Server window open.
echo.
endlocal
exit /b 0

:fail
echo.
echo [ERR] Cannot reach WaveDeck /health.
echo       Check the "WaveDeck Server" window for Traceback.
echo       Manual:
echo         cd /d "%CD%"
echo         set WAVEDECK_PORT=28765
echo         %PYEXE% run.py
echo.
pause
endlocal
exit /b 1
