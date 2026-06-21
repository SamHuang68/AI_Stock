@echo off
REM v3.6: rebuild stock_terminal_v2.html from v1 source + restart server
chcp 65001 >nul
cd /d "%~dp0.."

echo === Step 1/3: Rebuild stock_terminal_v2.html from v1 base ===
python build_v2.py
if errorlevel 1 (
    echo BUILD FAILED, abort
    pause
    exit /b 1
)
echo.

echo === Step 2/3: Kill old server on port 18432 ===
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":18432" ^| findstr "LISTENING"') do (
    echo   - killing PID %%a
    taskkill /F /PID %%a 2>nul
)
timeout /t 1 /nobreak >nul
echo.

echo === Step 3/3: Start fresh server ===
start "Stock Terminal Server" /MIN cmd /c "python server\server.py"
timeout /t 2 /nobreak >nul
echo.

echo === Done. Open in browser: ===
echo   http://localhost:18432/stock_terminal_v2.html
echo.
echo Force-reload browser with Ctrl+F5 if needed.
pause
