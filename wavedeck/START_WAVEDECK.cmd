@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo  ============================================
echo   WaveDeck · 浪潮執行台
echo   http://127.0.0.1:18433/
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

echo [1/3] 啟動伺服器（新視窗，請勿關閉）...
echo       若黑窗出現 Traceback，把內容貼給我。
start "WaveDeck Server" cmd /k %PYEXE% run.py

echo [2/3] 等待 /health 就緒...
set /a _i=0
:wait_loop
set /a _i+=1
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:18433/health' -TimeoutSec 1; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>nul
if %ERRORLEVEL%==0 goto ready
if %_i% GEQ 20 goto fail
timeout /t 1 /nobreak >nul
goto wait_loop

:ready
echo [3/3] 開啟瀏覽器...
start "" "http://127.0.0.1:18433/"
echo.
echo  已就緒。若畫面空白請按 F5；伺服器黑窗請保持開啟。
echo.
endlocal
exit /b 0

:fail
echo.
echo [ERR] 20 秒內無法連上 http://127.0.0.1:18433/health
echo       請看標題為 "WaveDeck Server" 的黑窗錯誤訊息。
echo       手動診斷：
echo         cd /d "%~dp0"
echo         %PYEXE% run.py
echo.
pause
endlocal
exit /b 1
