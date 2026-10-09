@echo off
setlocal
title BlarAI #1689 confined-model spike - set up the throwaway account
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
echo   BlarAI spike #1689: a throwaway account for a test
echo ============================================================
echo.
echo What this is: a test of whether a locked-down Windows account
echo can run the AI model on the graphics chip without any network.
echo.
echo Step 1 of 2: a LIST of what would be created. Nothing is changed yet.
echo.
pause

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0spike-provision.ps1" -DryRun
set DRYRC=%errorlevel%
echo.
if not "%DRYRC%"=="0" (
  echo The check found a problem, so nothing will be created.
  echo Please send the text above to Claude.
  echo.
  pause
  exit /b %DRYRC%
)

echo ------------------------------------------------------------
echo Above is everything that would be created. Nothing has been
echo created yet. To remove it all later, run spike-cleanup.ps1.
echo ------------------------------------------------------------
echo.
echo Type YES (in capitals) and press Enter to create it.
echo Anything else, or just closing this window, creates nothing.
set /p CONFIRM=Your answer:
if /i not "%CONFIRM%"=="YES" (
  echo.
  echo You did not type YES. Nothing was created.
  pause
  exit /b 0
)

echo.
echo Step 2 of 2: creating the account and its permissions...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0spike-provision.ps1" -Apply
set APPLYRC=%errorlevel%
echo.
if "%APPLYRC%"=="0" (
  echo Done. The account is ready. Tell Claude it is ready; Claude runs the tests.
) else (
  echo Something stopped the set-up. Nothing further was done.
  echo Please send the text above to Claude. It is safe to run this again.
)
echo.
pause
exit /b %APPLYRC%
