"""Own Win32 window identity, physical geometry, and overlay window configuration."""

import ctypes
import os
from ctypes import wintypes as wt

from dantetl.domain import Rect, WindowGeometry, WindowTarget
from dantetl.i18n import tr


class WindowUnavailable(RuntimeError):
    """The exact selected window no longer exists or cannot be inspected."""


def _rect(value: wt.RECT) -> Rect:
    return Rect(value.left, value.top, value.right - value.left, value.bottom - value.top)


class Windows:
    """Small native boundary. All positions are per-monitor-aware physical pixels."""

    def __init__(self) -> None:
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.dwm = ctypes.WinDLL("dwmapi", use_last_error=True)
        self._enum_callback = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        signatures = {
            "EnumWindows": ([self._enum_callback, wt.LPARAM], wt.BOOL),
            "IsWindow": ([wt.HWND], wt.BOOL),
            "IsWindowVisible": ([wt.HWND], wt.BOOL),
            "IsIconic": ([wt.HWND], wt.BOOL),
            "GetWindowTextLengthW": ([wt.HWND], ctypes.c_int),
            "GetWindowTextW": ([wt.HWND, wt.LPWSTR, ctypes.c_int], ctypes.c_int),
            "GetWindowThreadProcessId": ([wt.HWND, ctypes.POINTER(wt.DWORD)], wt.DWORD),
            "GetWindowRect": ([wt.HWND, ctypes.POINTER(wt.RECT)], wt.BOOL),
            "GetClientRect": ([wt.HWND, ctypes.POINTER(wt.RECT)], wt.BOOL),
            "ClientToScreen": ([wt.HWND, ctypes.POINTER(wt.POINT)], wt.BOOL),
            "GetForegroundWindow": ([], wt.HWND),
            "GetDesktopWindow": ([], wt.HWND),
            "GetShellWindow": ([], wt.HWND),
            "GetDpiForWindow": ([wt.HWND], wt.UINT),
            "GetWindowLongPtrW": ([wt.HWND, ctypes.c_int], ctypes.c_ssize_t),
            "SetWindowLongPtrW": ([wt.HWND, ctypes.c_int, ctypes.c_ssize_t], ctypes.c_ssize_t),
            "SetWindowDisplayAffinity": ([wt.HWND, wt.DWORD], wt.BOOL),
            "GetWindowDisplayAffinity": ([wt.HWND, ctypes.POINTER(wt.DWORD)], wt.BOOL),
            "SetWindowPos": (
                [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT],
                wt.BOOL,
            ),
            "SetProcessDpiAwarenessContext": ([ctypes.c_void_p], wt.BOOL),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.user, name)
            function.argtypes = args
            function.restype = result
        self.dwm.DwmGetWindowAttribute.argtypes = [wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]
        self.dwm.DwmGetWindowAttribute.restype = ctypes.c_long

    def enable_dpi_awareness(self) -> None:
        # Must precede QApplication/window creation. Access denied means already set.
        if not self.user.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            error = ctypes.get_last_error()
            if error != 5:
                raise ctypes.WinError(error)

    def process_id(self, hwnd: int) -> int:
        process_id = wt.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        return process_id.value

    def title(self, hwnd: int) -> str:
        length = self.user.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        self.user.GetWindowTextW(hwnd, buffer, len(buffer))
        return buffer.value

    def is_target(self, target: WindowTarget) -> bool:
        return bool(self.user.IsWindow(target.hwnd)) and (
            self.process_id(target.hwnd) == target.process_id
        )

    def list_targets(self) -> list[WindowTarget]:
        targets: list[WindowTarget] = []

        def visit(hwnd: int, _: int) -> bool:
            if target := self._capture_target(hwnd):
                targets.append(target)
            return True

        callback = self._enum_callback(visit)
        if not self.user.EnumWindows(callback, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        return sorted(targets, key=lambda item: (item.title.casefold(), item.hwnd))

    def _capture_target(self, hwnd: int) -> WindowTarget | None:
        if (
            not hwnd
            or hwnd in (self.user.GetDesktopWindow(), self.user.GetShellWindow())
            or not self.user.IsWindowVisible(hwnd)
        ):
            return None
        pid = self.process_id(hwnd)
        if not pid or pid == os.getpid() or self.user.GetWindowLongPtrW(hwnd, -20) & 0x80:
            return None  # Exclude our windows and floating tool windows.
        cloaked = wt.DWORD()
        if self.dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked)):
            return None
        title = self.title(hwnd)
        if not title or cloaked.value:
            return None
        target = WindowTarget(hwnd, pid, title)
        try:
            geometry = self.geometry(target)
            return target if min(geometry.client.size) > 40 else None
        except WindowUnavailable:
            return None  # Enumeration/selection races naturally with windows closing.

    def foreground_target(self) -> WindowTarget:
        """Resolve only the currently focused eligible window, never an alternate selection."""
        target = self._capture_target(self.user.GetForegroundWindow())
        if target is None:
            raise WindowUnavailable(
                tr("Focus the game window, then press the capture hotkey again.")
            )
        if not self.is_foreground(target) or self.geometry(target).minimized:
            raise WindowUnavailable(
                tr("The focused window changed. Press the capture hotkey again.")
            )
        return target

    def geometry(self, target: WindowTarget) -> WindowGeometry:
        if not self.is_target(target):
            raise WindowUnavailable(
                tr("The selected window has closed. Refresh and select a window.")
            )
        client = wt.RECT()
        window = wt.RECT()
        origin = wt.POINT(0, 0)
        if not (
            self.user.GetClientRect(target.hwnd, ctypes.byref(client))
            and self.user.ClientToScreen(target.hwnd, ctypes.byref(origin))
            and self.user.GetWindowRect(target.hwnd, ctypes.byref(window))
        ):
            raise WindowUnavailable(tr("Could not read the selected window's geometry."))
        visible = wt.RECT()
        result = self.dwm.DwmGetWindowAttribute(
            target.hwnd, 9, ctypes.byref(visible), ctypes.sizeof(visible)
        )  # DWMWA_EXTENDED_FRAME_BOUNDS
        return WindowGeometry(
            client=Rect(origin.x, origin.y, client.right - client.left, client.bottom - client.top),
            visible_bounds=_rect(visible if result == 0 else window),
            window_bounds=_rect(window),
            dpi=self.user.GetDpiForWindow(target.hwnd) or 96,
            minimized=bool(self.user.IsIconic(target.hwnd)),
        )

    def is_foreground(self, target: WindowTarget) -> bool:
        return self.user.GetForegroundWindow() == target.hwnd and self.is_target(target)

    def configure_overlay(self, hwnd: int) -> None:
        # Layered + transparent gives cross-process mouse pass-through. Qt's widget
        # mouse transparency alone only affects widgets within our own application.
        style = self.user.GetWindowLongPtrW(hwnd, -20)
        ctypes.set_last_error(0)
        result = self.user.SetWindowLongPtrW(hwnd, -20, style | 0x80000 | 0x20 | 0x08000000 | 0x80)
        if result == 0 and ctypes.get_last_error():
            raise ctypes.WinError(ctypes.get_last_error())

    def set_overlay_capture(self, hwnd: int, included: bool) -> None:
        # Capture targets one game HWND, so the independent overlay is never OCR input.
        # WDA_NONE / WDA_EXCLUDEFROMCAPTURE affect desktop capture of this surface only.
        if not self.user.SetWindowDisplayAffinity(hwnd, 0 if included else 0x11):
            raise RuntimeError(
                tr("Windows could not change whether screen capture includes the overlay.")
            )

    def place_overlay(self, hwnd: int, bounds: Rect) -> None:
        # Physical desktop coordinates avoid Qt's virtual-desktop DPI conversion.
        if not self.user.SetWindowPos(
            hwnd, ctypes.c_void_p(-1), bounds.x, bounds.y, bounds.width, bounds.height, 0x0010
        ):  # HWND_TOPMOST, SWP_NOACTIVATE
            raise ctypes.WinError(ctypes.get_last_error())

    def overlay_properties(self, hwnd: int) -> tuple[int, int]:
        """Read back native flags for the live verification harness."""
        affinity = wt.DWORD()
        if not self.user.GetWindowDisplayAffinity(hwnd, ctypes.byref(affinity)):
            raise ctypes.WinError(ctypes.get_last_error())
        return self.user.GetWindowLongPtrW(hwnd, -20), affinity.value
