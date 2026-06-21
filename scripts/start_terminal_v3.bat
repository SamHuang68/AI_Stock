@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo ============================================
echo  Stock Terminal v3.0 - 19 Patterns (TradingView-grade)
echo  http://localhost:18432/stock_terminal_v2.html
echo ============================================
echo.
echo  v3 patterns:
echo    [v2 grade ]  Trend / Double T-B / H^&S / MA Cross / Range / Cup^&Handle / Triangle (asc/desc/sym)
echo    [Harmonics]  ABCD / XABCD (Gartley/Bat/Butterfly/Crab/Shark) / Cypher
echo    [Elliott  ]  Impulse 1-2-3-4-5 / ABC / ABCDE / WXY / WXYXZ / Three Drives
echo    [Cycle    ]  Autocorrelation FFT cycle detection
echo.

REM Always rebuild v2 (now embeds pattern_v3.js) so latest patches/CSS get picked up
echo [1/3] Building v2 HTML from v1 (now using pattern_v3.js)...
python build_v2.py
if errorlevel 1 (
    echo [FAIL] build_v2.py failed
    pause
    exit /b 1
)

echo [2/3] Opening browser...
start "" "http://localhost:18432/stock_terminal_v2.html"

echo [3/3] Starting local server on :18432
echo.
echo  Tip: long-press the v3 ROBOT button to toggle pattern overlay on chart.
echo  Press Ctrl+C to stop the server.
echo.
python server.py
