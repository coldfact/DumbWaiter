Param(
  [string]$TaskName = "DumbWaiterTray",
  [string]$WorkingDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
  [string]$ConfigPath = (Join-Path $PSScriptRoot "..\..\config.yaml"),
  [string]$ExecutablePath = "",
  [string]$WorkerPythonPath = "",
  [switch]$Debug,
  [switch]$WorkerDebug,
  [switch]$WorkerVerbose,
  [switch]$StartNow
)

if (-not (Test-Path $ConfigPath)) {
  Write-Host "Config not found: $ConfigPath"
  exit 1
}
$ConfigPath = (Resolve-Path $ConfigPath).Path

if ($ExecutablePath) {
  if (-not (Test-Path $ExecutablePath)) {
    Write-Host "Executable not found: $ExecutablePath"
    exit 1
  }

  $ExecutablePath = (Resolve-Path $ExecutablePath).Path
  $RunDir = Split-Path -Path $ExecutablePath -Parent
  $Args = "--config `"$ConfigPath`""
  if ($Debug) {
    $Args += " --debug"
  }
  if ($WorkerDebug) {
    $Args += " --worker-debug"
  }
  if ($WorkerVerbose) {
    $Args += " --worker-verbose"
  }
  if ($WorkerPythonPath) {
    if (-not (Test-Path $WorkerPythonPath)) {
      Write-Host "Worker python not found: $WorkerPythonPath"
      exit 1
    }
    $WorkerPythonPath = (Resolve-Path $WorkerPythonPath).Path
    $Args += " --python-path `"$WorkerPythonPath`""
  }
  $Action = New-ScheduledTaskAction -Execute $ExecutablePath -Argument $Args -WorkingDirectory $RunDir
}
else {
  $Pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
  if (-not $Pythonw) {
    Write-Host "pythonw.exe not found on PATH. Install Python or add it to PATH."
    exit 1
  }

  $ScriptPath = Join-Path $WorkingDir "dumb_waiter_tray\tray_app.py"
  if (-not (Test-Path $ScriptPath)) {
    Write-Host "Tray script not found: $ScriptPath"
    exit 1
  }

  $Args = "`"$ScriptPath`" --config `"$ConfigPath`""
  if ($Debug) {
    $Args += " --debug"
  }
  if ($WorkerDebug) {
    $Args += " --worker-debug"
  }
  if ($WorkerVerbose) {
    $Args += " --worker-verbose"
  }
  $Action = New-ScheduledTaskAction -Execute $Pythonw -Argument $Args -WorkingDirectory $WorkingDir
}

$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

try {
  $Description = "Dumb Waiter tray app - auto-click UI prompts in matching windows."
  Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description $Description -Force | Out-Null
  if ($ExecutablePath) {
    Write-Host "Installed Scheduled Task '$TaskName' to run Dumb Waiter tray EXE at logon."
  }
  else {
    Write-Host "Installed Scheduled Task '$TaskName' to run Dumb Waiter tray at logon."
  }

  if ($StartNow) {
    try {
      Start-ScheduledTask -TaskName $TaskName
      Write-Host "Started Scheduled Task '$TaskName' now."
    }
    catch {
      Write-Host "Installed task, but could not start it now: $($_.Exception.Message)"
    }
  }
}
catch {
  Write-Host "Failed to register scheduled task: $($_.Exception.Message)"
  exit 1
}
