"""Native PCR pet window, desktop-edge geometry, effects and pointer capture.

WindowsPet supplies task state/composition; HoChanPet supplies characters and
presentation. This module has no standalone launcher or asset-building path.
"""
from __future__ import annotations
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
import json
import math
import os
from pathlib import Path
import time
import traceback

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from animation_clock import Clip
from layered_buffer import LayeredBuffers
from codex_bridge import HEARTBEAT_FILE_NAME, PERMISSION_REQUESTS_DIR_NAME, read_status
from win32_api import (
    WM_DESTROY,
    WM_TIMER,
    WM_ENTERMENULOOP,
    WM_EXITMENULOOP,
    WM_MOUSEMOVE,
    WM_LBUTTONDOWN,
    WM_LBUTTONUP,
    WM_LBUTTONDBLCLK,
    WM_RBUTTONUP,
    MK_LBUTTON,
    CS_DBLCLKS,
    WS_POPUP,
    WS_EX_LAYERED,
    WS_EX_TOOLWINDOW,
    WS_EX_TOPMOST,
    WS_EX_NOACTIVATE,
    HWND_TOPMOST,
    SW_SHOW,
    SW_HIDE,
    SWP_NOSIZE,
    SWP_NOMOVE,
    SWP_NOZORDER,
    SWP_NOACTIVATE,
    SWP_SHOWWINDOW,
    ULW_ALPHA,
    AC_SRC_OVER,
    AC_SRC_ALPHA,
    BI_RGB,
    DIB_RGB_COLORS,
    MF_STRING,
    MF_SEPARATOR,
    MF_CHECKED,
    TPM_RETURNCMD,
    TPM_NONOTIFY,
    TPM_RIGHTBUTTON,
    SPI_GETWORKAREA,
    POINT,
    SIZE,
    RECT,
    BLENDFUNCTION,
    BITMAPINFOHEADER,
    BITMAPINFO,
    LRESULT,
    WNDPROC,
    WNDCLASSW,
    MONITORINFO,
    MONITORENUMPROC,
    user32,
    gdi32,
    kernel32
)

APP_NAME = 'Ho-chan Desktop Pet'
CLASS_NAME = 'HoChanDesktopPetWindow'
WINDOW_SIZE = 640
BODY_ANCHOR_X = 410
BODY_ANCHOR_BOTTOM = 570
DRAG_THRESHOLD_PIXELS = 4
SUCCESS_EFFECT_DURATION_SECONDS = 1.35
EDGE_CONTACT_TOLERANCE = 10
EDGE_REVEAL_CLEARANCE = 28
EDGE_OFFSCREEN_PADDING = 16
EDGE_TRANSITION_DURATION_SECONDS = 0.48
EDGE_TAIL_WINDOW_SIZE = 68
EDGE_TAIL_SCREEN_OVERLAP = 30
TOPMOST_REFRESH_INTERVAL_MS = 1000


@dataclass(frozen=True)
class MonitorInfo:
    frame: tuple[int, int, int, int]
    work: tuple[int, int, int, int]


@dataclass(frozen=True)
class EdgePlacement:
    edge: str
    monitor: MonitorInfo
    tail_rect: tuple[int, int, int, int]


@dataclass
class EdgeMotion:
    start: tuple[int, int]
    target: tuple[int, int]
    started_at: float
    completion: str


def rect_contains_point(rect: tuple[int, int, int, int], point: tuple[int, int]) -> bool:
    return rect[0] <= point[0] < rect[2] and rect[1] <= point[1] < rect[3]


def rect_intersection_area(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
) -> int:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    return max(0, right - left) * max(0, bottom - top)


def enumerate_monitor_infos() -> list[MonitorInfo]:
    monitors: list[MonitorInfo] = []

    @MONITORENUMPROC
    def collect(
        monitor: wintypes.HANDLE,
        _device_context: wintypes.HDC,
        _monitor_rect: ctypes.POINTER(RECT),
        _data: int,
    ) -> int:
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            monitors.append(
                MonitorInfo(
                    frame=(
                        int(info.rcMonitor.left),
                        int(info.rcMonitor.top),
                        int(info.rcMonitor.right),
                        int(info.rcMonitor.bottom),
                    ),
                    work=(
                        int(info.rcWork.left),
                        int(info.rcWork.top),
                        int(info.rcWork.right),
                        int(info.rcWork.bottom),
                    ),
                )
            )
        return 1

    user32.EnumDisplayMonitors(None, None, collect, 0)
    if monitors:
        return monitors

    fallback = RECT()
    if user32.SystemParametersInfoW(
        SPI_GETWORKAREA,
        0,
        ctypes.byref(fallback),
        0,
    ):
        work = (
            int(fallback.left),
            int(fallback.top),
            int(fallback.right),
            int(fallback.bottom),
        )
        return [MonitorInfo(frame=work, work=work)]
    return []


def touched_desktop_edge(
    pet_frame: tuple[int, int, int, int],
    desktop_frame: tuple[int, int, int, int],
    allowed_edges: set[str] | None = None,
    tolerance: int = EDGE_CONTACT_TOLERANCE,
) -> str | None:
    allowed = (
        set(allowed_edges)
        if allowed_edges is not None
        else {"left", "right", "top", "bottom"}
    )
    overlaps_vertically = (
        pet_frame[3] >= desktop_frame[1]
        and pet_frame[1] <= desktop_frame[3]
    )
    overlaps_horizontally = (
        pet_frame[2] >= desktop_frame[0]
        and pet_frame[0] <= desktop_frame[2]
    )
    candidates: list[tuple[str, int]] = []
    if "left" in allowed and overlaps_vertically and pet_frame[0] <= desktop_frame[0] + tolerance:
        candidates.append(("left", max(0, pet_frame[2] - desktop_frame[0])))
    if "right" in allowed and overlaps_vertically and pet_frame[2] >= desktop_frame[2] - tolerance:
        candidates.append(("right", max(0, desktop_frame[2] - pet_frame[0])))
    if "top" in allowed and overlaps_horizontally and pet_frame[1] <= desktop_frame[1] + tolerance:
        candidates.append(("top", max(0, pet_frame[3] - desktop_frame[1])))
    if "bottom" in allowed and overlaps_horizontally and pet_frame[3] >= desktop_frame[3] - tolerance:
        candidates.append(("bottom", max(0, desktop_frame[3] - pet_frame[1])))
    if not candidates:
        return None
    return min(candidates, key=lambda candidate: candidate[1])[0]


def offscreen_delta(
    edge: str,
    pet_frame: tuple[int, int, int, int],
    desktop_frame: tuple[int, int, int, int],
    padding: int = EDGE_OFFSCREEN_PADDING,
) -> tuple[int, int]:
    if edge == "left":
        return (desktop_frame[0] - pet_frame[2] - padding, 0)
    if edge == "right":
        return (desktop_frame[2] - pet_frame[0] + padding, 0)
    if edge == "top":
        return (0, desktop_frame[1] - pet_frame[3] - padding)
    if edge == "bottom":
        return (0, desktop_frame[3] - pet_frame[1] + padding)
    raise ValueError(f"unknown desktop edge: {edge}")


def _containment_shift(
    item_min: float,
    item_max: float,
    container_min: float,
    container_max: float,
    clearance: float,
) -> float:
    safe_min = container_min + clearance
    safe_max = container_max - clearance
    if item_max - item_min > safe_max - safe_min:
        return (container_min + container_max - item_min - item_max) / 2
    if item_min < safe_min:
        return safe_min - item_min
    if item_max > safe_max:
        return safe_max - item_max
    return 0.0


def revealed_delta(
    edge: str,
    content_frame: tuple[int, int, int, int],
    desktop_frame: tuple[int, int, int, int],
    clearance: int = EDGE_REVEAL_CLEARANCE,
    bottom_drop: float = 0.0,
) -> tuple[float, float]:
    delta_x = 0.0
    delta_y = 0.0
    if edge == "left":
        delta_x = desktop_frame[0] + clearance - content_frame[0]
    elif edge == "right":
        delta_x = desktop_frame[2] - clearance - content_frame[2]
    elif edge == "top":
        delta_y = desktop_frame[1] + clearance - content_frame[1]
    elif edge == "bottom":
        delta_y = desktop_frame[3] - clearance + max(0.0, bottom_drop) - content_frame[3]
    else:
        raise ValueError(f"unknown desktop edge: {edge}")

    shifted = (
        content_frame[0] + delta_x,
        content_frame[1] + delta_y,
        content_frame[2] + delta_x,
        content_frame[3] + delta_y,
    )
    if edge in {"left", "right"}:
        delta_y += _containment_shift(
            shifted[1],
            shifted[3],
            desktop_frame[1],
            desktop_frame[3],
            clearance,
        )
    else:
        delta_x += _containment_shift(
            shifted[0],
            shifted[2],
            desktop_frame[0],
            desktop_frame[2],
            clearance,
        )
    return (delta_x, delta_y)


def tail_window_rect(
    edge: str,
    pet_frame: tuple[int, int, int, int],
    desktop_frame: tuple[int, int, int, int],
    size: int = EDGE_TAIL_WINDOW_SIZE,
    screen_overlap: int = EDGE_TAIL_SCREEN_OVERLAP,
) -> tuple[int, int, int, int]:
    centered_x = min(
        max((pet_frame[0] + pet_frame[2] - size) / 2, desktop_frame[0]),
        desktop_frame[2] - size,
    )
    centered_y = min(
        max((pet_frame[1] + pet_frame[3] - size) / 2, desktop_frame[1]),
        desktop_frame[3] - size,
    )
    if edge == "left":
        left, top = desktop_frame[0] - screen_overlap, centered_y
    elif edge == "right":
        left, top = desktop_frame[2] - size + screen_overlap, centered_y
    elif edge == "top":
        left, top = centered_x, desktop_frame[1] - screen_overlap
    elif edge == "bottom":
        left, top = centered_x, desktop_frame[3] - size + screen_overlap
    else:
        raise ValueError(f"unknown desktop edge: {edge}")
    return (
        round(left),
        round(top),
        round(left + size),
        round(top + size),
    )


def clear_transparent_rgb(image: Image.Image) -> Image.Image:
    rgba = np.array(image.convert("RGBA"))
    rgba[rgba[:, :, 3] == 0, :3] = 0
    return Image.fromarray(rgba, "RGBA")


def premultiplied_bgra(canvas: Image.Image) -> bytes:
    rgba = np.asarray(canvas.convert("RGBA"), dtype=np.uint16)
    alpha = rgba[:, :, 3:4]
    premultiplied = (rgba[:, :, :3] * alpha + 127) // 255
    bgra = np.empty((rgba.shape[0], rgba.shape[1], 4), dtype=np.uint8)
    bgra[:, :, 0] = premultiplied[:, :, 2]
    bgra[:, :, 1] = premultiplied[:, :, 1]
    bgra[:, :, 2] = premultiplied[:, :, 0]
    bgra[:, :, 3] = rgba[:, :, 3]
    return bgra.tobytes()


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json_file(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


@lru_cache(maxsize=32)
def load_ui_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    candidates = [
        fonts_dir / ("msyhbd.ttc" if bold else "msyh.ttc"),
        fonts_dir / ("Microsoft YaHei UI Bold.ttf" if bold else "Microsoft YaHei UI.ttf"),
        fonts_dir / ("simhei.ttf" if bold else "simsun.ttc"),
        fonts_dir / "Dengb.ttf" if bold else fonts_dir / "Deng.ttf",
        fonts_dir / ("seguisb.ttf" if bold else "segoeui.ttf"),
        "msyhbd.ttc" if bold else "msyh.ttc",
        "Microsoft YaHei UI Bold.ttf" if bold else "Microsoft YaHei UI.ttf",
        "simhei.ttf" if bold else "simsun.ttc",
        "seguisb.ttf" if bold else "segoeui.ttf",
        "arialbd.ttf" if bold else "arial.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(str(candidate), size)
        except (OSError, TypeError):
            continue
    return ImageFont.load_default()


def wrap_text_by_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    max_lines: int,
) -> list[str]:
    normalized = " ".join(str(text).replace("\r", " ").replace("\n", " ").split())
    if not normalized:
        return []

    lines: list[str] = []
    current = ""
    for char in normalized:
        candidate = current + char
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if current and bbox[2] - bbox[0] > max_width:
            lines.append(current)
            current = char
            if len(lines) >= max_lines:
                break
        else:
            current = candidate
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and len("".join(lines)) < len(normalized):
        lines[-1] = lines[-1].rstrip(" .。") + "..."
    return lines


def log_exception(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(traceback.format_exc(), encoding="utf-8")


class PcrPet:
    def __init__(
        self,
        animations: dict[str, Clip],
        app_dir: Path,
        status_path: Path,
    ) -> None:
        self.animations = animations
        self.app_dir = app_dir
        self.status_path = status_path
        self.frame_index = 0
        self.transient_key: str | None = None
        self.transient_once = False
        self.success_effect_started: float | None = None
        self.dragging = False
        self.mouse_down = False
        self.drag_start_cursor: tuple[int, int] | None = None
        self.drag_start_window: tuple[int, int] | None = None
        self.drag_previous: tuple[str | None, bool, int, float | None] | None = None
        self.click_feedback_enabled = False
        self.permission_request: dict[str, object] | None = None
        self.permission_request_id = ""
        self.permission_button_down: str | None = None
        self.permission_bubble_down = False
        self.permission_buttons: dict[str, tuple[int, int, int, int]] = {}
        self.permission_bubble_rect: tuple[int, int, int, int] | None = None
        self.permission_dir = self.status_path.parent / PERMISSION_REQUESTS_DIR_NAME
        self.heartbeat_path = self.status_path.parent / HEARTBEAT_FILE_NAME
        self.last_heartbeat = 0.0
        self.layered_buffers = {}
        self.hwnd: int | None = None
        self.tail_hwnd: int | None = None
        self.timer_id = 1
        self.edge_timer_id = 2
        self.topmost_timer_id = 3
        self.menu_loop_depth = 0
        self.edge_placement: EdgePlacement | None = None
        self.edge_transition: str | None = None
        self.reveal_after_hiding = False
        self.edge_motion: EdgeMotion | None = None
        self.wndproc = WNDPROC(self._wndproc)
        self.effects = self._load_effects()
        self.edge_tail_assets = self._load_edge_tail_assets()
        initial_status = read_status(self.status_path)
        self._apply_bridge_payload(initial_status)


    def _load_effects(self) -> dict[str, Image.Image]:
        result: dict[str, Image.Image] = {}
        effects_dir = self.app_dir / "assets" / "effects"
        for name in ("sparkle", "firework"):
            path = effects_dir / f"{name}.png"
            if path.is_file():
                result[name] = clear_transparent_rgb(Image.open(path).convert("RGBA"))
        return result

    def _load_edge_tail_assets(self) -> dict[str, Image.Image]:
        result: dict[str, Image.Image] = {}
        edge_dir = self.app_dir / "assets" / "characters" / "ho-chan" / "edge-tail"
        for edge in ("left", "right", "top", "bottom"):
            path = edge_dir / f"{edge}.png"
            if not path.is_file():
                continue
            with Image.open(path) as opened:
                image = clear_transparent_rgb(opened.convert("RGBA"))
            if image.size == (EDGE_TAIL_WINDOW_SIZE, EDGE_TAIL_WINDOW_SIZE):
                result[edge] = image
        return result

    def run(self) -> None:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass

        instance = kernel32.GetModuleHandleW(None)
        window_class = WNDCLASSW()
        window_class.style = CS_DBLCLKS
        window_class.lpfnWndProc = self.wndproc
        window_class.hInstance = instance
        window_class.hCursor = user32.LoadCursorW(None, ctypes.c_void_p(32512))
        window_class.lpszClassName = CLASS_NAME
        if not user32.RegisterClassW(ctypes.byref(window_class)):
            error = ctypes.get_last_error()
            if error != 1410:
                raise ctypes.WinError(error)

        work_area = RECT()
        user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(work_area), 0)
        x = work_area.right - WINDOW_SIZE - 36
        y = work_area.bottom - WINDOW_SIZE - 36

        self.hwnd = user32.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TOPMOST | (0 if os.environ.get('PCR_QA_WINDOW') == '1' else WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE),
            CLASS_NAME,
            APP_NAME,
            WS_POPUP,
            x,
            y,
            WINDOW_SIZE,
            WINDOW_SIZE,
            None,
            None,
            instance,
            None,
        )
        if not self.hwnd:
            raise ctypes.WinError(ctypes.get_last_error())

        self.tail_hwnd = user32.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
            CLASS_NAME,
            f"{APP_NAME} Tail",
            WS_POPUP,
            0,
            0,
            EDGE_TAIL_WINDOW_SIZE,
            EDGE_TAIL_WINDOW_SIZE,
            None,
            None,
            instance,
            None,
        )
        if not self.tail_hwnd:
            user32.DestroyWindow(self.hwnd)
            raise ctypes.WinError(ctypes.get_last_error())

        user32.ShowWindow(self.hwnd, SW_SHOW)
        user32.ShowWindow(self.tail_hwnd, SW_HIDE)
        self._restore_topmost()
        if not user32.SetTimer(self.hwnd, self.topmost_timer_id, TOPMOST_REFRESH_INTERVAL_MS, None):
            error = ctypes.get_last_error()
            user32.DestroyWindow(self.hwnd)
            raise ctypes.WinError(error)
        self._write_heartbeat(force=True)
        self._render_current()
        self._schedule_current()

        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))


    def _permission_response_path(self, request_id: str) -> Path:
        return self.permission_dir / f"{request_id}.response.json"

    def _permission_request_expired(self, payload: dict[str, object]) -> bool:
        expires_at = str(payload.get("expires_at", ""))
        if not expires_at:
            return False
        try:
            deadline = datetime.fromisoformat(expires_at)
        except ValueError:
            return False
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= deadline.astimezone(timezone.utc)


    def _window_rect(self, hwnd: int | None) -> tuple[int, int, int, int] | None:
        if hwnd is None:
            return None
        rect = RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        return (
            int(rect.left),
            int(rect.top),
            int(rect.right),
            int(rect.bottom),
        )

    def _restore_topmost(self) -> None:
        # WS_EX_TOPMOST only establishes the initial Z order. Other topmost
        # windows can later cover us, and external window tools can demote us.
        # Keep this independent of animation scheduling, including edge hiding.
        if self.menu_loop_depth or getattr(self, 'context_menu_active', False):
            return
        for hwnd in (self.hwnd, self.tail_hwnd):
            if hwnd and user32.IsWindowVisible(hwnd):
                user32.SetWindowPos(
                    hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
                )

    def _set_window_origin(self, hwnd: int, origin: tuple[int, int]) -> None:
        user32.SetWindowPos(
            hwnd,
            None,
            int(origin[0]),
            int(origin[1]),
            0,
            0,
            SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE,
        )


    def _screen_bounds_for_local(
        self,
        local_bounds: tuple[int, int, int, int],
    ) -> tuple[int, int, int, int] | None:
        window = self._window_rect(self.hwnd)
        if window is None:
            return None
        return (
            window[0] + local_bounds[0],
            window[1] + local_bounds[1],
            window[0] + local_bounds[2],
            window[1] + local_bounds[3],
        )

    def _interaction_monitor(self) -> MonitorInfo | None:
        monitors = enumerate_monitor_infos()
        if not monitors:
            return None
        cursor = POINT()
        if user32.GetCursorPos(ctypes.byref(cursor)):
            point = (int(cursor.x), int(cursor.y))
            for monitor in monitors:
                if rect_contains_point(monitor.frame, point):
                    return monitor
        window = self._window_rect(self.hwnd)
        if window is not None:
            return max(
                monitors,
                key=lambda monitor: rect_intersection_area(window, monitor.frame),
            )
        return monitors[0]

    @staticmethod
    def _exposed_edges(
        monitor: MonitorInfo,
        pet_frame: tuple[int, int, int, int],
        monitors: list[MonitorInfo],
    ) -> set[str]:
        physical = monitor.frame
        probe_offset = 2
        probe_x = min(max((pet_frame[0] + pet_frame[2]) // 2, physical[0] + 1), physical[2] - 1)
        probe_y = min(max((pet_frame[1] + pet_frame[3]) // 2, physical[1] + 1), physical[3] - 1)
        probes = {
            "left": (physical[0] - probe_offset, probe_y),
            "right": (physical[2] + probe_offset, probe_y),
            "top": (probe_x, physical[1] - probe_offset),
            "bottom": (probe_x, physical[3] + probe_offset),
        }
        other_frames = [
            candidate.frame
            for candidate in monitors
            if candidate.frame != monitor.frame
        ]
        return {
            edge
            for edge, point in probes.items()
            if not any(rect_contains_point(frame, point) for frame in other_frames)
        }

    def _start_edge_motion(
        self,
        target: tuple[int, int],
        completion: str,
    ) -> bool:
        if self.hwnd is None:
            return False
        current = self._window_rect(self.hwnd)
        if current is None:
            return False
        self.edge_motion = EdgeMotion(
            start=(current[0], current[1]),
            target=(int(target[0]), int(target[1])),
            started_at=time.monotonic(),
            completion=completion,
        )
        user32.KillTimer(self.hwnd, self.edge_timer_id)
        user32.SetTimer(self.hwnd, self.edge_timer_id, 16, None)
        return True

    def _advance_edge_motion(self) -> None:
        motion = self.edge_motion
        if motion is None or self.hwnd is None:
            return
        progress = min(
            1.0,
            max(
                0.0,
                (time.monotonic() - motion.started_at)
                / EDGE_TRANSITION_DURATION_SECONDS,
            ),
        )
        eased = progress * progress * (3.0 - 2.0 * progress)
        origin = (
            round(motion.start[0] + (motion.target[0] - motion.start[0]) * eased),
            round(motion.start[1] + (motion.target[1] - motion.start[1]) * eased),
        )
        self._set_window_origin(self.hwnd, origin)
        if progress < 1.0:
            return
        self._set_window_origin(self.hwnd, motion.target)
        self.edge_motion = None
        user32.KillTimer(self.hwnd, self.edge_timer_id)
        if motion.completion == "hide":
            self._finish_edge_hide()
        else:
            self._finish_edge_reveal()


    def _hide_tail(self) -> None:
        if self.tail_hwnd is not None:
            user32.ShowWindow(self.tail_hwnd, SW_HIDE)

    def _finish_edge_hide(self) -> None:
        placement = self.edge_placement
        if placement is None:
            self.edge_transition = None
            return
        self.edge_transition = None
        if self.reveal_after_hiding or self.activity_requires_visible_pet:
            self.reveal_after_hiding = False
            self._begin_edge_reveal(play_reveal_animation=False)
            return
        if self.hwnd is not None:
            user32.ShowWindow(self.hwnd, SW_HIDE)
        self._show_tail(placement)
        self._write_heartbeat(force=True)

    def _finish_edge_reveal(self) -> None:
        placement = self.edge_placement
        if placement is None:
            self.edge_transition = None
            return
        self._poll_bridge(force=True)
        self._settle_revealed_window(placement)
        self.edge_placement = None
        self.edge_transition = None
        self.reveal_after_hiding = False
        self._render_current()
        self._schedule_current()
        self._write_heartbeat(force=True)

    def _begin_edge_hide_if_needed(self) -> bool:
        if not self.can_hide_at_desktop_edge or self.hwnd is None:
            return False
        pet_frame = self._screen_bounds_for_local(self._current_pet_local_bounds())
        monitor = self._interaction_monitor()
        if pet_frame is None or monitor is None:
            return False
        edge = touched_desktop_edge(
            pet_frame,
            monitor.frame,
            self._exposed_edges(monitor, pet_frame, enumerate_monitor_infos()),
        )
        if edge is None or edge not in self.edge_tail_assets:
            return False
        placement = EdgePlacement(
            edge=edge,
            monitor=monitor,
            tail_rect=tail_window_rect(edge, pet_frame, monitor.frame),
        )
        self.edge_placement = placement
        self.edge_transition = "hiding"
        self.reveal_after_hiding = False
        self.success_effect_started = None
        self._switch_visual("edge_reveal", once=True)
        moving_pet_frame = self._screen_bounds_for_local(self._current_pet_local_bounds())
        if moving_pet_frame is None:
            self.edge_placement = None
            self.edge_transition = None
            return False
        delta = offscreen_delta(edge, moving_pet_frame, monitor.frame)
        current_window = self._window_rect(self.hwnd)
        if current_window is None or not self._start_edge_motion(
            (current_window[0] + delta[0], current_window[1] + delta[1]),
            "hide",
        ):
            self.edge_placement = None
            self.edge_transition = None
            return False
        return True

    def _begin_edge_reveal(self, play_reveal_animation: bool) -> bool:
        placement = self.edge_placement
        if placement is None:
            return False
        if self.edge_transition == "hiding":
            self.reveal_after_hiding = True
            return True
        if self.edge_transition == "revealing" or self.hwnd is None:
            return False
        self.edge_transition = "revealing"
        self.reveal_after_hiding = False
        self._hide_tail()
        if play_reveal_animation:
            self.success_effect_started = None
            self._switch_visual("edge_reveal", once=True)
        user32.ShowWindow(self.hwnd, SW_SHOW)
        self._restore_topmost()
        if not play_reveal_animation:
            self._render_current()
        content_frame = self._screen_bounds_for_local(self._current_content_local_bounds())
        if content_frame is None:
            self.edge_placement = None
            self.edge_transition = None
            return False
        pet_bounds = self._current_pet_local_bounds()
        bottom_drop = self._edge_bottom_drop(placement.edge, pet_bounds)
        delta = revealed_delta(
            placement.edge,
            content_frame,
            placement.monitor.work,
            bottom_drop=bottom_drop,
        )
        current_window = self._window_rect(self.hwnd)
        if current_window is None or not self._start_edge_motion(
            (round(current_window[0] + delta[0]), round(current_window[1] + delta[1])),
            "reveal",
        ):
            self.edge_placement = None
            self.edge_transition = None
            return False
        return True


    def _settle_revealed_window(self, placement: EdgePlacement) -> None:
        content_frame = self._screen_bounds_for_local(self._current_content_local_bounds())
        if content_frame is None or self.hwnd is None:
            return
        pet_bounds = self._current_pet_local_bounds()
        bottom_drop = self._edge_bottom_drop(placement.edge, pet_bounds)
        delta = revealed_delta(
            placement.edge,
            content_frame,
            placement.monitor.work,
            bottom_drop=bottom_drop,
        )
        if abs(delta[0]) < 0.5 and abs(delta[1]) < 0.5:
            return
        current_window = self._window_rect(self.hwnd)
        if current_window is not None:
            self._set_window_origin(
                self.hwnd,
                (round(current_window[0] + delta[0]), round(current_window[1] + delta[1])),
            )

    def _reveal_for_activity_if_needed(self) -> bool:
        if self.edge_placement is None or not self.activity_requires_visible_pet:
            return False
        return self._begin_edge_reveal(play_reveal_animation=False)

    def _effect_variant(
        self,
        name: str,
        size: int,
        opacity: float,
    ) -> Image.Image | None:
        source = self.effects.get(name)
        if source is None or size <= 0 or opacity <= 0:
            return None
        ratio = source.height / source.width
        variant = source.resize(
            (size, max(1, round(size * ratio))),
            Image.Resampling.LANCZOS,
        )
        if opacity < 0.999:
            alpha = np.asarray(variant.getchannel("A"), dtype=np.float32)
            alpha = np.uint8(np.clip(alpha * opacity, 0, 255))
            variant.putalpha(Image.fromarray(alpha, "L"))
        return variant

    def _composite_success_effects(self, canvas: Image.Image) -> None:
        if self.success_effect_started is None:
            return
        elapsed = time.monotonic() - self.success_effect_started
        if elapsed < 0 or elapsed > SUCCESS_EFFECT_DURATION_SECONDS:
            return
        progress = elapsed / SUCCESS_EFFECT_DURATION_SECONDS
        fade = min(1.0, progress / 0.18) * min(1.0, (1.0 - progress) / 0.28)
        effect_dx = BODY_ANCHOR_X - 230
        effect_dy = BODY_ANCHOR_BOTTOM - 390
        firework_size = round(34 + 28 * min(1.0, progress / 0.42))
        firework = self._effect_variant("firework", firework_size, fade * 0.82)
        if firework is not None:
            canvas.alpha_composite(
                firework,
                (
                    300 + effect_dx - firework.width // 2,
                    282 + effect_dy - firework.height // 2,
                ),
            )

        sparkles = [
            (154 + effect_dx, 266 + effect_dy, 19, 0.00),
            (279 + effect_dx, 235 + effect_dy, 15, 0.13),
            (184 + effect_dx, 224 + effect_dy, 12, 0.26),
        ]
        for center_x, center_y, base_size, phase in sparkles:
            local = (progress - phase) / max(0.01, 1.0 - phase)
            if local < 0 or local > 1:
                continue
            pulse = math.sin(math.pi * local)
            sparkle = self._effect_variant(
                "sparkle",
                round(base_size * (0.6 + 0.55 * pulse)),
                fade * pulse,
            )
            if sparkle is not None:
                canvas.alpha_composite(
                    sparkle,
                    (
                        center_x - sparkle.width // 2,
                        center_y - sparkle.height // 2,
                    ),
                )


    def _render_layered_window(
        self,
        hwnd: int,
        pixels: bytes,
        width: int,
        height: int,
        origin: tuple[int, int] | None = None,
    ) -> None:
        if hwnd not in self.layered_buffers:
            self.layered_buffers[hwnd] = LayeredBuffers()
        self.layered_buffers[hwnd].present(hwnd, pixels, width, height, origin)


    def _cursor_window_position(self) -> tuple[int, int] | None:
        if self.hwnd is None:
            return None
        cursor = POINT()
        window = RECT()
        user32.GetCursorPos(ctypes.byref(cursor))
        user32.GetWindowRect(self.hwnd, ctypes.byref(window))
        return (cursor.x - window.left, cursor.y - window.top)

    @staticmethod
    def _point_in_rect(point: tuple[int, int], rect: tuple[int, int, int, int] | None) -> bool:
        if rect is None:
            return False
        x, y = point
        left, top, right, bottom = rect
        return left <= x <= right and top <= y <= bottom

    def _hit_permission_button(self, point: tuple[int, int]) -> str | None:
        for action, rect in self.permission_buttons.items():
            if self._point_in_rect(point, rect):
                return action
        return None


    def _handle_left_button_down(self) -> None:
        if self.hwnd is None:
            return
        window_point = self._cursor_window_position()
        if self.permission_request is not None and window_point is not None:
            action = self._hit_permission_button(window_point)
            if action is not None:
                self.permission_button_down = action
                self.permission_bubble_down = True
                user32.SetCapture(self.hwnd)
                self._render_current()
                return
            if self._point_in_rect(window_point, self.permission_bubble_rect):
                self.permission_bubble_down = True
                user32.SetCapture(self.hwnd)
                return
        start = POINT()
        window = RECT()
        user32.GetCursorPos(ctypes.byref(start))
        user32.GetWindowRect(self.hwnd, ctypes.byref(window))
        self.mouse_down = True
        self.dragging = False
        self.drag_start_cursor = (start.x, start.y)
        self.drag_start_window = (window.left, window.top)
        self.drag_previous = (
            self.transient_key,
            self.transient_once,
            self.frame_index,
            self.success_effect_started,
        )
        self.click_feedback_enabled = False
        user32.SetCapture(self.hwnd)


    def _handle_left_button_up(self) -> None:
        if self.permission_button_down is not None or self.permission_bubble_down:
            action = self.permission_button_down
            self.permission_button_down = None
            self.permission_bubble_down = False
            user32.ReleaseCapture()
            point = self._cursor_window_position()
            if action is not None and point is not None and self._hit_permission_button(point) == action:
                self._write_permission_decision(action)
            else:
                self._render_current()
            return
        if not self.mouse_down:
            return
        was_dragging = self.dragging
        previous = self.drag_previous
        click_feedback = self.click_feedback_enabled
        self.mouse_down = False
        self.dragging = False
        self.drag_start_cursor = None
        self.drag_start_window = None
        self.drag_previous = None
        self.click_feedback_enabled = False
        user32.ReleaseCapture()

        if was_dragging and previous is not None:
            self._restore_after_drag(previous)
            self._begin_edge_hide_if_needed()
        elif click_feedback:
            self._switch_visual("click_feedback", once=True)

    def _cancel_mouse_drag(self) -> None:
        if not self.mouse_down:
            return
        previous = self.drag_previous
        was_dragging = self.dragging
        self.mouse_down = False
        self.dragging = False
        self.drag_start_cursor = None
        self.drag_start_window = None
        self.drag_previous = None
        self.click_feedback_enabled = False
        self.permission_button_down = None
        self.permission_bubble_down = False
        if was_dragging and previous is not None:
            self._restore_after_drag(previous)

    def _restore_after_menu_dismissal(self) -> None:
        if self.edge_placement is not None and self.edge_transition is None:
            if self.hwnd is not None:
                user32.ShowWindow(self.hwnd, SW_HIDE)
            self._show_tail(self.edge_placement)
        elif self.hwnd is not None:
            user32.ShowWindow(self.hwnd, SW_SHOW)
            self._render_current()
            self._schedule_current()
        self._restore_topmost()
        self._write_heartbeat(force=True)


    def _wndproc(self, hwnd: int, message: int, wparam: int, lparam: int) -> int:
        if message == WM_ENTERMENULOOP:
            self.menu_loop_depth += 1
        elif message == WM_EXITMENULOOP:
            self.menu_loop_depth = max(0, self.menu_loop_depth - 1)
            self._restore_topmost()
        if message == WM_DESTROY:
            buffers = self.layered_buffers.pop(hwnd, None)
            if buffers:
                buffers.close()
        if hwnd == self.tail_hwnd:
            if message == WM_LBUTTONUP:
                self._begin_edge_reveal(play_reveal_animation=True)
                return 0
            if message == WM_RBUTTONUP:
                self._show_menu(hwnd)
                return 0
            if message == WM_DESTROY:
                self.tail_hwnd = None
                return 0
            return user32.DefWindowProcW(hwnd, message, wparam, lparam)
        if message == WM_TIMER:
            if wparam == self.topmost_timer_id:
                self._restore_topmost()
                return 0
            if wparam == self.edge_timer_id:
                self._advance_edge_motion()
                return 0
            self._advance()
            return 0
        if message in (WM_LBUTTONDOWN, WM_LBUTTONDBLCLK):
            self._handle_left_button_down()
            return 0
        if message == WM_MOUSEMOVE:
            self._handle_mouse_move(wparam)
            return 0
        if message == WM_LBUTTONUP:
            self._handle_left_button_up()
            return 0
        if message == WM_RBUTTONUP:
            self._show_menu(hwnd)
            return 0
        if message == WM_DESTROY:
            user32.KillTimer(hwnd, self.timer_id)
            user32.KillTimer(hwnd, self.edge_timer_id)
            user32.KillTimer(hwnd, self.topmost_timer_id)
            self.edge_motion = None
            if self.tail_hwnd is not None:
                tail_hwnd = self.tail_hwnd
                user32.DestroyWindow(tail_hwnd)
                self.tail_hwnd = None
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)
