"""Bounded WGC session with asynchronous startup and shutdown, independent of Qt."""

import logging
import threading
import time
from collections.abc import Callable
from typing import Protocol

from jp_overlay.domain import (
    CapturedFrame,
    CaptureSnapshot,
    CaptureState,
    WindowGeometry,
    WindowTarget,
    client_crop,
)

logger = logging.getLogger(__name__)


class GeometrySource(Protocol):
    def geometry(self, target: WindowTarget) -> WindowGeometry: ...


class FrameMailbox:
    """A single replaceable frame; consumers cannot create a backlog."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot = CaptureSnapshot(CaptureState.STARTING)

    def publish(self, frame: CapturedFrame) -> None:
        with self._lock:
            if self._snapshot.state not in (
                CaptureState.STOPPING,
                CaptureState.STOPPED,
                CaptureState.FAILED,
            ):
                self._snapshot = CaptureSnapshot(CaptureState.RUNNING, frame)

    def set_state(self, state: CaptureState, message: str = "") -> None:
        with self._lock:
            if self._snapshot.state in (CaptureState.FAILED, CaptureState.STOPPED):
                return
            self._snapshot = CaptureSnapshot(state, message=message)

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
    ) -> None:
        if not 1 <= fps <= 30:
            raise ValueError("Capture rate must be between 1 and 30.")
        self.target = target
        self.mailbox = FrameMailbox()
        self._windows = windows
        self._fps = fps
        self._clock = clock
        self._stop = threading.Event()
        self._done = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def finished(self) -> bool:
        return self._done.is_set()

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("A capture session can only be started once.")
        self._thread = threading.Thread(target=self._run, name="capture-owner", daemon=True)
        self._thread.start()

    def request_stop(self) -> None:
        self.mailbox.set_state(CaptureState.STOPPING)
        self._stop.set()

    def snapshot(self) -> CaptureSnapshot:
        return self.mailbox.snapshot()

    def _run(self) -> None:
        try:
            self._capture()
        except Exception as error:
            logger.exception("Capture session failed")
            self.mailbox.set_state(CaptureState.FAILED, str(error))
        finally:
            self.mailbox.set_state(CaptureState.STOPPED)
            self._done.set()

    def _capture(self) -> None:
        # Native dependency imports stay at the boundary and off the GUI thread.
        from windows_capture import Frame, InternalCaptureControl, WindowsCapture

        if self._stop.is_set():
            return
        self._windows.geometry(self.target)
        last_sample = float("-inf")
        sequence = 0
        closed = threading.Event()
        capture = WindowsCapture(
            window_hwnd=self.target.hwnd,
            cursor_capture=False,
            minimum_update_interval=round(1000 / self._fps),
        )

        @capture.event
        def on_frame_arrived(frame: Frame, control: InternalCaptureControl) -> None:
            nonlocal last_sample, sequence
            if self._stop.is_set():
                control.stop()
                return
            now = self._clock()
            if now - last_sample < 1 / self._fps:
                return
            try:
                geometry = self._windows.geometry(self.target)
                crop = client_crop((frame.width, frame.height), geometry)
                if crop is None:
                    return  # A resize may deliver frames with obsolete dimensions.
                pixels = frame.frame_buffer[
                    crop.y : crop.y + crop.height, crop.x : crop.x + crop.width, :4
                ].tobytes(order="C")
                sequence += 1
                self.mailbox.publish(CapturedFrame(sequence, now, geometry, pixels))
                last_sample = now
            except Exception as error:
                logger.exception("Could not process a captured frame")
                self.mailbox.set_state(CaptureState.FAILED, str(error))
                self._stop.set()
                control.stop()

        @capture.event
        def on_closed() -> None:
            closed.set()

        if self._stop.is_set():
            return
        control = capture.start_free_threaded()
        started = self._clock()
        try:
            while not self._stop.wait(0.05):
                if closed.is_set() or control.is_finished():
                    break
                if sequence == 0 and self._clock() - started > 10:
                    raise RuntimeError(
                        "No usable frame arrived. Restore the window and try windowed or "
                        "borderless mode. Protected or unsupported windows cannot be captured."
                    )
        finally:
            if control.is_finished():
                control.wait()
            else:
                control.stop()
