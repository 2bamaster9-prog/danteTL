import threading
import time
from dataclasses import replace

from jp_overlay.domain import CapturedFrame, Rect, WindowGeometry
from jp_overlay.grouping import DialogueGrouper, TextBlock
from jp_overlay.recognition import OcrResult, TextCharacter, TextRegion
from jp_overlay.tracking import TextTrack, TextTracker
from jp_overlay.translation import TranslationRequest, TranslationSession, TranslationState


def track(text="日本語", revision=1, key=1) -> TextTrack:
    return TextTrack(key, text, Rect(100, 100, 200, 40), text_revision=revision)


def until(predicate) -> None:
    deadline = time.monotonic() + 4
    while not predicate():
        assert time.monotonic() < deadline, "Translation worker did not reach expected state"
        time.sleep(0.005)


class Backend:
    def __init__(self, identity="fake-v1") -> None:
        self.cache_identity = identity
        self.calls: list[tuple[str, ...]] = []
        self.closed = False
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def translate(self, texts: tuple[str, ...]) -> tuple[str, ...]:
        self.calls.append(texts)
        self.entered.set()
        assert self.release.wait(3)
        return tuple(f"{self.cache_identity}: {text}" for text in texts)

    def close(self) -> None:
        self.closed = True


def stop(session: TranslationSession) -> None:
    session.request_stop()
    until(lambda: session.finished)


def test_unchanged_text_movement_and_duplicate_regions_translate_once(tmp_path) -> None:
    backend = Backend()
    session = TranslationSession(lambda: backend, tmp_path / "cache.sqlite3")
    session.start()
    try:
        session.update((track(), track(key=2), track("English", key=3)))
        until(lambda: len(session.snapshot().results) == 2)
        assert backend.calls == [("日本語",)]
        moved = replace(track(), bounds=Rect(300, 300, 200, 40))
        session.update((moved, track(key=2)))
        assert session.snapshot().pending == 0
        assert len(backend.calls) == 1
    finally:
        stop(session)
    assert backend.closed


def test_noisy_readings_do_not_clear_english_or_trigger_more_translation(tmp_path) -> None:
    backend = Backend()
    session = TranslationSession(lambda: backend, tmp_path / "cache.sqlite3")
    tracker = TextTracker()
    sequence = 0

    def observe(text: str, confidence: float, bounds: Rect) -> None:
        nonlocal sequence
        sequence += 1
        now = sequence * 0.25
        viewport = Rect(0, 0, 1280, 720)
        frame = CapturedFrame(sequence, now, WindowGeometry(viewport, viewport, viewport, 96), b"")
        characters = tuple(TextCharacter(char, bounds, confidence) for char in text)
        region = TextRegion(text, bounds, characters)
        tracker.observe(OcrResult(frame, (region,), 20, now + 0.02))
        session.update(tracker.translation_tracks(frame, now + 0.02))

    session.start()
    try:
        observe("ポーションを使う", 0.95, Rect(100, 100, 200, 40))
        observe("ポーションを使う", 0.9, Rect(100, 100, 200, 40))
        until(lambda: len(session.snapshot().results) == 1)
        translated = session.snapshot().results
        for _ in range(10):
            for _ in range(3):
                observe("ボーションを使う", 0.7, Rect(80, 100, 220, 40))
                assert session.snapshot().results == translated
                assert session.snapshot().pending == 0
            observe("ポーションを使う", 0.8, Rect(100, 100, 200, 40))
    finally:
        stop(session)
    assert backend.calls == [("ポーションを使う",)]


def test_dialogue_translates_as_one_request_and_rejects_a_late_changed_member(tmp_path) -> None:
    backend = Backend()
    backend.release.clear()
    session = TranslationSession(lambda: backend, tmp_path / "cache.sqlite3")
    first = TextTrack(1, "新しい冒険が始まりますが、", Rect(100, 100, 400, 32))
    second = TextTrack(2, "その前に準備をしてください。", Rect(100, 144, 400, 32))
    grouper = DialogueGrouper()
    session.start()
    try:
        pending = grouper.update((first, second), (first,), 0)
        session.update(pending.ready)
        assert session.snapshot().pending == 0
        ready = grouper.update((first, second), (first, second), 0.4)
        session.update(ready.ready)
        assert backend.entered.wait(3)
        assert backend.calls == [(first.text + second.text,)]
        changed = replace(second, text="準備ができたら出発しましょう。", text_revision=2)
        new_block = TextBlock((first, changed))
        session.update((new_block,))
        backend.release.set()
        until(lambda: len(session.snapshot().results) == 1)
        result = session.snapshot().results[0]
        assert result.request == TranslationRequest.from_block(new_block)
        assert backend.calls == [(first.text + second.text,), (first.text + changed.text,)]
        moved = TextBlock(
            tuple(replace(t, bounds=replace(t.bounds, x=200)) for t in new_block.lines)
        )
        session.update((moved,))
        assert session.snapshot().results == (result,)
        assert session.snapshot().pending == 0
        # Splitting a group also rejects its reply even though its anchor line still exists.
        session.update((first,))
        assert session.snapshot().results == ()
        until(lambda: len(session.snapshot().results) == 1)
        assert session.snapshot().results[0].request == TranslationRequest.from_track(first)
    finally:
        backend.release.set()
        stop(session)


def test_revision_change_and_removed_tracks_reject_inflight_translation(tmp_path) -> None:
    backend = Backend()
    backend.release.clear()
    session = TranslationSession(lambda: backend, tmp_path / "cache.sqlite3")
    session.start()
    try:
        session.update((track("古い文章"), track("消えた文章", key=2)))
        assert backend.entered.wait(3)
        session.update((track("新しい文章", revision=2),))
        assert session.snapshot().results == ()
        backend.release.set()
        until(lambda: len(session.snapshot().results) == 1)
        result = session.snapshot().results[0]
        assert result.request == TranslationRequest.from_track(track("新しい文章", revision=2))
        assert result.english.endswith("新しい文章")
        session.update(())
        assert session.snapshot().results == ()
    finally:
        backend.release.set()
        stop(session)


def test_invalidation_prevents_same_key_from_accepting_old_generation(tmp_path) -> None:
    backend = Backend()
    backend.release.clear()
    session = TranslationSession(lambda: backend, tmp_path / "cache.sqlite3")
    session.start()
    try:
        session.update((track(),))
        assert backend.entered.wait(3)
        session.invalidate()
        backend.release.set()
        # Stop waits for in-flight work; an invalidated result must not survive cleanup.
        stop(session)
        assert session.snapshot().results == ()
    finally:
        backend.release.set()
        stop(session)


def test_backend_swap_closes_old_before_loading_new_and_uses_separate_cache(tmp_path) -> None:
    old = Backend("old")
    old.release.clear()
    new = Backend("new")
    loaded = threading.Event()

    def load_new():
        assert old.closed
        loaded.set()
        return new

    session = TranslationSession(lambda: old, tmp_path / "cache.sqlite3")
    session.start()
    try:
        session.update((track(),))
        assert old.entered.wait(3)
        session.switch_backend(load_new)
        assert not loaded.is_set()
        assert session.snapshot().results == ()
        old.release.set()
        until(lambda: len(session.snapshot().results) == 1)
        assert session.snapshot().results[0].english.startswith("new:")
        assert new.calls == [("日本語",)]
    finally:
        old.release.set()
        stop(session)
    assert new.closed


def test_cache_reuses_text_after_session_restart_and_track_id_changes(tmp_path) -> None:
    path = tmp_path / "cache.sqlite3"
    for key in (1, 99):
        backend = Backend()
        session = TranslationSession(lambda current=backend: current, path)
        session.start()
        try:
            session.update((track(key=key),))
            until(lambda current=session: len(current.snapshot().results) == 1)
            assert session.snapshot().results[0].request.track_id == key
            assert len(backend.calls) == (1 if key == 1 else 0)
        finally:
            stop(session)


def test_shutdown_is_nonblocking_and_rejects_late_output(tmp_path) -> None:
    backend = Backend()
    backend.release.clear()
    session = TranslationSession(lambda: backend, tmp_path / "cache.sqlite3")
    session.start()
    session.update((track(),))
    assert backend.entered.wait(3)
    session.request_stop()
    assert not session.finished
    assert session.snapshot().state == TranslationState.STOPPING
    backend.release.set()
    until(lambda: session.finished)
    assert backend.closed
    assert session.snapshot().results == ()


def test_load_failure_is_visible_and_capture_can_continue_independently(tmp_path) -> None:
    def fail():
        raise RuntimeError("Missing model")

    session = TranslationSession(fail, tmp_path / "cache.sqlite3")
    session.start()
    until(lambda: session.finished)
    stop(session)
    assert session.snapshot().state == TranslationState.FAILED
    assert session.snapshot().message == "Missing model"


def test_desired_work_and_batch_size_are_bounded(tmp_path) -> None:
    backend = Backend()
    backend.release.clear()
    session = TranslationSession(lambda: backend, tmp_path / "cache.sqlite3")
    session.start()
    try:
        session.update(tuple(track(f"日本語{i}", key=i) for i in range(200)))
        assert backend.entered.wait(3)
        assert session.snapshot().pending == 128
        assert len(backend.calls[0]) <= 4
        session.update((track("最新の文章", key=500),))
        backend.release.set()
        until(lambda: len(session.snapshot().results) == 1)
        assert backend.calls[-1] == ("最新の文章",)
        assert len(backend.calls) == 2
    finally:
        backend.release.set()
        stop(session)
