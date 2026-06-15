# SEPA Signals — installs three Windows Task Scheduler tasks.
# All times are LOCAL (London) time. Set your PC clock to London time.
#
# Schedule (London / US Eastern):
#   14:00 London (09:00 ET)  — Pre-market scan: see today's buyable list at the open
#   21:30 London (16:30 ET)  — Post-close ingest: download today's settled prices
#   22:00 London (17:00 ET)  — Post-close scan: fresh signals + Telegram alerts
#
# Why 21:30 for ingest (30 min after US close)?
#   yfinance data for today's session is settled by ~16:15 ET.
#   Pre-market earnings (released 07-08 ET) are baked into today's close price.
#   After-hours earnings show up in tomorrow's price action — no need to rush.
#
# Run once as Administrator in PowerShell:
#   Right-click PowerShell → "Run as Administrator"
#   cd C:\sepa-signals\deploy\windows
#   .\install_tasks.ps1

$sepaDir = Resolve-Path "$PSScriptRoot\..\.."

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable

# ── Task 1: Pre-market scan at 14:00 (09:00 ET) ──────────────────────────────
# Runs the scanner on yesterday's data so you know what's buyable at the open.
# Dedup prevents re-alerting names already alerted the night before.
$preAction  = New-ScheduledTaskAction `
    -Execute "$sepaDir\.venv\Scripts\python.exe" `
    -Argument "-m sepa.run_daily" `
    -WorkingDirectory $sepaDir

$preTrigger = New-ScheduledTaskTrigger -Daily -At "14:00"

Register-ScheduledTask `
    -TaskName   "SEPA-PreMarket" `
    -Action     $preAction `
    -Trigger    $preTrigger `
    -Settings   $settings `
    -RunLevel   Highest `
    -Force

Write-Host "✓ SEPA-PreMarket task registered (runs at 14:00 London / 09:00 ET)"

# ── Task 2: Post-close ingest at 21:30 (16:30 ET) ────────────────────────────
$ingestAction  = New-ScheduledTaskAction `
    -Execute "$sepaDir\.venv\Scripts\python.exe" `
    -Argument "-m sepa.ingest" `
    -WorkingDirectory $sepaDir

$ingestTrigger = New-ScheduledTaskTrigger -Daily -At "21:30"

Register-ScheduledTask `
    -TaskName   "SEPA-Ingest" `
    -Action     $ingestAction `
    -Trigger    $ingestTrigger `
    -Settings   $settings `
    -RunLevel   Highest `
    -Force

Write-Host "✓ SEPA-Ingest task registered (runs at 21:30 London / 16:30 ET)"

# ── Task 3: Post-close scan + alerts at 22:00 (17:00 ET) ─────────────────────
$dailyAction  = New-ScheduledTaskAction `
    -Execute "$sepaDir\.venv\Scripts\python.exe" `
    -Argument "-m sepa.run_daily" `
    -WorkingDirectory $sepaDir

$dailyTrigger = New-ScheduledTaskTrigger -Daily -At "22:00"

Register-ScheduledTask `
    -TaskName   "SEPA-Daily" `
    -Action     $dailyAction `
    -Trigger    $dailyTrigger `
    -Settings   $settings `
    -RunLevel   Highest `
    -Force

Write-Host "✓ SEPA-Daily task registered (runs at 22:00 London / 17:00 ET)"
Write-Host ""
Write-Host "Tasks registered:"
Write-Host "  SEPA-PreMarket  14:00 London  — pre-market signal review"
Write-Host "  SEPA-Ingest     21:30 London  — download today's prices"
Write-Host "  SEPA-Daily      22:00 London  — fresh scan + Telegram alerts"
Write-Host ""
Write-Host "To verify: open Task Scheduler and look for SEPA-PreMarket, SEPA-Ingest, SEPA-Daily."
Write-Host "Logs will appear in: $sepaDir\data\logs\"
