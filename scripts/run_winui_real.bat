@echo off
REM ── BlarAI WinUI with the REAL model (live-verify, self-building) ─────
REM Elevates itself (Hyper-V needs admin), closes any running BlarAI window,
REM rebuilds the WinUI app so you always run the latest code, then launches
REM the launcher with the WinUI surface over the named pipe.
REM
REM #788: this normal launch starts the sealed Hyper-V VM LAZILY — plain chat
REM never needs it, so boot skips the ~10-15s Alpine cold-boot and the VM comes
REM up on demand only if a feature that needs it fires. For eager URL-ingest
REM bring-up use run_winui_golive.bat (which passes --go-live).

REM Already elevated?  `net session` only succeeds with admin rights.
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting Administrator access — please approve the UAC prompt...
    echo A new elevated window will open; you can close this one.
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

REM ── Elevated from here ────────────────────────────────────────────────
cd /d C:\Users\mrbla\BlarAI

echo Closing any running BlarAI window so the app can be rebuilt...
taskkill /im BlarAI.Desktop.exe /f >nul 2>&1

echo Building the latest BlarAI UI (a few seconds)...
"C:\Program Files\dotnet\dotnet.exe" build services\ui_winui\BlarAI.Desktop.csproj -c Debug -p:Platform=x64 -v minimal
if %errorlevel% neq 0 (
    echo.
    echo BUILD FAILED — see the messages above. Press any key to close.
    pause >nul
    exit /b 1
)

echo Launching BlarAI (WinUI, real model). First boot takes ~30s (model compile).
.venv\Scripts\python.exe -m launcher --winui
echo.
echo BlarAI exited. Press any key to close this window.
pause >nul
