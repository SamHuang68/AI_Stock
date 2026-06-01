@echo off
REM v3.7 commit - global ETF holdings + multi-market click-through
chcp 65001 >nul
cd /d "%~dp0"

if exist ".git\index.lock" del /F /Q ".git\index.lock"

(
echo v3.7: global ETF holdings + multi-market chart click-through
echo.
echo Problem:
echo   00988A ^(Uni-President Global Innovation Active^) showed only 13
echo   Taiwan stocks in TOP 10 holdings even though it's a global ETF
echo   with 46 holdings spanning US ^(17^) / TW ^(13^) / JP ^(9^) / KR ^(1^) /
echo   CN ^(1^). The TOP 3 by weight ^(Samsung, Micron, AMD^) all missing.
echo.
echo Root cause:
echo   etf_delta_tracker.py _MDJ_ROW_RE hardcoded two assumptions:
echo     1^) ^(\d{4,6}^) accepts pure digits only - AMD/MU/AAPL filtered
echo     2^) \.TW suffix locked - 6963.JP/009150.KS/0700.HK filtered
echo   Both 41/46 foreign holdings of 00988A excluded by regex.
echo.
echo Fix:
echo   etf_delta_tracker.py:
echo     - Regex relaxed: code = [0-9A-Za-z]{1,7}; suffix = [A-Z]{2}
echo     - holdings now carry 'market' field ^(TW/US/JP/KS/HK/SH/SZ/DE/L^)
echo     - dedupe key bumped to code.market ^(was just code^).
echo   etf_v3.js:
echo     - new mapToYahoo^(sym, mdjMkt^): MoneyDJ market code to Yahoo
echo       symbol suffix. JP-^>.T, SH-^>.SS, HK auto-padStart^(4,'0'^);
echo       passes uiMkt='US' so loadSym doesn't re-suffix with .TW.
echo     - click handler reads data-mkt and routes via mapToYahoo.
echo     - display shows .US/.JP/.KS labels next to foreign codes;
echo       TW stays clean ^(no suffix shown^).
echo.
echo Verification ^(via Chrome -^> localhost:18432/yf/...^):
echo   6963.T   -^> ROHM CO LTD ^(JPY 5458^)
echo   009150.KS-^> SamsungElecMech ^(KRW 2127000^)
echo   AMD      -^> AMD ^(USD 516.10^)
echo   0700.HK  -^> TENCENT ^(HKD 427.20^)
echo   600519.SS-^> KWEICHOW MOUTAI ^(CNY 1326^)
echo   2454.TW  -^> MediaTek ^(TWD 4310^)
echo.
echo Apply steps:
echo   1. python etf_delta_tracker.py  ^(re-fetch holdings with market field^)
echo   2. rebuild_and_restart.bat      ^(apply etf_v3.js to browser^)
echo.
echo Files:
echo   etf_delta_tracker.py  regex + market field in 2 fetch functions
echo   etf_v3.js             mapToYahoo + click handler + suffix labels
echo   README.md             new v3.7 section
) > .git\COMMIT_MSG_v37.txt

git add README.md etf_delta_tracker.py etf_v3.js
git diff --cached --name-only
echo.

git commit -F .git\COMMIT_MSG_v37.txt
del /F /Q .git\COMMIT_MSG_v37.txt

echo.
git log --oneline -5
pause
