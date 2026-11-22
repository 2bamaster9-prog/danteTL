"""Screenshot-derived ink boxes, scaled and permuted; no game identity in policy."""

from dataclasses import replace

import pytest

from dantetl.domain import Rect
from dantetl.ocr.observation import TextTrack
from dantetl.translation.grouping import DialogueGrouper

ROWS = (
    (2, "コホン、え、えーと…市民の", (472, 403, 773, 63)),
    (4, "皆様…こ、こちらは現在十四分街", (468, 482, 901, 64)),
    (6, "における捜査活動を監督している", (471, 563, 892, 62)),
    (8, "ヤヌス区治安局長官です。", (470, 647, 680, 59)),
    (5, "も、申し訳ございません、", (2465, 497, 673, 59)),
    (7, "ホロウ災害の発生により、", (2461, 577, 680, 59)),
    (9, "捜査活動に影響が出ております。", (2463, 658, 866, 59)),
    (3, "W発", (1392, 416, 179, 52)),
)


@pytest.mark.parametrize("scale", [0.5, 0.75, 1, 1.5])
def test_both_bubbles_stay_whole_despite_width_growth_and_detector_order(scale):
    tracks = tuple(
        TextTrack(key, text, Rect(*(round(v * scale) for v in bounds)))
        for key, text, bounds in ROWS
    )
    grouper = DialogueGrouper()
    grouper.update(tracks[::-1], tracks, 0)
    result = grouper.update(tracks[::2] + tracks[1::2], tracks, 0.4)
    assert {tuple(t.track_id for t in b.lines) for b in result.blocks} == {
        (2, 4, 6, 8),
        (5, 7, 9),
        (3,),
    }
    assert result.ready == result.blocks


@pytest.mark.parametrize("change", ["gap", "font", "column", "choice", "header"])
def test_relaxed_width_does_not_cross_clear_boundaries(change):
    a = TextTrack(1, "皆様、ここで少し待っていてください。", Rect(100, 100, 800, 40))
    b = TextTrack(2, "私が戻るまで動かないでください。", Rect(100, 158, 850, 40))
    assert len(DialogueGrouper().update((a, b), (a, b), 0).blocks) == 1
    if change == "gap":
        b = replace(b, bounds=replace(b.bounds, y=230))
    elif change == "font":
        b = replace(b, bounds=replace(b.bounds, height=22))
    elif change == "column":
        b = replace(b, bounds=replace(b.bounds, x=1100))
    elif change == "choice":
        b = replace(b, text="2. " + b.text)
    else:
        a = replace(a, text="長い名前を持っている旅人", bounds=replace(a.bounds, width=600))
    assert len(DialogueGrouper().update((a, b), (a, b), 0).blocks) == 2
