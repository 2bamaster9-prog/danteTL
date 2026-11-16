"""A setting change must not reset scene time or launch before native cleanup."""

import itertools
import sys
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from dantejp.capture.worker import CaptureSession
from dantejp.domain import CaptureState, Rect, WindowGeometry, WindowTarget


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


def native_fixture(monkeypatch, *, fail_borderless=False):
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
