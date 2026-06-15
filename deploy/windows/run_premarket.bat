@echo off
:: SEPA Signals — pre-market scan (14:00 London / 09:00 ET)
:: Uses last night's price data to show what's buyable at the open.
:: Dedup prevents re-alerting names already sent the previous evening.

set SEPA_DIR=%~dp0..\..
set LOG_FILE=%SEPA_DIR%\data\logs\premarket.log

:: Create log folder if missing
if not exist "%SEPA_DIR%\data\logs" mkdir "%SEPA_DIR%\data\logs"

echo [%date% %time%] pre-market scan starting >> "%LOG_FILE%"
"%SEPA_DIR%\.venv\Scripts\python.exe" -m sepa.run_daily >> "%LOG_FILE%" 2>&1
echo [%date% %time%] pre-market scan done (exit %errorlevel%) >> "%LOG_FILE%"
