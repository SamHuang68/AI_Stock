@echo off
REM Start local ST (18432) and the Private Web ST host (18434 -> 18435) together.
REM Keep ASCII for the Windows console. Safe to run when either side is already up.
REM Exit code: 0 = both healthy, 1 = local down, 2 = web down, 3 = both down.
setlocal EnableExtensions
cd /d "%~dp0"

echo ============================================================
echo  1/2 Local ST  (START_TIP.cmd, managed install, 127.0.0.1:18432)
echo ============================================================
call :local_up
if not errorlevel 1 (
  echo Local ST already answers on 127.0.0.1:18432. Not started again.
  goto :web
)
REM START_TIP.cmd does not return while it starts the server, so start it detached and poll /health.
start "ST local launcher" /min "%SystemRoot%\System32\cmd.exe" /c ""%~dp0START_TIP.cmd""
echo Local launcher started. Waiting for /health ^(up to 120 seconds^)...
set /a TRIES=0
:wait_local
call :local_up
if not errorlevel 1 goto :web
set /a TRIES+=1
if %TRIES% GEQ 40 (
  echo [WARN] Local did not become healthy within 120 seconds. Check StockTerminalLocal\logs.
  goto :web
)
timeout /t 3 /nobreak >nul
goto :wait_local

:web
echo.
echo ============================================================
echo  2/2 Private Web ST  (scheduled task StockTerminal_PrivateWeb_Host)
echo ============================================================
call :gateway_up
if not errorlevel 1 (
  echo Gateway already answers on 127.0.0.1:18434. Not started again.
  goto :wait_web
)
schtasks /query /tn "StockTerminal_PrivateWeb_Host" /fo list 2>nul | findstr /i /c:"Running" >nul
if not errorlevel 1 (
  echo Task is already running ^(still starting^). Not started again.
  goto :wait_web
)
schtasks /run /tn "StockTerminal_PrivateWeb_Host"
if errorlevel 1 (
  echo [FAIL] Could not start task StockTerminal_PrivateWeb_Host.
  goto :summary
)
echo Task started.

:wait_web
echo Waiting for the gateway and its backend...
set /a TRIES=0
:wait
call :web_ready
if not errorlevel 1 goto :summary
set /a TRIES+=1
if %TRIES% GEQ 20 (
  echo [WARN] Web did not become ready within 60 seconds. Check StockTerminalPrivateWeb\current\logs.
  goto :summary
)
timeout /t 3 /nobreak >nul
goto :wait

:summary
echo.
echo ------------------------------------------------------------
set "RC=0"
call :local_up
if errorlevel 1 (echo  Local : DOWN  http://127.0.0.1:18432/& set /a RC^|=1) else (echo  Local : UP    http://127.0.0.1:18432/)
call :web_ready
if errorlevel 1 (echo  Web   : DOWN  http://127.0.0.1:18434/  ^(gateway or backend not ready^)& set /a RC^|=2) else (echo  Web   : UP    http://127.0.0.1:18434/)
echo ------------------------------------------------------------
exit /b %RC%

:local_up
curl.exe -s -m 3 http://127.0.0.1:18432/health 2>nul | findstr /c:"runtimeCommit" >nul
exit /b %ERRORLEVEL%

:gateway_up
curl.exe -s -m 3 http://127.0.0.1:18434/gateway/health 2>nul | findstr /c:"private-web" >nul
exit /b %ERRORLEVEL%

:web_ready
curl.exe -s -m 3 http://127.0.0.1:18434/gateway/health 2>nul | findstr /r /c:"upstream.:true" >nul
exit /b %ERRORLEVEL%
