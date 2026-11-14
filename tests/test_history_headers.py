"""Name/title hierarchies and adjacent responses, without model or game dependencies."""

from dataclasses import replace

import pytest

from jp_overlay.dialogue_classifier import Classification
from jp_overlay.dialogue_history import DialogueHistory
from jp_overlay.domain import Rect
from jp_overlay.grouping import TextBlock
from jp_overlay.tracking import TextTrack
from jp_overlay.translation import TranslatedText, TranslationRequest


def label(key, text, x, y, width, height):
    return TextBlock((TextTrack(key, text, Rect(x, y, width, height)),))


def panel():
    # Physical OCR geometry from the reported screenshot, including missing brackets.
    name = label(1, "厳彦(ゴンゲン", 1603, 1535, 557, 77)
    title = label(2, "仮想訓練場」教官", 1714, 1624, 436, 55)
    body = TextBlock(
        (
            TextTrack(
                3,
                "新人よ、少し体を動かさないか？トレーニングは体の状態を維持してく",
                Rect(978, 1773, 1869, 63),
            ),
            TextTrack(
                4,
                "れる。戦場はミスが許されるほど、甘い場所ではないぞ。",
                Rect(1156, 1856, 1482, 63),
            ),
        )
    )
    return name, title, body


def settle(history, blocks, now=0):
    for timestamp in (now, now + 1.3):
        history.observe(
            blocks,
            blocks,
            (3840, 2160),
            timestamp,
            scores={t: 0.99 for b in blocks for t in b.lines},
            assisted=True,
        )
    return history.classification_requests()


def publish(history, blocks):
    history.published(
        tuple(TranslatedText(TranslationRequest.from_block(b), "English " + b.text) for b in blocks)
    )


@pytest.mark.parametrize("alignment", ("left", "center", "right"))
@pytest.mark.parametrize("scale", (0.5, 1, 1.5))
def test_stacked_name_and_title_are_metadata_at_any_alignment_and_scale(alignment, scale):
    blocks = panel()
    changed = []
    for block in blocks:
        offset = (
            978 - block.bounds.x
            if alignment == "left"
            else (2847 - block.bounds.x - block.bounds.width if alignment == "right" else 0)
        )
        changed.append(
            TextBlock(
                tuple(
                    replace(
                        t,
                        bounds=Rect(
                            round((t.bounds.x + offset) * scale),
                            round(t.bounds.y * scale),
                            round(t.bounds.width * scale),
                            round(t.bounds.height * scale),
                        ),
                    )
                    for t in block.lines
                )
            )
        )
    name, title, body = changed
    history = DialogueHistory()
    keys = settle(history, tuple(reversed(changed)))
    assert len(keys) == 1 and keys[0].text == body.text and keys[0].speaker == name.text
    assert [(n.text, n.relation) for n in keys[0].panel.neighbors] == [
        (title.text, "speaker_detail")
    ]
    history.accept_classifications(((keys[0], Classification("dialogue", "yes")),))
    publish(history, changed)
    assert len(list(history.turns)) == 1
    assert history.turns[0].speaker == name.text
    assert history.turns[0].speaker_english == "English " + name.text


def test_already_grouped_header_reuses_its_exact_translation_and_all_member_confidence():
    name, title, body = panel()
    header = TextBlock((*name.lines, *title.lines))
    history = DialogueHistory()
    (key,) = settle(history, (header, body))
    assert key.speaker == header.text
    history.accept_classifications(((key, Classification("dialogue", "yes")),))
    publish(history, (header, body))
    assert history.turns[0].speaker_english == "English " + header.text
    low = DialogueHistory()
    for now in (0, 1.3):
        low.observe(
            (header, body),
            (header, body),
            (3840, 2160),
            now,
            scores={name.lines[0]: 0.99, title.lines[0]: 0.8},
            assisted=True,
        )
    low.accept_classifications(((key, Classification("dialogue", "yes")),))
    publish(low, (header, body))
    assert low.turns[0].speaker is None


def test_revealed_header_retracts_only_its_live_title_and_rejects_late_title_verdict():
    name, title, body = panel()
    history = DialogueHistory()
    previous = label(90, title.text, 100, 100, 500, 55)
    (old,) = settle(history, (previous,))
    history.accept_classifications(((old, Classification("dialogue", "no")),))
    publish(history, (previous,))
    # One isolated label can still look like anonymous speech to a classifier.
    (provisional,) = settle(history, (title,), 3)
    history.accept_classifications(((provisional, Classification("dialogue", "no")),))
    publish(history, (title,))
    assert len(list(history.turns)) == 2
    (key,) = settle(history, (name, title, body), 6)
    assert len(list(history.turns)) == 1 and history.turns[0].number == 1
    history.accept_classifications(
        ((provisional, Classification("dialogue", "no")), (key, Classification("dialogue", "yes")))
    )
    publish(history, (name, title, body))
    assert [t.source for t in history.turns] == [previous.text, body.text]


@pytest.mark.parametrize("single_line", (False, True))
def test_header_body_is_not_a_sibling_of_the_response_stack_below_it(single_line):
    name, title, body = panel()
    if single_line:
        body = TextBlock((replace(body.lines[0], text="新人よ、少し体を動かさないか？"),))
    first_y = body.bounds.y + body.bounds.height + 111
    first = label(5, "はい、一緒に行きましょう。", 978, first_y, 1400, 63)
    second = label(6, "いいえ、今は遠慮します。", 978, first_y + 174, 1400, 63)
    history = DialogueHistory()
    blocks = (name, title, body, first, second)
    keys = settle(history, blocks)
    spoken = next(k for k in keys if k.text == body.text)
    choices = tuple(k for k in keys if k.text != body.text)
    assert not spoken.panel.stacked_rows
    assert len(choices) == 2 and all(k.panel.stacked_rows == 2 for k in choices)
    assert all(k.speaker == "" for k in choices)  # The question is not the first option's speaker.
    assert any(n.relation == "headed_text" for n in choices[0].panel.neighbors)
    # A slow or wrong choice verdict cannot suppress the independently headed speech.
    history.accept_classifications(((spoken, Classification("dialogue", "yes")),))
    publish(history, blocks)
    assert [t.source for t in history.turns] == [body.text]
    history.accept_classifications(
        (
            (spoken, Classification("dialogue", "yes")),
            *((k, Classification("choice", "no")) for k in choices),
        )
    )
    publish(history, blocks)
    assert [t.source for t in history.turns] == [body.text]


def test_short_spoken_lines_are_not_name_title_metadata():
    name, title, body = panel()
    speech = tuple(
        replace(b, lines=(replace(b.lines[0], text=text),))
        for b, text in zip(
            (name, title), ("もう行きましょう。", "少し待ってください！"), strict=True
        )
    )
    keys = settle(DialogueHistory(), (*speech, body))
    assert {k.text for k in keys} == {b.text for b in (*speech, body)}


def test_header_context_is_stable_but_a_title_edit_invalidates_old_admission():
    blocks = panel()
    history = DialogueHistory()
    (key,) = settle(history, blocks)
    for i in range(5):
        moved = tuple(
            TextBlock(
                tuple(
                    replace(t, bounds=replace(t.bounds, x=t.bounds.x + i, y=t.bounds.y + i))
                    for t in b.lines
                )
            )
            for b in blocks
        )
        assert settle(history, tuple(reversed(moved)), 3 + i * 2) == (key,)
    name, title, body = blocks
    changed = replace(
        title, lines=(replace(title.lines[0], text="訓練施設の責任者", text_revision=2),)
    )
    (revised,) = settle(history, (name, changed, body), 20)
    assert revised != key
    history.accept_classifications(((key, Classification("dialogue", "yes")),))
    publish(history, (name, changed, body))
    assert not history.turns
