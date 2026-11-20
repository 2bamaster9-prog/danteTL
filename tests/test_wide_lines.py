from dataclasses import replace

import pytest

from dantetl.domain import Rect
from dantetl.ocr.values import TextCharacter, TextRegion
from dantetl.ocr.wide_lines import recover_wide_lines


def line(text: str, y: int = 30) -> TextRegion:
    chars = tuple(TextCharacter(c, Rect(100 + i * 20, y, 18, 20), 0.9) for i, c in enumerate(text))
    return TextRegion(text, Rect(100, y, len(text) * 20, 20), chars)


@pytest.mark.parametrize("body", ["あ" * 46, "あ" * 76, "あ" * 100], ids=["two", "three", "four"])
def test_wide_line_returns_each_glyph_once_at_its_source_position(body):
    source = line("符玄" + body + "から")
    partial = replace(source, text=source.text[2:48], characters=source.characters[2:48])
    label = line("設定", 60)

    def read(boxes):
        pieces = []
        for i, box in enumerate(boxes):
            chars = [c for c in source.characters if box.contains(c.bounds)]
            if i:
                chars[0] = replace(chars[0], text="」")
            if i < len(boxes) - 1:
                chars[-1] = replace(chars[-1], text="「")
            pieces.append(TextRegion("".join(c.text for c in chars), box, tuple(chars)))
        return tuple(pieces)

    assert recover_wide_lines((partial, label), read) == (source, label)


@pytest.mark.parametrize("failure", ["overlap", "lost-word"])
def test_uncertain_or_incomplete_retry_preserves_original(failure):
    source = line("物語" * 24)
    original = replace(source, characters=source.characters[1:], text=source.text[1:])

    def read(boxes):
        pieces = []
        for i, box in enumerate(boxes):
            chars = [c for c in source.characters if box.contains(c.bounds)]
            if i == 1:
                if failure == "overlap":
                    chars = [replace(c, text="外") for c in chars]
                else:
                    # Lose an observed glyph at the right edge while gaining one at the left.
                    chars.pop()
            pieces.append(TextRegion("".join(c.text for c in chars), box, tuple(chars)))
        return tuple(pieces)

    assert recover_wide_lines((original,), read) == (original,)


def test_wide_line_retries_are_bounded_and_exclude_vertical_or_ordinary_text():
    wide = line("長" * 50)
    excluded = (line("設定"), replace(wide, vertical=True), line("長" * 113))
    assert recover_wide_lines(excluded, lambda _: pytest.fail("unexpected retry")) == excluded
    rows = tuple(line("長" * 50, y=i * 30) for i in range(12))
    calls = []

    def read(boxes):
        calls.append(len(boxes))
        return tuple(TextRegion("", b) for b in boxes)

    assert recover_wide_lines(rows, read) == rows
    assert calls == [16]
