@echo off
rem Double-click wrapper for launch.ps1 in standard-token mode (hash-bound start of the MXC loopback-proxy egress probe).
rem What it measures: nothing itself. How to run: double-click from Explorer or run from a normal non-administrator
rem shell; do NOT use Run as administrator. launch.ps1 refuses an elevated or non-Medium-integrity token in this mode.
rem What it writes: nothing; the probe writes its raw records under its own output folder.
rem NOT MEASURED: see launch.ps1.
"C:\Program Files\PowerShell\7\pwsh.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch.ps1" -Token standard %*
echo.
echo Exit code %ERRORLEVEL%. Press any key to close.
pause >nul
