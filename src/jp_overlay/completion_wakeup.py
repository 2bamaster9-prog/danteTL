"""Coalesce worker completion hints into one queued Qt-thread callback."""

import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, Signal, Slot


class CompletionWakeup(QObject):
    """No payload/history: the receiver always reads current worker snapshots.

    notify() may run on any worker, outside its state lock. Only the queued slot
    invokes the receiver. close() revokes queued/late hints before widget teardown.
    """

    _requested = Signal()

    def __init__(self, callback: Callable[[], None], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._callback = callback
        self._lock = threading.Lock()
        self._pending = False
        self._closed = False
        self._requested.connect(self._deliver, Qt.ConnectionType.QueuedConnection)

    def notify(self) -> None:
        with self._lock:
            if self._closed or self._pending:
                return
            self._pending = True
            try:
                self._requested.emit()
            except RuntimeError:
                # A destroyed Qt receiver must never turn successful inference into
                # a failed worker. Normal shutdown closes this before destruction.
                self._closed, self._pending = True, False

    @Slot()
    def _deliver(self) -> None:
        with self._lock:
            self._pending = False
            if self._closed:
                return
        self._callback()

    def close(self) -> None:
        with self._lock:
            self._closed = True
