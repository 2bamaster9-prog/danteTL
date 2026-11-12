import os
from dataclasses import replace
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shiboken6  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from jp_overlay.diagnostics import DebugDisplay  # noqa: E402
from jp_overlay.domain import CapturedFrame, Rect, WindowGeometry  # noqa: E402
from jp_overlay.grouping import TextBlock  # noqa: E402
from jp_overlay.inspection import OcrInspector, image_target  # noqa: E402
from jp_overlay.overlay import OverlayWindow  # noqa: E402
from jp_overlay.recognition import OcrResult, TextCharacter, TextRegion  # noqa: E402
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


def cell(panel: OcrInspector, row: int, column: int):
    item = panel.table.item(row, column)
    assert item is not None
    return item


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


def test_debug_draws_without_translations_and_toggle_preserves_publication(app):
    overlay = OverlayWindow(Mock())
    overlay.resize(400, 300)
    overlay._bounds = Rect(0, 0, 400, 300)
    overlay.set_tracks(())
    overlay.set_translations((), enabled=True)
    assert overlay.grab().toImage().pixelColor(210, 210).alpha() == 0
    overlay.set_debug(DebugDisplay((Rect(200, 200, 40, 40),), (), "Debug"))
    assert overlay.grab().toImage().pixelColor(210, 210).alpha() > 0
    assert overlay._translations == () and overlay._tracks == ()
    overlay.set_debug(None)
    assert overlay.grab().toImage().pixelColor(210, 210).alpha() == 0
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


def test_grouped_english_uses_one_background_and_validates_every_member(app) -> None:
    overlay = OverlayWindow(Mock())
    overlay.resize(400, 200)
    overlay._bounds = Rect(0, 0, 400, 200)
    lines = (
        TextTrack(1, "新しい冒険が始まるので、", Rect(20, 20, 280, 32)),
        TextTrack(2, "準備をしよう。", Rect(20, 68, 240, 32)),
    )
    block = TextBlock(lines)
    overlay.set_tracks(lines)
    overlay.set_blocks((block,))
    overlay.set_translations(
        (TranslatedText(TranslationRequest.from_block(block), "Get ready for a new adventure."),),
        enabled=True,
    )
    assert overlay.grab().toImage().pixelColor(25, 60).alpha() > 0  # The gap is inside one block.
    overlay.set_blocks((TextBlock((lines[0], replace(lines[1], text_revision=2))),))
    assert overlay.grab().toImage().pixelColor(25, 25).alpha() == 0
    overlay.close()
    overlay.deleteLater()


def test_group_auto_font_uses_line_height_not_paragraph_height(app) -> None:
    layout = layout_english(
        "A complete sentence.", Rect(10, 10, 500, 150), (800, 300), source_line_height=32
    )
    assert layout.pixel_size == round(32 * 0.72)


def test_group_inspection_and_copy_map_to_raw_rows_without_duplicating_english(
    app, monkeypatch
) -> None:
    lines = (
        TextTrack(1, "新しい冒険が始まるので、", Rect(20, 20, 280, 32)),
        TextTrack(2, "準備をしよう。", Rect(20, 68, 240, 32)),
    )
    bounds = Rect(0, 0, 400, 200)
    frame = CapturedFrame(
        1, 0, WindowGeometry(bounds, bounds, bounds, 96), b"\xff" * (400 * 200 * 4)
    )
    regions = tuple(TextRegion(t.text, t.bounds) for t in lines)
    result = OcrResult(frame, regions, 20, 0)
    panel = OcrInspector()
    panel.set_result(result, (1, 2))
    translated = TranslatedText(
        TranslationRequest.from_block(TextBlock(lines)), "Get ready for a new adventure."
    )
    panel.set_translations((translated,))
    assert cell(panel, 0, 3).text() == translated.english
    assert cell(panel, 1, 3).text() == "↳ Group #1"
    assert lines[1].text in cell(panel, 1, 3).toolTip()
    clipboard = Mock()
    monkeypatch.setattr("jp_overlay.inspection.QGuiApplication.clipboard", lambda: clipboard)
    panel._copy_english()
    clipboard.setText.assert_called_with(translated.english)
    panel.table.selectRow(1)
    panel._copy_english()
    clipboard.setText.assert_called_with(translated.english)
    panel.set_result(
        replace(result, regions=(regions[0], replace(regions[1], text="違う文章。"))), (1, 2)
    )
    assert cell(panel, 0, 3).text() == cell(panel, 1, 3).text() == "—"
    panel.close()
    panel.deleteLater()


def test_raw_icon_evidence_is_visible_beside_cleaned_translation(app) -> None:
    chars = (TextCharacter("@", Rect(20, 10, 25, 30), 0.3),) + tuple(
        TextCharacter(c, Rect(70 + i * 25, 10, 25, 30), 0.95)
        for i, c in enumerate("道具を確認する")
    )
    raw = TextRegion("@道具を確認する", Rect(15, 10, 235, 30), chars)
    bounds = Rect(0, 0, 400, 100)
    frame = CapturedFrame(1, 0, WindowGeometry(bounds, bounds, bounds, 96), b"\xff" * 160000)
    panel = OcrInspector()
    panel.set_result(OcrResult(frame, (raw,), 20, 0), (1,))
    panel.set_translations(
        (TranslatedText(TranslationRequest(1, 1, "道具を確認する"), "Check items"),)
    )
    assert cell(panel, 0, 1).text() == raw.text
    assert cell(panel, 0, 3).text() == "Check items"
    assert panel.preview._regions == (raw,)
    panel.close()
    panel.deleteLater()
