# One daily YouTube Shorts generation run. Registered by register_schedule.ps1;
# also safe to run manually. Output goes to logs/daily-<yyyyMMdd>.log.
#
# The topic-history check makes a repeat-trend day a successful no-op (exit 0),
# so this script never uploads the same topic twice within the lookback window.
# On failure, a Windows toast points at the log (best-effort — the scheduled
# task otherwise fails silently).

param(
    # Overridable for testing and one-off runs (e.g. @("--allow-repeat")).
    [string[]]$ShortsArgs = @("--log-level", "INFO")
)

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo   # relative paths (output/, .env, models/) resolve from the repo root

$logDir = Join-Path $repo "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("daily-{0}.log" -f (Get-Date -Format "yyyyMMdd"))
$python = Join-Path $repo ".venv\Scripts\python.exe"

function Show-FailureToast {
    param([int]$ExitCode, [string]$LogPath)
    try {
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
        [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType = WindowsRuntime] | Out-Null
        $xml = @"
<toast><visual><binding template="ToastGeneric">
<text>YouTube Shorts daily run FAILED (exit $ExitCode)</text>
<text>See $LogPath</text>
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

Add-Content -Path $log -Value "=== run started $(Get-Date -Format o) ==="
# ToString() flattens the ErrorRecords PowerShell 5.1 wraps native stderr in
# (the pipeline logs to stderr by design). Appending per line (instead of one
# Add-Content sink) releases the file handle between lines, so the log can be
# tailed while the run is in progress.
& $python -m shorts @ShortsArgs 2>&1 |
    ForEach-Object { Add-Content -Path $log -Value $_.ToString() }
$code = $LASTEXITCODE
if ($null -eq $code) { $code = 1 }   # e.g. the interpreter itself failed to launch
Add-Content -Path $log -Value "=== run finished $(Get-Date -Format o) exit=$code ==="
if ($code -ne 0) {
    Add-Content -Path $log -Value "=== FAILED exit=$code ==="
    Show-FailureToast -ExitCode $code -LogPath $log
}
exit $code
