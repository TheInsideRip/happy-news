@echo off
rem Launcher for Windows Task Scheduler. Task Scheduler entries pass a slot
rem name (morning/afternoon/evening) as %1 for readability in the task list
rem only -- the Python code decides the slot from the clock itself, so any
rem argument here is accepted and simply ignored (never referenced below).
setlocal

rem %~dp0 is this script's own folder (drive + path, always with a trailing
rem backslash) -- deriving the repo root and PYTHONPATH from it, rather than
rem hardcoding "E:\Satcey Happy News", means the launcher keeps working if
rem the whole folder is ever moved or cloned somewhere else.
cd /d "%~dp0"

rem logs\ is gitignored, so a fresh clone or a first run on a new machine
rem may not have it yet -- create it before anything tries to append to a
rem file inside it.
if not exist "logs" mkdir "logs"

set "PYTHONPATH=%~dp0src"

python -m happy_news run >> "logs\run.log" 2>&1
set "RC=%errorlevel%"

endlocal & exit /b %RC%
