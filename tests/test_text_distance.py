"""Cutoff comparison against full Wagner-Fischer distance on Unicode strings."""

from itertools import product
from random import Random

import pytest

from dantejp.ocr.text_distance import within_edits


def distance(first, second):
    # Deliberately unbanded reference, with no trimming or early exits.
    rows = [list(range(len(second) + 1))]
    for i, a in enumerate(first, 1):
        row = [i]
        for j, b in enumerate(second, 1):
            row.append(min(rows[-1][j] + 1, row[j - 1] + 1, rows[-1][j - 1] + (a != b)))
        rows.append(row)
    return rows[-1][-1]


def test_cutoff_matches_full_distance_for_insertions_deletions_substitutions_and_unicode():
    words = ["".join(chars) for length in range(4) for chars in product("aあ🙂", repeat=length)]
    random = Random(371)
    pairs = list(product(words, repeat=2)) + [
        (
            "".join(random.choices("あいうえお", k=random.randrange(20, 40))),
            "".join(random.choices("あいうえお", k=random.randrange(20, 40))),
        )
        for _ in range(100)
    ]
    for first, second in pairs:
        exact = distance(first, second)
        for limit in range(3):
            assert within_edits(first, second, limit) == (exact <= limit), (first, second, limit)


def test_repetitive_long_strings_and_distant_edits_use_minimum_edit_count():
    assert within_edits("abababababab", "ababbababab", 1)
    assert within_edits("ab" * 256, "ba" + "ab" * 255, 2)
    first = "あ" * 512
    second = "い" + "あ" * 510 + "う"
    assert within_edits(first, second, 2)
    assert not within_edits(first, second, 1)
    assert not within_edits(first, "い" + "あ" * 255 + "う" + "あ" * 254 + "え", 2)
    with pytest.raises(ValueError):
        within_edits("a", "a", -1)
