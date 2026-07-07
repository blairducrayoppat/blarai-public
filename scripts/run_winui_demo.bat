@echo off
REM ── BlarAI WinUI demo launcher (Phase 2 live-verify) ──────────────────
REM Starts the no-GPU backend (real chat history + echo replies) and then
REM opens the WinUI 3 app. Double-click this file to try the new window.
REM
REM This is a DEV/DEMO convenience. The real model behind the pipe and a
REM proper Start-menu launch come in later phases.

cd /d C:\Users\mrbla\BlarAI

echo Starting BlarAI backend (no-model: real history, echo replies)...
start "BlarAI backend" .venv\Scripts\python.exe -m services.ui_backend --no-model

echo Waiting for the backend to come up...
timeout /t 2 /nobreak >nul

echo Opening BlarAI window...
start "" "services\ui_winui\bin\x64\Debug\net8.0-windows10.0.19041.0\BlarAI.Desktop.exe"

echo.
echo Done. Close the "BlarAI backend" window when you are finished to stop it.
