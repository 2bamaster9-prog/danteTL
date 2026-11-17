"""Small color summaries from the exact OCR observation, computed on the matching worker."""

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from dantejp.domain import CapturedFrame
from dantejp.ocr.values import TextRegion


@dataclass(frozen=True, slots=True)
class Lettering:
    ink: tuple[float, float, float]
    inline_accent: bool
    neutral: bool


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
    frame: CapturedFrame, rows: list[tuple[int, TextRegion]]
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
        if row.text.rstrip().endswith("。") and "を" in row.text:
            accent, neutral = _runs(crop)
        samples.append(
            (index, Lettering((float(ink[0]), float(ink[1]), float(ink[2])), accent, neutral))
        )
    return tuple(samples)
