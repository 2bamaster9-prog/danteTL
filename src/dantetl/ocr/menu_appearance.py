"""Exact native-pixel references for a small set of verified menu labels."""

import numpy as np
from numpy.typing import NDArray

from dantetl.domain import Rect
from dantetl.languages.source import SourceLanguage
from dantetl.ocr.regions import padded
from dantetl.ocr.tracking import TextTrack
from dantetl.ocr.values import OcrResult, TextRegion
from dantetl.ocr.visual_values import MenuSample

Pixels = NDArray[np.uint8]


def _patch(pixels: Pixels, b: Rect) -> Pixels:
    return pixels[b.y : b.y + b.height, b.x : b.x + b.width]


class MenuAppearance:
    def __init__(self, language: SourceLanguage) -> None:
        self._labels = language.standalone_menu_labels
        self._samples: dict[MenuSample, Pixels] = {}

    def observe(
        self,
        source: Pixels,
        result: OcrResult,
        tracks: tuple[TextTrack, ...],
        by_id: dict[int, TextRegion],
    ) -> None:
        # A later covered OCR disagreement supersedes that exact reference.
        readings = {(r.text, r.bounds) for r in by_id.values()}
        self._samples = {
            s: ref
            for s, ref in self._samples.items()
            if not result.covers(s.line.bounds)
            or (s.line.text, s.line.bounds) in readings
            or not np.array_equal(_patch(source, s.guard), ref)
        }
        examined = 0
        for line in tracks[:128]:
            region = by_id.get(line.track_id)
            if (
                line.vertical
                or line.text not in self._labels
                or region is None
                or region.text != line.text
                or region.bounds != line.bounds
                or not 0.95 <= (region.confidence or 0) <= 1
            ):
                continue
            b = line.bounds
            guard = padded(b, (source.shape[1], source.shape[0]), max(12, b.height * 2))
            if (
                not guard.contains(b)
                or min(b.size) < 2
                or guard.width * guard.height > 65536
                or not result.covers(guard)
            ):
                continue
            if examined >= 8:
                break
            examined += 1
            patch = _patch(source, guard)
            if any(
                s.line == line and np.array_equal(ref, patch) for s, ref in self._samples.items()
            ):
                continue
            glyphs = _patch(source, b)
            if not np.any(np.ptp(glyphs[:, :, :3], axis=(0, 1)) >= 32):
                continue
            if len(self._samples) >= 8:
                del self._samples[next(iter(self._samples))]
            self._samples[MenuSample(line, result.frame.sequence, guard)] = patch.copy()

    def matching(self, pixels: Pixels) -> tuple[MenuSample, ...]:
        return tuple(
            s for s, ref in self._samples.items() if np.array_equal(_patch(pixels, s.guard), ref)
        )
