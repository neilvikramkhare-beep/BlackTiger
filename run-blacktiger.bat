@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3.11 blacktiger_app.py %*
) else (
    python blacktiger_app.py %*
)

if errorlevel 1 (
    echo.
    echo BlackTiger exited with an error. Check output above.
    pause
)
