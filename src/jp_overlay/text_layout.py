"""Deterministic English layout in physical pixels, bounded to the client viewport."""

from dataclasses import dataclass, replace
from functools import lru_cache

from PySide6.QtGui import QFont, QFontMetricsF

from jp_overlay.domain import Rect


@dataclass(frozen=True, slots=True)
class EnglishLayout:
    bounds: Rect
    pixel_size: int
    line_height: int
    ascent: float
    lines: tuple[str, ...]
    truncated: bool


def _wrap(text: str, metrics: QFontMetricsF, width: int) -> tuple[str, ...]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}" if current else word
        if metrics.horizontalAdvance(candidate) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        for char in word:
            if current and metrics.horizontalAdvance(current + char) > width:
                lines.append(current)
                current = ""
            current += char
    if current:
        lines.append(current)
    return tuple(lines)


def layout_english(
    text: str,
    source: Rect,
    viewport: tuple[int, int],
    *,
    automatic: bool = True,
    manual_pixels: int = 20,
    vertical: bool = False,
    source_line_height: int | None = None,
    wrap_width: int | None = None,
) -> EnglishLayout:
    # Moving a source must not repeat font measurement/wrapping. Geometry-dependent
    # placement is separate from the bounded cache of text/size measurements.
    measured = _measure_english(
        text,
        Rect(0, 0, *source.size),
        viewport,
        automatic=automatic,
        manual_pixels=manual_pixels,
        vertical=vertical,
        source_line_height=source_line_height,
        wrap_width=wrap_width,
    )
    box = measured.bounds
    return replace(
        measured,
        bounds=Rect(
            max(0, min(source.x, viewport[0] - box.width)),
            max(0, min(source.y, viewport[1] - box.height)),
            box.width,
            box.height,
        ),
    )


@lru_cache(maxsize=512)
def _measure_english(
    text: str,
    source: Rect,
    viewport: tuple[int, int],
    *,
    automatic: bool,
    manual_pixels: int,
    vertical: bool,
    source_line_height: int | None,
    wrap_width: int | None,
) -> EnglishLayout:
    view_width, view_height = viewport
    if min(viewport) <= 0:
        raise ValueError("English layout needs a nonempty viewport.")
    padding = 4
    glyph_height = source_line_height or (source.width if vertical else source.height)
    preferred = max(12, min(48, round(glyph_height * 0.72))) if automatic else manual_pixels
    preferred = max(10, min(60, preferred))
    floor = max(12, round(preferred * 0.75)) if automatic else preferred
    floor = min(preferred, floor)
    width = min(view_width, max(40, wrap_width or (source.width if not vertical else 240)))
    font = QFont("Segoe UI")
    lines: tuple[str, ...] = ()
    pixels = preferred
    while True:
        font.setPixelSize(pixels)
        metrics = QFontMetricsF(font)
        line_height = max(1, round(metrics.lineSpacing()))
        lines = _wrap(text, metrics, max(1, width - padding * 2))
        if len(lines) * line_height + padding * 2 <= source.height:
            break
        if pixels == floor:
            # A limited width expansion preserves readability for longer English.
            if wrap_width is None:
                width = min(view_width, max(width, round(width * 1.5)))
            lines = _wrap(text, metrics, max(1, width - padding * 2))
            break
        pixels -= 1
    max_height = min(view_height, max(source.height, line_height * 4 + padding * 2))
    line_count = max(1, (max_height - padding * 2) // line_height)
    truncated = len(lines) > line_count
    lines = lines[:line_count]
    if truncated and lines:
        tail = lines[-1]
        while tail and metrics.horizontalAdvance(tail + "…") > width - padding * 2:
            tail = tail[:-1]
        lines = (*lines[:-1], tail + "…")
    height = min(view_height, max(source.height, len(lines) * line_height + padding * 2))
    x = max(0, min(source.x, view_width - width))
    y = max(0, min(source.y, view_height - height))
    return EnglishLayout(
        Rect(x, y, width, height), pixels, line_height, metrics.ascent(), lines, truncated
    )
