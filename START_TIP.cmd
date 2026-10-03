@echo off
REM Stock Terminal local entrypoint. Keep ASCII for the Windows console.
REM Managed installations dispatch before any build, Git or process operation.
setlocal EnableExtensions
cd /d "%~dp0"
if not exist "%~dp0scripts\go.ps1" (
  echo [FAIL] Stock Terminal launcher is missing.
  exit /b 1
)
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\go.ps1" %*
exit /b %ERRORLEVEL%
