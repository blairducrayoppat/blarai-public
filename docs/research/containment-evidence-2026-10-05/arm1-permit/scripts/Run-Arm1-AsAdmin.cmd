@echo off
setlocal enabledelayedexpansion
title BlarAI arm 1 - the confined account as a loopback client, with and without the permit filter
cd /d "%~dp0"

rem --- ask Windows for administrator rights if we do not have them (a permission prompt will appear) ---
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo This needs administrator permission. Windows will now ask you to allow it.
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

echo.
echo ============================================================
echo   BlarAI arm 1: six runs, conditions interleaved
echo   on, off, on, off, on, off  (on = four filters incl. the
echo   loopback permit; off = the two block filters only)
echo ============================================================
echo.
echo Each run is its own process and its own WFP engine session:
echo the model server starts as you, the account makes its request
echo three times (before, during and after the block), the block is
echo removed and checked, the server stops. About 2 to 3 minutes each.
echo.
echo Exit code 0 = request succeeded under the block; 9 = it failed
echo under the block (both are results). Anything else: stop and
echo send the text to Claude. Exit 3 means your own traffic was hit:
echo everything was removed at once, and the arm stops.
echo.
echo Stopping WSL first (its virtual machine takes memory the model
echo server needs; the run records WSL's state).
wsl --shutdown
echo.
pause

set BLOCKMAX=240
set RUNS=0
set FAILED=0
for %%C in (on off on off on off) do (
  call :onerun %%C
  if "!FAILED!"=="1" goto :done
)
goto :done

:onerun
set /a RUNS+=1
echo.
echo ------------------------------------------------------------
echo   run %RUNS% of 6: permit %1
echo ------------------------------------------------------------
if "%1"=="on" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0spike-wfp.ps1" -TestC -BlockMaxSeconds %BLOCKMAX%
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0spike-wfp.ps1" -TestC -NoLoopbackPermit -BlockMaxSeconds %BLOCKMAX%
)
set RC=%errorlevel%
echo run %RUNS% (permit %1) exit code %RC%
if "%RC%"=="0" goto :runok
if "%RC%"=="9" goto :runok
echo.
echo Exit code %RC% is not a result. Stopping here; send the text above to Claude.
set FAILED=1
exit /b 0
:runok
if %RUNS% lss 6 (
  echo.
  echo Press any key for the next run, or close this window to stop.
  pause >nul
)
exit /b 0

:done
echo.
if "%FAILED%"=="0" (
  echo All six runs finished. Reports: runs\testC-*.json. Tell Claude.
) else (
  echo Stopped after run %RUNS%. Nothing persistent was left behind: every
  echo filter lived in a session that ended with its process.
)
echo.
pause
exit /b %FAILED%
