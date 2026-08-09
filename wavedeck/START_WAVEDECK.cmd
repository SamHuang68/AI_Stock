@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo  ============================================
echo   WaveDeck · 浪潮執行台
echo  ============================================
echo.

if not exist "run.py" (
  echo [ERR] 找不到 run.py — wavedeck 目錄不完整。
  pause
  exit /b 1
)

set "PYEXE="
where py >nul 2>nul && set "PYEXE=py -3"
if not defined PYEXE (
  where python >nul 2>nul && set "PYEXE=python"
)
if not defined PYEXE (
  echo [ERR] 找不到 Python。請安裝 Python 3.10+ 並勾選 Add to PATH。
  pause
  exit /b 1
)

if not exist "data" mkdir "data"
del /q "data\wavedeck.port" >nul 2>nul

echo [1/3] 啟動伺服器（新視窗，請勿關閉）...
start "WaveDeck Server" cmd /k %PYEXE% run.py

echo [2/3] 等待 /health（若 18433 被 Windows 保留會自動換埠）...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0wait_ready.ps1"
if errorlevel 1 goto fail

set /p WD_PORT=<"data\wavedeck.port"
if not defined WD_PORT set WD_PORT=18433

echo [3/3] 開啟 http://127.0.0.1:%WD_PORT%/
start "" "http://127.0.0.1:%WD_PORT%/"
echo.
echo  已就緒。伺服器黑窗請保持開啟。
echo.
endlocal
exit /b 0

:fail
echo.
echo [ERR] 仍無法連上 WaveDeck。請看 "WaveDeck Server" 黑窗錯誤。
echo       手動指定埠：
echo         set WAVEDECK_PORT=28765
echo         %PYEXE% run.py
echo.
pause
endlocal
exit /b 1
