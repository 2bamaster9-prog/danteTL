"""Detached single replies and short named speech, without screenshots or real models."""

import time
from dataclasses import replace

import pytest

from jp_overlay.dialogue_classifier import Classification, ClassifierSession
from jp_overlay.dialogue_history import DialogueHistory
from jp_overlay.domain import Rect
from jp_overlay.grouping import TextBlock
from jp_overlay.history_layout import PanelLayout
from jp_overlay.tracking import TextTrack
from jp_overlay.translation import TranslatedText, TranslationRequest


def block(key, text, x, y, width, height):
    return TextBlock((TextTrack(key, text, Rect(x, y, width, height)),))


def screenshot_rows():
    # Actual local OCR bounds. The interaction icon/key was not detected as text.
    return (
        block(1, "厳彦(ゴンゲン)", 1613, 1535, 559, 79),
        block(2, "仮想訓練場」教官", 1722, 1624, 429, 56),
        block(3, "来たか、新人。", 1705, 1770, 382, 64),
        block(4, "ここで何を学べる?", 2572, 1367, 462, 51),
    )


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


def transform(blocks, scale=1, mirror=False, shift=0):
    return tuple(
        TextBlock(
            tuple(
                replace(
                    t,
                    bounds=Rect(
                        round(
                            (3840 - t.bounds.x - t.bounds.width if mirror else t.bounds.x) * scale
                        )
                        + shift,
                        round(t.bounds.y * scale) + shift,
                        round(t.bounds.width * scale),
                        round(t.bounds.height * scale),
                    ),
                )
                for t in b.lines
            )
        )
        for b in blocks
    )


@pytest.mark.parametrize("scale", (0.5, 1, 1.5))
@pytest.mark.parametrize("mirror", (False, True))
def test_short_speech_survives_and_one_detached_reply_gets_named_panel_context(scale, mirror):
    rows = transform(screenshot_rows(), scale, mirror)
    name, title, body, reply = rows
    history = DialogueHistory()
    keys = settle(history, tuple(reversed(rows)))
    assert {k.text for k in keys} == {body.text, reply.text}
    spoken = next(k for k in keys if k.text == body.text)
    option = next(k for k in keys if k.text == reply.text)
    assert spoken.speaker == name.text and spoken.panel.stacked_rows == 0
    assert not spoken.panel.detached_response and option.panel.detached_response
    assert not option.speaker and option.panel.stacked_rows == 0
    assert {(n.relation, n.text) for n in option.panel.neighbors} == {
        ("headed_text", body.text),
        ("panel_speaker", name.text),
        ("panel_speaker_detail", title.text),
    }
    assert option.panel.payload()["layout"] == "possible_single_response"
    # Neither history admission nor translation has to wait for the detached row.
    history.accept_classifications(((spoken, Classification("dialogue", "yes")),))
    publish(history, rows)
    assert [t.source for t in history.turns] == [body.text]
    assert history.turns[0].speaker_english == "English " + name.text
    history.accept_classifications(
        ((spoken, Classification("dialogue", "yes")), (option, Classification("choice", "no")))
    )
    publish(history, rows)
    assert [t.source for t in history.turns] == [body.text]


def test_new_header_evidence_recovers_a_short_line_mistaken_for_a_choice():
    name, title, body, reply = screenshot_rows()
    history = DialogueHistory()
    old = settle(history, (title, body))
    assert len(old) == 2 and all(k.panel.stacked_rows == 2 for k in old)
    history.accept_classifications(tuple((k, Classification("choice", "no")) for k in old))
    publish(history, (title, body))
    # Unchanged choice evidence is retained; merely removing siblings is insufficient.
    assert not settle(history, (body,), 3)
    keys = settle(history, (name, title, body, reply), 6)
    spoken = next(k for k in keys if k.text == body.text)
    history.accept_classifications(((spoken, Classification("dialogue", "yes")),))
    publish(history, (name, title, body, reply))
    assert [t.source for t in history.turns] == [body.text]


def test_genuine_headered_choice_does_not_recheck_on_every_geometry_jitter():
    rows = screenshot_rows()[:3]
    history = DialogueHistory()
    (key,) = settle(history, rows)
    history.accept_classifications(((key, Classification("choice", "no")),))
    publish(history, rows)
    assert not settle(history, transform(rows, shift=2), 3)
    assert not history.turns


def test_isolated_words_and_distant_hud_are_not_assumed_to_be_options():
    rows = screenshot_rows()
    (key,) = settle(DialogueHistory(), (rows[-1],))
    assert not key.panel.detached_response and not key.panel.neighbors
    hud = block(9, "説明を表示してください。", 3300, 100, 450, 50)
    keys = settle(DialogueHistory(), (*rows, hud))
    assert not next(k for k in keys if k.text == hud.text).panel.detached_response


def test_two_equally_near_panels_do_not_give_a_detached_row_an_arbitrary_speaker():
    panels = tuple(
        b
        for i, x in enumerate((100, 1400))
        for b in (
            block(i * 3, "旅の案内人", x, 300, 220, 50),
            block(i * 3 + 1, "北の街の住人", x, 360, 180, 35),
            block(i * 3 + 2, "また会ったね。", x, 460, 200, 40),
        )
    )
    row = block(10, "何のことですか？", 750, 200, 220, 40)
    layout = PanelLayout()
    layout.update((*panels, row))
    assert layout.header(panels[2]) and layout.header(panels[5])
    assert not layout.context(row).detached_response
    assert all(not layout.context(b).detached_response for b in (panels[2], panels[5]))


def until(predicate):
    deadline = time.monotonic() + 3
    while not predicate():
        assert time.monotonic() < deadline
        time.sleep(0.005)


def test_unchanged_panels_reuse_calls_and_changed_main_text_revokes_the_old_reply_verdict():
    calls = []

    class Engine:
        def classify(self, value, cancelled):
            calls.append(value)
            return Classification("choice" if value.panel.detached_response else "dialogue", "no")

        def close(self):
            pass

    session, history = ClassifierSession(Engine), DialogueHistory()
    rows = screenshot_rows()
    try:
        keys = settle(history, rows)
        session.update(keys)
        until(lambda: session.snapshot().pending == 0)
        for i in range(6):
            moved = transform(rows, shift=i % 3)
            repeated = settle(history, tuple(reversed(moved)), 3 + i * 2)
            assert repeated == keys
            session.update(repeated)
        assert len(calls) == 2
        changed = (
            *rows[:2],
            replace(
                rows[2], lines=(replace(rows[2].lines[0], text="準備はいいか？", text_revision=2),)
            ),
            rows[3],
        )
        revised = settle(history, changed, 20)
        history.accept_classifications(tuple((k, Classification("dialogue", "no")) for k in keys))
        publish(history, changed)
        assert not history.turns
        session.update(revised)
        until(lambda: session.snapshot().pending == 0)
        assert len(calls) == 4
        session.update(keys)
        until(lambda: session.snapshot().pending == 0)
        assert len(calls) == 4
    finally:
        session.request_stop()
        until(lambda: session.finished)
