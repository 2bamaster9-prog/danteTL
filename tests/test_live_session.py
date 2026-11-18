"""Replay the real scene policy without Qt, native capture, or inference threads."""

import threading
import time
from dataclasses import replace
from unittest.mock import Mock

import pytest

from dantejp.application.live_session import LiveSession
from dantejp.domain import (
    CapturedFrame,
    CaptureSnapshot,
    CaptureState,
    Rect,
    WindowGeometry,
    WindowTarget,
)
from dantejp.ocr.tracking import prepare_matching
from dantejp.ocr.visual import VisualState
from dantejp.ocr.worker import OcrResult, OcrSnapshot, OcrState, TextCharacter, TextRegion
from dantejp.translation.dialogue.classifier import Classification
from dantejp.translation.worker import (
    TranslatedText,
    TranslationRequest,
    TranslationSnapshot,
    TranslationState,
)


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
    def set_border(self, enabled):
        self.show_border = enabled

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

    def __init__(self, ocr=None):
        super().__init__()
        self.ocr = ocr
        self.sources = ()

    def poll(self):
        if (
            self.ocr
            and (result := self.ocr.current.result)
            and self.current.checked_sequence == result.frame.sequence
        ):
            self.current = replace(self.current, matching=prepare_matching(result, self.sources))
        return self.current

    def submit(
        self,
        frame,
        result,
        tracks,
        assignments,
        activity,
        candidate=None,
        evidence_bounds=(),
        matching_sources=(),
    ):
        self.sources = matching_sources
        self.submitted = (frame, result, tracks, assignments, activity, candidate)


class Replay:
    def __init__(self):
        self.ocr, self.capture = Ocr(), Capture()
        self.visual = Visual(self.ocr)
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
        if self.live.accepted != self.ocr.current.result:
            # Static settling may have advanced a revision since the worker's
            # previous matching snapshot. Return evidence for the refreshed tracks.
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


def test_completion_bursts_do_not_count_as_new_observations_or_change_english():
    replay = Replay()
    source = frame(1)
    regions = (TextRegion("設定", Rect(50, 40, 100, 30)),)
    scene = replay.observe(source, regions)
    backend = Mock()
    result = TranslatedText(TranslationRequest.from_block(scene.blocks[0]), "Settings")
    backend.snapshot.return_value = TranslationSnapshot(TranslationState.READY, (result,))
    english = replay.live.publish(backend, scene.requests, scene.blocks)
    for _ in range(100):
        replay.live.reconcile(source, 1.6)
        assert replay.live.scene(source, 1.6, grouping=True) == scene
        assert replay.live.publish(backend, scene.requests, scene.blocks) == english
    assert replay.live.accepted is not None and replay.live.accepted.frame is source
    assert replay.live._tracker._sequence == 1


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


@pytest.mark.parametrize("stale", [False, True])
def test_only_current_pattern_loss_can_start_a_new_weaker_similar_reading(stale):
    replay = Replay()
    box = Rect(100, 650, 380, 35)
    east, west = "東の門へ向かってください", "西の門へ向かってください"
    original = TextRegion(east, box, (TextCharacter(east, box, 0.99),))
    changed = TextRegion(west, box, (TextCharacter(west, box, 0.8),))
    scene = replay.observe(frame(1), (original,))
    old = scene.tracks[0]
    lost = replace(old, text_revision=0) if stale else old
    scene = replay.observe(frame(2, 2), (changed,), absent=frozenset((lost,)))
    assert scene.tracks[0].text == (east if stale else west)


def test_history_observes_complete_publications_without_changing_model_work():
    replay = Replay()
    replay.live.configure_history(True, "layout", layout_only=True)
    speaker = Rect(100, 605, 60, 27)
    regions = (
        TextRegion("旅人", speaker, (TextCharacter("旅人", speaker, 0.98),)),
        TextRegion("ここから先は危険だから、", Rect(100, 650, 380, 35)),
        TextRegion("私と一緒に進んでください。", Rect(100, 695, 380, 35)),
    )
    replay.observe(frame(1), regions)
    scene = replay.observe(frame(2, 1.5), regions)
    backend = Mock()
    results = tuple(
        TranslatedText(
            TranslationRequest.from_block(b), "Traveler" if b.text == "旅人" else "Fixture English"
        )
        for b in scene.requests
    )
    backend.snapshot.return_value = TranslationSnapshot(TranslationState.READY, results)
    replay.live.publish(backend, scene.requests, scene.blocks)
    replay.live.scene(frame(2, 1.5), 2.7, grouping=True)
    published = replay.live.publish(backend, scene.requests, scene.blocks)
    assert len(replay.live.history.turns) == 1
    turn = replay.live.history.turns[0]
    assert turn.speaker == "旅人" and turn.source == regions[1].text + regions[2].text
    assert turn.speaker_english == "Traveler"
    expected = backend.update.call_args
    replay.live.history.clear()
    assert replay.live.publish(backend, scene.requests, scene.blocks) == published
    assert backend.update.call_args == expected  # No extra sources or prompt-context reset.
    assert replay.live.history.turns == ()
    replay.live.stop(backend)
    assert replay.live.history.turns == ()


def test_classifier_never_holds_translation_and_swap_disable_drain_the_owner():
    replay = Replay()
    entered, release = threading.Event(), threading.Event()
    events = []

    class Engine:
        def __init__(self, key):
            self.key = key
            events.append((key, "load"))

        def classify(self, value, cancelled):
            if self.key == "old":
                entered.set()
                assert release.wait(3)
                assert cancelled.is_set()
            return Classification("dialogue", "no")

        def close(self):
            events.append((self.key, "close"))

    regions = (
        TextRegion("ここから先は危険です。私と一緒に進んでください。", Rect(100, 650, 700, 35)),
    )
    replay.observe(frame(1), regions)
    scene = replay.observe(frame(2, 1.5), regions)
    backend = Mock()
    english = TranslatedText(TranslationRequest.from_block(scene.blocks[0]), "Come with me.")
    backend.snapshot.return_value = TranslationSnapshot(TranslationState.READY, (english,))
    assert replay.live.publish(backend, scene.requests, scene.blocks).translations == (english,)
    assert not replay.live.history.turns and not events  # default-off really does no work
    replay.live.configure_history(True, "old", lambda: Engine("old"))
    replay.live.scene(frame(2, 1.5), 2.1, grouping=True)
    replay.live.scene(frame(2, 1.5), 2.7, grouping=True)
    assert entered.wait(2)
    try:
        for _ in range(30):
            assert replay.live.publish(backend, scene.requests, scene.blocks).translations == (
                english,
            )
        assert not replay.live.history.turns
        replay.live.configure_history(True, "new", lambda: Engine("new"))
        replay.live.scene(frame(2, 1.5), 2.8, grouping=True)
        assert events == [("old", "load")]
        release.set()
        deadline = time.monotonic() + 3
        while not replay.live.history.turns:
            assert time.monotonic() < deadline
            replay.live.scene(frame(2, 1.5), 3.5, grouping=True)
            replay.live.publish(backend, scene.requests, scene.blocks)
            time.sleep(0.005)
        assert events[:3] == [("old", "load"), ("old", "close"), ("new", "load")]
        replay.live.configure_history(False, "new", lambda: Engine("new"))
        assert replay.live.history_status.startswith("Disabled")
    finally:
        release.set()
        replay.live.stop()
        replay.capture.finished = replay.ocr.finished = replay.visual.finished = True
        deadline = time.monotonic() + 3
        while not replay.live.drain():
            assert time.monotonic() < deadline
            time.sleep(0.005)
    assert events[-1] == ("new", "close")
    assert len(replay.live.history.turns) == 1  # Disabling keeps the readable transcript.


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
