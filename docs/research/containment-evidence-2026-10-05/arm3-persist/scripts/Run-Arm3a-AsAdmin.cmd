@echo off
title BlarAI arm 3a - persistent filter set, no restart (attended fallback)
cd /d "%~dp0"
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo This needs administrator permission. Windows will now ask you to allow it.
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
echo.
echo BlarAI arm 3a: a PERSISTENT block on the throwaway account, added and then removed by key (no restart).
echo These objects outlive this window. The run removes them itself; this file then runs the removal once more.
echo If anything looks wrong, run:  spike-wfp-persist.ps1 -Remove   (README.md has a second, independent rollback).
echo Needs the rollback proof: spike-wfp-persist.ps1 -SelfTest -WriteProof must have run on these exact files.
echo.
pause
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0spike-wfp-persist.ps1" -DryRun
echo.
echo The dry run above changed nothing. Press a key to run for real, or close this window to stop.
pause
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0spike-wfp-persist.ps1" -Arm3a
echo arm 3a exit code %errorlevel%
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0spike-wfp-persist.ps1" -Remove
echo removal exit code %errorlevel% (0 = all four objects read back absent)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0spike-wfp-persist.ps1" -Check
echo check exit code %errorlevel% (20 = absent, which is what you want now)
pause
