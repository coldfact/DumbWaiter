import argparse
import ctypes
import time
import re
import signal
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any, Set

import yaml

# UI Automation
from pywinauto import Desktop

# Input helpers
import pyautogui

__version__ = "0.0.1"


def set_dpi_awareness():
    """
    Avoid wrong coordinates on Windows with scaling (125%/150%).
    """
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


@dataclass
class Region:
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    def contains_rect(self, rect: Tuple[int, int, int, int]) -> bool:
        # rect: (l, t, r, b)
        l, t, r, b = rect
        # check intersection (not strict containment) so it still works if slightly over region edge
        return not (r < self.left or l > self.right or b < self.top or t > self.bottom)

    def intersect(self, other: "Region") -> Optional["Region"]:
        left = max(self.left, other.left)
        top = max(self.top, other.top)
        right = min(self.right, other.right)
        bottom = min(self.bottom, other.bottom)
        if right <= left or bottom <= top:
            return None
        return Region(left=left, top=top, width=(right - left), height=(bottom - top))

    def intersection_rect(
        self, rect: Tuple[int, int, int, int]
    ) -> Optional[Tuple[int, int, int, int]]:
        left = max(self.left, rect[0])
        top = max(self.top, rect[1])
        right = min(self.right, rect[2])
        bottom = min(self.bottom, rect[3])
        if right <= left or bottom <= top:
            return None
        return (left, top, right, bottom)


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def normalize_control_label(s: str) -> str:
    """
    Normalize UI labels and strip trailing keyboard hint text.
    Examples:
      "Run Alt+Enter" -> "run"
      "Run (Ctrl+R)" -> "run"
      "Accept all" -> "accept all"
    """
    name = normalize_text(s)
    name = re.sub(
        r"\s*\((?:alt|ctrl|shift|cmd|win)\+[^)]*\)\s*$", "", name, flags=re.IGNORECASE
    )
    name = re.sub(r"\s+(?:alt|ctrl|shift|cmd|win)\+.*$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"(?:alt|ctrl|shift|cmd|win)\+.*$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def is_exact_target_match(control_name: str, target: str) -> bool:
    """
    Strict text match to avoid false positives like "Always run".
    """
    return normalize_control_label(control_name) == normalize_text(target)


def compile_target_regexes(
    targets: List[str],
    target_regexes: Optional[List[str]],
) -> List[Optional[re.Pattern]]:
    compiled: List[Optional[re.Pattern]] = []
    regexes = target_regexes or []
    for idx, _ in enumerate(targets):
        if idx >= len(regexes):
            compiled.append(None)
            continue
        pattern = str(regexes[idx] or "").strip()
        if not pattern:
            compiled.append(None)
            continue
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE))
        except re.error as exc:
            raise SystemExit(
                f"Invalid uia.target_regexes[{idx}] regex '{pattern}': {exc}"
            )
    return compiled


def format_targets_for_log(targets: List[str]) -> str:
    normalized = [str(t).strip() for t in targets if str(t).strip()]
    if not normalized:
        return "(no targets)"
    quoted = [f"'{t}'" for t in normalized]
    if len(quoted) == 1:
        return quoted[0]
    if len(quoted) == 2:
        return f"{quoted[0]} and {quoted[1]}"
    return f"{', '.join(quoted[:-1])}, and {quoted[-1]}"


def install_interrupt_handlers(ignore_interrupts: bool, verbose: bool = False) -> None:
    """
    Optional hardening for VS Code integrated terminals where external actions
    can send console control events while this watcher is running.
    """
    if not ignore_interrupts:
        return

    def _ignore_signal(signum, _frame):
        if verbose:
            signal_name = getattr(signal.Signals(signum), "name", str(signum))
            print(f"[SIGNAL] Ignored {signal_name}.")

    for sig_name in ("SIGINT", "SIGBREAK", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, _ignore_signal)
        except Exception:
            continue


def get_bool_env(var_name: str) -> Optional[bool]:
    raw = os.environ.get(var_name)
    if raw is None:
        return None
    val = raw.strip().lower()
    if val in {"1", "true", "yes", "on"}:
        return True
    if val in {"0", "false", "no", "off"}:
        return False
    return None


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def get_virtual_screen_region() -> Region:
    """
    Return the virtual desktop bounds across monitors.
    """
    try:
        user32 = ctypes.windll.user32
        left = int(user32.GetSystemMetrics(76))  # SM_XVIRTUALSCREEN
        top = int(user32.GetSystemMetrics(77))  # SM_YVIRTUALSCREEN
        width = int(user32.GetSystemMetrics(78))  # SM_CXVIRTUALSCREEN
        height = int(user32.GetSystemMetrics(79))  # SM_CYVIRTUALSCREEN
        if width > 0 and height > 0:
            return Region(left=left, top=top, width=width, height=height)
    except Exception:
        pass

    size = pyautogui.size()
    return Region(left=0, top=0, width=int(size.width), height=int(size.height))


def region_from_fractions(
    base: Region,
    left_fraction: float,
    top_fraction: float,
    width_fraction: float,
    height_fraction: float,
) -> Optional[Region]:
    left_fraction = clamp01(left_fraction)
    top_fraction = clamp01(top_fraction)
    width_fraction = clamp01(width_fraction)
    height_fraction = clamp01(height_fraction)

    left = base.left + int(base.width * left_fraction)
    top = base.top + int(base.height * top_fraction)
    right = left + int(base.width * width_fraction)
    bottom = top + int(base.height * height_fraction)

    clipped = base.intersect(
        Region(
            left=left, top=top, width=max(0, right - left), height=max(0, bottom - top)
        )
    )
    return clipped


def resolve_scope_region_for_base(
    base: Region,
    scope_cfg: Dict[str, Any],
    preset_override: Optional[str] = None,
) -> Region:
    preset = normalize_text(
        str(preset_override or scope_cfg.get("preset", "right_half"))
    )
    region: Optional[Region] = None

    if preset in {"full", "full screen", "full_screen"}:
        region = base
    elif preset == "left_half":
        region = region_from_fractions(base, 0.0, 0.0, 0.5, 1.0)
    elif preset == "right_half":
        region = region_from_fractions(base, 0.5, 0.0, 0.5, 1.0)
    elif preset == "top_half":
        region = region_from_fractions(base, 0.0, 0.0, 1.0, 0.5)
    elif preset == "bottom_half":
        region = region_from_fractions(base, 0.0, 0.5, 1.0, 0.5)
    elif preset == "top_left_quarter":
        region = region_from_fractions(base, 0.0, 0.0, 0.5, 0.5)
    elif preset == "top_right_quarter":
        region = region_from_fractions(base, 0.5, 0.0, 0.5, 0.5)
    elif preset == "bottom_left_quarter":
        region = region_from_fractions(base, 0.0, 0.5, 0.5, 0.5)
    elif preset == "bottom_right_quarter":
        region = region_from_fractions(base, 0.5, 0.5, 0.5, 0.5)
    elif preset == "center_box":
        region = region_from_fractions(base, 0.2, 0.2, 0.6, 0.6)
    elif preset == "custom_fractions":
        region = region_from_fractions(
            base,
            left_fraction=float(scope_cfg.get("left_fraction", 0.0)),
            top_fraction=float(scope_cfg.get("top_fraction", 0.0)),
            width_fraction=float(scope_cfg.get("width_fraction", 1.0)),
            height_fraction=float(scope_cfg.get("height_fraction", 1.0)),
        )
    else:
        valid = [
            "full_screen",
            "left_half",
            "right_half",
            "top_half",
            "bottom_half",
            "top_left_quarter",
            "top_right_quarter",
            "bottom_left_quarter",
            "bottom_right_quarter",
            "center_box",
            "custom_fractions",
        ]
        raise SystemExit(f"Invalid scope.preset '{preset}'. Valid options: {valid}")

    if region is None:
        raise SystemExit("Scope region resolved to empty area. Check scope settings.")

    inset_percent = max(0.0, min(40.0, float(scope_cfg.get("inset_percent", 0.0))))
    if inset_percent > 0.0:
        dx = int(region.width * (inset_percent / 100.0))
        dy = int(region.height * (inset_percent / 100.0))
        region = Region(
            left=region.left + dx,
            top=region.top + dy,
            width=max(1, region.width - (2 * dx)),
            height=max(1, region.height - (2 * dy)),
        )

    return region


def resolve_scope_region(
    scope_cfg: Dict[str, Any], verbose: bool = False
) -> Optional[Region]:
    """
    Optional global screen scope to avoid unrelated controls (e.g., top menu items).
    """
    if not bool(scope_cfg.get("enabled", False)):
        return None

    screen = get_virtual_screen_region()
    preset = normalize_text(str(scope_cfg.get("preset", "right_half")))
    region = resolve_scope_region_for_base(screen, scope_cfg, preset_override=preset)

    if verbose:
        print(
            "[SCOPE] Using scope region "
            f"{region.left},{region.top},{region.width},{region.height} (preset={preset})"
        )

    return region


def is_minimized_window(window: Any) -> bool:
    """
    Best-effort minimized detection across different UIA wrapper implementations.
    """
    try:
        if window.is_minimized():
            return True
    except Exception:
        pass

    try:
        rect = window.rectangle()
        if rect.width() <= 1 or rect.height() <= 1:
            return True
        # Minimized windows often report parked coordinates around -32000.
        if rect.left <= -30000 and rect.top <= -30000:
            return True
    except Exception:
        return False

    return False


def ensure_window_ready(window: Any, verbose: bool = False) -> Optional[Region]:
    """
    If a target window is minimized, maximize it so unattended runs can proceed.
    Returns the usable window bounds, or None if unavailable.
    """
    if is_minimized_window(window):
        if verbose:
            print(
                f"[UIA] Restoring window '{window.window_text()}' from minimized state"
            )
        try:
            window.restore()
        except Exception:
            pass
        try:
            window.maximize()
        except Exception:
            pass
        time.sleep(0.3)

    try:
        rect = window.rectangle()
    except Exception:
        return None

    if rect.width() <= 1 or rect.height() <= 1:
        return None

    return Region(
        left=rect.left, top=rect.top, width=rect.width(), height=rect.height()
    )


def get_matching_windows(
    window_title_regex: str, verbose: bool = False
) -> List[Tuple[Any, Region]]:
    """
    Find windows that match the title regex and return them with usable bounds.
    """
    title_re = re.compile(window_title_regex, re.IGNORECASE)

    try:
        desktop = Desktop(backend="uia")
        windows = desktop.windows()
    except Exception as e:
        if verbose:
            print(f"[UIA] Desktop init failed: {e}")
        return []

    matches: List[Tuple[Any, Region]] = []
    for window in windows:
        try:
            title = window.window_text() or ""
        except Exception:
            continue

        if not title_re.search(title):
            continue

        region = ensure_window_ready(window, verbose=verbose)
        if region is None:
            continue
        matches.append((window, region))

    return matches


def apply_scope_to_windows(
    windows_with_regions: List[Tuple[Any, Region]],
    scope_region: Optional[Region],
    scope_cfg: Optional[Dict[str, Any]] = None,
    relative_to_window: bool = False,
) -> List[Tuple[Any, Region]]:
    if relative_to_window:
        cfg = scope_cfg or {}
        if not bool(cfg.get("enabled", False)):
            return windows_with_regions
        preset = normalize_text(str(cfg.get("preset", "right_half")))
        scoped: List[Tuple[Any, Region]] = []
        for window, window_region in windows_with_regions:
            local_scope = resolve_scope_region_for_base(
                window_region, cfg, preset_override=preset
            )
            clipped = window_region.intersect(local_scope)
            if clipped is not None:
                scoped.append((window, clipped))
        return scoped

    if scope_region is None:
        return windows_with_regions

    scoped: List[Tuple[Any, Region]] = []
    for window, window_region in windows_with_regions:
        clipped = window_region.intersect(scope_region)
        if clipped is not None:
            scoped.append((window, clipped))
    return scoped


def uia_click_targets(
    windows_with_regions: List[Tuple[Any, Region]],
    targets: List[str],
    target_regexes: Optional[List[str]] = None,
    debug_mode: bool = False,
    verbose: bool = False,
) -> bool:
    """
    Try to find and invoke UIA Button controls whose name contains any target text.
    Search is strictly scoped to windows already matched by title regex.
    """
    targets_n = [normalize_text(t) for t in targets if t.strip()]
    if not targets_n:
        return False
    target_patterns = compile_target_regexes(targets_n, target_regexes)
    debug_terms = sorted(
        {term for target in targets_n for term in target.split(" ") if term}
    )
    seen_debug_candidates = set()

    # Common UIA control types seen across desktop/webview/Electron button-like widgets.
    preferred_control_types = ["Button", "Hyperlink", "MenuItem", "SplitButton"]

    # Global priority order: process first target across all windows before second target.
    for target_index, target in enumerate(targets_n):
        target_pattern = target_patterns[target_index]
        for window, window_region in windows_with_regions:
            for control_type in preferred_control_types:
                try:
                    controls = window.descendants(control_type=control_type)
                except Exception as exc:
                    if debug_mode:
                        print(f"[DEBUG][UIA] descendants({control_type}) failed: {exc}")
                    continue

                for control in controls:
                    try:
                        title = window.window_text()
                        name_raw = control.window_text()
                        if not name_raw:
                            continue

                        candidate_norm = normalize_text(name_raw)
                        candidate_label = normalize_control_label(name_raw)
                        r = control.rectangle()
                        rect = (r.left, r.top, r.right, r.bottom)
                        in_scope = window_region.contains_rect(rect)

                        if debug_mode:
                            debug_key = (title or "", candidate_norm, rect)
                            if debug_key not in seen_debug_candidates and any(
                                term in candidate_norm for term in debug_terms
                            ):
                                checks = []
                                for idx, t in enumerate(targets_n):
                                    tp = target_patterns[idx]
                                    if tp is None:
                                        matched = is_exact_target_match(name_raw, t)
                                        mode = "exact"
                                    else:
                                        matched = tp.search(candidate_norm) is not None
                                        mode = f"regex:{tp.pattern}"
                                    checks.append(f"{t}={matched}({mode})")
                                print(
                                    "[DEBUG][UIA] "
                                    f"text='{name_raw}' label='{candidate_label}' "
                                    f"type={control_type} in_scope={in_scope} rect={rect} "
                                    f"checks=[{', '.join(checks)}]"
                                )
                                seen_debug_candidates.add(debug_key)

                        if target_pattern is not None:
                            if target_pattern.search(candidate_norm) is None:
                                continue
                        elif not is_exact_target_match(name_raw, target):
                            continue

                        if not in_scope:
                            continue

                        if verbose:
                            print(
                                f"[UIA] Clicking '{control.window_text()}' "
                                f"(type={control_type}) at {rect} (window='{title}')"
                            )

                        try:
                            control.invoke()
                        except Exception as exc_invoke:
                            if debug_mode:
                                print(f"[DEBUG][UIA] invoke() failed: {exc_invoke}")
                            try:
                                control.click_input()
                            except Exception as exc_click:
                                if debug_mode:
                                    print(
                                        f"[DEBUG][UIA] click_input() failed: {exc_click}"
                                    )
                                clipped_rect = window_region.intersection_rect(rect)
                                if clipped_rect is None:
                                    continue
                                click_x = (clipped_rect[0] + clipped_rect[2]) // 2
                                click_y = (clipped_rect[1] + clipped_rect[3]) // 2
                                pyautogui.click(click_x, click_y)
                        return True
                    except Exception as exc_ctrl:
                        if debug_mode:
                            print(f"[DEBUG][UIA] Control processing error: {exc_ctrl}")
                        continue

            # Final fallback: search any named element with exact target text and click its center.
            # This catches Electron/webview controls that don't expose standard button control types.
            try:
                all_controls = window.descendants()
            except Exception as exc:
                if debug_mode:
                    print(f"[DEBUG][UIA] Fallback descendants() failed: {exc}")
                continue
            for control in all_controls:
                try:
                    title = window.window_text()
                    name_raw = control.window_text()
                    if not name_raw:
                        continue

                    candidate_norm = normalize_text(name_raw)
                    candidate_label = normalize_control_label(name_raw)

                    if target_pattern is not None:
                        if target_pattern.search(candidate_norm) is None:
                            continue
                    elif not is_exact_target_match(name_raw, target):
                        continue

                    r = control.rectangle()
                    rect = (r.left, r.top, r.right, r.bottom)
                    in_scope = window_region.contains_rect(rect)
                    if debug_mode:
                        debug_key = (title or "", candidate_norm, rect)
                        if debug_key not in seen_debug_candidates and any(
                            term in candidate_norm for term in debug_terms
                        ):
                            checks = []
                            for idx, t in enumerate(targets_n):
                                tp = target_patterns[idx]
                                if tp is None:
                                    matched = is_exact_target_match(name_raw, t)
                                    mode = "exact"
                                else:
                                    matched = tp.search(candidate_norm) is not None
                                    mode = f"regex:{tp.pattern}"
                                checks.append(f"{t}={matched}({mode})")
                            print(
                                "[DEBUG][UIA] "
                                f"text='{name_raw}' label='{candidate_label}' "
                                f"type=Any in_scope={in_scope} rect={rect} "
                                f"checks=[{', '.join(checks)}]"
                            )
                            seen_debug_candidates.add(debug_key)

                    if not in_scope:
                        continue

                    if (r.right - r.left) <= 1 or (r.bottom - r.top) <= 1:
                        continue

                    clipped_rect = window_region.intersection_rect(rect)
                    if clipped_rect is None:
                        continue
                    click_x = (clipped_rect[0] + clipped_rect[2]) // 2
                    click_y = (clipped_rect[1] + clipped_rect[3]) // 2
                    if verbose:
                        print(
                            f"[UIA] Fallback click on '{control.window_text()}' "
                            f"at ({click_x},{click_y}) (window='{title}')"
                        )
                    pyautogui.click(click_x, click_y)
                    return True
                except Exception as exc_fb:
                    if debug_mode:
                        print(f"[DEBUG][UIA] Fallback control error: {exc_fb}")
                    continue

    return False


_KNOWN_TOP_KEYS: Set[str] = {
    "targets",
    "interval_seconds",
    "verbose",
    "debug_mode",
    "ignore_keyboard_interrupt",
    "continue_on_error",
    "uia",
    "scope",
}
_KNOWN_UIA_KEYS: Set[str] = {"enabled", "window_title_regex", "target_regexes"}
_KNOWN_SCOPE_KEYS: Set[str] = {
    "enabled",
    "relative_to_window",
    "preset",
    "inset_percent",
    "left_fraction",
    "top_fraction",
    "width_fraction",
    "height_fraction",
}


def _warn_unknown_config_keys(cfg: dict) -> None:
    """Warn about unrecognized config keys (catches typos like 'intervall_seconds')."""
    for key in cfg:
        if key not in _KNOWN_TOP_KEYS:
            print(f"[WARN] Unknown config key '{key}' — will be ignored.")
    for key in cfg.get("uia", {}):
        if key not in _KNOWN_UIA_KEYS:
            print(f"[WARN] Unknown config key 'uia.{key}' — will be ignored.")
    for key in cfg.get("scope", {}):
        if key not in _KNOWN_SCOPE_KEYS:
            print(f"[WARN] Unknown config key 'scope.{key}' — will be ignored.")


def main() -> None:
    set_dpi_awareness()

    default_cfg = Path(__file__).resolve().parent / "config.yaml"
    ap = argparse.ArgumentParser(
        description="Dumb Waiter: auto-click 'Accept all' or 'Run' in windows matching title regex (UIA only)."
    )
    ap.add_argument(
        "--config",
        default=str(default_cfg),
        help=f"Path to config.yaml (default: {default_cfg})",
    )
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    if not cfg_path.exists():
        raise SystemExit(f"Config file not found: {cfg_path}")
    cfg = load_yaml(cfg_path)
    _warn_unknown_config_keys(cfg)

    targets = cfg.get("targets", ["accept all", "run"])
    interval_s = float(cfg.get("interval_seconds", 2.0))
    verbose = bool(cfg.get("verbose", False))
    debug_mode = bool(cfg.get("debug_mode", False))
    ignore_keyboard_interrupt = bool(cfg.get("ignore_keyboard_interrupt", False))
    continue_on_error = bool(cfg.get("continue_on_error", True))

    env_verbose = get_bool_env("DUMB_WAITER_VERBOSE")
    env_debug_mode = get_bool_env("DUMB_WAITER_DEBUG_MODE")
    if env_verbose is not None:
        verbose = env_verbose
    if env_debug_mode is not None:
        debug_mode = env_debug_mode
    install_interrupt_handlers(ignore_keyboard_interrupt, verbose=verbose)

    uia_enabled = bool(cfg.get("uia", {}).get("enabled", True))
    window_title_regex = (
        cfg.get("uia", {}).get("window_title_regex", "") or ""
    ).strip()
    if not window_title_regex:
        raise SystemExit(
            "Config 'uia.window_title_regex' is required and must be non-empty."
        )
    target_regexes = cfg.get("uia", {}).get("target_regexes", [])
    if target_regexes is not None and not isinstance(target_regexes, list):
        raise SystemExit("Config 'uia.target_regexes' must be a list when provided.")
    scope_cfg = cfg.get("scope", {})
    scope_enabled = bool(scope_cfg.get("enabled", False))
    scope_relative_to_window = bool(scope_cfg.get("relative_to_window", False))
    scope_preset = normalize_text(str(scope_cfg.get("preset", "right_half")))
    scope_region = None
    if scope_enabled and not scope_relative_to_window:
        scope_region = resolve_scope_region(scope_cfg, verbose=verbose)
    if scope_region is None:
        if scope_enabled and scope_relative_to_window:
            scope_text = f"window_relative:{scope_preset}"
        else:
            scope_text = "scope disabled"
    elif scope_enabled:
        scope_text = (
            f"{scope_preset} "
            f"({scope_region.left},{scope_region.top},{scope_region.width},{scope_region.height})"
        )
    else:
        scope_text = (
            "full matched window area "
            f"({scope_region.left},{scope_region.top},{scope_region.width},{scope_region.height})"
        )
    print(
        f"[START] Dumb Waiter v{__version__} — Looking for "
        f"{format_targets_for_log(targets)} "
        f"in windows matching '{window_title_regex}' "
        f"within {scope_text}; polling every {interval_s}s."
    )
    if env_verbose is not None or env_debug_mode is not None:
        print(
            "[START] Env overrides: "
            f"DUMB_WAITER_VERBOSE={env_verbose} "
            f"DUMB_WAITER_DEBUG_MODE={env_debug_mode}"
        )
    if ignore_keyboard_interrupt:
        print("[START] Interrupt protection is ON (SIGINT/SIGBREAK ignored).")

    if verbose:
        print("Dumb Waiter running with:")
        print(f"  config = {cfg_path}")
        if scope_region is None:
            if scope_enabled and scope_relative_to_window:
                print(f"  scope = window_relative:{scope_preset}")
            else:
                print("  scope = disabled")
        else:
            print(
                "  scope = "
                f"{scope_region.left},{scope_region.top},{scope_region.width},{scope_region.height}"
            )
        print(f"  targets = {targets}")
        if target_regexes:
            print(f"  uia.target_regexes = {target_regexes}")
        print(f"  interval_seconds = {interval_s}")
        print(f"  debug_mode = {debug_mode}")
        print(f"  ignore_keyboard_interrupt = {ignore_keyboard_interrupt}")
        print(f"  continue_on_error = {continue_on_error}")
        print(
            f"  uia.enabled = {uia_enabled}, window_title_regex = {window_title_regex}"
        )

    while True:
        try:
            clicked = False
            windows_with_regions = get_matching_windows(
                window_title_regex, verbose=verbose
            )
            scoped_windows = apply_scope_to_windows(
                windows_with_regions,
                scope_region,
                scope_cfg=scope_cfg,
                relative_to_window=scope_relative_to_window,
            )

            if verbose and not windows_with_regions:
                print(f"[UIA] No windows matched regex '{window_title_regex}'.")
            if (
                verbose
                and windows_with_regions
                and not scoped_windows
                and scope_enabled
            ):
                print(
                    "[SCOPE] Matching windows exist, but none intersect the configured scope."
                )

            if uia_enabled and scoped_windows:
                clicked = uia_click_targets(
                    windows_with_regions=scoped_windows,
                    targets=targets,
                    target_regexes=target_regexes,
                    debug_mode=debug_mode,
                    verbose=verbose,
                )

            if verbose and not clicked:
                print("[IDLE] No target found.")

            time.sleep(interval_s)
        except KeyboardInterrupt:
            if ignore_keyboard_interrupt:
                if verbose:
                    print("[LOOP] KeyboardInterrupt received; continuing.")
                continue
            if verbose:
                print("[EXIT] KeyboardInterrupt received; stopping.")
            break
        except Exception as e:
            print(f"[ERROR] Loop exception: {e}")
            if not continue_on_error:
                raise


if __name__ == "__main__":
    main()
