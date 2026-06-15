@echo off
:: SEPA Signals — post-close data ingest (prices + fundamentals)
:: Scheduled via Task Scheduler to run at 21:30 London / 16:30 ET daily.
:: 30 minutes after US market close — prices are settled by then.

set SEPA_DIR=%~dp0..\..
set LOG_FILE=%SEPA_DIR%\data\logs\ingest.log

:: Create log folder if missing
if not exist "%SEPA_DIR%\data\logs" mkdir "%SEPA_DIR%\data\logs"

echo [%date% %time%] ingest starting >> "%LOG_FILE%"
"%SEPA_DIR%\.venv\Scripts\python.exe" -m sepa.ingest >> "%LOG_FILE%" 2>&1
echo [%date% %time%] ingest done (exit %errorlevel%) >> "%LOG_FILE%"
