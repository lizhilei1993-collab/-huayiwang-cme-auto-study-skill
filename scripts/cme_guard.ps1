# CME video runner watchdog
# Trigger: scheduled task CMEVideoRunner is Running (process alive) but runner.log has no new lines for > 12 min
# Action: kill the stuck runner process -> re-trigger CMEVideoRunner (playback resumes from server-side progress)
# Also: if CDP port 9222 is down, start CMEChromeSupervisor

$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference = 'SilentlyContinue'
$AB = $env:CME_DATA_DIR
if (-not $AB) { $AB = Join-Path $PSScriptRoot '..\ab' }
$LOG = Join-Path $AB 'runner.log'
$GUARDLOG = Join-Path $AB 'guard.log'
$STALE_SEC = 720

function Write-GuardLog($msg) {
    $line = "$(Get-Date -Format 'MM-dd HH:mm:ss') $msg"
    Add-Content -Path $GUARDLOG -Value $line -Encoding UTF8
}

# 1) Chrome CDP 9222 alive?
$cdpOk = $false
try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:9222/json/version' -TimeoutSec 5 -UseBasicParsing
    if ($r.StatusCode -eq 200) { $cdpOk = $true }
} catch { $cdpOk = $false }

if (-not $cdpOk) {
    Write-GuardLog 'CDP 9222 DOWN -> start CMEChromeSupervisor'
    Start-ScheduledTask -TaskName 'CMEChromeSupervisor'
    Start-Sleep -Seconds 15
}

# 2) runner stall check
$task = Get-ScheduledTask -TaskName 'CMEVideoRunner'
$proc = @(Get-CimInstance Win32_Process -Filter "Name like 'pythonw%'" | Where-Object { $_.CommandLine -like '*cme_runner.py*' })

if ($task.State -eq 'Running' -or $proc.Count -gt 0) {
    if (Test-Path $LOG) {
        $age = ((Get-Date) - (Get-Item $LOG).LastWriteTime).TotalSeconds
        if ($age -gt $STALE_SEC) {
            Write-GuardLog ("runner log stale {0:N0}s -> restart (procs={1})" -f $age, $proc.Count)
            foreach ($p in $proc) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
            Start-Sleep -Seconds 4
            Start-ScheduledTask -TaskName 'CMEVideoRunner'
            Start-Sleep -Seconds 10
            $n = @(Get-CimInstance Win32_Process -Filter "Name like 'pythonw%'" | Where-Object { $_.CommandLine -like '*cme_runner.py*' })
            Write-GuardLog ("restart done, runner procs={0}" -f $n.Count)
        }
    }
}
