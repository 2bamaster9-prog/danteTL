"""Bounded WGC session with asynchronous startup and shutdown, independent of Qt."""

import logging
import threading
import time
from collections.abc import Callable
from typing import Protocol

from dantetl.capture.windows import WindowClosed
from dantetl.domain import (
    CapturedFrame,
    CaptureSnapshot,
    CaptureState,
    WindowGeometry,
    WindowTarget,
    client_crop,
)
from dantetl.i18n import tr

logger = logging.getLogger(__name__)

# windows-capture exposes this WGC capability error as a plain Python Exception.
_INTERVAL_UNSUPPORTED = (
    "Setting a minimum update interval is not supported "
    "by the Graphics Capture API on this platform."
)


class GeometrySource(Protocol):
    def geometry(self, target: WindowTarget) -> WindowGeometry: ...


class FrameMailbox:
    """A single replaceable frame; consumers cannot create a backlog."""

    def __init__(self, on_change: Callable[[], None] | None = None) -> None:
        self._lock = threading.Lock()
        self._snapshot = CaptureSnapshot(CaptureState.STARTING)
        self._notify = on_change or (lambda: None)

    def publish(self, frame: CapturedFrame) -> None:
        with self._lock:
            if self._snapshot.state in (
                CaptureState.STOPPING,
                CaptureState.STOPPED,
                CaptureState.FAILED,
            ):
                return
            self._snapshot = CaptureSnapshot(CaptureState.RUNNING, frame)
        self._notify()

    def set_state(self, state: CaptureState, message: str = "") -> None:
        with self._lock:
            if self._snapshot.state in (CaptureState.FAILED, CaptureState.STOPPED):
                return
            if self._snapshot.state == state and self._snapshot.message == message:
                return
            self._snapshot = CaptureSnapshot(state, message=message)
        self._notify()

    def snapshot(self) -> CaptureSnapshot:
        with self._lock:
            return self._snapshot


class CaptureSession:
    """One HWND session. Start once; request_stop never waits on the calling thread.

    The native library owns its capture thread. A Python owner thread performs native
    startup/teardown. Callback buffers are copied before returning to the library.
    """

    def __init__(
        self,
        target: WindowTarget,
        windows: GeometrySource,
        fps: int = 4,
        clock: Callable[[], float] = time.monotonic,
        *,
        on_change: Callable[[], None] | None = None,
        show_border: bool = True,
    ) -> None:
        if fps < 0:
            raise ValueError(tr("Capture rate cannot be negative."))
        self.target = target
        self.mailbox = FrameMailbox(on_change)
        self._windows = windows
        self._fps = fps
        self._native_interval_ms: int | None = 1000 // fps if fps else 0
        self._clock = clock
        self._stop = threading.Event()
        self._done = threading.Event()
        self._thread: threading.Thread | None = None
        self._options_lock = threading.Lock()
        self._show_border = show_border
        self._sequence = 0
        self._next_sample = float("-inf")

    @property
    def finished(self) -> bool:
        return self._done.is_set()

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError(tr("A capture session can only be started once."))
        self._thread = threading.Thread(target=self._run, name="capture-owner", daemon=True)
        self._thread.start()

    def request_stop(self) -> None:
        self.mailbox.set_state(CaptureState.STOPPING)
        self._stop.set()

    def snapshot(self) -> CaptureSnapshot:
        return self.mailbox.snapshot()

    def set_border(self, enabled: bool) -> None:
        """Coalesce a native setting change; leave frames and processing state intact."""
        with self._options_lock:
            self._show_border = enabled

    def _border(self) -> bool:
        with self._options_lock:
            return self._show_border

    def _run(self) -> None:
        try:
            while self._capture():
                pass  # Reopen only the same HWND, rechecking its identity on every attempt.
        except WindowClosed:
            return  # The target can disappear before native startup or a border reopen.
        except Exception as error:
            logger.exception("Capture session failed")
            self.mailbox.set_state(CaptureState.FAILED, str(error))
        finally:
            self.mailbox.set_state(CaptureState.STOPPED)
            self._done.set()

    def _capture(self) -> bool:
        # Native dependency imports stay at the boundary and off the GUI thread.
        from windows_capture import Frame, InternalCaptureControl, WindowsCapture

        if self._stop.is_set():
            return False
        self._windows.geometry(self.target)
        border = self._border()
        first_sequence = self._sequence
        period = 1 / self._fps if self._fps else 0.0
        jitter = min(0.016, period / 8)
        closed = threading.Event()
        capture = WindowsCapture(
            window_hwnd=self.target.hwnd,
            cursor_capture=False,
            draw_border=None if border else False,
            minimum_update_interval=self._native_interval_ms,
        )

        @capture.event
        def on_frame_arrived(frame: Frame, control: InternalCaptureControl) -> None:
            if self._stop.is_set():
                control.stop()
                return
            now = self._clock()
            # Admit a slightly early delivery in its scheduled slot, including
            # when Windows supplies frames at its default cadence.
            if period and now < self._next_sample - jitter:
                return
            try:
                geometry = self._windows.geometry(self.target)
                crop = client_crop((frame.width, frame.height), geometry)
                if crop is None:
                    return  # A resize may deliver frames with obsolete dimensions.
                client = frame.frame_buffer[
                    crop.y : crop.y + crop.height, crop.x : crop.x + crop.width, :4
                ]
                # WGC rows are packed BGRA, but their pitch can include padding or
                # window chrome. Copy one contiguous row at a time into owned bytes.
                row_bytes = crop.width * 4
                pixels = client.reshape(crop.height, row_bytes).view(f"V{row_bytes}").tobytes()
                self._sequence += 1
                self.mailbox.publish(CapturedFrame(self._sequence, now, geometry, pixels))
                if period:
                    self._next_sample = max(now, self._next_sample) + period
            except WindowClosed:
                closed.set()
                control.stop()
            except Exception as error:
                logger.exception("Could not process a captured frame")
                self.mailbox.set_state(CaptureState.FAILED, str(error))
                self._stop.set()
                control.stop()

        @capture.event
        def on_closed() -> None:
            closed.set()

        if self._stop.is_set():
            return False
        try:
            control = capture.start_free_threaded()
        except Exception as error:
            if self._native_interval_ms is None or not str(error).endswith(_INTERVAL_UNSUPPORTED):
                raise
            logger.info("WGC does not support a custom frame interval; using its default cadence")
            self._native_interval_ms = None
            return True
        started = self._clock()
        try:
            while not self._stop.wait(0.05):
                if closed.is_set() or control.is_finished():
                    break
                if self._border() != border:
                    return True
                if self._sequence == first_sequence and self._clock() - started > 10:
                    raise RuntimeError(
                        tr(
                            "No usable frame arrived. Restore the window and try windowed or "
                            "borderless mode. Protected or unsupported windows cannot be captured."
                        )
                    )
        finally:
            if control.is_finished():
                control.wait()
            else:
                control.stop()
        return False
