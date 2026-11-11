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
from jp_overlay.tracking import TextTrack  # noqa: E402


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
