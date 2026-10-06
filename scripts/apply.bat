@echo off
REM scripts\apply.bat is retired (2026-10-07). The previous version force-checked-out a
REM remote branch (git checkout -B), stashed untracked files and killed whatever listened
REM on :18432. That conflicts with the managed local install and with the shared rule
REM against forced resets. The old logic remains in Git history.
echo [RETIRED] scripts\apply.bat no longer does anything.
echo   Start Stock Terminal with START_TIP.cmd from the registered checkout.
echo   Update the development checkout with: git pull --ff-only origin main
echo   See AGENTS.md ^(sections 1 and 2^).
exit /b 2
