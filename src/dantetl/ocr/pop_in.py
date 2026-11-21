"""Conservative evidence for an isolated sentence arriving in one capture."""

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from dantetl.domain import Rect
from dantetl.ocr.regions import padded

Pixels = NDArray[np.uint8]


@dataclass(slots=True)
class SentenceAppearance:
    bounds: Rect
    reference: Pixels

    def matches(self, pixels: Pixels) -> bool:
        b = self.bounds
        return bool(
            np.array_equal(self.reference, pixels[b.y : b.y + b.height, b.x : b.x + b.width])
        )

    @classmethod
    def from_transition(
        cls, before: Pixels, source: Pixels, line: Rect
    ) -> "SentenceAppearance | None":
        h, w = source.shape[:2]
        guard = padded(line, (w, h), 2 * line.height)
        if (
            not guard.contains(line)
            or guard.width * guard.height > 131072
            or line.width < 12
            or line.height < 2
        ):
            return None
        # The previous capture must show a blank panel throughout the line and its
        # continuation. A typewriter suffix cannot establish a whole-line arrival.
        sh, sw = before.shape[:2]
        previous = before[
            guard.y * sh // h : ((guard.y + guard.height) * sh + h - 1) // h,
            guard.x * sw // w : ((guard.x + guard.width) * sw + w - 1) // w,
        ]
        if not previous.size or np.any(np.ptp(previous[:, :, :3], axis=(0, 1)) > 8):
            return None
        panel = source[guard.y : guard.y + guard.height, guard.x : guard.x + guard.width]
        x, y = line.x - guard.x, line.y - guard.y
        end, bottom = x + line.width, y + line.height
        # Glyph antialiasing can extend a couple of native pixels outside the
        # recognizer's character boxes. The exact follow-up check includes them.
        fringe = padded(line, (w, h), 2)
        left, top = fringe.x - guard.x, fringe.y - guard.y
        right, foot = left + fringe.width, top + fringe.height
        # Existing text above, beside or below can belong to the same utterance.
        for strip in (panel[:top], panel[foot:], panel[top:foot, :left], panel[top:foot, right:]):
            if strip.size and np.any(np.ptp(strip[:, :, :3], axis=(0, 1)) > 8):
                return None
        ink = panel[y:bottom, x:end, :3]
        if any(
            not np.any(np.ptp(part, axis=(0, 1)) >= 48) for part in np.array_split(ink, 3, axis=1)
        ):
            return None
        return cls(guard, panel.copy())
