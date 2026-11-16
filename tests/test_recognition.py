import threading
import time
from collections.abc import Callable
from dataclasses import replace

from dantejp.domain import CapturedFrame, Rect, WindowGeometry
from dantejp.ocr.worker import (
    OcrResult,
    OcrSession,
    OcrState,
    TextRegion,
    overlay_result_ready,
)


def frame(sequence: int) -> CapturedFrame:
    bounds = Rect(-100, 20, 100, 100)
    return CapturedFrame(sequence, 10.0, WindowGeometry(bounds, bounds, bounds, 144), b"")


def await_condition(predicate: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 3
    while not predicate():
        assert time.monotonic() < deadline, "Worker did not reach expected state"
        time.sleep(0.005)


def result_sequence(session: OcrSession) -> int | None:
    result = session.snapshot().result
    return result.frame.sequence if result else None


class BlockingRecognizer:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.sequences: list[int] = []

    def recognize(self, source: CapturedFrame, *, cropped: bool = False) -> tuple[TextRegion, ...]:
        self.sequences.append(source.sequence)
        self.entered.set()
        assert self.release.wait(3)
        return (TextRegion(str(source.sequence), Rect(0, 0, 10, 10)),)

    def close(self) -> None:
        pass


def test_ocr_completion_wakes_receiver_after_snapshot_and_preserves_ack_gate():
    engine = BlockingRecognizer()
    engine.release.set()
    snapshots = []
    session = OcrSession(
        lambda: engine,
        require_ack=True,
        on_change=lambda: snapshots.append(session.snapshot()),
    )
    session.start()
    try:
        session.submit(frame(1))
        await_condition(lambda: any(s.result for s in snapshots))
        assert snapshots[-1].result.frame.sequence == 1
        session.submit(frame(2))
        # A notification cannot consume or acknowledge the source observation.
        assert session._acknowledged == 0
        session.acknowledge(1)
        await_condition(lambda: any(s.result and s.result.frame.sequence == 2 for s in snapshots))
    finally:
        session.request_stop()
        await_condition(lambda: session.finished)
    assert snapshots[-1].state == OcrState.STOPPED


def test_finished_waits_for_cleanup_and_owner_thread_exit():
    cleaning, release = threading.Event(), threading.Event()

    class Engine(BlockingRecognizer):
        def close(self):
            cleaning.set()
            assert release.wait(3)

    engine = Engine()
    session = OcrSession(lambda: engine)
    session.start()
    await_condition(lambda: session.snapshot().state == OcrState.READY)
    session.request_stop()
    try:
        assert cleaning.wait(3)
        assert not session.finished
        assert session.snapshot().state == OcrState.STOPPING
    finally:
        release.set()
        await_condition(lambda: session.finished)
    assert not session._thread.is_alive()


def test_worker_skips_backlog_and_keeps_exact_source_frame() -> None:
    engine = BlockingRecognizer()
    session = OcrSession(lambda: engine)
    session.start()
    try:
        session.submit(frame(1))
        assert engine.entered.wait(3)
        assert session.snapshot().processing_since is not None
        for sequence in range(2, 1001):
            session.submit(frame(sequence))
        engine.release.set()
        await_condition(
            lambda: len(engine.sequences) == 2 and session.snapshot().result is not None
        )
        await_condition(lambda: result_sequence(session) == 1000)
        result = session.snapshot().result
        assert result is not None
        assert result.frame == frame(1000)
        assert result.regions[0].text == "1000"
        assert engine.sequences == [1, 1000]
        snapshot = session.snapshot()
        assert snapshot.processed_frames == 2
        assert snapshot.skipped_frames == 998
        assert snapshot.mean_duration_ms >= 0 and snapshot.queue_ms >= 0
        assert snapshot.processing_since is None
        session.submit(frame(1000))
        session.submit(frame(2))
        assert engine.sequences == [1, 1000]
    finally:
        engine.release.set()
        session.request_stop()
        await_condition(lambda: session.finished)


def test_pause_or_resize_discards_inflight_result_and_pending_work() -> None:
    class StagedRecognizer(BlockingRecognizer):
        def __init__(self) -> None:
            super().__init__()
            self.second_entered = threading.Event()
            self.second_release = threading.Event()

        def recognize(
            self, source: CapturedFrame, *, cropped: bool = False
        ) -> tuple[TextRegion, ...]:
            if not self.sequences:
                return super().recognize(source)
            self.sequences.append(source.sequence)
            self.second_entered.set()
            assert self.second_release.wait(3)
            return (TextRegion("new generation", Rect(0, 0, 10, 10)),)

        def close(self) -> None:
            pass

    engine = StagedRecognizer()
    session = OcrSession(lambda: engine)
    session.start()
    try:
        session.submit(frame(1))
        assert engine.entered.wait(3)
        session.submit(frame(2))
        session.invalidate()
        engine.release.set()
        # A new generation may resubmit even the same sequence after resume.
        session.submit(frame(1))
        assert engine.second_entered.wait(3)
        assert session.snapshot().result is None, "Invalidated inference published stale output"
        engine.second_release.set()
        await_condition(lambda: result_sequence(session) == 1)
        assert engine.sequences == [1, 1]
        assert result_sequence(session) == 1
        session.invalidate()
        assert session.snapshot().result is None
    finally:
        engine.release.set()
        engine.second_release.set()
        session.request_stop()
        await_condition(lambda: session.finished)


def test_inference_failure_clears_previous_detections() -> None:
    class FailingRecognizer:
        def recognize(
            self, source: CapturedFrame, *, cropped: bool = False
        ) -> tuple[TextRegion, ...]:
            if source.sequence == 2:
                raise RuntimeError("Inference failed")
            return (TextRegion("old text", Rect(0, 0, 10, 10)),)

        def close(self) -> None:
            pass

    session = OcrSession(FailingRecognizer)
    session.start()
    try:
        session.submit(frame(1))
        await_condition(lambda: result_sequence(session) == 1)
        session.submit(frame(2))
        await_condition(lambda: session.finished)
        assert session.snapshot().state == OcrState.FAILED
        assert session.snapshot().result is None
        assert session.snapshot().message == "Inference failed"
    finally:
        session.request_stop()
        await_condition(lambda: session.finished)


def test_stop_during_inference_is_nonblocking_and_rejects_late_result() -> None:
    engine = BlockingRecognizer()
    session = OcrSession(lambda: engine)
    session.start()
    session.submit(frame(1))
    assert engine.entered.wait(3)
    session.request_stop()
    session.submit(frame(2))
    assert session.snapshot().state == OcrState.STOPPING
    assert not session.finished
    engine.release.set()
    await_condition(lambda: session.finished)
    assert session.snapshot().state == OcrState.STOPPED
    assert session.snapshot().result is None
    assert engine.sequences == [1]
    session.request_stop()
    assert session.snapshot().state == OcrState.STOPPED


def test_model_failure_survives_stop_and_clear() -> None:
    def fail():
        raise RuntimeError("Missing local model")

    session = OcrSession(fail)
    session.start()
    await_condition(lambda: session.finished)
    session.request_stop()
    session.invalidate()
    assert session.snapshot().state == OcrState.FAILED
    assert session.snapshot().message == "Missing local model"


def test_stop_while_loading_never_publishes_ready_or_processes_pending_frame() -> None:
    entered, release = threading.Event(), threading.Event()
    engine = BlockingRecognizer()

    def load():
        entered.set()
        assert release.wait(3)
        return engine

    session = OcrSession(load)
    session.start()
    assert entered.wait(3)
    session.submit(frame(1))
    session.request_stop()
    release.set()
    await_condition(lambda: session.finished)
    assert session.snapshot().state == OcrState.STOPPED
    assert engine.sequences == []


def test_game_boxes_expire_on_changing_source_but_static_frames_remain_valid() -> None:
    result = OcrResult(frame(1), (), 20, 10.1)
    assert overlay_result_ready(result, frame(1), 90)
    assert overlay_result_ready(result, frame(2), 10.5)
    assert not overlay_result_ready(result, frame(2), 11)
    resized = replace(
        frame(1),
        geometry=WindowGeometry(Rect(0, 0, 200, 100), Rect(0, 0, 0, 0), Rect(0, 0, 0, 0), 96),
    )
    assert not overlay_result_ready(result, resized, 10.1)
