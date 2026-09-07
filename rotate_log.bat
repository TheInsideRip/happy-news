@echo off
rem Keep a log file from growing without limit.
rem
rem publish.bat appends every run's output to logs\run.log -- 18 runs a day,
rem forever, with nothing ever trimming it. Left alone that file eventually
rem fills the disk on the one laptop this system runs on, which takes the
rem page down with it. It is called BEFORE publish.bat opens its append
rem redirect, so nothing holds a handle on the file while it is rewritten.
rem
rem Usage: rotate_log.bat <log file> [max bytes] [lines to keep]
rem Always exits 0: a launcher must never fail because housekeeping did.
setlocal

set "LOG=%~1"
if "%LOG%"=="" exit /b 0
if not exist "%LOG%" exit /b 0

set "MAXBYTES=%~2"
if "%MAXBYTES%"=="" set "MAXBYTES=1048576"
set "KEEPLINES=%~3"
if "%KEEPLINES%"=="" set "KEEPLINES=2000"

set "LOGSIZE=0"
for %%A in ("%LOG%") do set "LOGSIZE=%%~zA"
if "%LOGSIZE%"=="" set "LOGSIZE=0"

if %LOGSIZE% LEQ %MAXBYTES% exit /b 0

rem Keep the most recent lines: the tail is what an operator reads after a
rem failure, so it is the half worth keeping.
powershell -NoProfile -NonInteractive -Command "$ErrorActionPreference='Stop'; $p='%LOG%'; $tail = Get-Content -LiteralPath $p -Tail %KEEPLINES%; Set-Content -LiteralPath $p -Value $tail -Encoding utf8"

exit /b 0
