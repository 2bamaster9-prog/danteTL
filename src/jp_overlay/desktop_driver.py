"""Qt scheduling adapter. Completion hints coalesce; application transitions stay headless."""

import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer

from jp_overlay.application_api import ApplicationCommands
from jp_overlay.completion_wakeup import CompletionWakeup


class DesktopDriver(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.wakeup = CompletionWakeup(lambda: self.refresh(inspect=False), self)
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(lambda: self.refresh(inspect=True))
        self._application: ApplicationCommands | None = None
        self._render: Callable[[bool], None] = lambda inspect: None
        self._active = self._again = self._closed = False

    def bind(
        self, application: ApplicationCommands, render: Callable[[bool], None], parent: QObject
    ) -> None:
        self.setParent(parent)
        self._application, self._render = application, render
        self.timer.start()

    def notify(self) -> None:
        self.wakeup.notify()

    def refresh(self, *, inspect: bool) -> None:
        if self._closed or self._application is None:
            return
        if self._active:
            self._again = True
            return
        self._active = True
        try:
            self._application.advance(time.monotonic())
            self._render(inspect)
        finally:
            self._active = False
            if self._again:
                self._again = False
                self.notify()

    def close(self) -> None:
        self._closed = True
        self.timer.stop()
        self.wakeup.close()
