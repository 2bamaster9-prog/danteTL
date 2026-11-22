"""Unchanged-scene work budgets and time/readiness independent of cached evidence."""

from dataclasses import replace

from dantetl.domain import Rect
from dantetl.ocr.observation import TextTrack
from dantetl.translation.dialogue.classifier import Classification
from dantetl.translation.dialogue.history import DialogueHistory
from dantetl.translation.grouping import TextBlock
from dantetl.translation.values import TranslatedText, TranslationRequest


def block(i, text, x, y, width=300, height=24):
    return TextBlock((TextTrack(i, text, Rect(x, y, width, height)),))


def publish(history, rows):
    history.published(
        tuple(TranslatedText(TranslationRequest.from_block(b), "English") for b in rows)
    )


def test_dense_unchanged_polls_do_not_repeat_geometry_work_but_readiness_and_time_advance(
    monkeypatch,
):
    rows = tuple(
        block(i, f"これは確認するための文章です{i}。", 100 + i % 8 * 450, 100 + i // 8 * 90)
        for i in range(128)
    )
    history = DialogueHistory()
    history.observe(rows, (), (3840, 2160), 0, assisted=True)
    geometry_reads = 0
    original = TextBlock.bounds.fget
    assert original is not None

    def bounds(value):
        nonlocal geometry_reads
        geometry_reads += 1
        return original(value)

    monkeypatch.setattr(TextBlock, "bounds", property(bounds))
    for poll in range(60):
        history.observe(
            tuple(reversed(rows)) if poll % 2 else rows, (), (3840, 2160), poll / 30, assisted=True
        )
        assert not history.classification_requests()
    history.observe(rows, rows, (3840, 2160), 2, assisted=True)
    keys = history.classification_requests()
    assert len(keys) == 128
    # Work budget independent of repeated UI polls; no wall-clock/flaky timing limit.
    assert geometry_reads <= len(rows)
    history.accept_classifications(tuple((k, Classification("dialogue", "no")) for k in keys))
    publish(history, rows)
    assert len(history.turns) == 20
    previous = history.turns
    history.observe(rows, (), (3840, 2160), 3, assisted=True)
    assert not history.classification_requests()
    publish(history, rows)
    assert history.turns == previous
    history.clear()
    history.observe(rows, rows, (3840, 2160), 4, assisted=True)
    publish(history, rows)
    assert not history.turns


def test_cached_evidence_accepts_late_speaker_confidence_corrections_and_scene_reset():
    name = block(1, "リナ", 200, 700, 80)
    body = block(2, "私と一緒に進んでください。", 200, 750, 500)
    rows = (name, body)
    history = DialogueHistory()
    history.observe(rows, rows, (1920, 1080), 0, scores={name.lines[0]: 0.7}, assisted=True)
    history.observe(rows, rows, (1920, 1080), 2, assisted=True)
    key = next(k for k in history.classification_requests() if k.text == body.text)
    history.accept_classifications(((key, Classification("dialogue", "yes")),))
    publish(history, rows)
    assert len(history.turns) == 1 and history.turns[0].speaker is None
    history.observe(rows, rows, (1920, 1080), 3, scores={name.lines[0]: 0.99}, assisted=True)
    publish(history, rows)
    assert len(history.turns) == 1 and history.turns[0].speaker == name.text
    changed = replace(
        body, lines=(replace(body.lines[0], text="私と一緒に進んで下さい。", text_revision=2),)
    )
    corrected = (name, changed)
    for timestamp in (4, 6):
        history.observe(
            corrected,
            corrected,
            (1920, 1080),
            timestamp,
            corrections=((changed.lines[0], body.lines[0]),),
            assisted=True,
        )
    history.accept_classifications(
        tuple((k, Classification("dialogue", "yes")) for k in history.classification_requests())
    )
    publish(history, corrected)
    assert len(history.turns) == 1 and history.turns[0].source == changed.text
    history.reset_scene()
    history.observe(corrected, corrected, (1920, 1080), 7, assisted=True)
    publish(history, corrected)
    assert len(history.turns) == 1  # A reset invalidates the old semantic verdict.
    history.start()
    assert not history.turns
