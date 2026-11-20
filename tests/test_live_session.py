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
from dantejp.languages.selection import DEFAULT_SOURCE
from dantejp.ocr.tracking import prepare_matching
from dantejp.ocr.values import OcrResult, OcrSnapshot, OcrState, TextCharacter, TextRegion
from dantejp.ocr.visual import VisualSession
from dantejp.ocr.visual_values import VisualState
from dantejp.translation.dialogue.classifier import Classification
from dantejp.translation.values import (
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

    def __init__(self, ocr=None, *, language=DEFAULT_SOURCE):
        super().__init__()
        self.ocr = ocr
        self.language = language
        self.sources = ()

    def invalidate(self, *, language=DEFAULT_SOURCE):
        super().invalidate()
        self.language = language

    def poll(self):
        if (
            self.ocr
            and (result := self.ocr.current.result)
            and self.current.checked_sequence == result.frame.sequence
        ):
            self.current = replace(
                self.current,
                matching=prepare_matching(result, self.sources, language=self.language),
            )
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
    def __init__(self, *, language=DEFAULT_SOURCE):
        self.ocr, self.capture = Ocr(), Capture()
        self.visual = Visual(self.ocr, language=language)
        self.live = LiveSession(
            ocr_factory=lambda _: self.ocr, visual_factory=lambda: self.visual, language=language
        )
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


@pytest.mark.parametrize("failure", ["prepare_matching", "prepare_evidence"])
def test_review_failure_releases_ocr_and_recovers_on_the_next_result(monkeypatch, failure):
    from dantejp.ocr import visual

    original = getattr(visual, failure)

    def fault(result, *args, **kwargs):
        if result.frame.sequence == 2:
            raise ValueError("fixture review failure")
        return original(result, *args, **kwargs)

    monkeypatch.setattr(visual, failure, fault)
    ocr, capture, analysis = Ocr(), Capture(), VisualSession()
    live = LiveSession(ocr_factory=lambda _: ocr, visual_factory=lambda: analysis)
    live.start(capture, Mock())
    label = TextRegion("設定", Rect(50, 40, 100, 30))
    try:
        for seq in (1, 2, 3):
            source = frame(seq, float(seq))
            ocr.current = OcrSnapshot(OcrState.READY, OcrResult(source, (label,), 25, seq))
            deadline = time.monotonic() + 5
            while seq not in ocr.acknowledged:
                assert not analysis.finished and time.monotonic() < deadline
                live.reconcile(source, source.captured_at)
                time.sleep(0.002)
            assert live.accepted is not None
            rejected = seq == 2 and failure == "prepare_matching"
            assert live.accepted.frame.sequence == (1 if rejected else seq)
            assert bool(live.visual_state.review_message) == (seq == 2)
            if rejected:
                assert (source, None) in ocr.submitted
            assert live.scene(source, source.captured_at, grouping=True).tracks
            live.reconcile(source, source.captured_at)
        assert ocr.acknowledged == [1, 2, 3]
    finally:
        live.stop()
        capture.finished = ocr.finished = True
        deadline = time.monotonic() + 5
        while not live.drain():
            assert time.monotonic() < deadline
            time.sleep(0.002)


def test_visual_loss_between_ocr_passes_keeps_locked_dialogue_and_backend_scope():
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
    scene = replay.live.scene(frame(2, 1.5), 2.0, grouping=True)
    assert len(scene.tracks) == 2
    assert replay.live.publish(backend, scene.requests, scene.blocks).translations == (result,)
    replay.visual.current = replace(replay.visual.current, hidden=frozenset())
    replay.live.reconcile(frame(2, 1.5), 2.1)
    assert replay.live.publish(backend, scene.requests, scene.blocks).translations == (result,)
    backend.snapshot.return_value = TranslationSnapshot(
        TranslationState.READY, backend_generation=1
    )
    assert not replay.live.publish(backend, scene.requests, scene.blocks).translations
    assert replay.live.accepted and replay.live.accepted.regions == regions


def test_vacated_group_hides_locally_and_restores_cached_english_without_new_ocr():
    replay, backend = Replay(), Mock()
    regions = (
        TextRegion("ここから先は危険だから、", Rect(100, 650, 380, 35)),
        TextRegion("私と一緒に進んでください。", Rect(100, 695, 380, 35)),
        TextRegion("設定", Rect(850, 100, 100, 35)),
    )
    replay.observe(frame(1), regions)
    scene = replay.observe(frame(2, 1.5), regions)
    dialogue = next(b for b in scene.blocks if len(b.lines) == 2)
    label = next(b for b in scene.blocks if len(b.lines) == 1)
    english = tuple(
        TranslatedText(TranslationRequest.from_block(b), text)
        for b, text in ((dialogue, "Come with me."), (label, "Settings"))
    )
    backend.snapshot.return_value = TranslationSnapshot(TranslationState.READY, english)
    locked = replay.live.publish(backend, scene.requests, scene.blocks)
    backend.snapshot.return_value = TranslationSnapshot(TranslationState.READY)
    a, b = dialogue.lines
    for seq, cleared, visible in (
        (3, (a,), locked.blocks),
        (4, (a, replace(b, text_revision=b.text_revision + 1)), locked.blocks),
        (5, (a, b), (label,)),
        (6, (), locked.blocks),
    ):
        current = frame(seq, seq / 8 + 1.5)
        replay.visual.current = replace(
            replay.visual.current, frame=current, cleared=frozenset(cleared)
        )
        replay.live.reconcile(current, current.captured_at)
        observed = replay.live.scene(current, current.captured_at, grouping=True)
        assert observed.blocks == scene.blocks
        assert observed.tracks == tuple(t for t in scene.tracks if t not in cleared)
        shown = replay.live.publish(backend, observed.requests, observed.blocks)
        assert shown.blocks == visible
        assert shown.translations == ((english[1],) if visible == (label,) else locked.translations)
        assert backend.update.call_args.kwargs["retain"] == scene.blocks
    assert replay.ocr.acknowledged == [1, 2]


@pytest.mark.parametrize("verified_pixels", [False, True])
def test_similar_ocr_keeps_group_english_until_exact_replacement_arrives(verified_pixels):
    replay, backend = Replay(), Mock()
    top = Rect(100, 650, 380, 35)
    bottom = Rect(100, 695, 380, 35)

    def row(text, bounds, score):
        return TextRegion(text, bounds, (TextCharacter(text, bounds, score),))

    first = row("ここから先は危険だから、", top, 0.98)
    source = "私と一緒に（奥まで）進んでください。"
    typo = source.replace("）", "")
    original = row(typo, bottom, 0.94)
    scene = replay.observe(frame(1), (first, original))
    assert len(scene.blocks) == 1 and len(scene.blocks[0].lines) == 2
    old = TranslatedText(TranslationRequest.from_block(scene.blocks[0]), "Come with me.")
    backend.snapshot.return_value = TranslationSnapshot(TranslationState.READY, (old,))

    def publish():
        return replay.live.publish(backend, scene.requests, scene.blocks)

    assert publish().translations == (old,)
    original_tracks = scene.tracks
    same_pixels = frozenset(original_tracks) if verified_pixels else frozenset()
    for seq, score in enumerate((0.90, 0.94, 0.85), 2):
        scene = replay.observe(
            frame(seq, float(seq)),
            (first, row(source, bottom, score)),
            checked=frozenset(original_tracks),
            unchanged=same_pixels,
        )
        assert publish().translations == (old,)
        assert TranslationRequest.from_block(scene.requests[0]) == old.request
    scene = replay.observe(
        frame(5, 5.0),
        (first, row(source, bottom, 0.943)),
        checked=frozenset(original_tracks),
        unchanged=same_pixels,
    )
    assert publish().translations == (old,)
    request = TranslationRequest.from_block(scene.requests[0])
    assert request.source == first.text + source and request != old.request

    # The backend can drop the obsolete request immediately. A later geometry
    # update still moves the old English, with its original exact source attached.
    backend.snapshot.return_value = TranslationSnapshot(TranslationState.READY, pending=1)
    scene = replay.observe(
        frame(6, 8.0),
        (row(first.text, replace(top, x=125), 0.98), row(source, replace(bottom, x=125), 0.941)),
        hidden=frozenset(original_tracks),
    )
    retained = publish()
    assert retained.translations == (old,) and retained.blocks[0].bounds.x == 125
    assert TranslationRequest.from_block(retained.blocks[0]) == old.request
    assert TranslationRequest.from_block(scene.requests[0]) == request
    replacement = TranslatedText(request, "Come with me all the way inside.")
    backend.snapshot.return_value = TranslationSnapshot(TranslationState.READY, (replacement,))
    assert publish().translations == (replacement,)
    scene = replay.observe(frame(7, 10), (first, row("ここが目的地です。", bottom, 0.71)))
    assert publish().translations == (replacement,)


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
