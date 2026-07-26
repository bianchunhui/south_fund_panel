@echo off
chcp 65001 >nul 2>&1
set "DIR=C:\Users\chunh\ZCodeProject\south_fund_panel"
echo [start] launching Southbound Capital Monitor...
powershell -NoProfile -ExecutionPolicy Bypass -File "%DIR%\start_panel.ps1"
echo [done]
pause
