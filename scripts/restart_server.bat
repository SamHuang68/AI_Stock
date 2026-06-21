@echo off
REM 重啟 stock terminal server (apply server.py screener fix)
echo [restart] killing existing server on :18432 ...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":18432" ^| findstr "LISTENING"') do (
    echo   - killing PID %%a
    taskkill /F /PID %%a 2>nul
)
timeout /t 1 /nobreak >nul
echo [restart] starting server.py ...
cd /d "%~dp0"
start "Stock Terminal Server" /MIN cmd /c "python server.py"
timeout /t 2 /nobreak >nul
echo [restart] done. Server should be at http://localhost:18432
