param(
    [string]$PythonPath = "",
    [string]$ScriptPath = "",
    [string]$ConfigPath = "",
    [int]$RestartDelaySeconds = 1
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $ScriptPath) {
    $ScriptPath = Join-Path $PSScriptRoot "dumb_waiter.py"
}

if (-not $ConfigPath) {
    $ConfigPath = Join-Path $PSScriptRoot "config.yaml"
}

if (-not $PythonPath) {
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCmd) {
        throw "Could not find 'python' on PATH. Pass -PythonPath explicitly."
    }
    $PythonPath = $pythonCmd.Source
}

if (-not (Test-Path $PythonPath)) {
    throw "Python executable not found: $PythonPath"
}
if (-not (Test-Path $ScriptPath)) {
    throw "Script not found: $ScriptPath"
}
if (-not (Test-Path $ConfigPath)) {
    throw "Config not found: $ConfigPath"
}
if ($RestartDelaySeconds -lt 0) {
    throw "RestartDelaySeconds must be >= 0."
}

Write-Host "[watchdog] Starting resilient dumb_waiter runner."
Write-Host "[watchdog] python = $PythonPath"
Write-Host "[watchdog] script = $ScriptPath"
Write-Host "[watchdog] config = $ConfigPath"
Write-Host "[watchdog] restart_delay_seconds = $RestartDelaySeconds"
Write-Host "[watchdog] Press Ctrl+C to stop."

while ($true) {
    $start = Get-Date
    Write-Host "[watchdog] Launching dumb_waiter..."
    & $PythonPath $ScriptPath --config $ConfigPath
    $exitCode = $LASTEXITCODE
    $uptime = (Get-Date) - $start
    $uptimeText = "{0:hh\:mm\:ss}" -f $uptime
    Write-Host "[watchdog] dumb_waiter exited (code=$exitCode, uptime=$uptimeText). Restarting..."
    if ($RestartDelaySeconds -gt 0) {
        Start-Sleep -Seconds $RestartDelaySeconds
    }
}
