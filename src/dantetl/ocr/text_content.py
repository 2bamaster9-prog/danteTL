"""Conservative text-only observations for tracking; raw OCR remains untouched."""

from dataclasses import replace
from math import isfinite
from statistics import median

from dantetl.domain import union_bounds
from dantetl.languages.selection import DEFAULT_SOURCE
from dantetl.languages.source import SourceLanguage
from dantetl.ocr.values import TextCharacter, TextRegion

_STRUCTURAL = frozenset("（）()[]“”\"'，．：；？！!?…+-−±%％")


def _isolated_icon(
    language: SourceLanguage, edge: tuple[TextCharacter, ...], core: tuple[TextCharacter, ...]
) -> bool:
    if len(core) < 4 or not language.contains_text("".join(c.text for c in core)):
        return False
    if any(
        c in _STRUCTURAL or c in language.extra_edge_marks or c.isnumeric()
        for char in edge
        for c in char.text
    ):
        return False
    if not all(isfinite(c.confidence) and 0 <= c.confidence <= 1 for c in (*edge, *core)):
        return False
    strength = median(c.confidence for c in core)
    if not all(0 <= c.confidence <= 0.55 for c in edge) or strength < 0.75:
        return False
    if strength - max(c.confidence for c in edge) < 0.25:
        return False
    leading = edge[0].bounds.x < core[0].bounds.x
    left, right = (edge[-1], core[0]) if leading else (core[-1], edge[0])
    gap = right.bounds.x - (left.bounds.x + left.bounds.width)
    glyph = median(c.bounds.width for c in core)
    usual_gap = median(
        max(0, b.bounds.x - a.bounds.x - a.bounds.width)
        for a, b in zip(core, core[1:], strict=False)
    )
    return gap >= max(3, glyph * 0.45, usual_gap * 3)


def content_region(region: TextRegion, language: SourceLanguage = DEFAULT_SOURCE) -> TextRegion:
    """Use character extents, dropping only isolated weak edge glyphs by strong text.

    No global confidence threshold is raised. Quotes, punctuation, numbers, interior
    characters, and incomplete character metadata retain their recognized content.
    """
    characters = region.characters
    if not characters or "".join(c.text for c in characters) != region.text:
        return region
    if any(min(c.bounds.size) <= 0 for c in characters):
        return region
    ordered = all(
        a.bounds.x <= b.bounds.x for a, b in zip(characters, characters[1:], strict=False)
    )
    if language.trim_edge_icons and not region.vertical and ordered:
        for count in (2, 1):
            if _isolated_icon(language, characters[:count], characters[count:]):
                characters = characters[count:]
                break
        for count in (2, 1):
            if _isolated_icon(language, characters[-count:], characters[:-count]):
                characters = characters[:-count]
                break
    return replace(
        region,
        text="".join(c.text for c in characters),
        characters=characters,
        bounds=union_bounds(tuple(c.bounds for c in characters)),
    )
