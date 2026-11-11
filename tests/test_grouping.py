from dataclasses import replace

import pytest

from jp_overlay.domain import Rect
from jp_overlay.grouping import DialogueGrouper, TextBlock, join_lines
from jp_overlay.tracking import TextTrack
from jp_overlay.translation import TranslationRequest


def line(
    key=1, text="新しい冒険がここから始まりますが、", *, x=100, y=700, width=640, height=32
) -> TextTrack:
    return TextTrack(key, text, Rect(x, y, width, height))


def dialogue() -> tuple[TextTrack, ...]:
    return (line(), line(2, "その前に旅の準備をしてください。", y=744, width=540))


def test_dialogue_is_joined_in_reading_order_and_keeps_original_line_height() -> None:
    tracks = dialogue()
    grouper = DialogueGrouper()
    first = grouper.update(tracks[::-1], tracks, 0)
    assert len(first.blocks) == 1 and first.ready == ()
    block = grouper.update(tracks, tracks, 0.36).ready[0]
    assert block.lines == tracks
    assert block.text == "新しい冒険がここから始まりますが、その前に旅の準備をしてください。"
    assert block.bounds == Rect(100, 700, 640, 76)
    assert block.line_height == 32


def test_incomplete_group_cannot_send_only_its_confirmed_fragment() -> None:
    tracks = dialogue()
    grouper = DialogueGrouper()
    result = grouper.update(tracks, tracks[:1], 0)
    assert len(result.blocks[0].lines) == 2 and not result.ready
    assert not grouper.update(tracks, tracks[:1], 1).ready
    assert len(grouper.update(tracks, tracks, 1.1).ready) == 1


def test_speaker_name_and_completed_sentences_stay_separate_from_wrapped_dialogue() -> None:
    tracks = (line(9, "三月なのか", y=655, width=140), *dialogue())
    result = DialogueGrouper().update(tracks, tracks, 0)
    assert [len(b.lines) for b in result.blocks] == [1, 2]
    completed = (replace(tracks[1], text="今日も一緒に出かけましょう。"), tracks[2])
    assert len(DialogueGrouper().update(completed, completed, 0).blocks) == 2


def test_long_narrow_speaker_label_is_not_prepended_to_dialogue() -> None:
    tracks = (line(9, "長い名前を持っている旅人", y=656, width=240), *dialogue())
    result = DialogueGrouper().update(tracks, tracks, 0)
    assert [len(block.lines) for block in result.blocks] == [1, 2]


@pytest.mark.parametrize(
    "first,second",
    [
        ("ストーリーを振り返る", "アイテムの一覧を表示する"),
        ("1. 新しい冒険に出発する", "2. 今はこの場所に残ります。"),
        ("◆新しい冒険に出発する", "◆今はこの場所に残ります。"),
        ("長い名前の話者の表示：", "その前に旅の準備をしてください。"),
    ],
)
def test_menu_labels_choices_and_speaker_headers_are_not_paragraphs(first, second) -> None:
    tracks = (line(text=first), line(2, second, y=744))
    result = DialogueGrouper().update(tracks, tracks, 0)
    assert len(result.blocks) == len(result.ready) == 2


def test_separate_columns_group_independently_and_ambiguous_neighbours_do_not_merge() -> None:
    a, b = dialogue()
    tracks = (
        a,
        b,
        replace(a, track_id=3, bounds=replace(a.bounds, x=900)),
        replace(b, track_id=4, bounds=replace(b.bounds, x=900)),
    )
    result = DialogueGrouper().update(tracks, tracks, 0)
    assert [tuple(t.track_id for t in block.lines) for block in result.blocks] == [(1, 2), (3, 4)]
    ambiguous = (a, b, replace(b, track_id=3, bounds=replace(b.bounds, x=110)))
    assert len(DialogueGrouper().update(ambiguous, ambiguous, 0).blocks) == 3


@pytest.mark.parametrize("change", [{"y": 800}, {"height": 18}, {"x": 180}])
def test_large_gaps_different_font_sizes_and_unaligned_lines_stay_separate(change) -> None:
    a, b = dialogue()
    tracks = (a, replace(b, bounds=replace(b.bounds, **change)))
    assert len(DialogueGrouper().update(tracks, tracks, 0).blocks) == 2


def test_movement_does_not_change_requests_but_any_member_edit_does() -> None:
    tracks = dialogue()
    block = TextBlock(tracks)
    moved = TextBlock(tuple(replace(t, bounds=replace(t.bounds, x=300)) for t in tracks))
    assert TranslationRequest.from_block(moved) == TranslationRequest.from_block(block)
    edited = TextBlock((tracks[0], replace(tracks[1], text_revision=2)))
    assert TranslationRequest.from_block(edited) != TranslationRequest.from_block(block)


def test_regrouping_edit_and_reset_wait_for_new_group_evidence() -> None:
    tracks = dialogue()
    grouper = DialogueGrouper()
    grouper.update(tracks, tracks, 0)
    assert grouper.update(tracks, tracks, 0.5).ready
    edited = (tracks[0], replace(tracks[1], text="準備ができたら出発しましょう。", text_revision=2))
    assert not grouper.update(edited, tracks, 1).ready
    assert not grouper.update(edited, tracks, 1.5).ready  # Old confirmed members cannot approve it.
    assert grouper.update(edited, edited, 1.6).ready
    grouper.reset()
    assert not grouper.update(edited, edited, 2).ready
    assert len(grouper.update(edited, edited, 2.1, enabled=False).ready) == 2


def test_vertical_text_stays_individual_and_latin_word_boundaries_keep_spaces() -> None:
    tracks = tuple(replace(t, vertical=True) for t in dialogue())
    assert len(DialogueGrouper().update(tracks, tracks, 0).blocks) == 2
    assert (
        join_lines((line(text="ゲームはStar"), line(2, "Railです。"))) == "ゲームはStar Railです。"
    )


def test_group_size_source_size_and_state_are_bounded_without_dropping_visible_lines() -> None:
    tracks = tuple(line(i, "新しい冒険について話しましょう、", y=i * 44) for i in range(128))
    grouper = DialogueGrouper()
    result = grouper.update(tracks, tracks, 0)
    assert sum(len(block.lines) for block in result.blocks) == 128
    assert all(len(block.lines) <= 6 and len(block.text) <= 512 for block in result.blocks)
    longer = tuple(replace(t, text="冒険の準備" * 30 + "、") for t in tracks[:6])
    result = grouper.update(longer, longer, 1)
    assert sum(len(block.lines) for block in result.blocks) == 6
    assert all(len(block.text) <= 512 for block in result.blocks)
    assert grouper.update((), (), 2).blocks == ()
    assert not grouper._since
