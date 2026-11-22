"""Decide when visual changes warrant regional, follow-up, or full OCR."""

from dataclasses import dataclass, field
from math import ceil

import cv2
import numpy as np

from dantetl.domain import Rect
from dantetl.ocr.discovery import DiscoveryTiles
from dantetl.ocr.regions import padded, scan_regions
from dantetl.ocr.visual_values import SettledScan


@dataclass(slots=True)
class ScanChanges:
    deadline: float
    growing: list[Rect] = field(default_factory=list)
    ready: list[Rect] = field(default_factory=list)
    settling: list[Rect] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ScanDecision:
    request: bool
    areas: tuple[Rect, ...] | None
    settled: SettledScan | None


class ScanCadence:
    def __init__(self) -> None:
        self._last_full = float("-inf")
        self._followup: float | None = None
        self._followup_areas: tuple[Rect, ...] | None = None
        self.avoided = 0

    def decide(
        self,
        tiles: DiscoveryTiles,
        changes: ScanChanges,
        size: tuple[int, int],
        known: tuple[Rect, ...],
        *,
        now: float,
        fresh: bool,
    ) -> ScanDecision:
        due = self._followup is not None and now >= self._followup
        refresh = now - self._last_full >= 3.0
        # Delay only the revealing area, not unrelated newly opened UI. Dirty tiles
        # accumulate until requested so rate limiting never loses a one-frame change.
        eligible = tiles.dirty.copy()
        rows, columns = eligible.shape
        for b in changes.growing:
            x1, y1 = max(0, b.x * columns // size[0]), max(0, b.y * rows // size[1])
            x2, y2 = (
                min(columns, ceil((b.x + b.width) * columns / size[0])),
                min(rows, ceil((b.y + b.height) * rows / size[1])),
            )
            eligible[y1:y2, x1:x2] = False
        count, _, stats, _ = cv2.connectedComponentsWithStats(
            eligible.astype(np.uint8), connectivity=8
        )
        areas = list(changes.ready)
        for x, y, w, h, _ in stats[1:count]:
            left, top = int(x) * size[0] // columns, int(y) * size[1] // rows
            right, bottom = ceil(int(x + w) * size[0] / columns), ceil(int(y + h) * size[1] / rows)
            areas.append(padded(Rect(left, top, right - left, bottom - top), size, 48))
        if due and not changes.growing:
            proposed = None if self._followup_areas is None else (*areas, *self._followup_areas)
        else:
            proposed = tuple(areas)
        coverage = None if refresh else scan_regions(proposed, size, known)
        request = fresh and coverage != ()
        settled_scan = None
        if (
            changes.settling
            and coverage is not None
            and any(not any(area.contains(box) for area in coverage) for box in changes.settling)
        ):
            settled_scan = SettledScan(
                changes.deadline,
                scan_regions((*coverage, *changes.settling), size, known),
            )
        if request:
            first = self._last_full == float("-inf")
            if coverage is None:
                self._last_full = now
            tiles.requested(None if coverage is None else eligible, now)
            self._followup = None if due or (refresh and not first) else now + 0.3
            self._followup_areas = coverage
        elif fresh:
            self.avoided += 1
        return ScanDecision(request, coverage, settled_scan)
