@echo off
setlocal EnableDelayedExpansion
:: ============================================================
:: BlarAI - TRY THE NEW BRAIN (Qwen3.6-35B-A3B)
:: ============================================================
:: Double-click this to run BlarAI with the CANDIDATE brain
:: instead of the usual Qwen3-14B.
::
:: THIS CHANGES NOTHING PERMANENTLY.
::   The selection lives only in this window's environment and
::   disappears when BlarAI closes. Your normal launcher is
::   untouched and still uses the 14B. Nothing in the project's
::   settings files is edited.
::
:: WHAT TO EXPECT
::   - The same BlarAI window you always use.
::   - The first startup takes ~60s longer: it is a bigger model
::     (18 GB) and its signature is verified before it loads.
::   - If the model or its signature is missing, BlarAI REFUSES
::     to start rather than quietly using the old brain.
::
:: WORTH TRYING
::   - Ask the same question twice. This brain is not yet
::     reproducible, which is the open question (#930).
::   - Try things where the usual brain feels over-cautious.
:: ============================================================

title BlarAI - TRYING the Qwen3.6-35B-A3B brain

:: -- Self-elevate to Administrator (Hyper-V needs it) --------
net session >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Requesting Administrator access...
    powershell -Command "Start-Process -Verb RunAs -FilePath '%~f0' -WorkingDirectory '%~dp0'"
    exit /b 0
)

cd /d "%~dp0"

:: -- Select the candidate brain for THIS RUN ONLY ------------
set "BLARAI_BRAIN_MODEL_DIR=B:\models\Qwen3.6-35B-A3B-int4-ov"

:: -- Ask for the normal BlarAI window, not the text console ---
set "BLARAI_UI=winui"

:: -- Run the window built from THIS code ---------------------
:: The BlarAI window is a compiled app and its build output is
:: not stored in the project, so without a build you could be
:: running a window compiled from different code, or none at all.
::
:: If BlarAI is already open it cannot be rebuilt underneath you,
:: and closing it would throw away whatever you were in the
:: middle of. So this asks rather than deciding for you.
tasklist /fi "imagename eq BlarAI.Desktop.exe" 2>nul | find /i "BlarAI.Desktop.exe" >nul
if !ERRORLEVEL! EQU 0 (
    echo.
    echo   BlarAI is already open.
    echo.
    echo   To try the new brain this launcher has to close that
    echo   window first. Anything unfinished in it will be lost.
    echo.
    choice /c YN /n /m "   Close the open BlarAI and continue?  [Y/N] "
    if errorlevel 2 (
        echo.
        echo   Left it alone. Nothing was changed.
        echo.
        pause
        exit /b 0
    )
    taskkill /im BlarAI.Desktop.exe /f >nul 2>&1
)

echo Building the BlarAI window from this code (a few seconds)...
"C:\Program Files\dotnet\dotnet.exe" build services\ui_winui\BlarAI.Desktop.csproj -c Debug -p:Platform=x64 -v minimal
if !ERRORLEVEL! NEQ 0 (
    echo.
    echo   The BlarAI window could not be built, so this launcher is
    echo   stopping rather than starting something unexpected.
    echo   The messages above say why.
    echo.
    pause
    exit /b 1
)

echo.
echo   ============================================================
echo    BlarAI is starting with the CANDIDATE brain:
echo      Qwen3.6-35B-A3B  (not your usual Qwen3-14B)
echo.
echo    This is for this session only. Close BlarAI and your
echo    normal launcher goes back to the 14B automatically.
echo   ============================================================
echo.

call "%~dp0.venv\Scripts\activate.bat"
python -m launcher --winui

if !ERRORLEVEL! NEQ 0 (
    echo.
    echo   BlarAI exited with error code !ERRORLEVEL!.
    echo   Log: %%LOCALAPPDATA%%\BlarAI\launcher.log
    echo.
    pause
)
