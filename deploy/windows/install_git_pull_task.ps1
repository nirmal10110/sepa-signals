# SEPA Signals - registers a Task Scheduler job to git pull every 2 hours.
# Run once as Administrator:
#   cd C:\Users\lathe\sepa-signals\deploy\windows
#   .\install_git_pull_task.ps1

$sepaDir = Resolve-Path "$PSScriptRoot\..\.."
$batFile  = "$PSScriptRoot\git_pull.bat"

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable

$action  = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$batFile`""

# Repeat every 2 hours, starting at midnight, running indefinitely
$trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 30) `
    -Once -At "00:00"

Register-ScheduledTask `
    -TaskName   "SEPA-GitPull" `
    -Action     $action `
    -Trigger    $trigger `
    -Settings   $settings `
    -RunLevel   Highest `
    -Force

Write-Host "OK SEPA-GitPull task registered (runs every 30 minutes)"
Write-Host "Log: $sepaDir\data\logs\git_pull.log"
