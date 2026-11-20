"""Bounded broad-phase OCR candidates. Exact matching remains the tracker's policy."""

from dantetl.domain import Rect
from dantetl.ocr.values import TextRegion


def _cells(bounds: Rect) -> tuple[tuple[int, int], ...] | None:
    # Match distance uses the larger glyph thickness, so expand BOTH rectangles.
    radius = max(24, min(bounds.size) * 3)
    left, top = (bounds.x - radius) // 128, (bounds.y - radius) // 128
    right = (bounds.x + bounds.width + radius) // 128
    bottom = (bounds.y + bounds.height + radius) // 128
    if (right - left + 1) * (bottom - top + 1) > 256:
        return None  # Oversized geometry must not allocate a screen-sized index.
    return tuple((x, y) for y in range(top, bottom + 1) for x in range(left, right + 1))


class SpatialCandidates:
    """One observation's index; large boxes safely use all-pairs matching."""

    def __init__(self, regions: list[tuple[int, TextRegion]]) -> None:
        self._regions = dict(regions)
        self._grid: dict[tuple[int, int], list[int]] = {}
        self._wide: set[int] = set()
        for index, region in regions:
            cells = _cells(region.bounds)
            if cells is None:
                self._wide.add(index)
            else:
                for cell in cells:
                    self._grid.setdefault(cell, []).append(index)

    def for_bounds(self, bounds: Rect) -> tuple[tuple[int, TextRegion], ...]:
        cells = _cells(bounds)
        if cells is None:
            return tuple(self._regions.items())
        indices = self._wide.copy()
        for cell in cells:
            indices.update(self._grid.get(cell, ()))
        return tuple((index, self._regions[index]) for index in sorted(indices))
