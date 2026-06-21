@echo off
chcp 65001 > nul
cd /d "%~dp0.."
echo Running daily data snapshot backup...
python server\backup_data.py
echo.
echo Done. Snapshots are in the backups\ folder.
