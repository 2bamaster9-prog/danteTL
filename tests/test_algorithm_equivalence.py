from dataclasses import replace
from random import Random
from unittest.mock import patch

import cv2
import numpy as np

from dantetl.domain import CapturedFrame, Rect, WindowGeometry
from dantetl.ocr import tracking, visual
from dantetl.ocr.observation import TextTrack
from dantetl.ocr.tracking import TextActivity, TextTracker
from dantetl.ocr.values import OcrResult, TextRegion
from dantetl.translation.grouping import DialogueGrouper


class AllPairs:
    def __init__(self, regions):
        self.regions = tuple(regions)

    def for_bounds(self, bounds):
        return self.regions


def test_spatial_matching_preserves_all_pairs_replay_with_reorder_edits_and_large_boxes():
    random = Random(1134)
    fast, reference = TextTracker(), TextTracker()
    bounds = Rect(0, 0, 3840, 2160)
    regions = tuple(
        TextRegion("会心率" + str(i % 7), Rect(30 + i % 8 * 450, 30 + i // 8 * 160, 260, 32))
        for i in range(96)
    )
    for sequence in range(1, 24):
        rows = [
            replace(
                r,
                text=r.text if sequence % 4 else r.text + "の効果",
                bounds=replace(
                    r.bounds,
                    x=r.bounds.x + random.randrange(-30, 31),
                    y=r.bounds.y + random.randrange(-8, 9),
                ),
            )
            for r in regions
            if random.random() > 0.08
        ]
        # Very different glyph thicknesses, vertical lines, enormous geometry fallback.
        rows += [
            TextRegion("日本語", Rect(100, 1600, 800 if sequence % 2 else 40, 200)),
            TextRegion("縦の文章", Rect(3300, 200, 36, 600), vertical=True),
            TextRegion("広い画面", Rect(-30000, -30000, 60000, 60000)),
        ]
        random.shuffle(rows)
        frame = CapturedFrame(
            sequence, sequence / 4, WindowGeometry(bounds, bounds, bounds, 144), b""
        )
        result = OcrResult(frame, tuple(rows), 800, frame.captured_at + 0.8)
        ids = fast.observe(result)
        with patch.object(tracking, "SpatialCandidates", AllPairs):
            assert ids == reference.observe(result)
        assert fast.advance(frame, result.completed_at) == reference.advance(
            frame, result.completed_at
        )
        if sequence == 12:
            fast.reset()
            reference.reset()


def test_cached_group_layout_matches_rebuilding_across_readiness_growth_moves_and_reset():
    fast, reference = DialogueGrouper(), DialogueGrouper()
    lines = (
        TextTrack(1, "新しい冒険が始まりますが、", Rect(100, 700, 640, 32)),
        TextTrack(2, "その前に準備をしてください。", Rect(100, 744, 540, 32)),
    )
    for step in range(30):
        if step == 8:
            lines = (
                lines[0],
                replace(lines[1], text="明日から旅に出発しましょう。", text_revision=2),
            )
        if step == 16:
            lines = tuple(replace(t, bounds=replace(t.bounds, x=200)) for t in lines)
        if step == 24:
            fast.reset()
            reference.reset()
        confirmed = lines[:1] if step % 7 < 2 else lines
        activity = tuple(TextActivity(t, step / 8, step % 9 == 0, False) for t in lines)
        options = {"enabled": step < 20, "activity": activity}
        reference._layout_key = None  # Reference recomputes adjacency on every tick.
        assert fast.update(lines, confirmed, step / 8, **options) == reference.update(
            lines, confirmed, step / 8, **options
        )


def legacy_ink(reference, current):
    """Frozen scalar cell oracle for retention-policy equivalence, including short last cells."""
    if np.array_equal(reference, current):
        return True
    dark = float(np.median(reference)) > float(np.mean(reference))
    before = visual._ink(reference, dark)
    if before is None or np.count_nonzero(before >= 0.75) < 24:
        return None
    padded = cv2.copyMakeBorder(current, 1, 1, 1, 1, cv2.BORDER_REPLICATE)
    scores = cv2.matchTemplate(padded, reference, cv2.TM_CCOEFF_NORMED)
    y, x = np.unravel_index(np.argmax(np.abs(scores)), scores.shape)
    after = visual._ink(
        padded[y : y + reference.shape[0], x : x + reference.shape[1]],
        dark if scores[y, x] >= 0 else not dark,
    )
    if after is None:
        return False
    step = max(6, reference.shape[0] // 2)
    for start in range(0, reference.shape[1], step):
        a, b = before[:, start : start + step], after[:, start : start + step]
        diff = np.count_nonzero(((a >= 0.75) & (b < 0.55)) | ((b >= 0.75) & (a < 0.55)))
        ink = np.count_nonzero((a >= 0.65) | (b >= 0.65))
        if diff > max(4, ink * 0.12):
            return False
    return True


def test_vectorized_glyph_evidence_matches_scalar_for_polarity_brightness_shift_and_edits():
    visual.VisualAnalyzer()  # Load optional native dependencies at their normal boundary.
    random = np.random.default_rng(147)
    for i in range(300):
        height, width = int(random.integers(5, 49)), int(random.integers(4, 257))
        reference = random.integers(20, 240, (height, width)).astype(np.float32)
        prepared = visual._InkReference.prepare(reference)
        current = reference.copy()
        if i % 5 == 0:
            current = np.clip(current + 15, 0, 255)
        elif i % 5 == 1:
            current = 255 - current
        elif i % 5 == 2:
            current[:, width // 2 :] = random.integers(20, 240, current[:, width // 2 :].shape)
        elif i % 5 == 3:
            current = np.roll(current, 1, axis=1)
        assert visual._same_ink(reference, current, prepared) == legacy_ink(reference, current)
