@echo off
:: ============================================================
:: BlarAI — Live System Launcher (Real GPU + NPU Inference)
:: ============================================================
:: Double-click this file to launch BlarAI with real inference.
:: You will be prompted for Administrator access (required for
:: Hyper-V VM management).
::
:: Prerequisites:
::   - Python 3.11 venv at .venv\
::   - OpenVINO GenAI installed
::   - Model files in models\
:: ============================================================

title BlarAI Assistant — Real Inference

:: ── Self-elevate to Administrator ──────────────────────────
net session >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Requesting Administrator access...
    powershell -Command "Start-Process -Verb RunAs -FilePath '%~f0' -WorkingDirectory '%~dp0'"
    exit /b 0
)

:: Ensure we're in the project directory
cd /d "%~dp0"

:: Activate the Python virtual environment
call "%~dp0.venv\Scripts\activate.bat"

:: Launch BlarAI
python -m launcher

:: If the app exits with an error, keep the window open
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo   BlarAI exited with error code %ERRORLEVEL%.
    echo   Check %%LOCALAPPDATA%%\BlarAI\launcher.log for details.
    echo.
    pause
)
