"""A setting change must not reset scene time or launch before native cleanup."""

import itertools
import sys
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from dantetl.capture.worker import CaptureSession
from dantetl.domain import CaptureState, Rect, WindowGeometry, WindowTarget


class Windows:
    def geometry(self, target):
        assert target == WindowTarget(12, 34, "fixture")
        bounds = Rect(0, 0, 8, 8)
        return WindowGeometry(bounds, bounds, bounds, 96)


def wait_for(predicate):
    deadline = time.monotonic() + 3
    while not predicate():
        assert time.monotonic() < deadline
        time.sleep(0.01)


def native_fixture(monkeypatch, *, fail_borderless=False, start_error=None):
    instances = []
    release = threading.Event()

    class Capture:
        def __init__(self, **options):
            self.on_frame_arrived = lambda frame, control: None
            self.on_closed = lambda: None
            if instances:
                assert instances[-1].stopped, "Overlapping native captures"
            if fail_borderless and options["draw_border"] is False:
                raise RuntimeError("Border setting unsupported")
            self.options = options
            self.stopping = threading.Event()
            self.stopped = False
            self.closed = False
            instances.append(self)

        def event(self, callback):
            setattr(self, callback.__name__, callback)
            return callback

        def start_free_threaded(self):
            if start_error and (error := start_error(self.options)):
                self.stopped = True  # Startup failed before returning a native control.
                raise Exception(error)
            self.on_frame_arrived(
                SimpleNamespace(
                    width=8, height=8, frame_buffer=np.zeros((8, 8, 4), dtype=np.uint8)
                ),
                self,
            )
            return self

        def is_finished(self):
            return self.closed

        def stop(self):
            self.stopping.set()
            assert release.wait(3), "Native cleanup was not released"
            self.stopped = True

        def wait(self):
            self.stop()

    monkeypatch.setitem(
        sys.modules,
        "windows_capture",
        SimpleNamespace(WindowsCapture=Capture, Frame=object, InternalCaptureControl=object),
    )
    return instances, release


def test_border_change_drains_native_capture_keeps_frame_and_increases_sequence(monkeypatch):
    instances, release = native_fixture(monkeypatch)
    clock = itertools.count(step=0.3)
    session = CaptureSession(WindowTarget(12, 34, "fixture"), Windows(), clock=lambda: next(clock))
    session.start()
    try:
        wait_for(lambda: session.snapshot().frame is not None)
        first = session.snapshot().frame
        session.set_border(False)
        wait_for(lambda: instances[0].stopping.is_set())
        assert session.snapshot().frame == first
        assert session.snapshot().state == CaptureState.RUNNING
        assert not session.finished and len(instances) == 1
        session.set_border(True)
        session.set_border(False)  # Coalesce edits during teardown.
        release.set()
        wait_for(lambda: len(instances) == 2 and session.snapshot().frame != first)
        assert instances[0].options["draw_border"] is None
        assert instances[1].options["draw_border"] is False
        assert instances[1].options["window_hwnd"] == 12
        latest = session.snapshot().frame
        assert first and latest and latest.sequence > first.sequence
    finally:
        release.set()
        session.request_stop()
        wait_for(lambda: session.finished)
    assert len(instances) == 2 and instances[-1].stopped


@pytest.mark.parametrize("reopening", [False, True], ids=["final-frame", "border-reopen"])
@pytest.mark.parametrize("closed", [True, False])
def test_geometry_loss_distinguishes_closure_from_failure(monkeypatch, reopening, closed):
    from dantetl.capture.windows import WindowClosed, WindowUnavailable

    instances, release = native_fixture(monkeypatch)
    windows = Windows()
    session = CaptureSession(WindowTarget(12, 34, "fixture"), windows, fps=0)
    session.start()
    try:
        wait_for(lambda: session.snapshot().frame is not None)
        if reopening:
            session.set_border(False)
            wait_for(lambda: instances[0].stopping.is_set())

        def unavailable(_):
            raise (WindowClosed if closed else WindowUnavailable)("fixture")

        monkeypatch.setattr(windows, "geometry", unavailable)
        release.set()
        if not reopening:
            instances[0].on_frame_arrived(None, instances[0])
        wait_for(lambda: session.finished)
        assert len(instances) == 1 and instances[0].stopped
        assert session.snapshot().state == (CaptureState.STOPPED if closed else CaptureState.FAILED)
    finally:
        release.set()
        session.request_stop()
        wait_for(lambda: session.finished)


def test_padded_native_rows_publish_only_owned_client_pixels(monkeypatch):
    instances, release = native_fixture(monkeypatch)
    session = CaptureSession(WindowTarget(12, 34, "fixture"), Windows(), fps=0)
    session.start()
    try:
        wait_for(lambda: session.snapshot().frame is not None)
        storage = np.arange(8 * 13 * 4, dtype=np.uint8).reshape(8, 13, 4)
        client = storage[:, 2:10]
        expected = client.tobytes()
        instances[0].on_frame_arrived(
            SimpleNamespace(width=8, height=8, frame_buffer=client), instances[0]
        )
        storage.fill(0)
        frame = session.snapshot().frame
        assert frame and frame.sequence == 2 and frame.bgra == expected
    finally:
        release.set()
        session.request_stop()
        wait_for(lambda: session.finished)


UNSUPPORTED_INTERVAL = (
    "Capture session threw an exception: Graphics capture error: Setting a minimum update "
    "interval is not supported by the Graphics Capture API on this platform."
)


@pytest.mark.parametrize("supports_interval", [True, False])
@pytest.mark.parametrize(
    ("fps", "interval_ms", "callbacks"),
    [
        (8, 125, ((0.004, 1), (0.121, 2), (0.127, 2), (0.249, 3), (0.375, 4))),
        (144, 6, ((0.001, 1), (0.0068, 2), (0.007, 2), (0.014, 3))),
        (0, 0, ((0.0, 2), (0.0001, 3), (0.0002, 4))),
    ],
)
def test_capture_sampling_paces_numeric_targets_and_accepts_all_unlimited_callbacks(
    monkeypatch, fps, interval_ms, callbacks, supports_interval
):
    def require_supported(options):
        if not supports_interval and options["minimum_update_interval"] is not None:
            return UNSUPPORTED_INTERVAL

    instances, release = native_fixture(monkeypatch, start_error=require_supported)
    now = 0.0
    session = CaptureSession(WindowTarget(12, 34, "fixture"), Windows(), fps=fps, clock=lambda: now)
    session.start()
    try:
        wait_for(lambda: session.snapshot().frame is not None)
        native = instances[-1]
        expected_intervals = [interval_ms] if supports_interval else [interval_ms, None]
        assert [i.options["minimum_update_interval"] for i in instances] == expected_intervals
        assert all(i.options["window_hwnd"] == 12 for i in instances)
        data = SimpleNamespace(width=8, height=8, frame_buffer=np.zeros((8, 8, 4), dtype=np.uint8))
        for timestamp, expected in callbacks:
            now = timestamp
            native.on_frame_arrived(data, native)
            frame = session.snapshot().frame
            assert frame and frame.sequence == expected
        if not supports_interval:
            release.set()
            session.set_border(False)
            wait_for(lambda: len(instances) >= 3)
            assert instances[2].options == {**native.options, "draw_border": False}
    finally:
        release.set()
        session.request_stop()
        wait_for(lambda: session.finished)


@pytest.mark.parametrize("error,attempts", [("Access denied", 1), (UNSUPPORTED_INTERVAL, 2)])
def test_capture_start_failure_retries_only_unsupported_interval_once(monkeypatch, error, attempts):
    instances, _ = native_fixture(monkeypatch, start_error=lambda _: error)
    session = CaptureSession(WindowTarget(12, 34, "fixture"), Windows())
    session.start()
    wait_for(lambda: session.finished)
    assert len(instances) == attempts
    assert session.snapshot().state == CaptureState.FAILED and session.snapshot().message == error


@pytest.mark.parametrize("action", ["close", "failure", "cancel"])
def test_border_change_never_reopens_a_closed_failed_or_stopping_source(monkeypatch, action):
    instances, release = native_fixture(monkeypatch, fail_borderless=action == "failure")
    release.set()
    session = CaptureSession(WindowTarget(12, 34, "fixture"), Windows())
    session.start()
    wait_for(lambda: session.snapshot().frame is not None)
    if action == "close":
        instances[0].closed = True
        instances[0].on_closed()
    elif action == "cancel":
        session.request_stop()
    session.set_border(False)
    wait_for(lambda: session.finished)
    assert len(instances) == 1 and instances[0].stopped
    assert session.snapshot().state == (
        CaptureState.FAILED if action == "failure" else CaptureState.STOPPED
    )
    if action == "failure":
        assert "Border setting unsupported" in session.snapshot().message
