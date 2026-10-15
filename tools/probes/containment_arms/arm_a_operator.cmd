@echo off
rem #1740 phase 2, arm A: runs the containment probes as the coder account.
rem Double-click. Windows asks for administrator approval; the window stays open at the end.
echo This runs the #1740 probes as blarai-coder through a temporary scheduled task,
echo then removes the task. Run it only after the #775 flip.
echo.
pause
"C:\Program Files\PowerShell\7\pwsh.exe" -NoProfile -Command "Start-Process -Verb RunAs -FilePath 'C:\Program Files\PowerShell\7\pwsh.exe' -ArgumentList '-NoProfile','-NoExit','-ExecutionPolicy','Bypass','-File','%~dp0arm_a_operator.ps1'"
