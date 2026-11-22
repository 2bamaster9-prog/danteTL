"""Centered Honkai subtitle geometry, without retaining game pixels or using models."""

from dataclasses import replace

import pytest

from dantetl.domain import CapturedFrame, Rect, WindowGeometry
from dantetl.ocr.observation import TextTrack
from dantetl.ocr.tracking import TextActivity, TextTracker
from dantetl.ocr.values import OcrResult, TextRegion
from dantetl.translation.dialogue.history import DialogueHistory
from dantetl.translation.grouping import DialogueGrouper, TextBlock
from dantetl.translation.values import TranslatedText, TranslationRequest


def subtitles(scale=1.0):
    # Meiki content bounds from the supplied 3840x2160 screenshot. The first line
    # loses some edge glyphs, shifting its measured center 36 px from the final row.
    rows = (
        ("アメセラ", (1779, 1607, 276, 63)),
        (
            "私はで故にいました。フアミリーに回収されるまでに、記保モジュールの大半がけてしまい、その修理",
            (487, 1720, 2761, 53),
        ),
        ("は天文学的数字になります。", (1583, 1784, 641, 50)),
    )
    return tuple(
        TextTrack(i, text, Rect(*(round(v * scale) for v in bounds)))
        for i, (text, bounds) in enumerate(rows, 1)
    )


@pytest.mark.parametrize("scale", [0.5, 0.75, 1, 1.5])
def test_centered_subtitle_groups_and_enters_history_with_larger_speaker(scale):
    tracks = subtitles(scale)
    grouper, history = DialogueGrouper(), DialogueHistory()
    size = (round(3840 * scale), round(2160 * scale))
    for now, order in ((0, tracks[::-1]), (0.5, tracks), (1, (tracks[2], *tracks[:2]))):
        grouped = grouper.update(order, tracks, now)
        assert [b.lines for b in grouped.blocks] == [(tracks[0],), tracks[1:]]
        history.observe(grouped.blocks, grouped.ready, size, now, scores={tracks[0]: 0.9517})
        history.published(
            tuple(
                TranslatedText(TranslationRequest.from_block(b), "An astronomical repair bill.")
                for b in grouped.ready
            )
        )
    assert len(history.turns) == 1
    assert history.turns[0].source == "".join(t.text for t in tracks[1:])
    assert history.turns[0].speaker == "アメセラ"
    assert history.turns[0].english == "An astronomical repair bill."
    assert len(grouper.update(tracks, tracks, 2, enabled=False).blocks) == 3


@pytest.mark.parametrize(
    "change",
    [
        {"x": 1700},
        {"y": 1850},
        {"height": 28},
    ],
)
def test_centered_exception_keeps_column_spacing_and_font_guards(change):
    speaker, first, last = subtitles()
    last = replace(last, bounds=replace(last.bounds, **change))
    tracks = (speaker, first, last)
    assert len(DialogueGrouper().update(tracks, tracks, 0).blocks) == 3


@pytest.mark.parametrize(
    "text",
    [
        "ストーリーを振り返って確認する",
        "今日はここに残って待ちましょう。",
        "◆今は出発せず、ここに残って待つ",
        "1. 今は出発せず、ここに残って待つ",
        "名前がとても長いキャラクター：",
    ],
)
def test_center_alignment_alone_does_not_merge_menu_rows_or_completed_choices(text):
    speaker, first, last = subtitles()
    tracks = (speaker, replace(first, text=text), last)
    assert len(DialogueGrouper().update(tracks, tracks, 0).blocks) == 3
    history = DialogueHistory()
    for now in (0, 2):
        grouped = DialogueGrouper().update(tracks, tracks, now)
        history.observe(grouped.blocks, grouped.blocks, (3840, 2160), now)
        history.published(
            tuple(
                TranslatedText(TranslationRequest.from_block(b), "Choice") for b in grouped.blocks
            )
        )
    assert not history.turns


def test_pending_centered_continuation_reserves_group_without_publishing_fragments():
    speaker, first, last = subtitles()
    growing = replace(last, text="は天文学的", bounds=Rect(1770, 1784, 267, 50))
    tracks = (speaker, first, growing)
    grouper = DialogueGrouper()
    activity = tuple(TextActivity(t, 0, t == growing, t == growing) for t in tracks)
    grouped = grouper.update(tracks, tracks[:2], 1, activity=activity)
    assert grouped.blocks[-1].lines == tracks[1:]
    assert all(b.lines == (speaker,) for b in grouped.ready)
    complete = (speaker, first, last)
    activity = tuple(TextActivity(t, 1.1, True, False) for t in complete)
    assert not grouper.update(complete, complete, 1.2, activity=activity).ready
    ready = grouper.update(complete, complete, 1.3, activity=activity).ready
    assert ready[-1].lines == complete[1:]


def test_partial_scans_keep_centered_group_and_do_not_duplicate_history():
    tracks = subtitles()
    tracker, grouper, history = TextTracker(), DialogueGrouper(), DialogueHistory()
    rect = Rect(0, 0, 3840, 2160)
    geometry = WindowGeometry(rect, rect, rect, 96)
    for i, track in enumerate(tracks):
        frame = CapturedFrame(i + 1, i * 0.1, geometry, b"")
        tracker.observe(
            OcrResult(
                frame,
                (TextRegion(track.text, track.bounds),),
                20,
                frame.captured_at + 0.02,
                (track.bounds,),
            )
        )
    tracker.confirm_observations(tuple((i, i, t.text) for i, t in enumerate(tracks, 1)), 1)
    for sequence in range(4, 9):
        frame = CapturedFrame(sequence, sequence, geometry, b"")
        # A scan elsewhere says nothing about the subtitle members.
        tracker.observe(OcrResult(frame, (), 20, sequence + 0.02, (Rect(0, 0, 100, 100),)))
        visible = tracker.visible(frame, sequence + 0.5)
        grouped = grouper.update(
            visible,
            tracker.translation_tracks(frame, sequence + 0.5),
            sequence + 0.5,
            activity=tracker.translation_activity(),
        )
        assert len(grouped.blocks[-1].lines) == 2
        history.observe(grouped.blocks, grouped.ready, rect.size, sequence + 0.5)
        history.published(
            tuple(
                TranslatedText(TranslationRequest.from_block(b), "Whole turn")
                for b in grouped.ready
            )
        )
    assert len(history.turns) == 1 and history.turns[0].speaker is None


def test_centered_short_reply_accepts_wider_name_and_growth_updates_same_turn():
    speaker = TextBlock((subtitles()[0],))
    first = TextTrack(9, "うん。", Rect(1840, 1720, 156, 53))
    grown = replace(
        first,
        text="うん。では私と一緒に来てください。",
        bounds=Rect(1418, 1720, 1000, 53),
        text_revision=2,
    )
    history = DialogueHistory()
    for track, start in ((first, 0), (grown, 2)):
        block = TextBlock((track,))
        for now in (start, start + 1.3):
            history.observe(
                (speaker, block), (block,), (3840, 2160), now, scores={speaker.lines[0]: 0.96}
            )
            history.published((TranslatedText(TranslationRequest.from_block(block), "Yes."),))
    assert len(history.turns) == 1 and history.turns[0].source == grown.text
    assert history.turns[0].speaker == "アメセラ"
