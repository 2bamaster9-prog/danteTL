from dataclasses import replace

import numpy as np
import pytest

from jp_overlay.crop_recovery import recovery_preserves_lines, split_glyphs
from jp_overlay.domain import CapturedFrame, Rect, WindowGeometry
from jp_overlay.meiki import MeikiRecognizer, convert_regions
from jp_overlay.ocr_runtime import CPU
from jp_overlay.recognition import TextCharacter, TextRegion


def row(text, bounds, confidence):
    return TextRegion(text, bounds, (TextCharacter(text, bounds, confidence),))


def severed():
    image = np.full((100, 195, 3), 245, np.uint8)
    image[20:42, 20:25] = 30
    image[20:42, 45:50] = 30
    rows = (row("上半分", Rect(10, 20, 60, 10), 0.55), row("下半分", Rect(10, 29, 60, 13), 0.60))
    return image, rows


@pytest.mark.parametrize("invert", [False, True])
def test_recovery_needs_connected_ink_across_a_weak_split_not_just_adjacent_lines(invert):
    image, rows = severed()
    if invert:
        image = 255 - image
    assert split_glyphs(image, rows) == ((0, 1),)
    image[29:31] = image[0, 0]
    assert split_glyphs(image, rows) == ()


def test_unknown_strong_vertical_ambiguous_and_unbounded_evidence_never_triggers():
    image, rows = severed()
    assert not split_glyphs(image, (rows[0],))
    assert not split_glyphs(image, tuple(replace(r, characters=()) for r in rows))
    assert not split_glyphs(image, tuple(row(r.text, r.bounds, 0.92) for r in rows))
    assert not split_glyphs(image, tuple(replace(r, vertical=True) for r in rows))
    assert not split_glyphs(image, (*rows, row("三", Rect(10, 41, 60, 10), 0.6)))
    assert not split_glyphs(image, rows * 33)
    assert not split_glyphs(np.full_like(image, 245), rows)


def test_recovery_must_improve_the_whole_line_and_preserve_unrelated_raw_content():
    _, rows = severed()
    other = row("別の行", Rect(100, 60, 50, 20), 0.96)
    original = (*rows, other)
    complete = row("設定", Rect(10, 20, 60, 22), 0.95)
    candidate = (other, complete)
    assert recovery_preserves_lines(original, candidate, ((0, 1),))
    assert not recovery_preserves_lines(original, (complete,), ((0, 1),))
    assert not recovery_preserves_lines(
        original, (complete, replace(other, text="別の誤り")), ((0, 1),)
    )
    assert not recovery_preserves_lines(original, (*candidate, complete), ((0, 1),))
    assert not recovery_preserves_lines(
        original, (other, row("設定", complete.bounds, 0.85)), ((0, 1),)
    )
    assert not recovery_preserves_lines(
        original, (other, replace(complete, vertical=True)), ((0, 1),)
    )
    assert not recovery_preserves_lines(
        original, (other, row("半分", rows[0].bounds, 0.99)), ((0, 1),)
    )


def test_centered_padding_maps_line_and_character_coordinates_before_clipping():
    rows = convert_regions(
        [{"bbox": [392, 187, 442, 209]}, {"bbox": [0, 0, 10, 10]}],
        [
            {
                "text": "設定",
                "chars": [{"char": "設", "bbox": [394, 189, 420, 210], "conf": 0.95}],
                "is_vertical": False,
            },
            {"text": "padding", "chars": [], "is_vertical": False},
        ],
        195,
        210,
        origin=(382, 167),
    )
    assert len(rows) == 1
    assert rows[0].bounds == Rect(10, 20, 50, 22)
    assert rows[0].characters[0].bounds == Rect(12, 22, 26, 21)


@pytest.mark.parametrize("accepted", [False, True])
@pytest.mark.parametrize("empty_first", [False, True])
def test_empty_retry_can_recover_severed_glyphs_once_without_rescaling_source_pixels(
    tmp_path, monkeypatch, accepted, empty_first
):
    image, halves = severed()
    seen = []
    monkeypatch.setattr("jp_overlay.meiki.local_model_paths", lambda _: ())

    class Engine:
        active_provider = CPU

        def __init__(self, *args):
            self.detected = []

        def run_ocr(self, bgr, **kwargs):
            seen.append(bgr)
            if empty_first and len(seen) == 1:
                return []
            if len(seen) == 1 + empty_first:
                rows, origin = halves, (0, 0)
            else:
                rows = (row("設定", Rect(10, 20, 60, 22), 0.95 if accepted else 0.65),)
                origin = (382, 222)
                assert np.array_equal(bgr[222:322, 382:577], image)
            boxes = [
                [
                    r.bounds.x + origin[0],
                    r.bounds.y + origin[1],
                    r.bounds.x + r.bounds.width + origin[0],
                    r.bounds.y + r.bounds.height + origin[1],
                ]
                for r in rows
            ]
            self.detected = [{"bbox": b} for b in boxes]
            return [
                {
                    "text": r.text,
                    "is_vertical": r.vertical,
                    "chars": [{"char": r.text, "bbox": b, "conf": r.confidence}],
                }
                for r, b in zip(rows, boxes, strict=True)
            ]

    monkeypatch.setattr("jp_overlay.meiki._LocalMeiki", Engine)
    bounds = Rect(0, 0, 195, 100)
    rgba = np.full((100, 195, 4), 255, np.uint8)
    rgba[:, :, :3] = image
    frame = CapturedFrame(8, 2.4, WindowGeometry(bounds, bounds, bounds, 168), rgba.tobytes())
    engine = MeikiRecognizer(tmp_path)
    result = engine.recognize(frame, cropped=True)
    assert len(seen) == 2 + empty_first
    assert result == (row("設定", Rect(10, 20, 60, 22), 0.95),) if accepted else result == halves
    assert seen[0].shape == (100, 195, 3)
    assert all(image.shape == (544, 960, 3) for image in seen[1:])
    assert np.array_equal(seen[0], image)
    engine.close()
