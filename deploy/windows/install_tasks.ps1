# SEPA Signals — installs two Windows Task Scheduler tasks.
# Run once as Administrator in PowerShell:
#   Right-click PowerShell → "Run as Administrator"
#   cd C:\sepa-signals\deploy\windows
#   .\install_tasks.ps1

$sepaDir = Resolve-Path "$PSScriptRoot\..\.."

# ── Task 1: Nightly ingest at 9:00 PM ────────────────────────────────────────
$ingestAction  = New-ScheduledTaskAction `
    -Execute "$sepaDir\.venv\Scripts\python.exe" `
    -Argument "-m sepa.ingest" `
    -WorkingDirectory $sepaDir

$ingestTrigger = New-ScheduledTaskTrigger -Daily -At "21:00"

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable

Register-ScheduledTask `
    -TaskName   "SEPA-Ingest" `
    -Action     $ingestAction `
    -Trigger    $ingestTrigger `
    -Settings   $settings `
    -RunLevel   Highest `
    -Force

Write-Host "✓ SEPA-Ingest task registered (runs at 9:00 PM daily)"

# ── Task 2: Nightly scan + alerts at 10:00 PM ────────────────────────────────
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

Write-Host "✓ SEPA-Daily task registered (runs at 10:00 PM daily)"
Write-Host ""
Write-Host "To verify: open Task Scheduler and look for SEPA-Ingest and SEPA-Daily."
Write-Host "Logs will appear in: $sepaDir\data\logs\"
