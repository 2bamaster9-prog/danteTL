"""Comparable-width centered subtitles, anonymous turns and conservative negative layouts."""

from dataclasses import replace

import pytest

from dantejp.domain import Rect
from dantejp.ocr.tracking import TextActivity, TextTrack
from dantejp.translation.dialogue.history import DialogueHistory
from dantejp.translation.grouping import DialogueGrouper, TextBlock
from dantejp.translation.worker import TranslatedText, TranslationRequest


def subtitles(scale=1):
    # Actual Meiki character extents from the supplied still; no game-title dispatch.
    rows = (
        ("蠢楽(キンラク)", (1608, 1608, 559, 79)),
        ("そうか。見学なら、ここで登録してくれ。それと、セキュリティチェッ", (987, 1774, 1864, 63)),
        ("ク……はい。くれぐれも「迷惑を起こさない」ようにしてくれ。", (1065, 1856, 1659, 64)),
    )
    return tuple(
        TextTrack(i, text, Rect(*(round(v * scale) for v in bounds)))
        for i, (text, bounds) in enumerate(rows, 1)
    )


def publish(history, grouped, size, now, scores=None):
    history.observe(grouped.blocks, grouped.ready, size, now, scores=scores)
    history.published(
        tuple(
            TranslatedText(TranslationRequest.from_block(b), "Whole translated turn.")
            for b in grouped.ready
        )
    )


@pytest.mark.parametrize("scale", [0.5, 0.75, 1, 1.5])
@pytest.mark.parametrize("with_speaker", [False, True])
def test_centered_similar_width_rows_form_one_request_and_history_turn(scale, with_speaker):
    name, *body = subtitles(scale)
    tracks = (name, *body) if with_speaker else tuple(body)
    size = (round(3840 * scale), round(2160 * scale))
    grouper, history = DialogueGrouper(), DialogueHistory()
    for now, order in ((0, tracks), (0.5, tracks[::-1]), (1, tracks)):
        grouped = grouper.update(order, tracks, now)
        assert grouped.blocks[-1].lines == tuple(body)
        publish(history, grouped, size, now, {name: 0.793})
    assert len(history.turns) == 1
    assert history.turns[0].source == "".join(t.text for t in body)
    assert history.turns[0].speaker is None  # Real screenshot OCR is uncertain, never guess.
    if with_speaker:
        publish(history, grouped, size, 2, {name: 0.96})
        assert len(history.turns) == 1 and history.turns[0].speaker == name.text


@pytest.mark.parametrize(
    "change",
    [
        {"x": 1260},
        {"y": 1920},
        {"height": 35},
        {"width": 2500},
    ],
)
def test_prose_still_requires_close_matching_font_and_alignment(change):
    _, first, last = subtitles()
    tracks = (first, replace(last, bounds=replace(last.bounds, **change)))
    assert len(DialogueGrouper().update(tracks, tracks, 1).blocks) == 2


@pytest.mark.parametrize(
    "first",
    [
        "ここから物語の続きを確認する",
        "◆見学なら、ここで登録してくれ",
    ],
)
def test_centered_choices_and_non_prose_stay_separate(first):
    _, upper, lower = subtitles()
    tracks = (replace(upper, text=first), lower)
    grouped = DialogueGrouper().update(tracks, tracks, 0)
    assert len(grouped.blocks) == 2
    history = DialogueHistory()
    for now in (0, 2):
        publish(history, grouped, (3840, 2160), now)
    assert not history.turns


def test_centered_tight_prose_can_continue_after_a_sentence_boundary():
    _, upper, lower = subtitles()
    tracks = (replace(upper, text="そうか。ここで登録してくれ。"), lower)
    assert len(DialogueGrouper().update(tracks, tracks, 0).blocks) == 1


@pytest.mark.parametrize("scale", [0.5, 1])
@pytest.mark.parametrize(
    "upper,tail",
    [
        ("戦とは、ただの殴り合いじゃない。技術も知恵も問われる、最悪の", "「ゲーム」だ。"),
        ("戦とはただの殴り合いじゃない技術も知恵も問われる最悪の", "ゲーム」だ。"),
        ("その先にあるのは今まで誰も見たことのない幻の", "『海』でした。"),
        ("この町であなたに会えるとは思ってもみなかっ", "た。"),
        ("私たちをここまで案内してくれたのはあのチ", "ャットボットだ。"),
    ],
)
def test_centered_final_fragment_forms_one_confirmed_request(scale, upper, tail):
    def row(key, text, bounds):
        return TextTrack(key, text, Rect(*(round(v * scale) for v in bounds)))

    first = row(1, upper, (1041, 1774, 1750, 61))
    last = row(2, tail, (1774, 1858, 308, 59))
    button = row(3, "「設定」を開く。", (1720, 1942, 416, 59))
    tracks = (button, last, first)
    grouper = DialogueGrouper()
    pending = grouper.update(tracks, (first, button), 0)
    assert [b.lines for b in pending.blocks] == [(first, last), (button,)]
    assert all(first not in b.lines and last not in b.lines for b in pending.ready)
    ready = grouper.update(tracks[::-1], tracks, 1).ready
    assert ready[0].lines == (first, last) and ready[0].text == upper + tail


@pytest.mark.parametrize(
    "tail",
    [
        "「設定」",
        "「次へ。」",
        "「設定」を開く。",
        "◆『戻る』を選ぶ。",
        "――「今から出発」だ。",
        "少し話をしよう。",
    ],
)
def test_centered_single_option_under_unfinished_speech_stays_separate(tail):
    first = TextTrack(1, "この先に何が待っているか分からないけれど私たちの", Rect(0, 0, 800, 32))
    last = TextTrack(2, tail, Rect(290, 43, 220, 32))
    tracks = (first, last)
    assert [b.lines for b in DialogueGrouper().update(tracks, tracks, 0).blocks] == [
        (first,),
        (last,),
    ]


def test_competing_centered_endings_leave_the_subtitle_unresolved():
    first = TextTrack(1, "この先に何が待っているか分からないけれど私たちの", Rect(0, 0, 800, 32))
    last = TextTrack(2, "「旅」です。", Rect(290, 43, 220, 32))
    other = replace(last, track_id=3, text="「道」だ。", bounds=Rect(280, 44, 230, 32))
    tracks = (other, last, first)
    assert all(len(b.lines) == 1 for b in DialogueGrouper().update(tracks, tracks, 0).blocks)


def test_early_continuation_waits_and_unchanged_group_survives_polls():
    name, first, last = subtitles()
    grouper = DialogueGrouper()
    tracks = (name, first, last)
    activity = tuple(TextActivity(t, 0, t == last, t == last) for t in tracks)
    pending = grouper.update(tracks, tracks[:2], 1, activity=activity)
    assert pending.blocks[-1].lines == (first, last)
    assert all(b.lines == (name,) for b in pending.ready)
    activity = tuple(TextActivity(t, 1.1, True, False) for t in tracks)
    assert not grouper.update(tracks, tracks, 1.2, activity=activity).ready
    ready = grouper.update(tracks, tracks, 1.3, activity=activity)
    assert ready.ready[-1].lines == (first, last)
    for now in (1.4, 2, 5):
        current = grouper.update(tracks[::-1], tracks, now, activity=activity)
        assert current.blocks == ready.blocks
        assert current.ready[-1] == ready.ready[-1]


def test_single_anonymous_subtitle_waits_for_readiness_and_logs_once_without_a_name():
    history = DialogueHistory()
    block = TextBlock(
        (TextTrack(1, "あなたと一緒にここから出発しましょう。", Rect(1000, 1774, 1840, 63)),)
    )
    result = TranslatedText(TranslationRequest.from_block(block), "Let's leave together.")
    history.observe((block,), (), (3840, 2160), 0)
    history.published((result,))
    history.observe((block,), (), (3840, 2160), 2)
    history.published((result,))
    assert not history.turns
    for now in (2.1, 3, 4):
        history.observe((block,), (block,), (3840, 2160), now)
        history.published((result,))
    assert len(history.turns) == 1 and history.turns[0].speaker is None
    assert history.turns[0].source == block.text
    history.clear()
    history.observe((block,), (block,), (3840, 2160), 5)
    history.published((result,))
    assert not history.turns


@pytest.mark.parametrize("text", ["鑫楽（キンラク）", "鑫楽(キンラク)"])
def test_reading_annotation_can_establish_name_but_menu_annotation_cannot(text):
    name, first, _ = subtitles()
    # Off-center body deliberately cannot qualify through the anonymous-subtitle path.
    body = TextBlock(
        (
            replace(
                first, text="こちらで登録してから進んでください。", bounds=Rect(500, 1774, 1700, 63)
            ),
        )
    )
    history = DialogueHistory()
    for label, expected in ((text, True), ("スキル(キンラク)", False), ("鑫楽(効果)", False)):
        history.start()
        speaker = replace(name, text=label, bounds=Rect(500, 1680, 559, 60))
        blocks = (TextBlock((speaker,)), body)
        for now in (0, 2):
            history.observe(blocks, blocks, (3840, 2160), now, scores={speaker: 0.96})
            history.published((TranslatedText(TranslationRequest.from_block(body), "Go ahead."),))
        assert bool(history.turns) == expected


@pytest.mark.parametrize(
    "text,heading",
    [
        ("秘技を使用した後、攻撃力+35%を獲得する。", ""),
        ("古い時代から大切にされてきた品物。", "アイテム"),
        ("使うと味方全体の体力を回復する。", "使用効果"),
        ("◆はい、ここから一緒に出発しましょう。", ""),
    ],
)
def test_anonymous_path_does_not_bypass_description_or_choice_guards(text, heading):
    line = TextTrack(1, text, Rect(960, 1774, 1920, 63))
    blocks = (TextBlock((line,)),)
    if heading:
        blocks += (TextBlock((TextTrack(2, heading, Rect(1700, 1680, 440, 60)),)),)
    history = DialogueHistory()
    for now in (0, 2):
        history.observe(blocks, blocks, (3840, 2160), now)
        history.published((TranslatedText(TranslationRequest.from_block(blocks[0]), "UI text."),))
    assert not history.turns
