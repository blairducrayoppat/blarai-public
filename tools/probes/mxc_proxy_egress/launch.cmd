@echo off
rem Double-click wrapper for launch.ps1 (hash-bound start of the MXC loopback-proxy egress probe).
rem What it measures: nothing itself. How to run: double-click, or launch.cmd [probe args].
rem What it writes: nothing; the probe writes its raw records under its own output folder.
rem NOT MEASURED: see launch.ps1.
"C:\Program Files\PowerShell\7\pwsh.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch.ps1" %*
echo.
echo Exit code %ERRORLEVEL%. Press any key to close.
pause >nul
