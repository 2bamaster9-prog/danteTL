"""A recognition-only retry for an isolated edit inside a previously detected line."""

from __future__ import annotations

import logging
from itertools import pairwise
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from dantetl.domain import CapturedFrame, Rect
from dantetl.ocr.regions import intersects, padded
from dantetl.ocr.values import OcrResult, TextRegion

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


@runtime_checkable
class LineReader(Protocol):
    def read_line(self, bgr: np.ndarray) -> TextRegion | None: ...


def _character_cells(row: TextRegion) -> tuple[Rect, ...]:
    if row.characters:
        if (
            len(row.characters) != len(row.text)
            or "".join(c.text for c in row.characters) != row.text
        ):
            return ()
        return tuple(c.bounds for c in row.characters)
    # Without character boxes, only a localized substitution in a numeric field
    # is eligible. The freshly read digit must agree with the changed position.
    if not row.text.isdecimal():
        return ()
    b = row.bounds
    edges = [b.x + round(i * b.width / len(row.text)) for i in range(len(row.text) + 1)]
    return tuple(Rect(left, b.y, right - left, b.height) for left, right in pairwise(edges))


def reread_line(
    reader: LineReader, frame: CapturedFrame, previous: OcrResult, area: Rect
) -> tuple[TextRegion, Rect] | None:
    """Return only the pixels actually read. Any ambiguity uses ordinary detection."""
    import cv2
    import numpy as np

    size = frame.geometry.client.size
    if (
        previous.frame.sequence >= frame.sequence
        or previous.frame.geometry.client.size != size
        or previous.frame.geometry.dpi != frame.geometry.dpi
        or len(previous.frame.bgra) != frame.width * frame.height * 4
        or len(frame.bgra) != frame.width * frame.height * 4
        or not previous.covers(area)
        or area.width * area.height > 131_072
        or len(previous.regions) > 512
    ):
        return None
    rows = [r for r in previous.regions if intersects(area, r.bounds)]
    if len(rows) != 1:
        return None
    old = rows[0]
    if (
        old.vertical
        or not 1 <= len(old.text) <= 32
        or (old.confidence or 0) < 0.85
        or not 10 <= old.bounds.height <= 96
        or old.bounds.width > 768
    ):
        return None
    cells = _character_cells(old)
    if not cells:
        return None

    sample = padded(old.bounds, size, 2)
    collar = padded(sample, size, 4)
    if not area.contains(collar) or collar.size != (old.bounds.width + 12, old.bounds.height + 12):
        return None

    def pixels(source: CapturedFrame, box: Rect) -> NDArray[np.uint8]:
        image = np.frombuffer(source.bgra, np.uint8).reshape(source.height, source.width, 4)
        return image[box.y : box.y + box.height, box.x : box.x + box.width]

    changed = np.any(pixels(previous.frame, area) != pixels(frame, area), axis=2)
    x, y, w, h = cv2.boundingRect(changed.view(np.uint8))
    change = Rect(area.x + x, area.y + y, w, h)
    if not w or not padded(old.bounds, size, 1).contains(change):
        return None
    indices = [i for i, cell in enumerate(cells) if padded(cell, size, 3).contains(change)]
    if len(indices) != 1:
        return None
    index = indices[0]
    # A cleared digit can still receive a confident reader prediction from its
    # neighbors. Require visible contrast inside the edited character cell.
    cell = cells[index]
    if min(cell.size) <= 0 or not area.contains(cell):
        return None
    if np.ptp(pixels(frame, cell)[:, :, :3], axis=(0, 1)).max() < 16:
        return None
    try:
        region = reader.read_line(cv2.cvtColor(pixels(frame, sample), cv2.COLOR_BGRA2BGR))
    except Exception:
        logging.getLogger(__name__).warning(
            "Fixed-line recognition failed; retrying detection", exc_info=True
        )
        return None
    if region is None or region.vertical or (region.confidence or 0) < 0.85:
        return None
    text = region.text
    if (
        len(text) != len(old.text)
        or text[index] == old.text[index]
        or text[:index] != old.text[:index]
        or text[index + 1 :] != old.text[index + 1 :]
        or (not old.characters and not text.isdecimal())
    ):
        return None
    candidate = region.translated(sample.x, sample.y)
    if not sample.contains(candidate.bounds) or not candidate.bounds.contains(change):
        return None
    if old.characters and (
        len(candidate.characters) != len(text)
        or "".join(c.text for c in candidate.characters) != text
        or candidate.characters[index].confidence < 0.85
        or not padded(candidate.characters[index].bounds, size, 3).contains(change)
    ):
        return None
    return candidate, sample
