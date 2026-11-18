import threading
import time
from dataclasses import replace

import cv2
import numpy as np
import pytest

from dantejp.domain import CapturedFrame, Rect, WindowGeometry
from dantejp.ocr.tracking import TextTrack, TextTracker, TrackingPolicy
from dantejp.ocr.visual import VisualAnalyzer, VisualSession, VisualState
from dantejp.ocr.worker import OcrResult, TextRegion

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


def test_missing_strokes_supply_early_corroboration_for_a_covered_ocr_miss():
    analyzer = VisualAnalyzer()
    result, track = reference()
    analyzer.observe(picture(1), result, (track,), (1,))
    assert not analyzer.observe(picture(2, ink=False), result, (track,), (1,)).hidden
    gone = analyzer.observe(picture(3, ink=False), result, (track,), (1,))
    assert gone.hidden == {track}
    assert not gone.cleared
    assert gone.ocr_sequence == 1
    assert analyzer.observe(picture(4), result, (track,), (1,)).hidden == {track}
    assert not analyzer.observe(picture(5), result, (track,), (1,)).hidden


def test_lettering_loss_over_the_same_backing_needs_three_captures_at_eight_fps():
    analyzer = VisualAnalyzer()
    result, track = reference()

    def observe(sequence, **kwargs):
        return analyzer.observe(picture(sequence, **kwargs), result, (track,), (1,))

    observe(1)
    assert not observe(2, ink=False).cleared
    assert not observe(3, ink=False).cleared
    assert not observe(4).cleared
    for sequence in (5, 6):
        assert not observe(sequence, ink=False).cleared
    for _ in range(5):
        assert not observe(6, ink=False).cleared
    assert observe(7, ink=False).cleared == {track}
    assert not observe(8).cleared


@pytest.mark.parametrize("shaded", (False, True))
def test_panel_replacement_hides_on_first_capture_and_restores_on_first_return(shaded):
    analyzer = VisualAnalyzer()
    result, track = reference()
    neighbor = TextTrack(2, "設定", Rect(20, 82, 148, 24))
    result = replace(
        result,
        frame=picture(1, second=True),
        regions=(*result.regions, TextRegion(neighbor.text, neighbor.bounds)),
    )
    tracks = (track, neighbor)
    analyzer.observe(result.frame, result, tracks, (1, 2))
    # Another label remains elsewhere. Only this panel changes color and loses its ink.
    closed = picture(2, ink=False, second=True)
    pixels = np.frombuffer(closed.bgra, np.uint8).reshape(240, 400, 4).copy()
    pixels[40:82, 10:210, :3] = 95
    if shaded:
        pixels[40:82, 10:210, :3] += (np.arange(200, dtype=np.uint8) // 4)[:, None]
    closed = replace(closed, bgra=pixels.tobytes())
    assert analyzer.observe(closed, result, tracks, (1, 2)).cleared == {track}
    assert not analyzer.observe(picture(3, second=True), result, tracks, (1, 2)).cleared


@pytest.mark.parametrize("scene", ["blank_flash", "shifted_ink", "colored_ink"])
def test_large_difference_alone_cannot_hide_on_first_capture(scene):
    analyzer = VisualAnalyzer()
    result, track = reference()
    analyzer.observe(result.frame, result, (track,), (1,))
    changed = picture(2, ink=False, brightness=65, second=scene != "blank_flash")
    pixels = np.frombuffer(changed.bgra, np.uint8).reshape(240, 400, 4).copy()
    if scene == "shifted_ink":
        pixels[75:77, 30:190, :3] = 240  # Just beyond the old bottom edge.
    elif scene == "colored_ink":
        pixels[55:68, 30:190:6, :3] = (0, 162, 0)  # Same gray level as the new backing.
    state = analyzer.observe(replace(changed, bgra=pixels.tobytes()), result, (track,), (1,))
    assert not state.cleared


def test_textured_screen_replacement_hides_on_its_first_capture_and_stays_hidden():
    analyzer = VisualAnalyzer()
    result, track = reference()
    state = analyzer.observe(result.frame, result, (track,), (1,))
    for seq in range(2, 10):
        state = analyzer.observe(noisy_picture(seq, ink=False), result, (track,), (1,))
        assert state.cleared == {track}
    assert state.absent == {track}
    assert not analyzer.observe(picture(10), result, (track,), (1,)).cleared


def test_isolated_textured_replacement_requires_a_second_matching_capture():
    analyzer = VisualAnalyzer()
    result, track = reference()
    analyzer.observe(result.frame, result, (track,), (1,))
    closed = picture(2, ink=False)
    pixels = np.frombuffer(closed.bgra, np.uint8).reshape(240, 400, 4).copy()
    noise = np.random.default_rng(7).integers(30, 150, (24, 180, 1), dtype=np.uint8)
    pixels[50:74, 20:200, :3] = noise
    closed = replace(closed, bgra=pixels.tobytes())
    for _ in range(3):
        assert not analyzer.observe(closed, result, (track,), (1,)).cleared
    assert analyzer.observe(
        replace(closed, sequence=3, captured_at=0.25), result, (track,), (1,)
    ).cleared == {track}


def test_populated_screen_change_keeps_a_surviving_line_with_minor_glyph_and_position_changes():
    analyzer = VisualAnalyzer()
    result, track = reference()
    analyzer.observe(result.frame, result, (track,), (1,))
    updated = noisy_picture(2, ink=True)
    pixels = np.frombuffer(updated.bgra, np.uint8).reshape(240, 400, 4).copy()
    pixels[50:74, 20:200] = np.roll(pixels[50:74, 20:200], 3, axis=1)
    pixels[50:74, 20:38, :3] = 75  # One glyph drops out, the rest slide a few pixels.
    for seq in (2, 3, 4):
        state = analyzer.observe(
            replace(updated, sequence=seq, captured_at=seq / 8, bgra=pixels.tobytes()),
            result,
            (track,),
            (1,),
        )
        assert not state.cleared


def test_delayed_positive_from_before_a_closure_cannot_restore_a_cleared_label():
    analyzer = VisualAnalyzer()
    result, track = reference()
    analyzer.observe(result.frame, result, (track,), (1,))
    for seq in range(3, 7):
        analyzer.observe(picture(seq, ink=False), result, (track,), (1,))
    delayed = replace(result, frame=picture(2))
    assert analyzer.observe(picture(7, ink=False), delayed, (track,), (1,)).cleared == {track}
    # OCR recognizes the original label over a new backdrop, while its old template
    # still disagrees. The exact positive observation supersedes the visual mask.
    restored = replace(result, frame=noisy_picture(8, ink=True))
    assert not analyzer.observe(restored.frame, restored, (track,), (1,)).cleared


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

    monkeypatch.setattr("dantejp.ocr.visual.VisualAnalyzer", fail)
    session = VisualSession()
    session.start()
    try:
        first = OcrResult(picture(1), (TextRegion(TEXT, BOX),), 20, 0.2)
        session.submit(first.frame, None, (), (), (), first)
        deadline = time.monotonic() + 3
        while True:
            state = session.poll()
            if state.frame:
                break
            assert time.monotonic() < deadline
            time.sleep(0.005)
        assert state.request_ocr and state.message
        assert state.matching and state.matching.matches(first, ())
        assert state.pixel_evidence and state.pixel_evidence.matches(first.frame)
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

    monkeypatch.setattr("dantejp.ocr.visual.VisualAnalyzer", Analyzer)
    notified = []

    def notification():
        # A snapshot read must not deadlock: callbacks run after publication/unlock.
        with session._condition:
            if session._snapshot.frame:
                notified.append(session._snapshot.frame.sequence)

    session = VisualSession(on_change=notification)
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
        while not notified:
            assert time.monotonic() < deadline
            time.sleep(0.005)
        assert notified == [100]
        assert not session.poll().request_ocr
    finally:
        release.set()
        session.request_stop()
        deadline = time.monotonic() + 3
        while not session.finished:
            assert time.monotonic() < deadline
            time.sleep(0.005)
