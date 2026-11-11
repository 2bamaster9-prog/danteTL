import threading

import pytest

from jp_overlay.capture import CaptureSession, FrameMailbox
from jp_overlay.domain import CapturedFrame, CaptureState, Rect, WindowGeometry, WindowTarget


class FakeWindows:
    def geometry(self, target: WindowTarget) -> WindowGeometry:
        bounds = Rect(0, 0, 8, 8)
        return WindowGeometry(bounds, bounds, bounds, 96)


def make_frame(sequence: int) -> CapturedFrame:
    return CapturedFrame(
        sequence, float(sequence), FakeWindows().geometry(WindowTarget(1, 1, "")), b""
    )


def test_latest_frame_replaces_previous_without_a_queue() -> None:
    mailbox = FrameMailbox()
    for sequence in range(1000):
        mailbox.publish(make_frame(sequence))
    assert mailbox.snapshot().frame == make_frame(999)


@pytest.mark.parametrize(
    "state", [CaptureState.STOPPING, CaptureState.STOPPED, CaptureState.FAILED]
)
def test_late_callback_cannot_revive_a_terminal_session(state: CaptureState) -> None:
    mailbox = FrameMailbox()
    mailbox.publish(make_frame(1))
    mailbox.set_state(state, "reason")
    mailbox.publish(make_frame(2))
    assert mailbox.snapshot().state == state
    assert mailbox.snapshot().frame is None


def test_cleanup_preserves_failure_diagnostic() -> None:
    mailbox = FrameMailbox()
    mailbox.set_state(CaptureState.FAILED, "Capture not supported")
    mailbox.set_state(CaptureState.STOPPED)
    assert mailbox.snapshot().message == "Capture not supported"
    assert mailbox.snapshot().state == CaptureState.FAILED


@pytest.mark.parametrize("state", [CaptureState.STOPPED, CaptureState.FAILED])
def test_repeated_stop_keeps_terminal_state(state: CaptureState) -> None:
    mailbox = FrameMailbox()
    mailbox.set_state(state, "final")
    mailbox.set_state(CaptureState.STOPPING)
    assert mailbox.snapshot().state == state
    assert mailbox.snapshot().message == "final"


def test_concurrent_shutdown_prevents_further_publication() -> None:
    mailbox = FrameMailbox()
    ready = threading.Event()
    finish = threading.Event()

    def producer() -> None:
        mailbox.publish(make_frame(1))
        ready.set()
        finish.wait(2)
        mailbox.publish(make_frame(2))

    thread = threading.Thread(target=producer)
    thread.start()
    assert ready.wait(2)
    mailbox.set_state(CaptureState.STOPPING)
    finish.set()
    thread.join(2)
    assert mailbox.snapshot().frame is None


def test_capture_rate_is_bounded() -> None:
    with pytest.raises(ValueError):
        CaptureSession(WindowTarget(1, 1, ""), FakeWindows(), fps=0)
