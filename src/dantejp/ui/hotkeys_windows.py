"""Native shortcuts; check key release only during an active show-original hold."""

import ctypes
from collections.abc import Callable
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QByteArray, QCoreApplication, Qt, QTimer

from dantejp.application.hotkeys import Hotkeys
from dantejp.i18n import tr


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
    def __init__(
        self,
        app: QCoreApplication,
        hotkeys: Hotkeys,
        *,
        key_down: Callable[[int], bool] | None = None,
    ) -> None:
        super().__init__()
        self._app, self._hotkeys = app, hotkeys
        user32 = ctypes.WinDLL("user32")
        get_state = user32.GetAsyncKeyState
        get_state.argtypes, get_state.restype = [ctypes.c_int], wintypes.SHORT
        self._key_down = key_down or (lambda key: bool(get_state(key) & 0x8000))
        # RegisterHotKey has no key-up event. No idle keyboard scan or hook is needed.
        self._release_timer = QTimer(app)
        self._release_timer.setInterval(16)
        self._release_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._release_timer.timeout.connect(self._check_release)
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
                    key_down=self._key_down,
                )
                if self._hotkeys.holding_original and not self._release_timer.isActive():
                    self._release_timer.start()
                return handled, 0
        return False, 0

    def _check_release(self) -> None:
        self._hotkeys.check_release(self._key_down)
        if not self._hotkeys.holding_original:
            self._release_timer.stop()

    def close(self) -> None:
        self._release_timer.stop()
        self._hotkeys.release()
        self._app.removeNativeEventFilter(self)
