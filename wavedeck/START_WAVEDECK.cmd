@echo off
setlocal
cd /d "%~dp0"
echo.
echo  WaveDeck - 浪潮執行台
echo  http://127.0.0.1:18433/
echo.
where py >nul 2>nul && (
  start "WaveDeck Server" cmd /k py -3 server\server.py
) || (
  start "WaveDeck Server" cmd /k python server\server.py
)
timeout /t 1 /nobreak >nul
start "" "http://127.0.0.1:18433/"
endlocal
