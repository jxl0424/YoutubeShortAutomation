# One daily YouTube Shorts generation run. Registered by register_schedule.ps1;
# also safe to run manually. Output goes to logs/daily-<yyyyMMdd>.log.
#
# The topic-history check makes a repeat-trend day a successful no-op (exit 0),
# so this script never uploads the same topic twice within the lookback window.

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo   # relative paths (output/, .env, models/) resolve from the repo root

$logDir = Join-Path $repo "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("daily-{0}.log" -f (Get-Date -Format "yyyyMMdd"))
$python = Join-Path $repo ".venv\Scripts\python.exe"

Add-Content -Path $log -Value "=== run started $(Get-Date -Format o) ==="
# ToString() flattens the ErrorRecords PowerShell 5.1 wraps native stderr in
# (the pipeline logs to stderr by design). Appending per line (instead of one
# Add-Content sink) releases the file handle between lines, so the log can be
# tailed while the run is in progress.
& $python -m shorts --log-level INFO 2>&1 |
    ForEach-Object { Add-Content -Path $log -Value $_.ToString() }
$code = $LASTEXITCODE
Add-Content -Path $log -Value "=== run finished $(Get-Date -Format o) exit=$code ==="
exit $code
