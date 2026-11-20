"""Replay derived OCR geometry from the supplied paragraph; no game pixels are stored."""

from dataclasses import replace

import pytest

from dantejp.domain import CapturedFrame, Rect, WindowGeometry
from dantejp.ocr.tracking import TextActivity, TextTrack, TextTracker
from dantejp.ocr.values import OcrResult, TextRegion
from dantejp.translation.grouping import DialogueGrouper
from dantejp.translation.values import TranslationRequest


def description():
    return tuple(
        TextTrack(i, text, Rect(*bounds))
        for i, (text, bounds) in enumerate(
            (
                ("秘技を使用した後、次の戦闘開始", (2887, 627, 719, 48)),
                ("時、セイバーの攻撃力:35%、2ター", (2889, 698, 772, 48)),
                ("ン継続。「炉心共鳴」を2層獲得す", (2887, 767, 745, 51)),
                ("る。", (2888, 848, 72, 38)),
            ),
            1,
        )
    )


@pytest.mark.parametrize("scale", [0.5, 1, 1.5])
def test_wrapped_description_includes_short_terminal_ink_and_preserves_raw_members(scale):
    body = tuple(
        replace(
            t,
            bounds=Rect(
                *(
                    round(n * scale)
                    for n in (t.bounds.x, t.bounds.y, t.bounds.width, t.bounds.height)
                )
            ),
        )
        for t in description()
    )
    heading = TextTrack(
        9,
        "強化",
        Rect(round(2900 * scale), round(545 * scale), round(98 * scale), round(40 * scale)),
    )
    tracks = (heading, *body)
    grouper = DialogueGrouper()
    result = grouper.update(tracks[::-1], tracks, 0)
    assert [b.lines for b in result.blocks] == [(heading,), body]
    assert result.blocks[1].text == "".join(t.text for t in body)
    assert grouper.update(tracks, tracks, 0.36).ready[-1].lines == body
    assert len(grouper.update(tracks, tracks, 0.4, enabled=False).blocks) == 5


def test_unfinished_aligned_prose_reserves_paragraph_before_final_punctuation():
    lines = description()
    menu = TextTrack(8, "設定", Rect(100, 50, 60, 32))
    grouper = DialogueGrouper()
    # OCR discovers rows separately. No preliminary line translation is scheduled.
    for count, now in ((1, 0), (1, 0.4), (2, 0.42), (3, 0.55), (4, 0.65)):
        visible = (menu, *lines[:count])
        activity = (TextActivity(menu, -1, False, False),) + tuple(
            TextActivity(t, (0, 0.42, 0.55, 0.65)[i], False, False)
            for i, t in enumerate(lines[:count])
        )
        grouped = grouper.update(visible, visible, now, activity=activity)
        assert all(b.lines == (menu,) for b in grouped.ready)
        assert len(grouped.blocks) == 2
    finished = grouper.update(visible, visible, 0.84, activity=activity)
    assert finished.ready[-1].lines == lines
    # Changed/unconfirmed continuation cannot approve an obsolete group source.
    changed = replace(lines[-1], text="ります。", text_revision=2)
    update = grouper.update(
        (*visible[:-1], changed),
        visible,
        1,
        activity=activity[:-1] + (TextActivity(changed, 1, True, True),),
    )
    assert all(b.lines == (menu,) for b in update.ready)


def test_prose_wait_is_bounded_and_short_menu_readiness_is_unchanged():
    first = description()[0]
    activity = (TextActivity(first, 0, False, False),)
    grouper = DialogueGrouper()
    assert not grouper.update((first,), (first,), 0.4, activity=activity).ready
    assert grouper.update((first,), (first,), 0.56, activity=activity).ready
    short = replace(first, text="設定")
    assert grouper.update(
        (short,), (short,), 0, activity=(TextActivity(short, 0, False, False),)
    ).ready


@pytest.mark.parametrize(
    "tail",
    [
        TextTrack(4, "戻る", Rect(2888, 848, 72, 38)),
        TextTrack(4, "る。", Rect(2888, 848, 72, 25)),
        TextTrack(4, "る。", Rect(2888, 940, 72, 38)),
        TextTrack(4, "る。", Rect(3050, 848, 72, 38)),
    ],
)
def test_short_tail_exception_does_not_absorb_smaller_labels_distant_or_unaligned_text(tail):
    tracks = (*description()[:3], tail)
    blocks = DialogueGrouper().update(tracks, tracks, 0).blocks
    assert [len(b.lines) for b in blocks] == [3, 1]


def test_internal_punctuation_does_not_join_choices_completed_sentences_or_narrow_headers():
    a, b = description()[:2]
    for first in (
        replace(a, text="◆秘技を使用した後、次の戦闘開始"),
        replace(a, text="秘技を使用した後、次の戦闘を開始。"),
        replace(a, bounds=replace(a.bounds, width=300)),
        replace(a, text="秘技の詳細な説明を確認する"),
    ):
        tracks = (first, b)
        assert len(DialogueGrouper().update(tracks, tracks, 0).blocks) == 2
    # Two possible successors remain ambiguous even with strong paragraph punctuation.
    tracks = (a, b, replace(b, track_id=3, bounds=replace(b.bounds, x=b.bounds.x + 10)))
    assert len(DialogueGrouper().update(tracks, tracks, 0).blocks) == 3


def test_partial_ocr_discovery_reserves_body_then_keeps_unscanned_group_members():
    tracker, grouper = TextTracker(), DialogueGrouper()
    bounds = Rect(0, 0, 3840, 2160)
    geometry = WindowGeometry(bounds, bounds, bounds, 96)
    lines = description()
    frame = CapturedFrame(1, 0, geometry, b"")
    for i, line in enumerate(lines):
        frame = replace(frame, sequence=i + 1, captured_at=i * 0.12)
        tracker.observe(
            OcrResult(
                frame,
                (TextRegion(line.text, line.bounds),),
                20,
                frame.captured_at + 0.02,
                (line.bounds,),
            )
        )
        current = tracker.visible(frame, frame.captured_at + 0.02)
        confirmed = tracker.translation_tracks(frame, frame.captured_at + 0.02)
        group = grouper.update(
            current, confirmed, frame.captured_at + 0.02, activity=tracker.translation_activity()
        )
        assert len(group.blocks) == 1 and not group.ready
    # Source-matched visual probes confirm each partial scan without fabricating OCR results.
    tracker.confirm_observations(tuple((i + 1, i + 1, t.text) for i, t in enumerate(lines)), 1)
    current = tracker.translation_tracks(frame, 1)
    ready = grouper.update(current, current, 1, activity=tracker.translation_activity()).ready
    assert len(ready) == 1 and ready[0].text == "".join(t.text for t in lines)
    for sequence in range(5, 10):
        source = replace(frame, sequence=sequence, captured_at=sequence)
        tracker.observe(OcrResult(source, (), 20, sequence + 0.02, (Rect(0, 0, 100, 100),)))
        current = tracker.translation_tracks(source, sequence + 0.5)
        assert (
            grouper.update(
                current, current, sequence + 0.5, activity=tracker.translation_activity()
            ).ready
            == ready
        )
    tracker.reset()
    grouper.reset()
    assert not grouper.update((), (), 20, activity=()).blocks


def fragmented_description():
    # Cropping the same screenshot split the third visual row around its quoted term.
    return (
        *description()[:2],
        TextTrack(3, "ン継続。", Rect(2889, 771, 161, 45)),
        TextTrack(4, "炉心共鳴」を2層獲得す", Rect(3129, 770, 503, 47)),
        replace(description()[3], track_id=5),
    )


def test_split_row_inside_established_paragraph_preserves_reading_order_and_member_validity():
    lines = fragmented_description()
    grouper = DialogueGrouper()
    for order in (lines, lines[::-1], (lines[3], lines[0], lines[4], lines[2], lines[1])):
        grouped = grouper.update(order, lines, 1)
        assert len(grouped.blocks) == 1 and grouped.blocks[0].lines == lines
        assert grouped.blocks[0].text == "".join(t.text for t in lines)
    grouped = grouper.update(lines, lines, 1.36)
    assert grouped.ready == grouped.blocks
    request = TranslationRequest.from_block(grouped.ready[0])
    revised = (*lines[:3], replace(lines[3], text_revision=2), lines[4])
    assert not grouper.update(revised, lines, 2).ready
    assert TranslationRequest.from_block(grouper.update(revised, revised, 3).blocks[0]) != request


@pytest.mark.parametrize(
    "change",
    [
        {"x": 3250},  # Too large a gap / outside the established column.
        {"height": 25},  # A smaller annotation.
        {"y": 800},  # A different baseline.
    ],
)
def test_fragment_join_rejects_unrelated_column_font_and_baseline(change):
    lines = fragmented_description()
    foreign = replace(lines[3], bounds=replace(lines[3].bounds, **change))
    tracks = (*lines[:3], foreign, lines[4])
    grouped = DialogueGrouper().update(tracks, tracks, 0)
    assert any(b.lines == (foreign,) for b in grouped.blocks)


def test_fragment_join_requires_existing_prose_and_unique_successor():
    lines = fragmented_description()
    assert len(DialogueGrouper().update(lines[2:], lines[2:], 0).blocks) == 3
    duplicate = replace(lines[3], track_id=6, bounds=replace(lines[3].bounds, x=3130))
    tracks = (*lines, duplicate)
    groups = DialogueGrouper().update(tracks, tracks, 0).blocks
    assert any(b.lines == (lines[3],) for b in groups)
    assert any(b.lines == (duplicate,) for b in groups)
