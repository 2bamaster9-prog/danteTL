"""Scene replays for contextual classification, independent of any real model."""

import json
import time
from dataclasses import replace

import pytest

from dantejp.domain import Rect
from dantejp.ocr.tracking import TextTrack
from dantejp.translation.dialogue.classifier import (
    Classification,
    ClassifierSession,
    parse_classification,
)
from dantejp.translation.dialogue.history import DialogueHistory
from dantejp.translation.dialogue.layout import PanelLayout
from dantejp.translation.grouping import TextBlock
from dantejp.translation.worker import TranslatedText, TranslationRequest


def block(key, text, x=300, y=300, width=600, height=40):
    return TextBlock((TextTrack(key, text, Rect(x, y, width, height)),))


def options():
    return (
        block(1, "それなら私が手伝おう。", y=300),
        block(2, "今は無理だ。", y=410, width=450),
        block(3, "もう少し詳しく教えて。", y=520, width=700),
    )


def move(blocks, scale=1, dx: float = 0, dy: float = 0):
    return tuple(
        TextBlock(
            tuple(
                replace(
                    t,
                    bounds=Rect(
                        round(t.bounds.x * scale + dx),
                        round(t.bounds.y * scale + dy),
                        round(t.bounds.width * scale),
                        round(t.bounds.height * scale),
                    ),
                )
                for t in b.lines
            )
        )
        for b in blocks
    )


def settle(history, blocks, now=0):
    history.observe(blocks, blocks, (3840, 2160), now, assisted=True)
    history.observe(blocks, blocks, (3840, 2160), now + 1.3, assisted=True)
    return history.classification_requests()


def publish(history, blocks):
    history.published(
        tuple(TranslatedText(TranslationRequest.from_block(b), "English " + b.text) for b in blocks)
    )


def until(condition):
    deadline = time.monotonic() + 3
    while not condition():
        assert time.monotonic() < deadline
        time.sleep(0.005)


@pytest.mark.parametrize("alignment", ["left", "center", "right"])
@pytest.mark.parametrize("scale", [0.5, 1, 2])
def test_unmarked_response_stack_has_same_context_across_resolution_and_order(alignment, scale):
    rows = options()
    if alignment != "left":
        rows = tuple(
            move((b,), dx=(600 - b.bounds.width) / (2 if alignment == "center" else 1))[0]
            for b in rows
        )
    first = PanelLayout()
    first.update(rows)
    changed = move(rows, scale, 33, -15)
    second = PanelLayout()
    second.update(tuple(reversed(changed)))
    for before, after in zip(rows, changed, strict=True):
        assert first.context(before) == second.context(after)
        assert first.context(before).stacked_rows == 3
        assert {n.text for n in first.context(before).neighbors} == {
            b.text for b in rows if b != before
        }


def test_wrapped_paragraph_separate_bubbles_and_columns_are_not_choice_stacks():
    paragraph = TextBlock(
        (
            TextTrack(1, "ここから先は危険だから、", Rect(100, 300, 600, 40)),
            TextTrack(2, "一緒に進んでください。", Rect(100, 355, 500, 40)),
        )
    )
    bubble = block(3, "大丈夫、私についてきて。", x=1800, y=400)
    heading = block(4, "案内人", x=100, y=220, width=120, height=45)
    layout = PanelLayout()
    layout.update((paragraph, bubble, heading))
    assert not layout.peers(paragraph) and not layout.peers(bubble)
    assert all(n.text != bubble.text for n in layout.context(paragraph).neighbors)
    # Tight rows remain paragraph evidence even with grouping temporarily disabled.
    fragments = tuple(TextBlock((t,)) for t in paragraph.lines)
    layout.update(fragments)
    assert all(not layout.peers(b) for b in fragments)


def test_common_alignment_survives_similar_width_rows_but_not_a_drifting_chain():
    rows = tuple(
        block(i, "これは選択肢です。", x=600 - width // 2, y=300 + i * 110, width=width)
        for i, width in enumerate((600, 580, 400))
    )
    layout = PanelLayout()
    layout.update(rows)
    assert all(layout.peers(b) == rows for b in rows)
    # Each local pair nearly aligns, but the first and last share no panel axis.
    drift = tuple(block(i, "これは文章です。", x=300 + i * 25, y=300 + i * 110) for i in range(4))
    layout.update(drift)
    assert all(len(layout.peers(b)) < 4 for b in drift)


def test_multiline_options_use_outer_gaps_and_do_not_swallow_a_nearby_dialogue_panel():
    first = TextBlock(
        (
            TextTrack(1, "まずは街へ戻って、", Rect(1200, 300, 500, 40)),
            TextTrack(2, "仲間に知らせよう。", Rect(1200, 350, 440, 40)),
        )
    )
    second = block(3, "このまま先へ進もう。", x=1200, y=460, width=500)
    spoken = block(4, "君はどうするつもりだ？", x=100, y=600, width=600)
    layout = PanelLayout()
    layout.update((first, second, spoken))
    assert layout.peers(first) == (first, second)
    assert not layout.peers(spoken)
    assert any(n.multiline for n in layout.context(second).neighbors)


def test_marker_on_one_alternative_excludes_the_whole_structural_list():
    rows = options()
    rows = (replace(rows[0], lines=(replace(rows[0].lines[0], text="▶私が手伝おう。"),)), *rows[1:])
    assert not settle(DialogueHistory(), rows)


def test_choice_verdict_excludes_siblings_before_any_can_enter_history():
    history = DialogueHistory()
    rows = options()
    keys = settle(history, rows)
    assert len(keys) == 3
    assert all(k.speaker == "" for k in keys)  # Other options are not character names.
    history.accept_classifications(((keys[0], Classification("dialogue", "no")),))
    publish(history, rows)
    assert not history.turns  # A fast first reply cannot race a pending sibling.
    history.accept_classifications(
        tuple(
            (k, Classification("choice" if i == 1 else "dialogue", "no"))
            for i, k in enumerate(keys)
        )
    )
    publish(history, rows)
    assert not history.turns
    # Hiding the other options is not evidence that the remaining option was spoken.
    assert not settle(history, (rows[0],), 2)
    # The same words later spoken alone need a fresh role check, not a permanent blacklist.
    alone = move((rows[0],), dx=50, dy=600)
    current = settle(history, alone, 3)
    assert len(current) == 1 and current[0] != keys[0]
    history.accept_classifications(((current[0], Classification("dialogue", "no")),))
    publish(history, alone)
    assert [t.source for t in history.turns] == [rows[0].text]


def test_new_option_context_immediately_revokes_old_verdict_but_must_settle_for_new_work():
    history = DialogueHistory()
    rows = options()
    old = settle(history, (rows[0],))[0]
    history.accept_classifications(((old, Classification("dialogue", "no")),))
    history.observe(rows, rows, (3840, 2160), 2, assisted=True)
    assert not history.classification_requests()
    history.accept_classifications(((old, Classification("dialogue", "no")),))
    publish(history, rows)
    assert not history.turns
    history.observe(rows, rows, (3840, 2160), 3.3, assisted=True)
    assert len(history.classification_requests()) == 3


def test_revealed_options_correct_only_their_live_premature_history_entry():
    history = DialogueHistory()
    rows = options()
    earlier = block(90, "これは前の場面の会話です。", x=1600)
    key = settle(history, (earlier,))[0]
    history.accept_classifications(((key, Classification("dialogue", "no")),))
    publish(history, (earlier,))
    first = settle(history, (rows[0],), 3)[0]
    history.accept_classifications(((first, Classification("dialogue", "no")),))
    publish(history, (rows[0],))
    assert len(history.turns) == 2
    keys = settle(history, rows, 6)
    history.accept_classifications(tuple((k, Classification("choice", "no")) for k in keys))
    publish(history, rows)
    assert [t.source for t in history.turns] == [earlier.text]


def test_panel_changes_recheck_once_but_jitter_reorder_polling_and_unrelated_hud_do_not():
    calls = []

    class Engine:
        def classify(self, value, cancelled):
            calls.append(value)
            return Classification("choice" if value.panel.stacked_rows else "dialogue", "no")

        def close(self):
            pass

    history, session = DialogueHistory(), ClassifierSession(Engine)
    rows = options()
    try:
        keys = settle(history, rows)
        session.update(keys)
        until(lambda: session.snapshot().pending == 0)
        for i in range(20):
            shifted = move(rows, dx=i % 3, dy=i % 2)
            hud = block(99, f"所持金{i}", x=3200, y=50, width=100)
            repeated = settle(history, (*reversed(shifted), hud), 3 + i * 2)
            assert repeated == keys
            session.update(repeated)
        assert len(calls) == 3
        # Same body in a different panel role must not reuse its choice verdict.
        alone = settle(history, (rows[0],), 50)
        session.update(alone)
        until(lambda: session.snapshot().pending == 0)
        assert len(calls) == 4
        # Return to the original exact panel reuses its cached outcomes.
        session.update(settle(history, rows, 53))
        until(lambda: session.snapshot().pending == 0)
        assert len(calls) == 4
    finally:
        session.request_stop()
        until(lambda: session.finished)


def test_loading_heading_and_nearby_controls_are_context_not_an_assumed_speaker():
    history = DialogueHistory()
    heading = block(1, "ロード中のヒント", width=250)
    quote = block(2, "危険を感じたら、すぐに逃げてください。", y=380)
    keys = settle(history, (heading, quote))
    key = next(k for k in keys if k.text == quote.text)
    assert heading.text == key.speaker or any(n.text == heading.text for n in key.panel.neighbors)
    history.accept_classifications(
        ((key, parse_classification('{"kind":"loading","speaker":"no"}')),)
    )
    publish(history, (heading, quote))
    assert not history.turns


def test_real_neighbor_edits_are_not_hidden_by_excerpt_truncation_and_dense_context_is_bounded():
    body = block(1, "ここで待っていてください。", y=600)
    text = "詳しい説明" * 70
    heading = block(2, text, y=520)
    layout = PanelLayout()
    layout.update((body, heading))
    before = layout.context(body)
    edited = replace(
        heading, lines=(replace(heading.lines[0], text=text[:150] + "新" + text[151:]),)
    )
    layout.update((body, edited))
    assert layout.context(body) != before
    dense = tuple(
        block(i, "これは長い説明文です。" * 20, x=(i % 8) * 700, y=(i // 8) * 110)
        for i in range(128)
    )
    layout.update(dense)
    for b in dense:
        panel = layout.context(b)
        assert len(panel.neighbors) <= 4
        assert sum(len(n.text) for n in panel.neighbors) <= 192
        assert "digest" not in json.dumps(panel.payload())
