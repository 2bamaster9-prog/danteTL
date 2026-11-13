"""Replay the real scene policy without Qt, native capture, or inference threads."""

from dataclasses import replace
from unittest.mock import Mock

import pytest

from jp_overlay.domain import (
    CapturedFrame,
    CaptureSnapshot,
    CaptureState,
    Rect,
    WindowGeometry,
    WindowTarget,
)
from jp_overlay.live_session import LiveSession
from jp_overlay.recognition import OcrResult, OcrSnapshot, OcrState, TextRegion
from jp_overlay.translation import (
    TranslatedText,
    TranslationRequest,
    TranslationSnapshot,
    TranslationState,
)
from jp_overlay.visual import VisualState


def frame(sequence, now=1.0):
    bounds = Rect(0, 0, 1200, 900)
    return CapturedFrame(sequence, now, WindowGeometry(bounds, bounds, bounds, 96), b"")


class Worker:
    finished = False

    def __init__(self):
        self.stop_requested = False
        self.invalidations = 0

    def start(self):
        pass

    def request_stop(self):
        self.stop_requested = True

    def invalidate(self):
        self.invalidations += 1


class Capture(Worker):
    target = WindowTarget(1, 2, "Fixture")
    current = CaptureSnapshot(CaptureState.RUNNING)

    def snapshot(self):
        return self.current


class Ocr(Worker):
    current = OcrSnapshot(OcrState.READY)

    def __init__(self):
        super().__init__()
        self.acknowledged = []
        self.submitted = []

    def snapshot(self):
        return self.current

    def acknowledge(self, sequence):
        self.acknowledged.append(sequence)

    def submit(self, frame, areas=None):
        self.submitted.append((frame, areas))


class Visual(Worker):
    current = VisualState()

    def poll(self):
        return self.current

    def submit(self, frame, result, tracks, assignments, activity, candidate=None):
        self.submitted = (frame, result, tracks, assignments, activity, candidate)


class Replay:
    def __init__(self):
        self.ocr, self.visual, self.capture = Ocr(), Visual(), Capture()
        self.live = LiveSession(ocr_factory=lambda _: self.ocr, visual_factory=lambda: self.visual)
        self.live.start(self.capture, Mock())

    def observe(self, source, regions, *, scanned=None, **evidence):
        self.ocr.current = OcrSnapshot(
            OcrState.READY, OcrResult(source, regions, 25, source.captured_at, scanned)
        )
        self.visual.current = VisualState(
            frame=source, checked_sequence=source.sequence, ocr_sequence=source.sequence, **evidence
        )
        self.live.reconcile(source, source.captured_at)
        return self.live.scene(source, source.captured_at + 0.6, grouping=True)


def test_reconcile_waits_for_source_evidence_then_preserves_unscanned_tracks():
    replay = Replay()
    first = frame(1)
    label = TextRegion("設定", Rect(50, 40, 100, 30))
    replay.ocr.current = OcrSnapshot(OcrState.READY, OcrResult(first, (label,), 25, 1.0))
    replay.visual.current = VisualState(frame=first, checked_sequence=0)
    replay.live.reconcile(first, 1.0)
    assert replay.live.accepted is None and not replay.ocr.acknowledged
    scene = replay.observe(first, (label,))
    assert replay.live.accepted is replay.ocr.current.result
    assert replay.visual.submitted[1] is replay.ocr.current.result
    assert replay.ocr.acknowledged[-1] == 1
    old = scene.tracks[0]
    second = frame(2, 1.5)
    new = TextRegion("戻る", Rect(600, 40, 100, 30))
    scene = replay.observe(second, (new,), scanned=(Rect(580, 20, 160, 80),))
    assert old in scene.tracks and len(scene.tracks) == 2
    assert replay.live.accepted and replay.live.accepted.regions == (new,)
    # A noisy full pass is held by source-matched visual evidence, not inspector state.
    scene = replay.observe(
        frame(3, 2.0), (), unchanged=frozenset(scene.tracks), checked=frozenset(scene.tracks)
    )
    assert len(scene.tracks) == 2


def test_dialogue_publication_mask_restore_and_backend_scope_without_window():
    replay = Replay()
    regions = (
        TextRegion("ここから先は危険だから、", Rect(100, 650, 380, 35)),
        TextRegion("私と一緒に進んでください。", Rect(100, 695, 380, 35)),
    )
    replay.observe(frame(1), regions)
    scene = replay.observe(frame(2, 1.5), regions)
    assert len(scene.blocks) == 1 and len(scene.blocks[0].lines) == 2
    assert scene.requests == scene.blocks
    backend = Mock()
    result = TranslatedText(TranslationRequest.from_block(scene.blocks[0]), "Come with me.")
    backend.snapshot.return_value = TranslationSnapshot(TranslationState.READY, (result,))
    published = replay.live.publish(backend, scene.requests, scene.blocks)
    assert published.translations == (result,)
    replay.visual.current = replace(replay.visual.current, hidden=frozenset(scene.tracks))
    replay.live.reconcile(frame(2, 1.5), 2.0)
    assert not replay.live.publish(backend, scene.requests, scene.blocks).translations
    replay.visual.current = replace(replay.visual.current, hidden=frozenset())
    replay.live.reconcile(frame(2, 1.5), 2.1)
    assert replay.live.publish(backend, scene.requests, scene.blocks).translations == (result,)
    backend.snapshot.return_value = TranslationSnapshot(
        TranslationState.READY, backend_generation=1
    )
    assert not replay.live.publish(backend, scene.requests, scene.blocks).translations
    assert replay.live.accepted and replay.live.accepted.regions == regions


def test_resize_reset_and_stop_wait_for_workers_before_another_capture():
    replay = Replay()
    replay.observe(frame(1), (TextRegion("設定", Rect(50, 40, 100, 30)),))
    backend = Mock()
    replay.live.accept_size((1200, 900), backend)
    assert replay.live.accepted is None
    backend.invalidate.assert_called_once()
    assert not replay.live.accept_size((1200, 900), backend)
    replay.live.stop(backend)
    assert all(w.stop_requested for w in (replay.capture, replay.ocr, replay.visual))
    replay.capture.finished = True
    assert not replay.live.drain()
    with pytest.raises(RuntimeError, match="previous capture"):
        replay.live.start(Capture(), None)
    replay.ocr.finished = True
    assert not replay.live.drain()
    replay.visual.finished = True
    assert replay.live.drain() and replay.live.capture is None
    replay.live.start(Capture(), None)
    assert (
        replay.live.accepted is None and not replay.live.scene(frame(10), 5, grouping=True).tracks
    )


def test_scene_change_resets_dialogue_once_and_stopping_rejects_late_ocr_setup():
    replay = Replay()
    source = frame(1)
    replay.observe(source, (), changed_areas=(Rect(0, 0, 1200, 900),))
    translator = Mock()
    translator.snapshot.return_value = TranslationSnapshot(TranslationState.READY)
    replay.live.publish(translator, (), ())
    assert translator.update.call_args.kwargs["reset_context"]
    replay.live.publish(translator, (), ())
    assert not translator.update.call_args.kwargs["reset_context"]
    capture = Capture()
    capture.current = CaptureSnapshot(CaptureState.STOPPING)
    factory = Mock()
    live = LiveSession(ocr_factory=factory)
    live.start(capture, None)
    live.add_recognition(Mock())
    factory.assert_not_called()
