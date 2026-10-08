@echo off
REM Open Stock Terminal and WaveDeck after their services are ready.
REM Exit bits: 1 = local down, 2 = web down, 4 = WaveDeck down.
setlocal EnableExtensions
cd /d "%~dp0"
call "%~dp0START_LOCAL_AND_WEB.cmd" %*
set "ST_RC=%ERRORLEVEL%"
call "%~dp0START_WAVEDECK.cmd" %*
if errorlevel 1 set /a ST_RC^|=4
exit /b %ST_RC%
