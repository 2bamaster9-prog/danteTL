"""Conservative, same-image recovery evidence for horizontally severed OCR glyphs.

No dictionary, history or output synthesis: a retry must produce complete model
observations and preserve every unrelated line. Work is bounded by detector limits.
"""

from typing import Any

import cv2
import numpy as np

from jp_overlay.domain import Rect, union_bounds
from jp_overlay.ocr_values import TextRegion


def _overlap(a: Rect, b: Rect) -> float:
    width = max(0, min(a.x + a.width, b.x + b.width) - max(a.x, b.x))
    height = max(0, min(a.y + a.height, b.y + b.height) - max(a.y, b.y))
    return width * height / max(1, a.width * a.height)


def split_glyphs(image: Any, regions: tuple[TextRegion, ...]) -> tuple[tuple[int, int], ...]:
    """Find mutually unambiguous weak rows joined by ink across their supposed seam."""
    if not 2 <= len(regions) <= 64:
        return ()
    weak = [
        i
        for i, r in enumerate(regions)
        if not r.vertical and r.text.strip() and r.confidence is not None and r.confidence < 0.8
    ]
    pairs = []
    degree = [0] * len(regions)
    for pos, i in enumerate(weak):
        for j in weak[pos + 1 :]:
            a, b = sorted((regions[i].bounds, regions[j].bounds), key=lambda box: box.y)
            horizontal = min(a.x + a.width, b.x + b.width) - max(a.x, b.x)
            gap = b.y - a.y - a.height
            height = min(a.height, b.height)
            if (
                height < 5
                or horizontal < max(a.width, b.width) * 0.8
                or not -0.2 * height <= gap <= max(1, 0.15 * height)
                or min(a.height, b.height) < max(a.height, b.height) * 0.5
            ):
                continue
            pairs.append((i, j))
            degree[i] += 1
            degree[j] += 1
    confirmed = []
    for i, j in pairs:
        if degree[i] != 1 or degree[j] != 1:
            continue
        a, b = sorted((regions[i].bounds, regions[j].bounds), key=lambda box: box.y)
        union = union_bounds((a, b))
        if union.width < union.height or union.width > 512 or union.height > 128:
            continue
        patch = image[union.y : union.y + union.height, union.x : union.x + union.width]
        if patch.shape[:2] != (union.height, union.width):
            continue
        gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
        if int(gray.max()) - int(gray.min()) < 24:
            continue
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        # Use the minority class as ink; ambiguous/busy patches fail closed below.
        if np.count_nonzero(binary) > binary.size / 2:
            binary = cv2.bitwise_not(binary)
        density = np.count_nonzero(binary) / binary.size
        if not 0.05 <= density <= 0.45:
            continue
        _, _, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
        seam = (a.y + a.height + b.y) / 2 - union.y
        # Japanese radicals need not connect across the full glyph height. Require
        # a substantial component to cross the seam, without demanding it reach
        # the disconnected upper radical as well.
        margin = max(1.0, union.height * 0.05)
        if any(
            top < seam - margin
            and top + h > seam + margin
            and h >= union.height * 0.55
            and 1 < w < union.width * 0.8
            for _, top, w, h, _ in stats[1:]
        ):
            confirmed.append((i, j))
        if len(confirmed) == 4:
            break
    return tuple(confirmed)


def recovery_preserves_lines(
    original: tuple[TextRegion, ...],
    candidate: tuple[TextRegion, ...],
    pairs: tuple[tuple[int, int], ...],
) -> bool:
    """Accept only complete, stronger glyphs and one-to-one unchanged other lines."""
    if not pairs or len(candidate) > 64:
        return False
    used: set[int] = set()
    repaired: set[int] = set()
    for first, second in pairs:
        a, b = sorted((original[first].bounds, original[second].bounds), key=lambda box: box.y)
        whole = union_bounds((a, b))
        seam = (a.y + a.height + b.y) / 2
        matches = [
            i
            for i, row in enumerate(candidate)
            if i not in used
            and not row.vertical
            and row.confidence is not None
            and row.confidence >= 0.9
            and row.confidence
            >= max(original[first].confidence or 0, original[second].confidence or 0) + 0.15
            and _overlap(whole, row.bounds) >= 0.8
            and _overlap(row.bounds, whole) >= 0.65
            and row.characters
            and all(
                c.confidence >= 0.8
                and c.bounds.y < seam - whole.height * 0.15
                and c.bounds.y + c.bounds.height > seam + whole.height * 0.15
                for c in row.characters
            )
        ]
        if len(matches) != 1:
            return False
        used.add(matches[0])
        repaired.update((first, second))
    for index, before in enumerate(original):
        if index in repaired:
            continue
        matches = [
            i
            for i, after in enumerate(candidate)
            if i not in used
            and after.text == before.text
            and after.vertical == before.vertical
            and _overlap(before.bounds, after.bounds) >= 0.8
            and _overlap(after.bounds, before.bounds) >= 0.8
            and (
                before.confidence is None
                or (after.confidence is not None and after.confidence >= before.confidence - 0.05)
            )
        ]
        if len(matches) != 1:
            return False
        used.add(matches[0])
    return len(used) == len(candidate)
