import os
import threading
import time
from dataclasses import replace
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shiboken6  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from jp_overlay.diagnostics import DebugDisplay  # noqa: E402
from jp_overlay.domain import CapturedFrame, Rect, WindowGeometry  # noqa: E402
from jp_overlay.grouping import TextBlock  # noqa: E402
from jp_overlay.inspection import OcrInspector, image_target  # noqa: E402
from jp_overlay.overlay import OverlayWindow  # noqa: E402
from jp_overlay.recognition import OcrResult, TextCharacter, TextRegion  # noqa: E402
from jp_overlay.text_layout import layout_english  # noqa: E402
from jp_overlay.tracking import TextTrack  # noqa: E402
from jp_overlay.translation import (  # noqa: E402
    BackendChoice,
    TranslatedText,
    TranslationRequest,
    TranslationSnapshot,
    TranslationState,
)
from jp_overlay.ui import MainWindow  # noqa: E402


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


def drain(window, predicate):
    deadline = time.monotonic() + 3
    while not predicate():
        assert time.monotonic() < deadline
        window._tick()
        time.sleep(0.005)


def test_no_models_do_not_start_inference_and_refresh_never_prepares_implicitly(
    app, tmp_path, monkeypatch
):
    windows = Mock()
    windows.list_targets.return_value = []
    factory = Mock()
    choice = BackendChoice("Gemma", factory, "gemma", "unprepared")
    monkeypatch.setattr("jp_overlay.ui.is_prepared", lambda key: not key)
    window = MainWindow(
        windows, factory, cache_path=tmp_path / "cache", backend_provider=lambda: (choice,)
    )
    assert window.backend_combo.currentData() is None
    assert window.translate_check.isEnabled() and window.models_button.isEnabled()
    assert "No translation model is downloaded" in window.notice.text()
    assert window.onboarding.property("tone") == "warning"
    window._tick()
    window._refresh_models()
    assert window.backend_combo.currentData() is None
    assert window.translate_check.isEnabled()
    factory.assert_not_called()
    window.close()
    window.deleteLater()


def test_downloaded_model_without_runtime_stays_visible_and_explains_setup(
    app, tmp_path, monkeypatch
):
    windows = Mock()
    windows.list_targets.return_value = []
    factory = Mock()
    choice = BackendChoice(
        "Gemma · runtime setup needed",
        factory,
        "gemma-unavailable",
        unavailable_reason="Open Runtime setup.",
    )
    setup = Mock()
    monkeypatch.setattr(MainWindow, "_manage_runtime", setup)
    window = MainWindow(windows, factory, (choice,), cache_path=tmp_path / "cache")
    assert window.backend_combo.isEnabled() and window.translate_check.isEnabled()
    assert window.backend_combo.currentData() is None  # Never implicitly load an unusable model.
    window._poll_translation(True)
    assert "runtime setup" in window.translation_status.text()
    window.backend_combo.setCurrentIndex(0)
    setup.assert_called_once()
    assert window.backend_combo.currentData() is None and window._translation is None
    factory.assert_not_called()
    window.close()
    window.deleteLater()


def test_download_completion_reports_missing_runtime_instead_of_false_readiness(
    app, tmp_path, monkeypatch
):
    import hashlib
    import io

    from jp_overlay.model_manager import ModelManager
    from jp_overlay.model_store import ModelBundle
    from jp_overlay.models import ModelAsset

    asset = ModelAsset("fixture", "revision", "weights", hashlib.sha256(b"good").hexdigest(), 4)
    bundle = ModelBundle("gemma", "Gemma", tmp_path, (asset,), "")
    monkeypatch.setattr("jp_overlay.model_store.urlopen", lambda *a, **k: io.BytesIO(b"good"))
    monkeypatch.setattr("jp_overlay.gemma.installed_device", lambda: None)
    manager = ModelManager((bundle,))
    manager._download()
    assert manager.operation is not None
    manager.operation._thread.join(2)
    manager._poll()
    assert manager.operation is None and bundle.present()
    assert "not installed" in manager.status.text() and "Acceleration" in manager.status.text()
    assert manager.download.text() == "Verify / repair"
    assert manager.progress.value() == manager.progress.maximum()
    assert manager.download_badge.text() == "✓  Downloaded"
    assert manager.download_badge.property("tone") == "success"
    assert not manager.runtime_badge.isHidden()
    manager.close()
    manager.deleteLater()


def test_runtime_setup_detects_without_installing_and_close_waits_for_cancel(
    app, tmp_path, monkeypatch
):
    from jp_overlay import runtime_dialog
    from jp_overlay.hardware import Adapter
    from jp_overlay.model_store import Cancelled

    calls = []
    entered = threading.Event()
    monkeypatch.setattr(
        runtime_dialog, "detect_adapters", lambda: (Adapter("RTX", 0x10DE, 16 * 2**30),)
    )

    def install(root, profile, progress, cancel):
        calls.append(threading.get_ident())
        entered.set()
        assert cancel.wait(2)
        raise Cancelled()

    monkeypatch.setattr(runtime_dialog, "install_runtime", install)
    windows = Mock()
    windows.list_targets.return_value = []
    window = MainWindow(windows, Mock(), cache_path=tmp_path / "cache")
    dialog = runtime_dialog.RuntimeSetupDialog(window, root=tmp_path)
    window._runtime_dialog = dialog
    assert dialog.operation
    dialog.operation._thread.join(2)
    dialog._poll()
    assert "RTX" in dialog.hardware.text() and dialog.choice.currentData().key == "nvidia"
    assert not calls and dialog.install.isEnabled() and not dialog.restart.isEnabled()
    dialog.install.click()
    assert entered.wait(1) and calls != [threading.get_ident()]
    assert not dialog.choice.isEnabled() and not dialog.restart.isEnabled()
    window.close()
    assert window._closing and dialog.operation
    dialog.operation._thread.join(2)
    dialog._poll()
    window._tick()
    assert dialog.operation is None and not window._timer.isActive()
    window.deleteLater()


def test_model_download_badges_and_missing_selection_warnings_are_distinct(
    app, tmp_path, monkeypatch
):
    from jp_overlay.hardware import Adapter, HardwareStatus
    from jp_overlay.model_store import ModelBundle
    from jp_overlay.models import ModelAsset

    asset = ModelAsset("test", "revision", "weights", "", 4)
    bundle = ModelBundle("gemma", "Gemma", tmp_path, (asset,), "Fixture")
    windows = Mock()
    windows.list_targets.return_value = []
    hardware = Mock(finished=True)
    hardware.snapshot.return_value = HardwareStatus((Adapter("RTX fixture", 0x10DE),))
    monkeypatch.setattr("jp_overlay.gemma.installed_device", lambda: None)
    window = MainWindow(windows, Mock(), models=(bundle,), hardware=hardware)
    manager = window._settings.models
    assert "Download required" in manager.download_badge.text()
    assert manager.download_badge.property("tone") == "warning"
    assert window.onboarding.property("tone") == "warning"
    assert "NVIDIA GPU detected" in window.acceleration_notice.label.text()
    (tmp_path / "weights").write_bytes(b"good")
    window._manage_models()
    assert manager.download_badge.text() == "✓  Downloaded"
    assert manager.download_badge.property("tone") == "success"
    assert manager.choice.itemText(0).startswith("✓")
    assert not manager.runtime_badge.isHidden() and "Acceleration" in manager.runtime_badge.text()
    choice = BackendChoice("Gemma", Mock(), "gemma", unavailable_reason="Missing runtime")
    window._backends = (choice,)
    window._update_notice()
    assert "No translation model is selected" in window.notice.text()
    assert window.models_button.text() == "Choose model"
    assert "selected" in window._settings.model_notice.label.text()
    window.close()
    assert not window._settings.isVisible()
    window.deleteLater()


def test_switch_clears_painted_and_paused_english_rejects_late_reply_and_keeps_model_caches(
    app, tmp_path
):
    class Backend:
        batch_size = 1

        def __init__(self, name):
            self.cache_identity = name
            self.calls = []
            self.entered, self.release = threading.Event(), threading.Event()
            self.release.set()

        def translate(self, texts):
            self.calls.append(texts)
            self.entered.set()
            assert self.release.wait(3)
            return tuple(f"{self.cache_identity}: {text}" for text in texts)

        def close(self):
            pass

    old, new, old_again = Backend("Sugoi"), Backend("Gemma"), Backend("Sugoi")
    windows = Mock()
    windows.list_targets.return_value = []
    choices = (
        BackendChoice("Sugoi", lambda: old, "sugoi-fast"),
        BackendChoice("Gemma", lambda: new, "gemma"),
    )
    window = MainWindow(windows, Mock(), choices, cache_path=tmp_path / "cache")
    window._timer.stop()
    window.advanced.setChecked(True)
    first = TextBlock((TextTrack(1, "猫", Rect(0, 0, 40, 20)),))
    second = TextBlock((TextTrack(2, "犬", Rect(0, 40, 40, 20)),))

    def poll_until(predicate, blocks):
        deadline = time.monotonic() + 3
        while True:
            window._poll_translation(True, blocks, blocks)
            if predicate():
                return
            assert time.monotonic() < deadline
            time.sleep(0.005)

    try:
        poll_until(lambda: bool(window._overlay._translations), (first,))
        bounds = Rect(0, 0, 80, 80)
        frame = CapturedFrame(1, 0, WindowGeometry(bounds, bounds, bounds, 96), b"\xff" * 25600)
        result = OcrResult(frame, (TextRegion("猫", first.bounds),), 1, 1)
        window.inspector.set_result(result, (1,))
        window.inspector.set_translations(window._overlay._translations)
        window.inspector.pause.setChecked(True)
        assert cell(window.inspector, 0, 3).text() == "Sugoi: 猫"
        old.entered.clear()
        old.release.clear()
        window._poll_translation(True, (first, second), (first, second))
        assert old.entered.wait(1)
        new.release.clear()
        window.backend_combo.setCurrentIndex(1)
        assert not window._overlay._translations and not window._overlay._blocks
        assert cell(window.inspector, 0, 3).text() == "—"
        assert window.inspector.result is result and window.inspector.pause.isChecked()
        old.release.set()
        assert new.entered.wait(1)
        window._poll_translation(True, (first, second), (first, second))
        assert not window._overlay._translations
        new.release.set()
        poll_until(lambda: len(window._overlay._translations) == 2, (first, second))
        assert all(t.english.startswith("Gemma:") for t in window._overlay._translations)
        window.inspector.pause.setChecked(False)
        assert cell(window.inspector, 0, 3).text() == "Gemma: 猫"
        window.backend_combo.setItemData(0, replace(choices[0], create=lambda: old_again))
        window.backend_combo.setCurrentIndex(0)
        assert not window._overlay._translations
        poll_until(lambda: len(window._overlay._translations) == 2, (first, second))
        assert all(t.english.startswith("Sugoi:") for t in window._overlay._translations)
        assert old_again.calls == []  # Its own cache still works; Gemma never read those entries.
        assert new.calls == [("猫",), ("犬",)]
    finally:
        old.release.set()
        new.release.set()
        window.close()
        drain(window, lambda: not window._closing or window._translation is None)
        window.deleteLater()


def test_app_shutdown_drains_startup_hardware_check(app, tmp_path):
    windows = Mock()
    windows.list_targets.return_value = []
    hardware = Mock(finished=False)
    hardware.snapshot.return_value = None
    window = MainWindow(windows, Mock(), hardware=hardware, cache_path=tmp_path / "cache")
    window.close()
    assert window._closing and window._timer.isActive()
    hardware.finished = True
    window._tick()
    assert not window._timer.isActive()
    window.deleteLater()


def test_runtime_restart_waits_for_translation_and_recovers_if_launch_fails(
    app, tmp_path, monkeypatch
):
    windows = Mock()
    windows.list_targets.return_value = []
    window = MainWindow(windows, Mock(), cache_path=tmp_path / "cache")
    worker = Mock(finished=False)
    window._translation = worker
    restart = Mock(side_effect=OSError("Could not launch"))
    monkeypatch.setattr("jp_overlay.ui.RuntimeRestart", restart)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a[-1]))
    window._request_restart(tmp_path)
    assert window._closing
    worker.request_stop.assert_called()
    restart.assert_not_called()
    worker.finished = True
    window.close()
    restart.assert_called_once()
    assert not window._closing and window._restart_target is None
    assert warnings == ["Could not launch"]
    central = window.centralWidget()
    assert central and central.isEnabled() and window._timer.isActive()
    window.close()
    window.deleteLater()


def test_preparation_decline_preserves_selection_and_accept_loads_once_off_ui(
    app, tmp_path, monkeypatch
):
    windows = Mock()
    windows.list_targets.return_value = []
    entered, release = threading.Event(), threading.Event()
    calls, receipts = [], []

    def load():
        calls.append(threading.get_ident())
        entered.set()
        assert release.wait(2)
        backend = Mock(cache_identity="fake")
        backend.batch_size = 1
        return backend

    base = BackendChoice("Sugoi", Mock(), "sugoi")
    gemma = BackendChoice("Gemma", load, "gemma", "new")
    monkeypatch.setattr("jp_overlay.ui.is_prepared", lambda key: not key)
    monkeypatch.setattr("jp_overlay.ui.mark_prepared", receipts.append)
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.No)
    window = MainWindow(windows, Mock(), (base, gemma), cache_path=tmp_path / "cache")
    window.backend_combo.setCurrentIndex(1)
    assert window.backend_combo.currentData() == base
    assert not entered.is_set() and not receipts
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    window.backend_combo.setCurrentIndex(1)
    window._tick()
    assert entered.wait(1)
    assert window._progress_dialog and window._progress_dialog.maximum() == 0
    assert not receipts and window._preparing == gemma
    assert window._translation is not None
    assert calls == [window._translation._thread.ident] and calls[0] != threading.get_ident()
    release.set()
    drain(window, lambda: window._preparing is None)
    assert receipts == ["new"] and len(calls) == 1
    assert window.backend_combo.currentData() == gemma and window._translation is not None
    window.close()
    drain(window, lambda: not window._timer.isActive())
    window.deleteLater()


def test_failed_preparation_restores_previous_selection_without_a_receipt(
    app, tmp_path, monkeypatch
):
    windows = Mock()
    windows.list_targets.return_value = []
    base = BackendChoice("Sugoi", Mock(), "sugoi")
    bad = BackendChoice("Gemma", Mock(side_effect=RuntimeError("GPU unavailable")), "gemma", "new")
    receipts, errors = [], []
    monkeypatch.setattr("jp_overlay.ui.is_prepared", lambda key: not key)
    monkeypatch.setattr("jp_overlay.ui.mark_prepared", receipts.append)
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: errors.append(a[-1]))
    window = MainWindow(windows, Mock(), (base, bad), cache_path=tmp_path / "cache")
    window.backend_combo.setCurrentIndex(1)
    drain(window, lambda: window._preparing is None)
    assert window.backend_combo.currentData() == base
    assert not receipts and errors == ["GPU unavailable"]
    window.close()
    window.deleteLater()


def test_nested_consent_event_loop_does_not_unload_previous_model(app, tmp_path, monkeypatch):
    windows = Mock()
    windows.list_targets.return_value = []
    base = BackendChoice("Sugoi", Mock(), "sugoi")
    gemma = BackendChoice("Gemma", Mock(), "gemma", "new")
    monkeypatch.setattr("jp_overlay.ui.is_prepared", lambda key: not key)
    window = MainWindow(windows, Mock(), (base, gemma), cache_path=tmp_path / "cache")
    session = Mock(finished=False)
    session.snapshot.return_value = TranslationSnapshot(TranslationState.READY)
    window._translation = session

    def question(*args):
        window._poll_translation(True)
        session.request_stop.assert_not_called()
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", question)
    window.backend_combo.setCurrentIndex(1)
    assert window.backend_combo.currentData() == base and window._translation == session
    window._translation = None
    window.close()
    window.deleteLater()


def test_closing_during_download_waits_for_cancellation_before_destroying_gui(
    app, tmp_path, monkeypatch
):
    from jp_overlay.model_store import Cancelled, ModelBundle, ModelProgress

    windows = Mock()
    windows.list_targets.return_value = []
    entered = threading.Event()

    def install(bundle, progress, cancel):
        progress(ModelProgress("Downloading", 1, 10))
        entered.set()
        assert cancel.wait(2)
        raise Cancelled()

    monkeypatch.setattr("jp_overlay.model_manager.install_model", install)
    bundle = ModelBundle("fake", "Fixture", tmp_path, (), "")
    window = MainWindow(windows, Mock(), models=(bundle,), cache_path=tmp_path / "cache")
    window._manage_models()
    manager = window._model_manager
    assert manager is not None
    manager._download()
    assert entered.wait(1)
    window.close()
    assert window._timer.isActive()
    deadline = time.monotonic() + 2
    while window._timer.isActive():
        assert time.monotonic() < deadline
        manager._poll()
        window._tick()
        time.sleep(0.005)
    assert manager.operation is None
    window.deleteLater()


def test_preview_letterboxing_maps_physical_pixels_once() -> None:
    target = image_target((1920, 1080), (640, 480))
    assert target.getRect() == (0, 60, 640, 360)
    # Original point (960, 540) lands in the preview center, including the top margin.
    scale = target.width() / 1920
    assert (target.x() + 960 * scale, target.y() + 540 * scale) == (320, 240)


def test_settings_edits_persist_and_restore_without_loading_a_model(app, tmp_path, monkeypatch):
    from jp_overlay.recognition import OcrChoice

    windows = Mock()
    windows.list_targets.return_value = []
    factory = Mock()
    choices = (OcrChoice("Automatic", factory, key="auto"), OcrChoice("CPU", factory, key="cpu"))
    path = tmp_path / "preferences.json"
    window = MainWindow(windows, factory, ocr_backends=choices, preferences_path=path)
    window._show_settings()
    original = window._settings
    window._show_settings()
    assert window._settings is original
    window.stabilize_check.setChecked(False)
    window._settings.opacity.setValue(61)
    window.automatic_font.setChecked(False)
    window.font_size.setValue(26)
    window.group_dialogue.setChecked(False)
    window.ocr_device.setCurrentIndex(1)
    window.capture_rate.setValue(5)
    window.translate_check.setChecked(False)
    window.overlay_check.setChecked(False)
    deadline = time.monotonic() + 2
    while not window._preferences.idle:
        assert time.monotonic() < deadline
        time.sleep(0.005)
    window.close()
    window.deleteLater()
    restored = MainWindow(windows, factory, ocr_backends=choices, preferences_path=path)
    assert not restored.stabilize_check.isChecked() and not restored.group_dialogue.isChecked()
    assert restored._overlay._opacity == 0.61 and restored.font_size.value() == 26
    assert not restored.automatic_font.isChecked() and restored.font_size.isEnabled()
    assert restored.ocr_device.currentData().key == "cpu" and restored.capture_rate.value() == 5
    assert not restored.translate_check.isChecked() and not restored.overlay_check.isChecked()
    assert not restored.advanced.isChecked() and not restored.inspector.pause.isChecked()
    factory.assert_not_called()
    restored.close()
    restored.deleteLater()


def test_hidden_inspector_does_no_frame_copy_or_table_build_and_resume_uses_latest_pair(
    app, monkeypatch
):
    from jp_overlay import inspection

    panel = OcrInspector()
    panel.set_active(False)
    copied = Mock(wraps=inspection.frame_image)
    monkeypatch.setattr(inspection, "frame_image", copied)
    bounds = Rect(0, 0, 4, 4)
    geometry = WindowGeometry(bounds, bounds, bounds, 96)
    latest = None
    for sequence, text in enumerate(("猫", "犬", "鳥"), 1):
        frame = CapturedFrame(sequence, sequence, geometry, b"\xff" * 64)
        latest = OcrResult(frame, (TextRegion(text, bounds),), 10, sequence)
        panel.set_result(latest, (7,))
        panel.set_translations((TranslatedText(TranslationRequest(7, 1, text), text + " English"),))
    copied.assert_not_called()
    assert panel.result is None and panel.table.rowCount() == 0
    panel.set_active(True)
    assert latest is not None
    assert copied.call_count == 1
    assert panel.result is latest and panel._display_frame is latest.frame
    assert cell(panel, 0, 1).text() == "鳥" and cell(panel, 0, 3).text() == "鳥 English"
    panel.pause.setChecked(True)
    newer = replace(
        latest, frame=replace(latest.frame, sequence=4), regions=(TextRegion("魚", bounds),)
    )
    panel.set_result(newer, (8,))
    panel.set_translations((TranslatedText(TranslationRequest(8, 1, "魚"), "Fish"),))
    assert panel.result is latest and cell(panel, 0, 3).text() == "鳥 English"
    panel.pause.setChecked(False)
    assert panel.result is newer and cell(panel, 0, 3).text() == "Fish"
    panel.clear()
    panel.set_active(False)
    panel.set_active(True)
    assert panel.result is None and panel._latest_frame is None
    panel.deleteLater()


def test_device_and_rate_edits_wait_for_next_capture_even_when_models_arrive_mid_session(
    app, tmp_path, monkeypatch
):
    from jp_overlay.domain import WindowTarget
    from jp_overlay.recognition import OcrChoice

    windows = Mock()
    windows.list_targets.return_value = [WindowTarget(1, 1, "Fixture")]
    cpu, gpu = Mock(), Mock()
    choices = (OcrChoice("CPU", cpu, key="cpu"), OcrChoice("GPU", gpu, key="auto"))
    capture, ocr = Mock(), Mock()
    monkeypatch.setattr("jp_overlay.ui.CaptureSession", capture)
    monkeypatch.setattr("jp_overlay.ui.OcrSession", ocr)
    monkeypatch.setattr("jp_overlay.ui.VisualSession", Mock())
    window = MainWindow(windows, cpu, ocr_backends=choices, cache_path=tmp_path / "cache")
    window._timer.stop()
    window._tick = Mock()
    window._ocr_models_ready = Mock(return_value=False)
    window._toggle_capture()
    assert capture.call_args.kwargs["fps"] == 8 and window._capture_ocr_choice == choices[1]
    window.ocr_device.setCurrentIndex(0)
    window.capture_rate.setValue(5)
    window._ocr_models_ready.return_value = True
    window._refresh_models()
    ocr.assert_called_once_with(gpu, require_ack=True)
    assert capture.call_count == 1  # Editing settings did not restart the current session.
    window._session = window._ocr = window._visual = None
    window._toggle_capture()
    assert capture.call_args.kwargs["fps"] == 5
    assert ocr.call_args.args == (cpu,)
    window._session = window._ocr = window._visual = None
    window.close()
    window.deleteLater()


@pytest.mark.parametrize("prepared", [False, True])
def test_saved_gemma_choice_survives_runtime_change_without_implicit_preparation(
    app, tmp_path, monkeypatch, prepared
):
    from jp_overlay.preferences import Preferences, PreferenceStore

    path = tmp_path / "preferences.json"
    store = PreferenceStore(path)
    store._write(Preferences(model="gemma"))
    windows = Mock()
    windows.list_targets.return_value = []
    factory = Mock()
    sugoi = BackendChoice("Sugoi", factory, "sugoi-fast")
    gemma = BackendChoice("Gemma Vulkan", factory, "gemma-vulkan", "vulkan-receipt")
    monkeypatch.setattr("jp_overlay.ui.is_prepared", lambda key: prepared or not key)
    consent = Mock(return_value=QMessageBox.StandardButton.No)
    monkeypatch.setattr(QMessageBox, "question", consent)
    window = MainWindow(windows, factory, (sugoi, gemma), preferences_path=path)
    assert window.backend_combo.currentData() == (gemma if prepared else None)
    consent.assert_not_called()
    factory.assert_not_called()
    if not prepared:
        window.backend_combo.setCurrentIndex(1)
        consent.assert_called_once()
        assert window.backend_combo.currentData() is None
    window._settings.opacity.setValue(63)
    drain(window, lambda: window._preferences.idle)
    assert PreferenceStore(path).initial.model == "gemma"
    # Explicit No translation is a successful user choice and persists immediately.
    if window.backend_combo.currentData() is None:
        window.backend_combo.setCurrentIndex(0)
    window.backend_combo.setCurrentIndex(2)
    drain(window, lambda: window._preferences.idle)
    assert PreferenceStore(path).initial.model == "none"
    factory.assert_not_called()
    window.close()
    window.deleteLater()


def test_live_reconciliation_and_ocr_ack_continue_while_inspector_is_hidden_or_paused(
    app, tmp_path
):
    from jp_overlay.recognition import OcrSnapshot, OcrState
    from jp_overlay.visual import VisualState

    windows = Mock()
    windows.list_targets.return_value = []
    window = MainWindow(windows, Mock(), cache_path=tmp_path / "cache")
    window._ocr, window._visual, window._tracker = Mock(), Mock(), Mock()
    window._tracker.visible.return_value = ()
    window._tracker.translation_activity.return_value = ()
    window._tracker.observe.return_value = (1,)
    bounds = Rect(0, 0, 4, 4)
    geometry = WindowGeometry(bounds, bounds, bounds, 96)
    frozen = None
    for sequence in range(1, 4):
        frame = CapturedFrame(sequence, sequence, geometry, b"\xff" * 64)
        result = OcrResult(frame, (TextRegion("猫", bounds),), 10, sequence)
        window._ocr.snapshot.return_value = OcrSnapshot(OcrState.READY, result)
        window._visual.poll.return_value = VisualState(
            frame=frame, request_ocr=True, checked_sequence=sequence
        )
        window._update_ocr(frame)
        assert window._accepted_ocr is result
        window._ocr.acknowledge.assert_called_with(sequence)
        assert window._visual.submit.call_args.args[1] is result
        if sequence == 1:
            assert window.inspector.result is None
            window.advanced.setChecked(True)
            frozen = window.inspector.result
            window.inspector.pause.setChecked(True)
        else:
            assert window.inspector.result is frozen
            window.advanced.setChecked(False)
    window._tracker.reset.assert_not_called()
    window._ocr.invalidate.assert_not_called()
    assert window._ocr.submit.call_count == 3
    window.inspector.pause.setChecked(False)
    assert window.inspector.result is None  # Still collapsed: no hidden image conversion.
    window.advanced.setChecked(True)
    assert window.inspector.result is window._accepted_ocr
    window._ocr = window._visual = None
    window.close()
    window.deleteLater()


def test_translation_off_leaves_game_unobscured_until_ocr_boxes_are_requested(app, tmp_path):
    from jp_overlay.domain import CaptureSnapshot, CaptureState, WindowTarget

    windows = Mock()
    windows.list_targets.return_value = []
    bounds = Rect(0, 0, 400, 200)
    geometry = WindowGeometry(bounds, bounds, bounds, 96)
    frame = CapturedFrame(1, time.monotonic(), geometry, b"\xff" * 320000)
    windows.geometry.return_value = geometry
    windows.is_foreground.return_value = True
    window = MainWindow(windows, Mock(), cache_path=tmp_path / "cache")
    window.translate_check.setChecked(False)
    window._session = Mock(finished=False, target=WindowTarget(1, 1, "Fixture"))
    window._session.snapshot.return_value = CaptureSnapshot(CaptureState.RUNNING, frame)
    window._valid_size = bounds.size
    window._update_ocr = Mock()
    window._tracker = Mock()
    track = TextTrack(1, "猫", Rect(20, 20, 40, 20))
    window._tracker.visible.return_value = (track,)
    window._tracker.translation_tracks.return_value = (track,)
    window._tracker.translation_activity.return_value = ()
    window._overlay.align = Mock()
    window._tick()
    window._overlay.align.assert_not_called()
    window.raw_boxes_check.setChecked(True)
    window._overlay.align.assert_called_with(bounds)
    window.overlay_check.setChecked(False)
    window._tracker.reset.assert_not_called()
    window._session = None
    window.close()
    window.deleteLater()


@pytest.mark.parametrize("cancel_operation", [False, True])
def test_settings_close_can_keep_setup_running_or_cancel_without_stopping_app(
    app, tmp_path, monkeypatch, cancel_operation
):
    from jp_overlay.model_store import Cancelled, ModelBundle

    windows = Mock()
    windows.list_targets.return_value = []
    entered = threading.Event()

    def install(bundle, progress, cancel):
        entered.set()
        assert cancel.wait(2)
        raise Cancelled()

    monkeypatch.setattr("jp_overlay.model_manager.install_model", install)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    selected = "Cancel operation" if cancel_operation else "Continue in background"
    monkeypatch.setattr(
        QMessageBox,
        "clickedButton",
        lambda self: next(b for b in self.buttons() if b.text() == selected),
    )
    bundle = ModelBundle("fixture", "Fixture", tmp_path, (), "")
    window = MainWindow(windows, Mock(), models=(bundle,), cache_path=tmp_path / "cache")
    window._manage_models()
    manager = window._settings.models
    manager._download()
    assert entered.wait(1) and manager.operation
    operation = manager.operation
    window._settings.close()
    assert not window._closing and window._timer.isActive()
    assert operation._cancel.is_set() == cancel_operation
    if not cancel_operation:
        assert window._settings.busy and not window._settings.isVisible()
    window.close()  # Closing the whole app always cancels and drains, without another prompt.
    operation._thread.join(2)
    manager._poll()
    window._tick()
    assert not window._settings.busy and not window._timer.isActive()
    window.deleteLater()


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
