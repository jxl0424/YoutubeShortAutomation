# One weekly channel-growth report run. Registered by
# register_report_schedule.ps1; also safe to run manually. Output goes to
# logs/report-<yyyyMMdd>.log; the report lands in reports/weekly-<date>.md.
#
# On success a toast shows the report's SUMMARY line (the report is useful
# without opening the file); on failure the toast points at the log.

param(
    [string[]]$ReportArgs = @("--log-level", "INFO")
)

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo   # relative paths (.env, .secrets/) resolve from the repo root

$logDir = Join-Path $repo "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("report-{0}.log" -f (Get-Date -Format "yyyyMMdd"))
$python = Join-Path $repo ".venv\Scripts\python.exe"

function Show-Toast {
    param([string]$Title, [string]$Body)
    try {
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
        [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType = WindowsRuntime] | Out-Null
        $xml = @"
<toast><visual><binding template="ToastGeneric">
<text>$Title</text>
<text>$Body</text>
</binding></visual></toast>
"@
        $doc = New-Object Windows.Data.Xml.Dom.XmlDocument
        $doc.LoadXml($xml)
        # PowerShell's registered AUMID — lets a plain script raise toasts.
        $appId = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
        $toast = New-Object Windows.UI.Notifications.ToastNotification($doc)
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show($toast)
    } catch {
        # Notification is a nicety; never let it change the run's outcome.
    }
}

Add-Content -Path $log -Value "=== report started $(Get-Date -Format o) ==="
# Per-line Add-Content keeps the log tailable mid-run (a pipeline sink would
# hold an exclusive lock); ToString() flattens PS 5.1's stderr ErrorRecords.
& $python -m shorts.analytics @ReportArgs 2>&1 |
    ForEach-Object { Add-Content -Path $log -Value $_.ToString() }
$code = $LASTEXITCODE
if ($null -eq $code) { $code = 1 }   # e.g. the interpreter itself failed to launch
Add-Content -Path $log -Value "=== report finished $(Get-Date -Format o) exit=$code ==="

if ($code -eq 0) {
    $summary = (Select-String -Path $log -Pattern "^SUMMARY: " |
        Select-Object -Last 1).Line -replace "^SUMMARY: ", ""
    if (-not $summary) { $summary = "Report written (see reports\)." }
    Show-Toast -Title "DaDailyScroll weekly report" -Body $summary
} else {
    Add-Content -Path $log -Value "=== FAILED exit=$code ==="
    Show-Toast -Title "Weekly report FAILED (exit $code)" -Body "See $log"
}
exit $code
