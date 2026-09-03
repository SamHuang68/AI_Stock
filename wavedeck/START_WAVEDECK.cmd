@echo off
setlocal EnableExtensions
chcp 65001 >nul
REM 重用 Stock Terminal 的絕對 Python 釘選，不得退回 PATH 裡的裸 python。
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

set "ST_ROOT="
for %%I in ("%WD_HOME%\..") do if exist "%%~fI\data\stock_python.path" set "ST_ROOT=%%~fI"
if not defined ST_ROOT for %%I in ("%WD_HOME%\..\..") do if exist "%%~fI\data\stock_python.path" set "ST_ROOT=%%~fI"

set "PYEXE="
if defined ST_ROOT set /p PYEXE=<"%ST_ROOT%\data\stock_python.path"
if defined PYEXE if not exist "%PYEXE%" set "PYEXE="
if not defined PYEXE for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "PYEXE=%%P"
if not defined PYEXE (
  echo [ERR] 找不到 Python 3。請先執行 START_TIP.cmd 建立釘選路徑。
  pause
  exit /b 1
)

if not exist "data" mkdir "data"
del /q "data\wavedeck.port" >nul 2>nul

echo [1/3] Starting server window...
start "WaveDeck Server" cmd /k cd /d "%CD%" ^& "%PYEXE%" run.py

echo [2/3] Waiting for /health (auto port fallback if 18433 blocked)...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$homePath = '%CD%';" ^
  "$portFile = Join-Path $homePath 'data\wavedeck.port';" ^
  "$ports = @(18433,18765,28765,38433,8765);" ^
  "$deadline = (Get-Date).AddSeconds(30);" ^
  "while ((Get-Date) -lt $deadline) {" ^
  "  if (Test-Path $portFile) { $p = (Get-Content $portFile -Raw).Trim(); if ($p -match '^\d+$' -and [int]$p -ge 1 -and [int]$p -le 65535 -and [int]$p -notin @(18434,18435)) { try { $r = Invoke-WebRequest -UseBasicParsing -Uri ('http://127.0.0.1:'+$p+'/health') -TimeoutSec 1; if ($r.StatusCode -eq 200) { exit 0 } } catch {} } }" ^
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
echo         "%PYEXE%" run.py
echo.
pause
endlocal
exit /b 1
