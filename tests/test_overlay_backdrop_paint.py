import os
import time
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from dantetl.domain import Rect  # noqa: E402
from dantetl.ocr.observation import TextTrack  # noqa: E402
from dantetl.translation.grouping import TextBlock  # noqa: E402
from dantetl.translation.values import TranslatedText, TranslationRequest  # noqa: E402
from dantetl.ui import overlay  # noqa: E402


def test_native_blur_follows_painted_labels_and_retires_before_replacements(monkeypatch):
    app = QApplication.instance() or QApplication([])
    native = Mock()
    events = []

    def place(hwnd, bounds, boxes, *, included):
        events.append(("place", boxes))
        return frozenset(boxes)

    native.place.side_effect = place
    monkeypatch.setattr(overlay, "LabelBackdrops", lambda windows: native)
    monkeypatch.setattr(overlay.QGuiApplication, "platformName", lambda: "windows")

    class Surface(overlay.OverlayWindow):
        def _paint_english(self, painter, layout, *, blurred):
            super()._paint_english(painter, layout, blurred=blurred)
            events.append(("paint", layout.bounds))

    def wait_for_blur():
        deadline = time.monotonic() + 2
        while not any(kind == "place" and boxes for kind, boxes in events):
            assert time.monotonic() < deadline, events
            QTest.qWait(5)
        first = next(i for i, (kind, boxes) in enumerate(events) if kind == "place" and boxes)
        assert all(("paint", box) in events[:first] for box in events[first][1])

    surface = Surface(Mock())
    tracks = tuple(TextTrack(n, "設定", Rect(n * 100, 10, 80, 24)) for n in (1, 2, 3))
    results = tuple(TranslatedText(TranslationRequest.from_track(t), "Settings") for t in tracks)
    try:
        surface.set_backdrop_blur(True)
        surface.align(Rect(0, 0, 600, 400))
        surface.set_scene(tracks, translations=results[:1], english=True)
        assert events == []
        wait_for_blur()
        events.clear()
        surface.set_scene(tracks, translations=results[1:2], english=True)
        assert events == [("place", ())]  # Hide the removed label's surface synchronously.
        wait_for_blur()
        app.processEvents()
        events.clear()
        surface.set_scene(tracks, translations=results[1:], english=True)
        surface.repaint()  # The third label has queued blur work.
        assert any(kind == "paint" for kind, _ in events)
        surface.set_scene((), english=False)
        events.clear()
        QTest.qWait(25)
        assert not any(kind == "place" and boxes for kind, boxes in events)
    finally:
        surface.set_backdrop_blur(False)
        surface.close()


def test_fragment_stays_painted_until_paragraph_is_ready_then_loses_its_backdrop(monkeypatch):
    app = QApplication.instance() or QApplication([])
    native = Mock()
    active = set()

    def place(hwnd, bounds, boxes, *, included):
        active.clear()
        active.update(boxes)
        return frozenset(boxes)

    native.place.side_effect = place
    monkeypatch.setattr(overlay, "LabelBackdrops", lambda windows: native)
    monkeypatch.setattr(overlay.QGuiApplication, "platformName", lambda: "windows")
    drawn = []

    class Surface(overlay.OverlayWindow):
        def _paint_english(self, painter, layout, *, blurred):
            super()._paint_english(painter, layout, blurred=blurred)
            drawn.append(layout.bounds)

    short = TextBlock((TextTrack(1, "その身をもって", Rect(270, 20, 155, 28)),))
    paragraph = TextBlock(
        (
            TextTrack(4, "伏龍はその身をもって", Rect(20, 20, 405, 28)),
            TextTrack(5, "大地を支え、千年の苦しみに耐える。", Rect(20, 62, 405, 28)),
        )
    )
    fragment_reply = TranslatedText(TranslationRequest.from_block(short), "With its body")
    full_reply = TranslatedText(
        TranslationRequest.from_block(paragraph), "The dragon supports the earth with its body."
    )
    tracks = short.lines + paragraph.lines
    surface = Surface(Mock())

    def wait_for_backdrop():
        deadline = time.monotonic() + 2
        while not active:
            assert time.monotonic() < deadline, drawn
            QTest.qWait(5)

    try:
        surface.resize(600, 300)
        surface.set_backdrop_blur(True)
        surface.align(Rect(0, 0, 600, 300))
        surface.set_scene(tracks, (short, paragraph), (fragment_reply,), english=True)
        surface.grab()
        app.processEvents()
        wait_for_backdrop()
        assert set(drawn) == active and len(active) == 1
        assert next(iter(active)).contains(short.bounds)
        drawn.clear()
        surface.set_scene(tracks, (short, paragraph), (fragment_reply, full_reply), english=True)
        assert not active
        surface.grab()
        app.processEvents()
        wait_for_backdrop()
        assert set(drawn) == active and len(active) == 1
        assert next(iter(active)).contains(paragraph.bounds)
    finally:
        surface.set_backdrop_blur(False)
        surface.close()
