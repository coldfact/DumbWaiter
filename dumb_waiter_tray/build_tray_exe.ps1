Param(
  [string]$PythonPath = "",
  [string]$Name = "dumb_waiter_tray",
  [string]$ConfigPath = (Join-Path $PSScriptRoot "..\config.yaml"),
  [string]$OutputDir = (Join-Path $PSScriptRoot "dist"),
  [string]$IconPath = "",
  [string]$WorkerPythonPath = "",
  [switch]$SkipPipInstall,
  [switch]$PreflightOnly,
  [switch]$InstallStartupTask,
  [bool]$StartAfterInstall = $true,
  [switch]$TaskDebug,
  [switch]$TaskWorkerDebug,
  [switch]$TaskWorkerVerbose,
  [string]$TaskName = "DumbWaiterTray"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$TrayScript = Join-Path $PSScriptRoot "tray_app.py"
$Requirements = Join-Path $PSScriptRoot "requirements.txt"
$BuildDir = Join-Path $PSScriptRoot "build"
$InstallTaskScript = Join-Path $PSScriptRoot "scripts\install_startup_task.ps1"

function Write-Ok([string]$Message) {
  Write-Host "[preflight][OK] $Message"
}

function Write-Warn([string]$Message) {
  Write-Host "[preflight][WARN] $Message"
}

function Write-Fail([string]$Message) {
  Write-Host "[preflight][FAIL] $Message"
}

function Test-IsAdministrator {
  try {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  }
  catch {
    return $false
  }
}

function Resolve-FilePath([string]$PathValue) {
  if (-not $PathValue) {
    return $null
  }
  if (-not (Test-Path $PathValue)) {
    return $null
  }
  return (Resolve-Path $PathValue).Path
}

if (-not $PythonPath) {
  $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
  if ($pythonCmd) {
    $PythonPath = $pythonCmd.Source
  }
}

$PythonPathResolved = Resolve-FilePath $PythonPath
$ConfigPathResolved = Resolve-FilePath $ConfigPath
$IconPathResolved = Resolve-FilePath $IconPath
$WorkerPythonPathResolved = Resolve-FilePath $WorkerPythonPath
$TrayScriptResolved = Resolve-FilePath $TrayScript
$RequirementsResolved = Resolve-FilePath $Requirements
$InstallTaskScriptResolved = Resolve-FilePath $InstallTaskScript

$preflightErrors = New-Object System.Collections.Generic.List[string]
$preflightWarnings = New-Object System.Collections.Generic.List[string]

Write-Host "[preflight] Running environment checks..."

if ($PythonPathResolved) {
  Write-Ok "Python executable found: $PythonPathResolved"
}
else {
  $preflightErrors.Add("Python executable not found. Pass -PythonPath explicitly.")
  Write-Fail "Python executable not found. Pass -PythonPath explicitly."
}

if ($TrayScriptResolved) {
  Write-Ok "Tray script found: $TrayScriptResolved"
}
else {
  $preflightErrors.Add("Tray script missing: $TrayScript")
  Write-Fail "Tray script missing: $TrayScript"
}

if ($RequirementsResolved) {
  Write-Ok "Requirements file found: $RequirementsResolved"
}
else {
  $preflightErrors.Add("Requirements file missing: $Requirements")
  Write-Fail "Requirements file missing: $Requirements"
}

if ($ConfigPathResolved) {
  Write-Ok "Config file found: $ConfigPathResolved"
}
else {
  $preflightErrors.Add("Config file not found: $ConfigPath")
  Write-Fail "Config file not found: $ConfigPath"
}

if ($IconPath) {
  if ($IconPathResolved) {
    Write-Ok "Icon file found: $IconPathResolved"
  }
  else {
    $preflightErrors.Add("Icon file not found: $IconPath")
    Write-Fail "Icon file not found: $IconPath"
  }
}

if ($WorkerPythonPath) {
  if ($WorkerPythonPathResolved) {
    Write-Ok "Worker Python found: $WorkerPythonPathResolved"
  }
  else {
    $preflightErrors.Add("Worker Python not found: $WorkerPythonPath")
    Write-Fail "Worker Python not found: $WorkerPythonPath"
  }
}

if ($PythonPathResolved) {
  & $PythonPathResolved --version 2>$null
  if ($LASTEXITCODE -eq 0) {
    Write-Ok "Python runtime responds to --version."
  }
  else {
    $preflightErrors.Add("Python runtime check failed for: $PythonPathResolved")
    Write-Fail "Python runtime check failed for: $PythonPathResolved"
  }

  if ($SkipPipInstall) {
    & $PythonPathResolved -m PyInstaller --version 1>$null 2>$null
    if ($LASTEXITCODE -eq 0) {
      Write-Ok "PyInstaller is available (required when -SkipPipInstall is used)."
    }
    else {
      $preflightErrors.Add("PyInstaller is not available but -SkipPipInstall was specified.")
      Write-Fail "PyInstaller is not available but -SkipPipInstall was specified."
    }
  }
  else {
    & $PythonPathResolved -m pip --version 1>$null 2>$null
    if ($LASTEXITCODE -eq 0) {
      Write-Ok "pip is available."
    }
    else {
      $preflightErrors.Add("pip is not available for the selected Python.")
      Write-Fail "pip is not available for the selected Python."
    }
  }
}

if (-not $WorkerPythonPathResolved) {
  $runtimePython = (Get-Command pythonw.exe -ErrorAction SilentlyContinue)
  if (-not $runtimePython) {
    $runtimePython = (Get-Command python.exe -ErrorAction SilentlyContinue)
  }
  if ($runtimePython) {
    Write-Ok "Runtime worker Python candidate found on PATH: $($runtimePython.Source)"
  }
  else {
    $preflightWarnings.Add("No python/pythonw found on PATH for EXE runtime worker launch. Use -WorkerPythonPath when installing task.")
    Write-Warn "No python/pythonw found on PATH for EXE runtime worker launch. Use -WorkerPythonPath when installing task."
  }
}

if ($InstallStartupTask) {
  if ($InstallTaskScriptResolved) {
    Write-Ok "Startup task installer script found: $InstallTaskScriptResolved"
  }
  else {
    $preflightErrors.Add("Startup task script missing: $InstallTaskScript")
    Write-Fail "Startup task script missing: $InstallTaskScript"
  }

  $registerCmd = Get-Command Register-ScheduledTask -ErrorAction SilentlyContinue
  if ($registerCmd) {
    Write-Ok "ScheduledTasks cmdlets available."
  }
  else {
    $preflightErrors.Add("ScheduledTasks cmdlets not available on this machine/session.")
    Write-Fail "ScheduledTasks cmdlets not available on this machine/session."
  }

  if (-not (Test-IsAdministrator)) {
    $preflightWarnings.Add("Not running as Administrator. Task registration may fail with 'Access is denied'.")
    Write-Warn "Not running as Administrator. Task registration may fail with 'Access is denied'."
  }
  else {
    Write-Ok "Running with Administrator privileges."
  }
}

if ($ConfigPathResolved -and ($ConfigPathResolved.StartsWith("\\") -or $ConfigPathResolved.StartsWith("//"))) {
  $preflightWarnings.Add("Config path is UNC/network-based. Ensure it is reachable at logon for scheduled task runs.")
  Write-Warn "Config path is UNC/network-based. Ensure it is reachable at logon for scheduled task runs."
}

if ($preflightWarnings.Count -gt 0) {
  Write-Host "[preflight] Completed with warnings: $($preflightWarnings.Count)"
}

if ($preflightErrors.Count -gt 0) {
  throw "Preflight failed with $($preflightErrors.Count) error(s)."
}

Write-Host "[preflight] PASS"

if ($PreflightOnly) {
  Write-Host "[preflight] Preflight-only mode complete."
  exit 0
}

$PythonPath = $PythonPathResolved
$ConfigPath = $ConfigPathResolved
if ($IconPath) {
  $IconPath = $IconPathResolved
}
if ($WorkerPythonPath) {
  $WorkerPythonPath = $WorkerPythonPathResolved
}

New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

Write-Host "[build] python = $PythonPath"
Write-Host "[build] script = $TrayScript"
Write-Host "[build] output = $OutputDir"

if (-not $SkipPipInstall) {
  Write-Host "[build] Installing/updating build dependencies..."
  & $PythonPath -m pip install --disable-pip-version-check -r $Requirements pyinstaller
  if ($LASTEXITCODE -ne 0) {
    throw "pip install failed with exit code $LASTEXITCODE"
  }
}

$PyArgs = @(
  "-m", "PyInstaller",
  "--noconfirm",
  "--clean",
  "--onefile",
  "--windowed",
  "--noupx",
  "--name", $Name,
  "--distpath", $OutputDir,
  "--workpath", $BuildDir,
  "--specpath", $PSScriptRoot
)

if ($IconPath) {
  $PyArgs += @("--icon", $IconPath)
}

$PyArgs += $TrayScript

Write-Host "[build] Running PyInstaller..."
& $PythonPath @PyArgs
if ($LASTEXITCODE -ne 0) {
  throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$ExePath = Join-Path $OutputDir "$Name.exe"
if (-not (Test-Path $ExePath)) {
  throw "Build completed but executable not found: $ExePath"
}

Write-Host "[build] Built: $ExePath"

if ($InstallStartupTask) {
  if (-not (Test-Path $InstallTaskScript)) {
    throw "Startup task script not found: $InstallTaskScript"
  }
  if ($StartAfterInstall) {
    Write-Host "[build] Installing startup task '$TaskName' and starting it now..."
  }
  else {
    Write-Host "[build] Installing startup task '$TaskName'..."
  }

  $InstallArgs = @{
    TaskName       = $TaskName
    ConfigPath     = $ConfigPath
    ExecutablePath = $ExePath
  }
  if ($WorkerPythonPath) {
    $InstallArgs["WorkerPythonPath"] = $WorkerPythonPath
  }
  if ($TaskDebug) {
    $InstallArgs["Debug"] = $true
  }
  if ($TaskWorkerDebug) {
    $InstallArgs["WorkerDebug"] = $true
  }
  if ($TaskWorkerVerbose) {
    $InstallArgs["WorkerVerbose"] = $true
  }
  if ($StartAfterInstall) {
    $InstallArgs["StartNow"] = $true
  }

  & $InstallTaskScript @InstallArgs
  if ($LASTEXITCODE -ne 0) {
    throw "Startup task install failed with exit code $LASTEXITCODE"
  }
}

Write-Host "[build] Done."
