from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional
import traceback

import pystray
from PIL import Image, ImageDraw


COLOR_IDLE = (34, 197, 94, 255)      # Green: idle / waiting
COLOR_ACTIVE = (220, 38, 38, 255)    # Red: active / clicker on
COLOR_BG_RING = (15, 23, 42, 255)
COLOR_FOREGROUND = (255, 255, 255, 255)


def make_status_icon(active: bool) -> Image.Image:
    """
    Draw a simple pointer-click inspired status icon.
    """
    fill = COLOR_ACTIVE if active else COLOR_IDLE
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    draw.ellipse((2, 2, 62, 62), fill=fill, outline=COLOR_BG_RING, width=2)

    pointer = [
        (18, 12),
        (43, 34),
        (33, 34),
        (38, 50),
        (31, 52),
        (25, 37),
        (16, 45),
    ]
    draw.polygon(pointer, fill=COLOR_FOREGROUND)

    draw.line((45, 10, 45, 17), fill=COLOR_FOREGROUND, width=3)
    draw.line((49, 18, 55, 14), fill=COLOR_FOREGROUND, width=3)
    draw.line((48, 24, 56, 24), fill=COLOR_FOREGROUND, width=3)

    return img


class DumbWaiterTrayApp:
    def __init__(
        self,
        config_path: Path,
        python_path: Optional[Path] = None,
        debug: bool = False,
        worker_debug: bool = False,
        worker_verbose: bool = False,
    ) -> None:
        self.config_path = config_path.resolve()
        self.repo_root = self._resolve_repo_root(self.config_path)
        self.worker_script = self.repo_root / "dumb_waiter.py"
        self.requested_python_path = python_path
        self.debug = debug
        self.worker_debug = worker_debug
        self.worker_verbose = worker_verbose
        self.log_path = self.repo_root / "dumb_waiter_tray" / "worker.log"
        self.tray_log_path = self.repo_root / "dumb_waiter_tray" / "tray.log"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker_process: Optional[subprocess.Popen] = None
        self._worker_log_handle = None
        self._last_exit_code: Optional[int] = None

        self.icon = pystray.Icon("DumbWaiterTray", make_status_icon(False), "Dumb Waiter | IDLE")
        self.icon.menu = pystray.Menu(
            pystray.MenuItem("Turn on", self.turn_on, enabled=lambda _item: not self.is_running()),
            pystray.MenuItem("Turn off", self.turn_off, enabled=lambda _item: self.is_running()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self.quit_app),
        )

        self._monitor_thread = threading.Thread(target=self._monitor_worker, daemon=True)
        self._monitor_thread.start()
        self._refresh_icon_and_title()
        self._log(
            f"initialized repo_root={self.repo_root} config={self.config_path} "
            f"requested_python={self.requested_python_path} worker_debug={self.worker_debug} "
            f"worker_verbose={self.worker_verbose}"
        )

    def _resolve_repo_root(self, config_path: Path) -> Path:
        config_root = config_path.parent
        if (config_root / "dumb_waiter.py").exists():
            return config_root
        return Path(__file__).resolve().parents[1]

    def _resolve_python_executable(self, requested_python: Optional[Path]) -> str:
        if requested_python is not None:
            resolved = requested_python.expanduser().resolve()
            if not resolved.exists():
                raise FileNotFoundError(f"Python executable not found: {resolved}")
            return str(resolved)

        # In source runs, sys.executable is the active Python interpreter.
        if not getattr(sys, "frozen", False):
            return sys.executable

        # In frozen runs, sys.executable is the tray EXE, so find a real Python runtime.
        for name in ("pythonw.exe", "python.exe", "pythonw", "python"):
            candidate = shutil.which(name)
            if candidate:
                return candidate
        raise RuntimeError(
            "Could not find python/pythonw on PATH for launching dumb_waiter.py. "
            "Start tray with --python-path <path-to-python.exe>."
        )

    def is_running(self) -> bool:
        with self._lock:
            return self._is_running_unlocked()

    def _is_running_unlocked(self) -> bool:
        return self._worker_process is not None and self._worker_process.poll() is None

    def _refresh_icon_and_title(self) -> None:
        running = self.is_running()
        self.icon.icon = make_status_icon(running)
        if running:
            self.icon.title = "Dumb Waiter | ACTIVE"
        elif self._last_exit_code is None:
            self.icon.title = "Dumb Waiter | IDLE"
        else:
            self.icon.title = f"Dumb Waiter | IDLE | last exit={self._last_exit_code}"
        try:
            self.icon.update_menu()
        except Exception:
            pass

    def _log(self, message: str) -> None:
        if not self.debug:
            return
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{stamp}] {message}\n"
        try:
            with self.tray_log_path.open("a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass

    def _start_worker(self) -> None:
        with self._lock:
            if self._is_running_unlocked():
                self._log("start requested but worker already running")
                return

            if not self.worker_script.exists():
                raise FileNotFoundError(f"Worker script missing: {self.worker_script}")
            if not self.config_path.exists():
                raise FileNotFoundError(f"Config file missing: {self.config_path}")

            self._worker_log_handle = self.log_path.open("a", encoding="utf-8")
            self._worker_log_handle.write(
                f"\n=== start {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n"
            )
            self._worker_log_handle.flush()

            python_executable = self._resolve_python_executable(self.requested_python_path)
            cmd = [python_executable, str(self.worker_script), "--config", str(self.config_path)]
            env = os.environ.copy()
            # Keep worker stdout/stderr UTF-8 when launched via pythonw/tray.
            # Without this, UI labels like "RunAlt+⏎" can raise UnicodeEncodeError
            # during logging and prevent the click path from completing.
            env.setdefault("PYTHONUTF8", "1")
            env.setdefault("PYTHONIOENCODING", "utf-8")
            if self.worker_debug:
                env["DUMB_WAITER_DEBUG_MODE"] = "1"
            if self.worker_verbose:
                env["DUMB_WAITER_VERBOSE"] = "1"
            creation_flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            self._log(
                f"starting worker python={python_executable} cmd={cmd} "
                f"PYTHONUTF8={env.get('PYTHONUTF8')} "
                f"PYTHONIOENCODING={env.get('PYTHONIOENCODING')} "
                f"DUMB_WAITER_DEBUG_MODE={env.get('DUMB_WAITER_DEBUG_MODE')} "
                f"DUMB_WAITER_VERBOSE={env.get('DUMB_WAITER_VERBOSE')}"
            )

            self._worker_process = subprocess.Popen(
                cmd,
                cwd=str(self.repo_root),
                stdout=self._worker_log_handle,
                stderr=subprocess.STDOUT,
                creationflags=creation_flags,
                env=env,
            )
            self._last_exit_code = None
            self._log(f"worker started pid={self._worker_process.pid}")

        self._refresh_icon_and_title()

    def _stop_worker(self) -> None:
        with self._lock:
            proc = self._worker_process
            self._worker_process = None

        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
                self._log(f"worker terminated gracefully pid={proc.pid}")
            except Exception:
                try:
                    proc.kill()
                    self._log(f"worker force-killed pid={proc.pid}")
                except Exception:
                    pass

        with self._lock:
            if self._worker_log_handle is not None:
                try:
                    self._worker_log_handle.write(
                        f"=== stop {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n"
                    )
                    self._worker_log_handle.flush()
                except Exception:
                    pass
                try:
                    self._worker_log_handle.close()
                except Exception:
                    pass
                self._worker_log_handle = None

        self._refresh_icon_and_title()

    def _monitor_worker(self) -> None:
        while not self._stop_event.wait(1.0):
            ended_code = None

            with self._lock:
                if self._worker_process is not None:
                    ended_code = self._worker_process.poll()
                    if ended_code is not None:
                        self._worker_process = None
                        self._last_exit_code = ended_code
                        if self._worker_log_handle is not None:
                            try:
                                self._worker_log_handle.write(
                                    f"=== exited {time.strftime('%Y-%m-%d %H:%M:%S')} code={ended_code} ===\n"
                                )
                                self._worker_log_handle.flush()
                            except Exception:
                                pass
                            try:
                                self._worker_log_handle.close()
                            except Exception:
                                pass
                            self._worker_log_handle = None

            if ended_code is not None:
                self._log(f"worker exited code={ended_code}")
                self._refresh_icon_and_title()

    def turn_on(self, _icon=None, _item=None) -> None:
        self._log("turn_on clicked")
        try:
            self._start_worker()
        except Exception as exc:
            self._last_exit_code = -1
            self.icon.title = f"Dumb Waiter | ERROR | {exc}"
            self._log(f"turn_on failed: {exc!r}")
        self._refresh_icon_and_title()

    def turn_off(self, _icon=None, _item=None) -> None:
        self._log("turn_off clicked")
        self._stop_worker()

    def quit_app(self, _icon=None, _item=None) -> None:
        self._log("quit clicked")
        self._stop_event.set()
        self._stop_worker()
        self.icon.stop()

    def run(self) -> None:
        self.icon.run()


def get_startup_error_log_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "startup_error.log"
    return Path(__file__).resolve().parent / "startup_error.log"


def write_startup_error(exc: BaseException) -> None:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    log_path = get_startup_error_log_path()
    try:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"\n=== startup error {stamp} ===\n")
            f.write("cwd: " + str(Path.cwd()) + "\n")
            f.write("executable: " + str(sys.executable) + "\n")
            f.write("argv: " + " ".join(sys.argv) + "\n")
            f.write("error: " + repr(exc) + "\n")
            f.write(traceback.format_exc())
            f.write("\n")
    except Exception:
        pass


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    default_config = repo_root / "config.yaml"

    parser = argparse.ArgumentParser(description="Dumb Waiter tray controller (Turn on / Turn off).")
    parser.add_argument(
        "--config",
        default=str(default_config),
        help=f"Path to dumb_waiter config.yaml (default: {default_config})",
    )
    parser.add_argument(
        "--python-path",
        default="",
        help="Optional python/pythonw executable used to run dumb_waiter.py.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable tray diagnostics in dumb_waiter_tray/tray.log.",
    )
    parser.add_argument(
        "--worker-debug",
        action="store_true",
        help="Force worker debug mode via DUMB_WAITER_DEBUG_MODE=1.",
    )
    parser.add_argument(
        "--worker-verbose",
        action="store_true",
        help="Force worker verbose mode via DUMB_WAITER_VERBOSE=1.",
    )
    args = parser.parse_args()

    python_path = Path(args.python_path) if args.python_path else None
    try:
        app = DumbWaiterTrayApp(
            Path(args.config),
            python_path=python_path,
            debug=args.debug,
            worker_debug=args.worker_debug,
            worker_verbose=args.worker_verbose,
        )
        app.run()
    except Exception as exc:
        write_startup_error(exc)
        raise


if __name__ == "__main__":
    main()
