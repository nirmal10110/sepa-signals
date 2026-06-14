@echo off
:: SEPA Signals — nightly scan + Telegram alerts
:: Scheduled via Task Scheduler to run at 10:00 PM daily.

set SEPA_DIR=%~dp0..\..
set LOG_FILE=%SEPA_DIR%\data\logs\daily.log

:: Create log folder if missing
if not exist "%SEPA_DIR%\data\logs" mkdir "%SEPA_DIR%\data\logs"

echo [%date% %time%] scan starting >> "%LOG_FILE%"
"%SEPA_DIR%\.venv\Scripts\python.exe" -m sepa.run_daily >> "%LOG_FILE%" 2>&1
echo [%date% %time%] scan done (exit %errorlevel%) >> "%LOG_FILE%"
