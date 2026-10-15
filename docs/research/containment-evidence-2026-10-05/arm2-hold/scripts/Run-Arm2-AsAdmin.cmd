@echo off
title BlarAI arm 2 - the long hold (attended fallback)
cd /d "%~dp0"
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo This needs administrator permission. Windows will now ask you to allow it.
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
echo.
echo BlarAI arm 2: one long hold of the block (default 3600 s, a probe every 60 s).
echo The unattended route is Start-ElevatedOnce.ps1 (see README.md); this is the fallback when you are at the machine.
echo Every WFP object lives in a dynamic session: closing this window or a reboot removes it.
echo Exit 0 = every sample blocked; 1 = a sample was NOT blocked (a result). Anything else: send the text to Claude.
echo.
pause
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0spike-wfp.ps1" -DryRun
echo.
echo The dry run above changed nothing. Press a key to start the real hold, or close this window to stop.
pause
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0spike-wfp.ps1" -LongHold -HoldSeconds 3600
echo.
echo exit code %errorlevel%
pause
