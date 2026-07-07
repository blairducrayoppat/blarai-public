@echo off
REM ── BlarAI WinUI — URL-INGEST GO-LIVE (real model) ───────────────────
REM Same as run_winui_real.bat, but passes --go-live so the guest parser
REM comes up and the operator can run /ingest <url> THIS session.
REM
REM --go-live is a CLI flag (not an env var) ON PURPOSE: it survives the UAC
REM self-elevation below (sys.argv is forwarded; the environment block is NOT).
REM The committed default stays welded (enabled=false); closing this and using
REM the ordinary launcher next time is deny-by-default again. Reversible by use.

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

echo.
echo ============================================================
echo  GO-LIVE LAUNCH: URL ingest is ENABLED for this session.
echo  The egress door opens once the guest parser reports READY.
echo  Type  /ingest ^<url^>  then approve or reject the preview.
echo  Close this window to return to deny-by-default next boot.
echo ============================================================
echo.
echo Launching BlarAI (WinUI, real model, --go-live). First boot ~30s (model compile).
.venv\Scripts\python.exe -m launcher --winui --go-live
echo.
echo BlarAI exited. Press any key to close this window.
pause >nul
