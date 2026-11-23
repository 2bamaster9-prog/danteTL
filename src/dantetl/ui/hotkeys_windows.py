"""Route registered Windows shortcuts into Qt."""

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QByteArray, QCoreApplication

from dantetl.application.hotkeys import Hotkeys
from dantetl.i18n import tr


class WindowsHotkeyRegistrar:
    def __init__(self) -> None:
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.RegisterHotKey.argtypes = [
            wintypes.HWND,
            ctypes.c_int,
            wintypes.UINT,
            wintypes.UINT,
        ]
        self._user32.RegisterHotKey.restype = wintypes.BOOL
        self._user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        self._user32.UnregisterHotKey.restype = wintypes.BOOL

    def register(self, identifier: int, modifiers: int, key: int) -> None:
        if not self._user32.RegisterHotKey(None, identifier, modifiers | 0x4000, key):
            error = ctypes.get_last_error()
            reason = (
                tr("Another app or Windows already uses this shortcut.")
                if error == 1409
                else tr("Windows could not register this shortcut (error {error}).", error=error)
            )
            raise OSError(reason)

    def unregister(self, identifier: int) -> None:
        if not self._user32.UnregisterHotKey(None, identifier):
            raise ctypes.WinError(ctypes.get_last_error())


class WindowsHotkeyEvents(QAbstractNativeEventFilter):
    def __init__(self, app: QCoreApplication, hotkeys: Hotkeys) -> None:
        super().__init__()
        self._app, self._hotkeys = app, hotkeys
        app.installNativeEventFilter(self)
        app.aboutToQuit.connect(self.close)

    def nativeEventFilter(
        self, eventType: QByteArray | bytes | bytearray | memoryview, message: int
    ) -> tuple[bool, int]:
        # Qt can route thread hotkeys through its internal Windows message window.
        if eventType in (b"windows_dispatcher_MSG", b"windows_generic_MSG"):
            event = wintypes.MSG.from_address(int(message))
            if event.message == 0x0312:  # WM_HOTKEY
                handled = self._hotkeys.dispatch(
                    event.wParam,
                    event.lParam & 0xFFFF,
                    (event.lParam >> 16) & 0xFFFF,
                )
                return handled, 0
        return False, 0

    def close(self) -> None:
        self._hotkeys.release()
        self._app.removeNativeEventFilter(self)
