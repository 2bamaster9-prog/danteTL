from dataclasses import replace

import pytest

from dantetl.domain import CapturedFrame, Rect, WindowGeometry
from dantetl.languages.selection import source_language
from dantetl.ocr.tracking import TextActivity, TextTrack, TextTracker
from dantetl.ocr.values import OcrResult, TextRegion
from dantetl.translation.grouping import DialogueGrouper

FIRST = "新しい冒険がここから始まりますが、"
SECOND = "その前に旅の準備をしてください。"


class Reveal:
    def __init__(self) -> None:
        self.tracker, self.grouper = TextTracker(), DialogueGrouper()
        self.now, self.sequence = 0.0, 0

    def step(self, first: str, second: str = "", dt: float = 1 / 6):
        self.now += dt
        self.sequence += 1
        viewport = Rect(0, 0, 1920, 1080)
        frame = CapturedFrame(
            self.sequence, self.now, WindowGeometry(viewport, viewport, viewport, 96), b""
        )
        regions = [TextRegion("設定", Rect(1500, 50, 60, 32))]
        if first:
            regions.append(TextRegion(first, Rect(100, 700, len(first) * 32, 32)))
        if second:
            regions.append(TextRegion(second, Rect(100, 744, len(second) * 32, 32)))
        self.tracker.observe(OcrResult(frame, tuple(regions), 25, self.now + 0.025))
        # Capture advances independently; polling must not pretend a candidate is static.
        latest = replace(frame, sequence=self.sequence + 1)
        return self.grouper.update(
            self.tracker.visible(latest, self.now + 0.025),
            self.tracker.translation_tracks(latest, self.now + 0.025),
            self.now + 0.025,
            activity=self.tracker.translation_activity(),
        )


def test_typewriter_waits_for_the_complete_paragraph_without_stacked_group_delay() -> None:
    replay = Reveal()
    for count in (1, 5, 10, 15, len(FIRST)):
        grouped = replay.step(FIRST[:count])
        assert not any(b.text != "設定" for b in grouped.ready)
    for count in (1, 5, 10, len(SECOND)):
        grouped = replay.step(FIRST, SECOND[:count])
        assert not any(b.text != "設定" for b in grouped.ready)
        assert len(grouped.blocks) == 2  # Menu plus the evolving paragraph, already grouped.
    finished_at = replay.now
    ready = replay.step(FIRST, SECOND).ready
    assert {b.text for b in ready} == {"設定", FIRST + SECOND}
    assert replay.now - finished_at < 0.2
    paragraph = next(b for b in ready if len(b.lines) == 2)
    assert paragraph.lines[0].track_id == 2  # Initial one-character reading retained its identity.


def test_unpunctuated_reveal_waits_for_a_quiet_period_but_does_not_stall_forever() -> None:
    replay = Reveal()
    for count in (1, 5, 10):
        assert not any(b.text != "設定" for b in replay.step(FIRST[:count]).ready)
    assert not any(b.text != "設定" for b in replay.step(FIRST[:10]).ready)
    assert any(b.text == FIRST[:10] for b in replay.step(FIRST[:10], dt=0.6).ready)


def test_pause_after_a_comma_waits_for_the_second_row():
    replay = Reveal()
    replay.step(FIRST[:7])
    replay.step(FIRST)
    assert not any(b.text == FIRST for b in replay.step(FIRST, dt=1.2).ready)
    replay.step(FIRST, SECOND)
    assert any(b.text == FIRST + SECOND for b in replay.step(FIRST, SECOND, dt=0.25).ready)


def test_static_ocr_comma_cannot_strand_a_finished_turn():
    replay = Reveal()
    replay.step(FIRST)
    assert any(b.text == FIRST for b in replay.step(FIRST, dt=1.6).ready)


@pytest.mark.parametrize(
    ("code", "text"),
    [
        ("ja", "マイレージ425/79710"),
        ("ja", "体力　４２５ ／ ７９７１０"),
        ("en", "Energy: 425/79710"),
    ],
)
def test_confirmed_status_counters_skip_dialogue_wait_only_when_static(code, text):
    grouper = DialogueGrouper(language=source_language(code))
    line = TextTrack(1, text, Rect(50, 100, 300, 20))
    observed = TextActivity(line, 1, False, False)

    def ready(confirmed, activity):
        return grouper.update((line,), confirmed, 1.01, activity=(activity,)).ready

    assert not ready((), observed)
    assert not ready((line,), replace(observed, pending=True))
    assert not ready((line,), replace(observed, growing=True))
    assert ready((line,), observed)[0].text == text


def test_prose_dates_and_incomplete_counters_keep_the_dialogue_wait():
    for text in (
        "残っているのは425/79710",
        "Collected 425/79710 today",
        "次の更新2026/11/21",
        "マイレージ12345/",
    ):
        line = TextTrack(1, text, Rect(50, 100, 300, 20))
        grouper = DialogueGrouper()
        activity = (TextActivity(line, 1, False, False),)
        assert not grouper.update((line,), (line,), 1.01, activity=activity).ready
        assert grouper.update((line,), (line,), 1.6, activity=activity).ready


def test_visual_readiness_only_accelerates_a_whole_isolated_sentence():
    language = source_language("en")
    grouper = DialogueGrouper(language=language)
    line = TextTrack(1, "Is the door open?", Rect(50, 100, 170, 20))
    activity = TextActivity(line, 1, False, False)

    def ready(track, observed):
        return grouper.update(
            (track,), (), 1.065, activity=(observed,), complete_lines=frozenset((track,))
        ).ready

    assert ready(line, activity)
    assert not ready(line, replace(activity, growing=True))
    assert not ready(line, replace(activity, pending=True))
    for fragment in (
        "Please talk to Dr.",
        "We could try…",
        "“Is the door open?",
        "When we get there,",
    ):
        edit = replace(line, text=fragment)
        assert not ready(edit, replace(activity, observation=edit))


def test_pending_source_edits_cannot_be_enqueued_as_the_old_confirmed_fragment() -> None:
    replay = Reveal()
    replay.step(FIRST, SECOND)
    assert any(len(b.lines) == 2 for b in replay.step(FIRST, SECOND).ready)
    changed = replay.step(FIRST, "違う文章に変わっています。")
    assert not any(len(b.lines) == 2 for b in changed.ready)


def test_revealed_multi_sentence_dialogue_can_join_after_a_completed_first_sentence() -> None:
    replay = Reveal()
    first = "新しい冒険がここから始まります。"
    for count in (1, 5, 10, len(first)):
        replay.step(first[:count])
    for count in (1, 5, len(SECOND)):
        assert len(replay.step(first, SECOND[:count]).blocks) == 2
    assert any(b.text == first + SECOND for b in replay.step(first, SECOND).ready)
