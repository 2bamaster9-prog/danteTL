"""Cutoff comparison against full Wagner-Fischer distance on Unicode strings."""

from itertools import product
from random import Random

import pytest

from dantejp.ocr.text_distance import LcsSimilarity, within_edits


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


def lcs_length(first, second):
    row = [0] * (len(second) + 1)
    for a in first:
        previous, row = row, [0]
        for j, b in enumerate(second, 1):
            row.append(previous[j - 1] + 1 if a == b else max(previous[j], row[-1]))
    return row[-1]


def test_bit_parallel_similarity_matches_independent_unicode_lcs_oracle():
    words = ["".join(chars) for size in range(5) for chars in product("aあ🙂", repeat=size)]
    for first in words:
        scorer = LcsSimilarity(first)
        for second in words:
            expected = (
                2 * lcs_length(first, second) / (len(first) + len(second)) if first or second else 1
            )
            assert scorer.ratio(second) == expected
    random = Random(897)
    for _ in range(50):
        first = "".join(random.choices("あいうえお🙂", k=512))
        second = first[:180] + "かきくけこ" + first[185:]
        assert LcsSimilarity(first).ratio(second) == 2 * lcs_length(first, second) / 1024


def test_repeated_text_similarity_is_symmetric_and_keeps_internal_edits():
    first = "あい" * 255 + "32"
    second = "いあ" * 255 + "35"
    assert LcsSimilarity(first).ratio(second) == LcsSimilarity(second).ratio(first)
    assert 0.99 < LcsSimilarity(first).ratio(second) < 1
    assert LcsSimilarity("こんにちは").ratio("さようなら") < 0.8
