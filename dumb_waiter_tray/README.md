# Dumb Waiter Tray

This folder adds a Windows tray controller for `dumb_waiter.py`.

> [!WARNING]
>
> - The tray can run Dumb Waiter unattended, so approvals can happen without active human review.
> - Only use this if you understand what actions may be approved and have constrained environment/process permissions.
> - Check in (commit/push) your code before leaving unattended automation running.
> - If you are unsure, do not enable unattended mode.
> - This project is provided as-is, without warranty; you are responsible for any consequences on your system, code, or data.

`tray_app.py` features:

- `Turn on` (start clicker)
- `Turn off` (stop clicker)
- `Reload config` – re-reads `config.yaml` without quitting the tray app. If the worker is running it is stopped and restarted; if idle it starts with the fresh config. Use this after editing targets, regions, or any other YAML setting.
- icon status:
    - Green = idle/waiting
    - Red = active

## Install dependencies

```powershell
python -m pip install -r .\dumb_waiter_tray\requirements.txt
```

## Run tray app manually

```powershell
python .\dumb_waiter_tray\tray_app.py --config .\config.yaml
```

For no terminal window:

```powershell
pythonw .\dumb_waiter_tray\tray_app.py --config .\config.yaml
```

Run with tray-level diagnostics:

```powershell
python .\dumb_waiter_tray\tray_app.py --config .\config.yaml --debug
```

> `--debug` enables lifecycle logging to `tray.log` (lightweight).
> Worker logging (`worker.log`) is controlled by `verbose` and `debug_mode` in `config.yaml`.

Logs:

- `dumb_waiter_tray/tray.log` — tray app lifecycle, worker launch/exit details (controlled by `--debug`)
- `dumb_waiter_tray/worker.log` — `dumb_waiter.py` output (controlled by `verbose` / `debug_mode` in `config.yaml`)
- `dumb_waiter_tray/dist/startup_error.log` — fatal tray startup exceptions (appears next to `dumb_waiter_tray.exe` in `dist/`)

If the EXE exits immediately with no tray icon:

```powershell
Get-Content .\dumb_waiter_tray\dist\startup_error.log -Tail 200
```

## Config notes (`config.yaml`)

Tray mode uses the same `config.yaml` as direct/script mode.

Most common changes:

- `uia.window_title_regex`: change from `"Antigravity"` to your app/window title regex.
    - Example: `"VS Code|Visual Studio Code"`
- `interval_seconds`: polling frequency (`1.0` is faster than `2.0`).
- `scope.preset`: reduce false positives (`right_half` or `bottom_right_quarter`).
- `debug_mode`: set `true` temporarily if a button is not being detected.

Example:

```yaml
interval_seconds: 1.0
uia:
    window_title_regex: "VS Code|Visual Studio Code"
scope:
    enabled: true
    preset: "bottom_right_quarter"
```

## Auto-start tray at logon

```powershell
powershell -ExecutionPolicy Bypass -File .\dumb_waiter_tray\scripts\install_startup_task.ps1
```

Install and start immediately:

```powershell
powershell -ExecutionPolicy Bypass -File .\dumb_waiter_tray\scripts\install_startup_task.ps1 -StartNow
```

Install/start with debug flag:

```powershell
powershell -ExecutionPolicy Bypass -File .\dumb_waiter_tray\scripts\install_startup_task.ps1 -StartNow -Debug
```

⚠️ Warning: if this fails with `Access is denied`, open PowerShell as Administrator and run the command again.

After it starts, look for the Dumb Waiter tray icon near the clock:

- Green icon = idle (watcher off)
- Red icon = active (watcher on)
- If you do not see it, click tray overflow (`^`) and pin it

Remove task:

```powershell
powershell -ExecutionPolicy Bypass -File .\dumb_waiter_tray\scripts\remove_startup_task.ps1
```

Install task to run built EXE instead of python script:

```powershell
powershell -ExecutionPolicy Bypass -File .\dumb_waiter_tray\scripts\install_startup_task.ps1 -ExecutablePath .\dumb_waiter_tray\dist\dumb_waiter_tray.exe
```

Pin the worker to a specific Python/venv (optional, EXE mode):

```powershell
powershell -ExecutionPolicy Bypass -File .\dumb_waiter_tray\scripts\install_startup_task.ps1 -ExecutablePath .\dumb_waiter_tray\dist\dumb_waiter_tray.exe -WorkerPythonPath N:\VENVS\vanna_poc\Scripts\python.exe
```

## Build tray EXE (PyInstaller)

Build:

```powershell
powershell -ExecutionPolicy Bypass -File .\dumb_waiter_tray\build_tray_exe.ps1
```

Preflight only (check machine/deps/task prerequisites; no build/install):

```powershell
powershell -ExecutionPolicy Bypass -File .\dumb_waiter_tray\build_tray_exe.ps1 -PreflightOnly
```

The build script runs preflight automatically before build/install.

Build and install startup task in one step (optional):

```powershell
powershell -ExecutionPolicy Bypass -File .\dumb_waiter_tray\build_tray_exe.ps1 -InstallStartupTask
```

With current script behavior, `-InstallStartupTask` starts the task immediately.
Disable immediate start if needed:

```powershell
powershell -ExecutionPolicy Bypass -File .\dumb_waiter_tray\build_tray_exe.ps1 -InstallStartupTask -StartAfterInstall:$false
```

Build + install + start with debug flag:

```powershell
powershell -ExecutionPolicy Bypass -File .\dumb_waiter_tray\build_tray_exe.ps1 -InstallStartupTask -TaskDebug
```

⚠️ Warning: startup task registration may require an elevated (Administrator) PowerShell session.

Build + install startup task + pin worker Python:

```powershell
powershell -ExecutionPolicy Bypass -File .\dumb_waiter_tray\build_tray_exe.ps1 -InstallStartupTask -WorkerPythonPath N:\VENVS\vanna_poc\Scripts\python.exe
```

By default, startup task install is left to the user. `-InstallStartupTask` is opt-in.

## Notes

Use tray + startup task for unattended user-session automation.
