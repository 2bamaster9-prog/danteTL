import os
from dataclasses import replace
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shiboken6  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from jp_overlay.domain import CapturedFrame, Rect, WindowGeometry  # noqa: E402
from jp_overlay.inspection import OcrInspector, image_target  # noqa: E402
from jp_overlay.overlay import OverlayWindow  # noqa: E402
from jp_overlay.recognition import OcrResult, TextRegion  # noqa: E402
from jp_overlay.text_layout import layout_english  # noqa: E402
from jp_overlay.tracking import TextTrack  # noqa: E402
from jp_overlay.translation import TranslatedText, TranslationRequest  # noqa: E402


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    yield application
    # Destroy widgets while their application and native modules are still alive.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    shiboken6.delete(application)


def test_preview_letterboxing_maps_physical_pixels_once() -> None:
    target = image_target((1920, 1080), (640, 480))
    assert target.getRect() == (0, 60, 640, 360)
    # Original point (960, 540) lands in the preview center, including the top margin.
    scale = target.width() / 1920
    assert (target.x() + 960 * scale, target.y() + 540 * scale) == (320, 240)


def test_text_selection_and_empty_result_replace_previous_frame_and_boxes(app) -> None:
    bounds = Rect(0, 0, 4, 4)
    source = CapturedFrame(1, 0, WindowGeometry(bounds, bounds, bounds, 96), b"\xff" * 64)
    panel = OcrInspector()
    result = OcrResult(source, (TextRegion("日本語", Rect(0, 0, 3, 3)),), 5, 1)
    panel.set_result(result)
    panel.table.selectRow(0)
    assert panel.preview.selected == 0
    item = panel.table.item(0, 1)
    assert item is not None and item.text() == "日本語"
    assert "x=0" in panel.details.text()
    panel.set_result(OcrResult(source, (), 5, 2))
    assert panel.table.rowCount() == 0
    assert panel.preview.selected == -1
    assert not panel.copy_button.isEnabled()
    panel.clear()
    assert panel.result is None
    panel.close()
    panel.deleteLater()


def test_overlay_does_not_request_repaint_for_equivalent_track_values(app, monkeypatch) -> None:
    overlay = OverlayWindow(Mock())
    repaint = Mock()
    monkeypatch.setattr(overlay, "update", repaint)
    track = TextTrack(17, "日本語", Rect(100, 200, 120, 30))
    overlay.set_tracks((track,))
    assert repaint.call_count == 1
    for _ in range(20):
        overlay.set_tracks((replace(track),))
    assert repaint.call_count == 1
    overlay.set_tracks((replace(track, bounds=Rect(120, 200, 120, 30)),))
    assert repaint.call_count == 2
    overlay.set_tracks(())
    assert repaint.call_count == 3
    overlay.close()
    overlay.deleteLater()


def test_inspector_displays_track_ids_without_replacing_raw_ocr_geometry(app) -> None:
    bounds = Rect(0, 0, 4, 4)
    source = CapturedFrame(1, 0, WindowGeometry(bounds, bounds, bounds, 96), b"\xff" * 64)
    panel = OcrInspector()
    result = OcrResult(source, (TextRegion("日本語", Rect(1, 1, 2, 2)),), 5, 1)
    panel.set_result(result, (47,))
    item = panel.table.item(0, 0)
    assert item is not None and item.text() == "47"
    assert panel.preview._regions == result.regions
    panel.close()
    panel.deleteLater()


def test_english_layout_wraps_and_stays_inside_screen_at_bottom_right(app) -> None:
    layout = layout_english(
        "A new adventure begins here, and there is more to discover.",
        Rect(1150, 690, 130, 30),
        (1280, 720),
    )
    assert Rect(0, 0, 1280, 720).contains(layout.bounds)
    assert len(layout.lines) > 1
    assert layout.pixel_size >= 12


def test_manual_font_and_overflow_are_explicit(app) -> None:
    layout = layout_english(
        "A very long translation " * 100,
        Rect(0, 0, 100, 30),
        (300, 200),
        automatic=False,
        manual_pixels=24,
    )
    assert layout.pixel_size == 24
    assert layout.truncated and layout.lines[-1].endswith("…")
    assert Rect(0, 0, 300, 200).contains(layout.bounds)


def test_english_column_rejects_translation_for_different_raw_text(app) -> None:
    bounds = Rect(0, 0, 4, 4)
    source = CapturedFrame(1, 0, WindowGeometry(bounds, bounds, bounds, 96), b"\xff" * 64)
    panel = OcrInspector()
    result = OcrResult(source, (TextRegion("猫", Rect(0, 0, 4, 4)),), 5, 1)
    panel.set_result(result, (1,))
    panel.set_translations((TranslatedText(TranslationRequest(1, 1, "猫"), "Cat"),))
    item = panel.table.item(0, 3)
    assert item is not None and item.text() == "Cat"
    panel.set_result(replace(result, regions=(TextRegion("犬", Rect(0, 0, 4, 4)),)), (1,))
    item = panel.table.item(0, 3)
    assert item is not None and item.text() == "—"
    panel.close()
    panel.deleteLater()


def test_english_overlay_keeps_original_visible_until_current_revision_is_ready(
    app, monkeypatch
) -> None:
    overlay = OverlayWindow(Mock())
    overlay.resize(400, 200)
    overlay._bounds = Rect(0, 0, 400, 200)
    track = TextTrack(1, "猫", Rect(20, 20, 100, 40), text_revision=2)
    overlay.set_tracks((track,))
    # Even identical text from a superseded revision must not cover the source.
    overlay.set_translations((TranslatedText(TranslationRequest(1, 1, "猫"), "Cat"),), enabled=True)
    assert overlay.grab().toImage().pixelColor(25, 25).alpha() == 0
    current = (TranslatedText(TranslationRequest.from_track(track), "Cat"),)
    overlay.set_translations(current, enabled=True)
    assert overlay.grab().toImage().pixelColor(25, 25).alpha() > 0
    repaint = Mock()
    monkeypatch.setattr(overlay, "update", repaint)
    overlay.set_translations(current, enabled=True)
    repaint.assert_not_called()
    overlay.set_translations((), enabled=True)
    assert overlay.grab().toImage().pixelColor(25, 25).alpha() == 0
    overlay.close()
    overlay.deleteLater()
