from dataclasses import replace

from jp_overlay.domain import CapturedFrame, Rect, WindowGeometry
from jp_overlay.presence import FrameEvidence
from jp_overlay.recognition import OcrResult, TextRegion
from jp_overlay.tracking import TextTracker

BOX = Rect(10, 10, 80, 20)


def frame(sequence: int, *, ink: bool = True, outside: int = 0) -> CapturedFrame:
    size = Rect(0, 0, 200, 100)
    pixels = bytearray(200 * 100 * 4)
    pixels[:4] = bytes([outside]) * 4
    if ink:
        for y in range(10, 30):
            start = (y * 200 + 10) * 4
            pixels[start : start + 320] = bytes([240, 240, 240, 255, 20, 20, 20, 255]) * 40
    return CapturedFrame(
        sequence, sequence * 0.25, WindowGeometry(size, size, size, 96), bytes(pixels)
    )


def test_equal_crops_ignore_animation_elsewhere_and_budget_is_bounded() -> None:
    signature = FrameEvidence(frame(1)).fingerprint(BOX)
    assert signature is not None
    assert FrameEvidence(frame(2, outside=255)).fingerprint(BOX) == signature
    assert FrameEvidence(frame(3, ink=False)).fingerprint(BOX) != signature
    limited = FrameEvidence(frame(1), pixel_budget=BOX.width * BOX.height)
    assert limited.fingerprint(BOX) == signature
    assert limited.fingerprint(BOX) is None
    assert FrameEvidence(frame(1)).fingerprint(Rect(-1, 0, 30, 30)) is None
    assert FrameEvidence(replace(frame(1), bgra=b"")).fingerprint(BOX) is None


def test_unchanged_text_pixels_survive_repeated_completed_ocr_misses() -> None:
    tracker = TextTracker()
    for sequence in (1, 2):
        source = frame(sequence)
        tracker.observe(OcrResult(source, (TextRegion("設定の確認", BOX),), 20, source.captured_at))
    original = tracker.translation_tracks(source, source.captured_at)
    assert len(original) == 1
    for sequence in range(3, 30):
        source = frame(sequence, outside=sequence)
        tracker.observe(OcrResult(source, (), 20, source.captured_at))
        assert tracker.visible(source, source.captured_at + 10) == original
        assert tracker.translation_tracks(source, source.captured_at + 10) == original
    # Once the crop changes, actual missing observations can retire it.
    for sequence in (30, 31):
        source = frame(sequence, ink=False)
        tracker.observe(OcrResult(source, (), 20, source.captured_at))
        assert tracker.visible(source, source.captured_at) == original
    source = frame(32, ink=False)
    tracker.observe(OcrResult(source, (), 20, source.captured_at))
    assert tracker.visible(source, source.captured_at) == ()


def test_second_frame_with_identical_pixels_can_confirm_initial_content_despite_ocr_miss() -> None:
    tracker = TextTracker()
    first = frame(1)
    tracker.observe(OcrResult(first, (TextRegion("設定の確認", BOX),), 20, first.captured_at))
    assert not tracker.translation_tracks(first, first.captured_at)
    second = frame(2)
    tracker.observe(OcrResult(second, (), 20, second.captured_at))
    assert tracker.translation_tracks(second, second.captured_at)[0].text == "設定の確認"


def test_changed_pixels_and_static_negative_result_settle_after_completion() -> None:
    tracker = TextTracker()
    source = frame(1)
    tracker.observe(OcrResult(source, (TextRegion("設定の確認", BOX),), 20, source.captured_at))
    original = tracker.visible(source, source.captured_at)
    gone = frame(2, ink=False)
    completed = gone.captured_at + 1.1
    tracker.observe(OcrResult(gone, (), 1100, completed))
    assert tracker.visible(gone, completed + 0.2) == original
    assert tracker.visible(gone, completed + 0.36) == ()


def test_changed_background_pixels_do_not_remove_text_that_ocr_still_recognizes() -> None:
    tracker = TextTracker()
    source = frame(1)
    region = TextRegion("設定の確認", BOX)
    tracker.observe(OcrResult(source, (region,), 20, source.captured_at))
    original = tracker.visible(source, source.captured_at)
    changed = frame(2, ink=False)
    tracker.observe(OcrResult(changed, (region,), 20, changed.captured_at))
    assert tracker.visible(changed, 100) == original


def test_static_text_commit_cannot_reuse_pixels_from_the_previous_reading() -> None:
    tracker = TextTracker()
    original = frame(1)
    tracker.observe(OcrResult(original, (TextRegion("猫", BOX),), 20, original.captured_at))
    changed = frame(2, ink=False)
    tracker.observe(OcrResult(changed, (TextRegion("犬", BOX),), 20, changed.captured_at))
    assert tracker.visible(changed, changed.captured_at + 0.4)[0].text == "犬"
    # Returning old pixels must not falsely prove that the newly committed text remains.
    for sequence in (3, 4, 5):
        source = frame(sequence)
        tracker.observe(OcrResult(source, (), 20, source.captured_at))
    assert tracker.visible(source, source.captured_at) == ()


def test_static_geometry_commit_requires_a_reference_for_the_new_crop() -> None:
    tracker = TextTracker()
    first = frame(1)
    tracker.observe(OcrResult(first, (TextRegion("設定", BOX),), 20, first.captured_at))
    second = frame(2)
    wider = replace(BOX, width=120)
    tracker.observe(OcrResult(second, (TextRegion("設定", wider),), 20, second.captured_at))
    assert tracker.visible(second, second.captured_at + 0.4)[0].bounds == wider
    # The old smaller crop cannot certify the entire newly committed geometry.
    for sequence in (3, 4, 5):
        source = frame(sequence)
        tracker.observe(OcrResult(source, (), 20, source.captured_at))
    assert tracker.visible(source, source.captured_at) == ()
