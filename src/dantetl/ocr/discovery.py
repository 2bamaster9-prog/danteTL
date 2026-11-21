"""Bounded change evidence for discovering text away from known OCR boxes."""

from dataclasses import dataclass
from typing import cast

import cv2
import numpy as np
from numpy.typing import NDArray

Mask = NDArray[np.bool_]
Bytes = NDArray[np.uint8]
GRID = (32, 18)
THUMBNAIL = (640, 360)


def _stroke_tiles(current: Bytes, reference: Bytes) -> Mask:
    # Count nearby changes in corner detail in any color channel. A smooth
    # brightness ramp or a straight scrolling edge has little mixed derivative.
    delta = cv2.absdiff(current, reference)
    changed = cv2.bitwise_not(cv2.inRange(delta, (0, 0, 0, 0), (7, 7, 7, 255)))
    clusters = cv2.blur(changed, (3, 3)) >= 80  # At least three nearby pixels.
    return cv2.resize(clusters.view(np.uint8) * 255, GRID, interpolation=cv2.INTER_AREA) > 0


@dataclass(frozen=True, slots=True)
class TileEvidence:
    gray: Bytes
    changed: Mask
    significant: Mask
    strong: Mask


class DiscoveryTiles:
    def __init__(self) -> None:
        self._thumbnail: Bytes | None = None
        self._gray = np.zeros(THUMBNAIL[::-1], np.uint8)
        self._strokes: Bytes | None = None
        self._reference: Bytes | None = None
        self._streak = np.zeros(GRID[::-1], np.uint8)
        self._moving_strokes = np.zeros(GRID[::-1], bool)
        self._accumulated = np.zeros(GRID[::-1], bool)
        self._slow_after = np.full(GRID[::-1], -np.inf)
        self.dirty = np.zeros(GRID[::-1], bool)

    @property
    def thumbnail(self) -> Bytes | None:
        return self._thumbnail

    def observe(self, pixels: Bytes, now: float, *, fresh: bool) -> TileEvidence:
        none = np.zeros(GRID[::-1], bool)
        if not fresh and self._thumbnail is not None:
            # New tracks may need to examine this same immutable source again.
            return TileEvidence(self._gray, ~none, none, none)
        small = cast(Bytes, cv2.resize(pixels, THUMBNAIL, interpolation=cv2.INTER_AREA))
        first = self._thumbnail is None
        changed, significant, strong = (~none if first else none), none, none
        recent = none
        if self._thumbnail is None or not np.array_equal(small, self._thumbnail):
            gray = cast(Bytes, cv2.cvtColor(small, cv2.COLOR_BGRA2GRAY))
            strokes = cast(Bytes, cv2.Sobel(small, -1, 1, 1, ksize=3, scale=0.5, delta=128))
            if self._strokes is not None and self._reference is not None:
                delta = cv2.absdiff(gray, self._gray)
                energy = delta.reshape(18, 20, 32, 20).mean(axis=(1, 3))
                if not np.array_equal(strokes, self._strokes):
                    recent = _stroke_tiles(strokes, self._strokes)
                    self._accumulated = _stroke_tiles(strokes, self._reference)
                changed = (energy > 0) | recent
                significant = energy > 1.5
                strong = energy >= 12
            self._thumbnail, self._gray, self._strokes = small, gray, strokes
        self.dirty |= (significant & (self._streak == 0)) | (~significant & (self._streak >= 2))
        # Accumulate sub-threshold changes against the last requested pixels in
        # this tile. During a fade, leave time for the normal confirmation scan.
        detail = ~self._moving_strokes & (recent | (self._accumulated & (now >= self._slow_after)))
        # Widespread particles can produce hundreds of real corners. Supplemental
        # discovery is for localized edits; preserve ordinary luminance demands
        # and full discovery when detail is scattered around the viewport.
        if np.count_nonzero(recent | self._accumulated) <= 12:
            self.dirty |= detail
        self._moving_strokes = recent
        self._streak = np.where(significant, np.minimum(self._streak + 1, 8), 0).astype(np.uint8)
        return TileEvidence(self._gray, changed, significant, strong)

    def requested(self, tiles: Mask | None, now: float) -> None:
        assert self._strokes is not None
        if tiles is None:
            self._reference = self._strokes.copy()
            self.dirty.fill(False)
            self._accumulated.fill(False)
        else:
            assert self._reference is not None
            mask = cv2.resize(tiles.view(np.uint8), THUMBNAIL, interpolation=cv2.INTER_NEAREST)
            cv2.copyTo(self._strokes, mask, self._reference)
            self.dirty[tiles] = self._accumulated[tiles] = False
            self._slow_after[tiles] = now + 0.3
