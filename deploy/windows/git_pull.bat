@echo off
:: SEPA Signals - auto-pull latest changes from GitHub every 2 hours.
:: Ensures the mini PC always runs the latest code pushed from any machine.

set SEPA_DIR=%~dp0..\..
set LOG_FILE=%SEPA_DIR%\data\logs\git_pull.log

if not exist "%SEPA_DIR%\data\logs" mkdir "%SEPA_DIR%\data\logs"

echo [%date% %time%] git pull starting >> "%LOG_FILE%"
cd /d "%SEPA_DIR%"
git pull origin main >> "%LOG_FILE%" 2>&1
echo [%date% %time%] git pull done (exit %errorlevel%) >> "%LOG_FILE%"
