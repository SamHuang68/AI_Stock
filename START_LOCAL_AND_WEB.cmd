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
echo Local launcher started. Waiting for /health ^(up to 40 checks; each request up to 3 seconds^)...
set /a TRIES=0
:wait_local
call :local_up
if not errorlevel 1 goto :web
set /a TRIES+=1
if %TRIES% GEQ 40 (
  echo [WARN] Local did not become healthy after 40 checks. Check StockTerminalLocal\logs.
  goto :web
)
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -Command "Start-Sleep -Seconds 3" >nul
goto :wait_local

:web
echo.
echo ============================================================
echo  2/2 Private Web ST  (scheduled task StockTerminal_PrivateWeb_Host)
echo ============================================================
call :web_ready
if not errorlevel 1 (
  echo Gateway and backend already answer on 127.0.0.1:18434. Not started again.
  goto :wait_web
)
powershell.exe -NoProfile -Command "try { if ([int](Get-ScheduledTask -TaskName 'StockTerminal_PrivateWeb_Host' -ErrorAction Stop).State -eq 4) { exit 0 }; exit 1 } catch { exit 2 }" >nul 2>nul
if errorlevel 2 (
  echo [FAIL] Could not query task StockTerminal_PrivateWeb_Host. No start requested.
  goto :summary
)
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
  echo [WARN] Web did not become ready after 20 checks. Check StockTerminalPrivateWeb\current\logs.
  echo If the gateway answers but its backend is down, run the managed STOP_PRIVATE_WEB.cmd, then retry.
  goto :summary
)
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -Command "Start-Sleep -Seconds 3" >nul
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
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -Command "try { $r = Invoke-RestMethod -Uri 'http://127.0.0.1:18432/health' -TimeoutSec 3 -ErrorAction Stop; if ($r.runtimeCommit -is [string] -and $r.runtimeCommit -match '\A[a-f0-9]{40}\z') { exit 0 }; exit 1 } catch { exit 1 }" >nul 2>nul
exit /b %ERRORLEVEL%

:web_ready
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -Command "try { $r = Invoke-RestMethod -Uri 'http://127.0.0.1:18434/gateway/health' -TimeoutSec 3 -ErrorAction Stop; if ($r.upstream -is [bool] -and $r.upstream) { exit 0 }; exit 1 } catch { exit 1 }" >nul 2>nul
exit /b %ERRORLEVEL%
