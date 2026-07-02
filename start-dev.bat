@echo off
REM One-click local dev launcher: starts the FastAPI backend + webapp together.
REM Double-click this file in Explorer, or run `npm run dev:all` from the repo root.
cd /d "%~dp0"
call npm run dev:all
pause
