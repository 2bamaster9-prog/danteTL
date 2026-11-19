"""Local pixel evidence for a dash omitted immediately before an opening bracket."""

from collections.abc import Sequence
from statistics import median

import numpy as np
from numpy.typing import NDArray

from dantejp.domain import CapturedFrame, Rect
from dantejp.languages.selection import DEFAULT_SOURCE
from dantejp.languages.source import SourceLanguage
from dantejp.ocr.values import TextRegion


def _margins(bounds: Rect, neighbours: Sequence[Rect]) -> list[int]:
    h = bounds.height
    starts = sorted(
        other.x
        for other in neighbours
        if 0.7 * h < abs(other.y - bounds.y) < 4.8 * h
        and 0.75 * h < other.height < 1.35 * h
        and other.width >= 4 * h
        and bounds.x - 5 * h < other.x < bounds.x - 0.4 * h
    )
    return [
        x
        for i, x in enumerate(starts)
        if (i > 0 and x - starts[i - 1] < 0.5 * h)
        or (i + 1 < len(starts) and starts[i + 1] - x < 0.5 * h)
    ]


def _dash_length(sample: NDArray[np.uint8], strip: NDArray[np.uint8], gap: float) -> int:
    import cv2

    h, width = strip.shape[:2]
    light = sample.max(axis=2)
    bright = sample[light >= max(110, float(np.percentile(light, 90)))]
    if len(bright) < 6:
        return 0
    color = np.median(bright, axis=0)
    mask = (np.max(np.abs(strip - color), axis=2) < 62).astype(np.uint8)
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    pieces = sorted(
        (
            (int(x), int(x + w), y + height / 2)
            for x, y, w, height, area in stats[1:]
            if w >= max(h * 0.26, 3 * height)
            and height <= h * 0.18
            and 0.28 * h <= y + height / 2 <= 0.72 * h
            and area >= w * 0.65
        ),
        reverse=True,
    )
    start = width
    for x, end, center in pieces:
        if start - end > gap or abs(center - pieces[0][2]) > h * 0.12:
            break
        start = x
    return width - start


def opening_dash_edges(
    frame: CapturedFrame,
    raw: tuple[TextRegion, ...],
    rows: Sequence[tuple[int, TextRegion]],
    prior_bounds: Sequence[Rect],
    language: SourceLanguage = DEFAULT_SOURCE,
) -> dict[int, int]:
    """Return source-image left edges, indexed by raw detection. Never synthesize OCR."""
    quotes = language.dash_quotes
    if quotes is None or len(frame.bgra) != frame.width * frame.height * 4:
        return {}
    pixels = np.frombuffer(frame.bgra, np.uint8).reshape(frame.height, frame.width, 4)
    edges: dict[int, int] = {}
    budget = 262_144  # Sample and prefix strips combined, per observation.
    neighbours = [r.bounds for _, r in rows if not r.vertical]
    for index, row in rows:
        b = row.bounds
        h = b.height
        if (
            row.vertical
            or not quotes.missing_dash_candidate(row.text)
            or not language.contains_text(row.text)
            or not 6 <= h <= 128
            or b.x <= 0
            or b.y < 0
            or b.x + b.width > frame.width
            or b.y + h > frame.height
        ):
            continue
        origins = _margins(b, neighbours)
        detector = raw[index].bounds.x
        if b.x - 5 * h <= detector < b.x - 0.4 * h:
            origins.append(detector)
        if not origins and prior_bounds:
            # An isolated regional scan can still examine this exact frame at the
            # established column margin. Prior geometry supplies no ink evidence.
            origins = _margins(b, prior_bounds)
        if not origins:
            continue
        left = max(0, int(median(origins) - 0.2 * h))
        width = min(b.width, 4 * h)
        cost = (b.x - left + width) * h
        if cost > budget:
            continue
        budget -= cost
        sample = pixels[b.y : b.y + h, b.x : b.x + width, :3]
        strip = pixels[b.y : b.y + h, left : b.x, :3]
        gap = h if abs(detector - left) <= 0.5 * h else h * 0.55
        edge = b.x - _dash_length(sample, strip, gap)
        if b.x - edge >= h * 0.65 and min(abs(edge - origin) for origin in origins) <= h * 0.8:
            edges[index] = edge
    return edges
