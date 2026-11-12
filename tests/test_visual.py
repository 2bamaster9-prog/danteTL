import threading
import time
from dataclasses import replace

import cv2
import numpy as np
import pytest

from jp_overlay.domain import CapturedFrame, Rect, WindowGeometry
from jp_overlay.recognition import OcrResult, TextRegion
from jp_overlay.tracking import TextTrack, TextTracker, TrackingPolicy
from jp_overlay.visual import VisualAnalyzer, VisualSession, VisualState

BOX = Rect(20, 50, 180, 24)
TEXT = "新しい冒険がここから始まります"


def picture(sequence, *, ink=True, second=False, second_chars=0, brightness=0, animation=False):
    pixels = np.full((240, 400, 4), 30 + brightness, dtype=np.uint8)
    pixels[:, :, 3] = 255
    if animation:
        pixels[:20, :100, :3] = sequence * 7 % 200
    if ink:
        for x in range(22, 190, 15):
            cv2.rectangle(pixels, (x, 53), (x + 9, 70), (230, 230, 230, 255), 2)
            cv2.line(pixels, (x, 62), (x + 9, 62), (230, 230, 230, 255), 2)
    if second or second_chars:
        for x in range(22, 22 + second_chars * 15 if second_chars else 150, 15):
            cv2.rectangle(pixels, (x, 85), (x + 9, 102), (230, 230, 230, 255), 2)
    bounds = Rect(0, 0, 400, 240)
    return CapturedFrame(
        sequence, (sequence - 1) / 8, WindowGeometry(bounds, bounds, bounds, 96), pixels.tobytes()
    )


def reference():
    source = picture(1)
    return OcrResult(source, (TextRegion(TEXT, BOX),), 300, 0.3), TextTrack(1, TEXT, BOX)


def test_diagnostic_changes_are_local_physical_rects_not_requested_ocr_coverage():
    analyzer = VisualAnalyzer()
    initial = analyzer.observe(picture(1))
    assert initial.scan_areas is None and initial.changed_areas == ()
    assert analyzer.observe(picture(2)).changed_areas == ()
    changed = analyzer.observe(picture(3, animation=True))
    assert changed.changed_areas
    assert all(Rect(0, 0, 400, 240).contains(b) for b in changed.changed_areas)
    assert all(b.y < 30 and b.x < 115 for b in changed.changed_areas)
    assert len(changed.changed_areas) <= 32 * 18


def test_idle_frames_skip_inference_but_changes_and_periodic_refreshes_are_not_starved():
    analyzer = VisualAnalyzer()
    requests = [i for i in range(1, 49) if analyzer.observe(picture(i)).request_ocr]
    assert requests[0] == 1
    assert 3 <= len(requests) <= 4, (
        requests
    )  # Startup/follow-up, then a full scan every three seconds.
    assert analyzer.observe(picture(49, ink=False)).request_ocr


def test_missing_strokes_hide_before_ocr_finishes_and_restore_without_forgetting_identity():
    analyzer = VisualAnalyzer()
    result, track = reference()
    analyzer.observe(picture(1), result, (track,), (1,))
    assert not analyzer.observe(picture(2, ink=False), result, (track,), (1,)).hidden
    gone = analyzer.observe(picture(3, ink=False), result, (track,), (1,))
    assert gone.hidden == {track}
    # OCR still has exactly the old source. No negative OCR result is required to mask it.
    assert gone.ocr_sequence == 1
    assert analyzer.observe(picture(4), result, (track,), (1,)).hidden == {track}
    assert not analyzer.observe(picture(5), result, (track,), (1,)).hidden


def test_duplicate_polling_is_not_disappearance_evidence():
    analyzer = VisualAnalyzer()
    result, track = reference()
    analyzer.observe(picture(1), result, (track,), (1,))
    for _ in range(10):
        assert not analyzer.observe(picture(2, ink=False), result, (track,), (1,)).hidden
    assert analyzer.observe(picture(3, ink=False), result, (track,), (1,)).hidden == {track}


def test_brightness_and_outside_animation_do_not_mask_still_present_text():
    analyzer = VisualAnalyzer()
    result, track = reference()
    analyzer.observe(picture(1), result, (track,), (1,))
    for i in range(2, 20):
        current = analyzer.observe(
            picture(i, brightness=20, animation=True), result, (track,), (1,)
        )
        assert not current.hidden
    assert analyzer.observe(picture(20, brightness=20), result, (track,), (1,)).stable_regions == (
        0,
    )


def noisy_picture(sequence, *, ink):
    source = picture(sequence, ink=ink)
    pixels = np.frombuffer(source.bgra, np.uint8).reshape(240, 400, 4).copy()
    noise = np.random.default_rng(sequence).integers(10, 140, (240, 400), dtype=np.uint8)
    background = pixels[:, :, 0] == 30
    for channel in range(3):
        pixels[:, :, channel][background] = noise[background]
    return replace(source, bgra=pixels.tobytes())


def test_textured_background_replacement_hides_but_animation_behind_text_does_not():
    analyzer = VisualAnalyzer()
    result, track = reference()
    result = replace(result, frame=noisy_picture(1, ink=True))
    analyzer.observe(result.frame, result, (track,), (1,))
    for i in range(2, 12):
        state = analyzer.observe(noisy_picture(i, ink=True), result, (track,), (1,))
        assert not state.hidden
        assert not state.blocked  # General background motion is not append-like growth.
    analyzer.observe(noisy_picture(12, ink=False), result, (track,), (1,))
    assert analyzer.observe(noisy_picture(13, ink=False), result, (track,), (1,)).hidden == {track}


def test_hover_color_inversion_preserves_the_same_glyph_shapes():
    analyzer = VisualAnalyzer()
    result, track = reference()
    analyzer.observe(result.frame, result, (track,), (1,))
    for i in range(2, 6):
        source = picture(i)
        pixels = np.frombuffer(source.bgra, np.uint8).reshape(240, 400, 4).copy()
        pixels[:, :, :3] = 255 - pixels[:, :, :3]
        state = analyzer.observe(replace(source, bgra=pixels.tobytes()), result, (track,), (1,))
        assert not state.hidden and not state.blocked


def test_new_continuation_pixels_block_old_partial_reading_before_ocr_knows_about_them():
    analyzer = VisualAnalyzer()
    result, track = reference()
    analyzer.observe(picture(1), result, (track,), (1,))
    growing = analyzer.observe(picture(3, second=True), result, (track,), (1,))
    assert growing.blocked == {1}
    assert growing.stable_regions == ()
    # After the new pixels settle, request a new full OCR rather than waiting for the refresh.
    settled = analyzer.observe(picture(5, second=True), result, (track,), (1,))
    assert settled.request_ocr and settled.blocked == {1}


def test_even_one_new_character_below_the_old_line_blocks_stale_partial_translation():
    analyzer = VisualAnalyzer()
    result, track = reference()
    analyzer.observe(picture(1), result, (track,), (1,))
    for sequence, count in ((3, 1), (4, 2), (5, 3)):
        state = analyzer.observe(picture(sequence, second_chars=count), result, (track,), (1,))
        assert state.blocked == {1}
        assert not state.stable_regions


def test_small_continuation_settling_requests_ocr_without_waiting_for_periodic_refresh():
    analyzer = VisualAnalyzer()
    result, track = reference()
    analyzer.observe(picture(1), result, (track,), (1,))
    assert analyzer.observe(picture(4), result, (track,), (1,)).request_ocr
    assert not analyzer.observe(picture(5, second_chars=1), result, (track,), (1,)).request_ocr
    assert analyzer.observe(picture(7, second_chars=1), result, (track,), (1,)).request_ocr


def test_stable_expanded_pixels_confirm_current_reading_without_a_second_model_pass():
    analyzer, tracker = VisualAnalyzer(), TextTracker()
    result, track = reference()
    tracker.observe(result)
    analyzer.observe(picture(1), result, (track,), (1,))
    latest = picture(3, animation=True)
    state = analyzer.observe(latest, result, (track,), (1,))
    assert state.stable_regions == (0,)
    assert not tracker.translation_tracks(latest, 0.3)
    tracker.confirm_visual(state.ocr_sequence, state.stable_regions, latest.captured_at)
    assert tracker.translation_tracks(latest, 0.3) == (track,)
    newer = OcrResult(picture(4), (TextRegion("違う文章です", BOX),), 100, 0.5)
    tracker.observe(newer)
    tracker.confirm_visual(state.ocr_sequence, state.stable_regions, 1)
    assert tracker.visible(newer.frame, 0.5)[0].text == TEXT


def test_single_unchanged_wgc_frame_can_still_use_normal_static_settling():
    analyzer, tracker = VisualAnalyzer(), TextTracker()
    result, track = reference()
    tracker.observe(result)
    state = analyzer.observe(result.frame, result, (track,), (1,))
    assert not state.blocked  # No new WGC callback is required to release an invented visual wait.
    assert tracker.translation_tracks(result.frame, 0.5) == (track,)


def test_unreliable_pixels_and_revision_changes_cannot_reuse_an_old_occlusion():
    analyzer = VisualAnalyzer()
    result, track = reference()
    analyzer.observe(picture(1), result, (track,), (1,))
    analyzer.observe(picture(2, ink=False), result, (track,), (1,))
    assert analyzer.observe(picture(3, ink=False), result, (track,), (1,)).hidden
    revised = replace(track, text="次の文章", text_revision=2)
    assert not analyzer.observe(picture(4, ink=False), result, (revised,), (1,)).hidden
    invalid = analyzer.observe(replace(picture(5), bgra=b""))
    assert invalid.request_ocr and invalid.message and not invalid.hidden


@pytest.mark.parametrize("fresh", [False, True])
def test_visual_absence_needs_a_fresh_negative_ocr_and_frees_capacity_for_the_new_menu(fresh):
    analyzer, tracker = VisualAnalyzer(), TextTracker(TrackingPolicy(max_tracks=1))
    result, track = reference()
    tracker.observe(result)
    analyzer.observe(picture(1), result, (track,), (1,))
    analyzer.observe(picture(2, ink=False), result, (track,), (1,))
    state = analyzer.observe(picture(3, ink=False), result, (track,), (1,))
    assert state.absent == {track}
    assert tracker.visible(picture(3, ink=False), 0.3) == (track,)
    changed = OcrResult(
        picture(3, ink=False), (TextRegion("次の画面", Rect(250, 150, 90, 24)),), 300, 0.55
    )
    assigned = tracker.observe(
        changed, visually_absent=state.absent, visual_sequence=3 if fresh else 2
    )
    assert assigned == ((2,) if fresh else (None,))


def test_detector_order_does_not_drop_visual_probes_for_existing_tracks():
    analyzer = VisualAnalyzer()
    result, track = reference()
    regions = (TextRegion("label", Rect(250, 5, 50, 15)),) * 300 + result.regions
    result = replace(result, regions=regions)
    assignments = (None,) * 300 + (1,)
    analyzer.observe(picture(1), result, (track,), assignments)
    assert analyzer.observe(picture(3), result, (track,), assignments).stable_regions == (300,)


def test_visual_initialization_failure_falls_back_and_still_finishes_shutdown(monkeypatch):
    calls = []

    def fail():
        calls.append(1)
        raise RuntimeError("Visual initialization unavailable")

    monkeypatch.setattr("jp_overlay.visual.VisualAnalyzer", fail)
    session = VisualSession()
    session.start()
    try:
        session.submit(picture(1), None, (), (), ())
        deadline = time.monotonic() + 3
        while True:
            state = session.poll()
            if state.frame:
                break
            assert time.monotonic() < deadline
            time.sleep(0.005)
        assert state.request_ocr and state.message
        session.submit(picture(2), None, (), (), ())
        while True:
            state = session.poll()
            if state.frame and state.frame.sequence == 2:
                break
            assert time.monotonic() < deadline
            time.sleep(0.005)
        assert calls == [1]  # No repeated native initialization/error-log storm.
    finally:
        session.request_stop()
        deadline = time.monotonic() + 3
        while not session.finished:
            assert time.monotonic() < deadline
            time.sleep(0.005)


def test_worker_coalesces_frames_and_rejects_evidence_after_invalidation(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []

    class Analyzer:
        def observe(self, frame, *args):
            calls.append(frame.sequence)
            if frame.sequence == 1:
                entered.set()
                assert release.wait(3)
            return VisualState(frame, True)

    monkeypatch.setattr("jp_overlay.visual.VisualAnalyzer", Analyzer)
    session = VisualSession()
    session.start()
    try:
        session.submit(picture(1), None, (), (), ())
        assert entered.wait(3)
        for i in range(2, 100):
            session.submit(picture(i), None, (), (), ())
        session.invalidate()
        session.submit(picture(100), None, (), (), ())
        release.set()
        deadline = time.monotonic() + 3
        while True:
            state = session.poll()
            if state.frame and state.frame.sequence == 100:
                break
            assert state.frame is None  # The blocked old generation cannot be published.
            assert time.monotonic() < deadline
            time.sleep(0.005)
        assert calls == [1, 100] and state.request_ocr
        assert not session.poll().request_ocr
    finally:
        release.set()
        session.request_stop()
        deadline = time.monotonic() + 3
        while not session.finished:
            assert time.monotonic() < deadline
            time.sleep(0.005)
