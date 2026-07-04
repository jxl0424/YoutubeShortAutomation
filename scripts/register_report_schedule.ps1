# One-time registration of the weekly report run in Windows Task Scheduler.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\register_report_schedule.ps1 [-Time "09:30"] [-Day Monday]
# Remove: Unregister-ScheduledTask -TaskName "YouTubeShortsWeeklyReport" -Confirm:$false
#
# Monday morning covers the previous Mon-Sun; the report window always ends
# yesterday regardless of when the task actually fires (see week_range).

param(
    [string]$Time = "09:30",
    [string]$Day = "Monday",
    [string]$TaskName = "YouTubeShortsWeeklyReport"
)

$repo = Split-Path -Parent $PSScriptRoot
$script = Join-Path $repo "scripts\run_weekly_report.ps1"

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`"" `
    -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Day -At $Time
# StartWhenAvailable: if the machine was asleep/off at the scheduled time, the
# run fires shortly after it becomes available instead of skipping the week.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Force | Out-Null

Write-Host "Registered task '$TaskName' to run every $Day at $Time (as the current user, while logged on)."
Write-Host "Trigger a test run now with:  Start-ScheduledTask -TaskName '$TaskName'"
