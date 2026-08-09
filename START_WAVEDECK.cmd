@echo off
setlocal
cd /d "%~dp0"
if not exist "wavedeck\START_WAVEDECK.cmd" (
  echo.
  echo  [ERR] 找不到 wavedeck\
  echo  請先同步 PR 分支 cursor/wavedeck-init-3497，或解壓 wavedeck 同步包到本目錄。
  echo.
  pause
  exit /b 1
)
call "wavedeck\START_WAVEDECK.cmd"
endlocal
