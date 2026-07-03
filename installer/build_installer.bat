@echo off
REM ============================================================
REM  build_installer.bat - one-click build of the Windows setup.exe
REM  Steps: build v2 html  ->  freeze server.py to server.exe (PyInstaller)
REM         ->  compile installer (Inno Setup / ISCC)
REM  Prereqs (one-time): Python + PyInstaller (auto-installed) + Inno Setup 6.
REM ============================================================
setlocal
cd /d "%~dp0.."

echo [1/3] Building v2 HTML (fresh) ...
python build_v2.py
if errorlevel 1 ( echo [FAIL] build_v2.py & pause & exit /b 1 )

echo.
echo [2/3] Freezing server.py to server.exe (PyInstaller) ...
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo PyInstaller not found - installing ...
    python -m pip install --user pyinstaller
    if errorlevel 1 ( echo [FAIL] pip install pyinstaller & pause & exit /b 1 )
)
REM Core app is pure stdlib; exclude heavy libs pulled in transitively by the
REM report module (etf_report -> pandas/numpy/matplotlib/...). Keeps exe small.
REM Those features are not part of the packaged interactive app (server.py
REM imports them under try/except, so absence degrades gracefully).
python -m PyInstaller --onefile --console --name server ^
  --distpath installer\build --workpath installer\build\_work --specpath installer\build ^
  --paths server --hidden-import alert_daemon --hidden-import watch_daemon ^
  --hidden-import datastore --hidden-import portfolio --hidden-import ai_local --hidden-import universe --hidden-import datasources --hidden-import etf_report_lite ^
  --exclude-module etf_report --exclude-module pandas --exclude-module numpy ^
  --exclude-module matplotlib --exclude-module PIL --exclude-module scipy ^
  --exclude-module lxml --exclude-module openpyxl --exclude-module pytest ^
  --exclude-module cryptography --exclude-module bcrypt --exclude-module websockets ^
  --exclude-module tkinter --exclude-module setuptools --exclude-module pygments ^
  --clean --noconfirm server\server.py
if errorlevel 1 ( echo [FAIL] PyInstaller & pause & exit /b 1 )
if not exist "installer\build\server.exe" ( echo [FAIL] server.exe not produced & pause & exit /b 1 )

echo.
echo [3/3] Compiling installer with Inno Setup (ISCC) ...
set "ISCC="
where iscc >nul 2>&1 && set "ISCC=iscc"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"

if not defined ISCC (
    echo.
    echo [INFO] Inno Setup compiler ^(ISCC^) not found.
    echo        server.exe is ready at installer\build\server.exe
    echo        Install Inno Setup 6 from https://jrsoftware.org/isdl.php  then run:
    echo            iscc installer\StockTerminal.iss
    pause
    exit /b 0
)

"%ISCC%" installer\StockTerminal.iss
if errorlevel 1 ( echo [FAIL] ISCC & pause & exit /b 1 )

echo.
echo [OK] Done. Installer is at:  installer\dist_installer\StockTerminal-Setup-v4.1.exe
echo Share that single .exe - recipient just double-clicks to install (no Python needed).
pause
