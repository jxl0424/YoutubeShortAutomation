# One-time registration of the daily Shorts run in Windows Task Scheduler.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\register_schedule.ps1 [-Time "09:00"]
# Remove: Unregister-ScheduledTask -TaskName "YouTubeShortsDaily" -Confirm:$false

param(
    [string]$Time = "09:00",
    [string]$TaskName = "YouTubeShortsDaily"
)

$repo = Split-Path -Parent $PSScriptRoot
$script = Join-Path $repo "scripts\run_daily.ps1"

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`"" `
    -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
# StartWhenAvailable: if the machine was asleep/off at the scheduled time, the
# run fires shortly after it becomes available instead of skipping the day.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Force | Out-Null

Write-Host "Registered task '$TaskName' to run daily at $Time (as the current user, while logged on)."
Write-Host "Trigger a test run now with:  Start-ScheduledTask -TaskName '$TaskName'"
