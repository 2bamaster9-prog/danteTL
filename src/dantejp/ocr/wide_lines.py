"""Recover compressed horizontal lettering with overlapping, source-relative reads."""

from collections.abc import Callable, Sequence
from dataclasses import replace
from itertools import pairwise

from dantejp.domain import Rect
from dantejp.ocr.values import TextCharacter, TextRegion


def _center(char: TextCharacter) -> float:
    return char.bounds.x + char.bounds.width / 2


def _join(pieces: Sequence[TextRegion]) -> tuple[TextCharacter, ...]:
    merged = pieces[0].characters
    for left, right in pairwise(pieces):
        # Anchor on two adjacent glyphs agreed on by both reads. Prefer the middle
        # of the overlap, where neither recognition saw a glyph cut by its edge.
        seam = (left.bounds.x + left.bounds.width + right.bounds.x) / 2
        height = right.bounds.height
        anchors = [
            (abs(_center(a) - seam), i, j)
            for i, (a, b) in enumerate(pairwise(merged))
            if abs(_center(a) - seam) <= height
            for j, (c, d) in enumerate(pairwise(right.characters))
            if a.text == c.text
            and b.text == d.text
            and abs(_center(a) - _center(c)) <= 0.30 * height
            and abs(_center(b) - _center(d)) <= 0.30 * height
        ]
        if not anchors:
            return ()
        _, i, j = min(anchors)
        merged = merged[: i + 1] + right.characters[j + 1 :]
    return merged


def recover_wide_lines(
    regions: tuple[TextRegion, ...],
    read: Callable[[list[Rect]], tuple[TextRegion, ...]],
) -> tuple[TextRegion, ...]:
    """Use one bounded batch of recognition crops; preserve original detector geometry."""
    boxes: list[Rect] = []
    spans: list[tuple[int, int, int]] = []
    for index, region in enumerate(regions):
        b = region.bounds
        if region.vertical or b.height <= 0 or b.width <= 36 * b.height:
            continue
        # Three extra glyph widths at either edge leave room for two intact
        # shared glyphs even when both cuts pass through characters.
        count = (b.width + 28 * b.height - 1) // (28 * b.height)
        if count > 4 or len(boxes) + count > 16:
            continue
        start = len(boxes)
        for i in range(count):
            left = max(0, b.width * i // count - 3 * b.height)
            right = min(b.width, b.width * (i + 1) // count + 3 * b.height)
            boxes.append(Rect(b.x + left, b.y, right - left, b.height))
        spans.append((index, start, len(boxes)))
    if not boxes:
        return regions
    pieces = read(boxes)
    recovered = list(regions)
    for index, start, end in spans:
        chars = _join(pieces[start:end])
        original = regions[index]
        text = "".join(c.text for c in chars)
        if not chars or text == original.text or len(text) < len(original.text):
            continue
        # A recovered glyph elsewhere cannot make up for a lost word. Allow
        # small localization differences between the two recognition scales.
        slack = 0.30 * original.bounds.height
        if all(
            any(
                c.bounds.x - slack <= _center(old) <= c.bounds.x + c.bounds.width + slack
                for c in chars
            )
            for old in original.characters
        ):
            recovered[index] = replace(original, text=text, characters=chars)
    return tuple(recovered)
