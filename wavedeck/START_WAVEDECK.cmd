@echo off
REM Keep this wrapper ASCII; PowerShell reads the UTF-8 launcher and Python pin.
setlocal EnableExtensions
set "WD_BROWSER_ARG="
if /i "%~1"=="--no-browser" set "WD_BROWSER_ARG=-NoBrowser"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0start_wavedeck.ps1" -WaveDeckRoot "%~dp0." %WD_BROWSER_ARG%
set "WD_RC=%ERRORLEVEL%"
endlocal & exit /b %WD_RC%
