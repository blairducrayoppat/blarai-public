@echo off
REM ── BlarAI knowledge-bank status (read-only) ─────────────────────────
REM Double-click to see what BlarAI has stored and what your /approve and
REM /reject decisions recorded. Read-only; safe to run while BlarAI is open.
cd /d "%~dp0.."
.venv\Scripts\python.exe scripts\kb_status.py
echo.
pause
