import threading
import time
from dataclasses import replace

import cv2
import numpy as np

from jp_overlay.domain import CapturedFrame, Rect, WindowGeometry
from jp_overlay.grouping import DialogueGrouper
from jp_overlay.recognition import (
    OcrResult,
    OcrSession,
    TextCharacter,
    TextRegion,
    recognize_regions,
)
from jp_overlay.regions import padded, scan_regions
from jp_overlay.tracking import TextTrack, TextTracker
from jp_overlay.visual import VisualAnalyzer, VisualSession, VisualState


def frame(sequence=1, *, size=(1000, 600), fill=30):
    bounds = Rect(-300, 50, *size)
    return CapturedFrame(
        sequence,
        sequence / 8,
        WindowGeometry(bounds, bounds, bounds, 168),
        bytes((fill, fill, fill, 255)) * (size[0] * size[1]),
    )


def wait_for(predicate):
    end = time.monotonic() + 4
    while not predicate():
        assert time.monotonic() < end
        time.sleep(0.005)


def test_scan_closure_includes_whole_intersected_lines_and_stays_disjoint():
    lines = (Rect(50, 100, 500, 30), Rect(60, 143, 420, 30))
    areas = scan_regions(
        (padded(Rect(200, 120, 10, 10), (1000, 600)), Rect(800, 400, 80, 60)), (1000, 600), lines
    )
    assert areas and len(areas) == 2
    assert all(any(a.contains(line) for a in areas) for line in lines)
    assert all(Rect(0, 0, 1000, 600).contains(a) for a in areas)
    assert scan_regions((Rect(0, 0, 800, 600),), (1000, 600)) is None
    assert scan_regions(tuple(Rect(x * 100, 0, 20, 20) for x in range(5)), (1000, 600)) is None
    assert scan_regions((), (1000, 600)) == ()


def test_crops_use_source_pixels_and_translate_line_and_character_coordinates_once():
    source = frame()
    seen = []

    class Engine:
        def recognize(self, image):
            seen.append(image)
            return (
                TextRegion(
                    "設定",
                    Rect(10, 10, 40, 20),
                    (TextCharacter("設定", Rect(12, 11, 35, 18), 0.95),),
                    True,
                ),
            )

        def close(self) -> None:
            pass

    areas = (Rect(100, 200, 100, 60), Rect(600, 300, 120, 70))
    regions, coverage = recognize_regions(Engine(), source, areas)
    assert coverage == areas
    assert [r.bounds for r in regions] == [Rect(110, 210, 40, 20), Rect(610, 310, 40, 20)]
    assert regions[1].characters[0].bounds == Rect(612, 311, 35, 18)
    assert regions[1].vertical
    assert [i.geometry.client.size for i in seen] == [a.size for a in areas]
    assert all(i.sequence == source.sequence and i.captured_at == source.captured_at for i in seen)
    assert seen[0].bgra == bytes((30, 30, 30, 255)) * 6000


def test_cut_off_detection_retries_full_frame_instead_of_publishing_a_fragment():
    calls = []

    class Engine:
        def recognize(self, image):
            calls.append(image.width)
            return (
                TextRegion("完全な文章" if image.width == 1000 else "完全", Rect(0, 10, 80, 20)),
            )

        def close(self) -> None:
            pass

    regions, coverage = recognize_regions(Engine(), frame(), (Rect(100, 100, 200, 100),))
    assert coverage is None and regions[0].text == "完全な文章"
    assert calls == [200, 1000]
    # The actual window edge is not an artificial crop boundary.
    regions, coverage = recognize_regions(Engine(), frame(), (Rect(0, 100, 200, 100),))
    assert coverage is not None and len(calls) == 3


def test_partial_misses_cannot_remove_unscanned_tracks_or_split_dialogue():
    tracker, grouper = TextTracker(), DialogueGrouper()
    lines = (
        TextRegion("旅の準備をしてから、", Rect(40, 100, 330, 30)),
        TextRegion("一緒に出かけましょう。", Rect(40, 140, 300, 30)),
    )
    initial = frame()
    tracker.observe(OcrResult(initial, lines, 20, 0.2))
    original = tracker.translation_tracks(initial, 1)
    group = grouper.update(original, original, 1, activity=tracker.translation_activity())
    assert len(group.ready) == 1 and len(group.ready[0].lines) == 2
    for i in range(2, 20):
        source = frame(i, fill=i * 3)
        tracker.observe(OcrResult(source, (), 20, source.captured_at, (Rect(700, 400, 100, 100),)))
        assert tracker.translation_tracks(source, 100) == original
        assert (
            grouper.update(original, original, 100, activity=tracker.translation_activity()).ready
            == group.ready
        )
    # Scanning only the continuation changes the complete group's request, not its first line.
    source = frame(20)
    revised = replace(lines[1], text="ここで待ってください。")
    tracker.observe(
        OcrResult(source, (revised,), 20, source.captured_at, (Rect(20, 135, 400, 45),))
    )
    current = tracker.translation_tracks(source, source.captured_at + 0.6)
    assert current[0] == original[0]
    grouped = grouper.update(
        current, current, source.captured_at + 1, activity=tracker.translation_activity()
    )
    assert len(grouped.ready) == 1 and grouped.ready[0].text.endswith(revised.text)


def test_later_unrelated_scan_does_not_settle_an_earlier_negative_observation():
    tracker = TextTracker()
    source = frame(1)
    box = Rect(20, 30, 90, 25)
    tracker.observe(OcrResult(source, (TextRegion("設定", box),), 20, 0.2))
    tracker.visible(source, 1)
    source = frame(2, fill=60)
    tracker.observe(OcrResult(source, (), 20, 0.3, (Rect(0, 0, 200, 100),)))
    unrelated = frame(3, fill=60)
    tracker.observe(OcrResult(unrelated, (), 20, 0.4, (Rect(600, 400, 100, 100),)))
    assert tracker.visible(unrelated, 10)


def test_worker_unions_waiting_coverage_on_latest_frame_and_waits_for_acknowledgement():
    entered, release = threading.Event(), threading.Event()
    calls = []

    class Engine:
        def recognize(self, source):
            calls.append((source.sequence, source.width))
            if source.sequence == 1:
                entered.set()
                assert release.wait(4)
            return ()

        def close(self) -> None:
            pass

    session = OcrSession(Engine, require_ack=True)
    session.start()
    try:
        session.submit(frame(1))
        assert entered.wait(4)
        a, b = Rect(10, 20, 100, 60), Rect(600, 400, 120, 70)
        session.submit(frame(2), (a,))
        session.submit(frame(3), (b,))
        release.set()
        wait_for(lambda: session.snapshot().result is not None)
        assert calls == [(1, 1000)]
        session.acknowledge(1)
        wait_for(lambda: (r := session.snapshot().result) is not None and r.frame.sequence == 3)
        assert calls == [(1, 1000), (3, 100), (3, 120)]
        result = session.snapshot().result
        assert result is not None and result.scanned == (a, b)
        session.submit(frame(4), (a,))
        session.invalidate()  # An unacknowledged old result cannot strand resume or stop.
        session.submit(frame(4), (b,))
        wait_for(lambda: session.snapshot().result is not None)
        result = session.snapshot().result
        assert result is not None and result.frame.sequence == 4
    finally:
        release.set()
        session.request_stop()
        wait_for(lambda: session.finished)


def ink_frame(sequence, *, label=False, continuation=False):
    source = frame(sequence)
    pixels = np.frombuffer(source.bgra, np.uint8).reshape(600, 1000, 4).copy()
    for x in range(50, 350, 18):
        cv2.rectangle(pixels, (x, 100), (x + 10, 120), (230, 230, 230, 255), 2)
    if continuation:
        for x in range(50, 140, 18):
            cv2.rectangle(pixels, (x, 140), (x + 10, 160), (230, 230, 230, 255), 2)
    if label:
        cv2.putText(
            pixels, "MENU", (770, 470), cv2.FONT_HERSHEY_SIMPLEX, 1, (230, 230, 230, 255), 2
        )
    return replace(source, bgra=pixels.tobytes())


def test_new_menu_is_scanned_locally_while_unrelated_dialogue_keeps_revealing():
    visual = VisualAnalyzer()
    source = ink_frame(1)
    track = TextTrack(1, "これから長い文章が表示されます", Rect(48, 98, 310, 25))
    result = OcrResult(source, (TextRegion(track.text, track.bounds),), 30, 0.2)
    visual.observe(source, result, (track,), (1,))
    visual.observe(ink_frame(4), result, (track,), (1,))
    state = visual.observe(ink_frame(5, label=True, continuation=True), result, (track,), (1,))
    assert state.request_ocr and state.scan_areas is not None
    assert any(a.contains(Rect(770, 448, 85, 28)) for a in state.scan_areas)
    assert all(not a.contains(track.bounds) for a in state.scan_areas)
    assert state.blocked == {1}


def test_periodic_full_scan_is_not_starved_by_frequent_small_changes():
    visual = VisualAnalyzer()
    full = []
    regional = []
    for i in range(1, 66):
        state = visual.observe(ink_frame(i, label=i % 4 < 2))
        if state.request_ocr:
            (full if state.scan_areas is None else regional).append(i)
    assert len(full) >= 3 and regional
    assert all(b - a <= 25 for a, b in zip(full, full[1:], strict=False))


def test_menu_request_does_not_consume_the_dialogues_later_settling_request():
    visual = VisualAnalyzer()
    first = ink_frame(1)
    track = TextTrack(1, "これから長い文章が表示されます", Rect(48, 98, 310, 25))
    result = OcrResult(first, (TextRegion(track.text, track.bounds),), 30, 0.2)
    visual.observe(first, result, (track,), (1,))
    visual.observe(ink_frame(4), result, (track,), (1,))
    visual.observe(ink_frame(5, continuation=True), result, (track,), (1,))
    menu = visual.observe(ink_frame(6, continuation=True, label=True), result, (track,), (1,))
    assert menu.request_ocr and menu.scan_areas
    assert all(not area.contains(track.bounds) for area in menu.scan_areas)
    settled = visual.observe(ink_frame(7, continuation=True, label=True), result, (track,), (1,))
    assert settled.request_ocr
    assert settled.scan_areas is None or any(
        area.contains(track.bounds) for area in settled.scan_areas
    )


def test_unconsumed_visual_requests_union_coverage_on_the_newest_frame(monkeypatch):
    a, b = Rect(10, 20, 100, 60), Rect(600, 400, 120, 70)

    class Analyzer:
        def observe(self, source, *args):
            return VisualState(source, True, scan_areas=(a if source.sequence == 1 else b,))

    monkeypatch.setattr("jp_overlay.visual.VisualAnalyzer", Analyzer)
    session = VisualSession()
    session.start()
    try:
        session.submit(frame(1), None, (), (), ())
        wait_for(lambda: session._snapshot.frame is not None)
        session.submit(frame(2), None, (), (), ())
        wait_for(lambda: (s := session._snapshot.frame) is not None and s.sequence == 2)
        state = session.poll()
        assert state.request_ocr and state.scan_areas == (a, b)
        assert state.frame and state.frame.sequence == 2
        assert not session.poll().request_ocr
    finally:
        session.request_stop()
        wait_for(lambda: session.finished)


def test_unrelated_partial_scan_cannot_delay_confirmation_of_a_finished_dialogue_edit():
    tracker, visual = TextTracker(), VisualAnalyzer()
    box = Rect(48, 98, 310, 25)
    first = OcrResult(ink_frame(1), (TextRegion("これから長い文章が表示されます", box),), 30, 0.2)
    ids = tracker.observe(first)
    old = tracker.translation_tracks(first.frame, 1)
    visual.observe(first.frame, first, old, ids)
    edit = OcrResult(
        ink_frame(2),
        (TextRegion("新しい冒険を始めましょう。", box),),
        30,
        0.3,
        (Rect(0, 80, 500, 100),),
    )
    ids = tracker.observe(edit)
    visual.observe(edit.frame, edit, old, ids, tracker.translation_activity())
    unrelated = OcrResult(ink_frame(4), (), 20, 0.55, (Rect(700, 400, 200, 100),))
    ids = tracker.observe(unrelated)
    state = visual.observe(unrelated.frame, unrelated, old, ids, tracker.translation_activity())
    assert state.stable_tracks == ((old[0].track_id, 2, edit.regions[0].text),)
    tracker.confirm_observations(state.stable_tracks, unrelated.frame.captured_at)
    assert tracker.visible(unrelated.frame, 0.55)[0].text == edit.regions[0].text
    newer = replace(
        edit, frame=ink_frame(5), regions=(TextRegion("次の文章に変わりました。", box),)
    )
    tracker.observe(newer)
    tracker.confirm_observations(state.stable_tracks, 0.7)
    assert tracker.visible(newer.frame, 0.7)[0].text == edit.regions[0].text
