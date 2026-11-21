"""Bounded ink and panel measurements from the exact OCR source on the matching worker."""

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from dantetl.domain import CapturedFrame, Rect
from dantetl.languages.selection import DEFAULT_SOURCE
from dantetl.languages.source import SourceLanguage
from dantetl.ocr.values import TextRegion


@dataclass(frozen=True, slots=True)
class PanelEdges:
    left: int
    top: int
    bottom: int

    def agrees(self, other: "PanelEdges", tolerance: float) -> bool:
        return (
            max(
                abs(self.left - other.left),
                abs(self.top - other.top),
                abs(self.bottom - other.bottom),
            )
            <= tolerance
        )


@dataclass(frozen=True, slots=True)
class Lettering:
    ink: tuple[float, float, float]
    inline_accent: bool
    neutral: bool
    panel: PanelEdges | None = None


def _panel_edges(pixels: NDArray[np.uint8], b: Rect) -> PanelEdges | None:
    """Measure a flat panel in the gutter just before the first glyph, away from the ink."""
    height, width = pixels.shape[:2]
    unit = min(128, b.height)
    x, y = b.x - max(3, round(0.3 * unit)), b.y + b.height // 2
    if not (0 < x < width and 0 <= y < height and unit >= 6):
        return None
    surface = pixels[y, x, :3].astype(np.int16)
    left, top, bottom = max(0, x - 2 * unit), max(0, y - 6 * unit), min(height, y + 6 * unit + 1)

    def edge(strip: NDArray[np.uint8]) -> int | None:
        # Require a sustained contrast outside the first edge. A uniform screen or a
        # single stray pixel in the gutter cannot establish an enclosing panel.
        delta = np.abs(strip - surface).max(axis=1)
        outside = np.flatnonzero(delta > 8)
        if not outside.size:
            return None
        index = int(outside[0])
        if index < 2 or index + 3 >= len(delta) or min(delta[index + 1 : index + 4]) < 12:
            return None
        return index

    gutter = edge(pixels[y, left : x + 1, :3][::-1])
    if gutter is None:
        return None
    up = edge(pixels[top : y + 1, x, :3][::-1])
    down = edge(pixels[y:bottom, x, :3])
    if up is None or down is None or up + down < b.height:
        return None
    return PanelEdges(x - gutter + 1, y - up + 1, y + down)


def _runs(crop: NDArray[np.uint8]) -> tuple[bool, bool]:
    import cv2

    h, w = crop.shape[:2]
    count = min(48, max(1, round(w / h)))
    crop = crop[:: max(1, h // 128), :: max(1, w // 2048)]
    strip = cv2.resize(crop, (count * 16, 24), interpolation=cv2.INTER_AREA)
    tiles = strip.reshape(24, count, 16, 3).transpose(1, 0, 2, 3).reshape(count, -1, 3)
    value = tiles.max(axis=2)
    background = np.percentile(value, 25, axis=1)
    strokes = (value >= 155) & (value >= background[:, None] + 65)
    size = strokes.sum(axis=1)
    usable = (size >= 16) & (size <= 0.65 * strokes.shape[1])
    chroma = np.ptp(tiles, axis=2)
    colored = usable & (((chroma >= 62) & strokes).sum(axis=1) >= 0.68 * size)
    gray = usable & (((chroma <= 36) & strokes).sum(axis=1) >= 0.68 * size)
    accent = bool(np.any(colored[1:] & colored[:-1]))
    neutral = bool(np.any(gray[1:] & gray[:-1]))
    return accent and neutral, neutral and not accent


def sample_lettering(
    frame: CapturedFrame,
    rows: list[tuple[int, TextRegion]],
    language: SourceLanguage = DEFAULT_SOURCE,
) -> tuple[tuple[int, Lettering], ...]:
    if len(frame.bgra) != frame.width * frame.height * 4:
        return ()
    pixels = np.frombuffer(frame.bgra, np.uint8).reshape(frame.height, frame.width, 4)
    samples = []
    for index, row in rows:
        b = row.bounds
        if row.vertical or not (
            0 <= b.x < b.x + b.width <= frame.width and 0 <= b.y < b.y + b.height <= frame.height
        ):
            continue
        crop = pixels[b.y : b.y + b.height, b.x : b.x + b.width, :3]
        points = crop[:: max(1, b.height // 18), :: max(1, b.width // 88)].reshape(-1, 3)
        surface = np.median(points, axis=0)
        contrast = np.max(np.abs(points - surface), axis=1)
        ink = np.median(points[contrast >= np.percentile(contrast, 85)], axis=0)
        accent = neutral = False
        if language.sample_effect_lettering(row.text):
            accent, neutral = _runs(crop)
        samples.append(
            (
                index,
                Lettering(
                    (float(ink[0]), float(ink[1]), float(ink[2])),
                    accent,
                    neutral,
                    _panel_edges(pixels, b),
                ),
            )
        )
    return tuple(samples)
